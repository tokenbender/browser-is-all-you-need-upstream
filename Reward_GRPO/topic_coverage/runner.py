"""Isolated, opt-in CPU coverage audit using the existing trusted task registry.

No live reward weights, manifests, fixtures, datasets or launchers are changed.
The local subprocess backend is for reviewed code in an isolated worker, not
hostile-code containment. Callers must explicitly acknowledge local execution.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Mapping

from Reward_GRPO.generalized_cpp_grpo import DEFAULT_REGISTRY, BindingError, TaskRegistry
from Reward_GRPO.topic_coverage.specs import TOPICS

PACKAGE = Path(__file__).resolve().parent
PROBES = PACKAGE / "probes"
FLAGS = ("-std=c++17", "-Wall", "-Wextra", "-Wpedantic", "-Werror", "-pthread")
MARKER = "TOPIC_COVERAGE_RECEIPT "
MAX_SOURCE_BYTES = 1024 * 1024


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_hashes(sources: Mapping[str, str]) -> dict[str, str]:
    return {name: hashlib.sha256(text.encode()).hexdigest() for name, text in sources.items()}


def write_json(path: Path, payload: Any) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def plain_directory(path: Path) -> Path:
    path = path.absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("symlink directory is not allowed")
    return path.resolve(strict=False)


def candidate_sources(task_id: str, directory: Path) -> dict[str, str]:
    if task_id not in TOPICS:
        raise ValueError("unsupported topic")
    directory = plain_directory(directory)
    stem = task_id.replace("-", "_")
    result = {}
    for name in (f"{stem}.h", f"{stem}.cpp"):
        path = directory / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_SOURCE_BYTES:
            raise ValueError(f"missing, oversized or unsafe candidate file: {name}")
        result[name] = path.read_text(encoding="utf-8")
    return result


def reference_sources(binding: Any) -> dict[str, str]:
    sources = {}
    for name in binding.manifest["candidate_files"]:
        reference = binding.fixture_dir / ".meta" / f"example{Path(name).suffix}"
        sources[name] = (
            reference if reference.is_file() else binding.starter_dir / name
        ).read_text(encoding="utf-8")
    return sources


def control_sources(binding: Any, task_id: str) -> dict[str, str]:
    """Use a versioned control when the pinned fixture reference has a known bug."""
    location = TOPICS[task_id].reference_control if task_id in TOPICS else None
    if location is None:
        return reference_sources(binding)
    return {name: (PACKAGE / location / name).read_text(encoding="utf-8")
            for name in binding.manifest["candidate_files"]}


def response_from_sources(sources: Mapping[str, str]) -> str:
    fence = chr(96) * 3
    return "\n\n".join(f"{name}\n{fence}cpp\n{text.rstrip()}\n{fence}" for name, text in sources.items())


def parse_result(command: Mapping[str, Any], group: str) -> dict[str, Any]:
    if command.get("launch_error"):
        return {"group": group, "status": "invalid", "reason": "process_launch_failed"}
    if command["timed_out"]:
        return {"group": group, "status": "fail", "reason": "runtime_timeout"}
    # Accept unrelated candidate stdout, but require exactly one complete protocol receipt.
    rows = [line[len(MARKER):] for line in command["stdout_tail"].splitlines()
            if line.startswith(MARKER)]
    try:
        if len(rows) != 1:
            raise ValueError("missing or duplicate probe receipt")
        data = json.loads(rows[0])
        if not isinstance(data, dict):
            raise ValueError("probe receipt must be an object")
        count = data.get("checks")
        if (data.get("protocol") != "topic-coverage-v1" or data.get("group") != group
                or data.get("status") not in {"pass", "fail"}
                or type(count) is not int or count < 0
                or (data["status"] == "pass" and count == 0)):
            raise ValueError("invalid probe receipt fields")
        expected_exit = 0 if data["status"] == "pass" else 1
        if command["returncode"] != expected_exit:
            raise ValueError("probe receipt and process exit disagree")
        return data
    except (ValueError, TypeError, KeyError) as error:
        return {"group": group, "status": "fail", "reason": "probe_protocol_failure",
                "detail": str(error), "returncode": command["returncode"]}


def aggregate_group(group: str, runs: list[dict], *, diagnostic: bool = False,
                    variable_sampling: bool = False) -> dict:
    statuses = [item["status"] for item in runs]
    status = "invalid" if "invalid" in statuses else "fail" if "fail" in statuses else "pass"
    signatures = [{key: item.get(key) for key in ("status", "checks", "requirement", "reason")}
                  for item in runs]
    repeatable = all(item == signatures[0] for item in signatures)
    # Fresh random draws are not identical test inputs. A concrete rule violation
    # remains a failure even when a later run encounters it at a different sample.
    if status != "invalid" and not repeatable and not variable_sampling and not diagnostic:
        # A healthy reference makes inconsistent candidate failures attributable
        # to the candidate, not an infrastructure error that earns neutral reward.
        status = "fail"
    item = {"group": group, "status": status, "repeatable": repeatable, "runs": runs,
            "sampling": "fresh_candidate_randomness" if variable_sampling else "fixed_inputs"}
    if not repeatable and not variable_sampling and not diagnostic:
        item["reason"] = "inconsistent_candidate_outcomes"
    if diagnostic:
        item["role"] = "diagnostic_only"
        item["warning"] = status != "pass" or any(
            run.get("observations", {}).get("suspicious_constant_output") == "true" for run in runs
        )
    return item


class AuditSession:
    """Compile the reference once; audit multiple immutable candidates sequentially."""

    def __init__(
        self, task_id: str, output_dir: Path, *, registry_path: Path = DEFAULT_REGISTRY,
        compiler: str = "g++", include_diagnostics: bool = False,
        repeats: int = 2, compile_timeout: float = 90, run_timeout: float = 30,
        allow_local_execution: bool = False,
    ) -> None:
        if not allow_local_execution:
            raise ValueError("local execution requires explicit acknowledgement")
        if task_id not in TOPICS:
            raise ValueError("unsupported topic")
        if type(repeats) is not int or not 1 <= repeats <= 5:
            raise ValueError("repeats must be between 1 and 5")
        for value in (compile_timeout, run_timeout):
            if not math.isfinite(value) or not 0 < value <= 300:
                raise ValueError("timeouts must be finite and in (0,300]")
        self.registry = TaskRegistry(registry_path)
        self.binding = self.registry.resolve(task_id)
        stem = task_id.replace("-", "_")
        if set(self.binding.manifest["candidate_files"]) != {f"{stem}.h", f"{stem}.cpp"}:
            raise ValueError("topic requires the canonical header/source pair")
        self.task_id, self.topic = task_id, TOPICS[task_id]
        self.output = plain_directory(output_dir)
        for protected in (self.binding.fixture_dir, self.binding.starter_dir, PROBES,
                          DEFAULT_REGISTRY.parent / "multi_env_fixtures"):
            if self.output == protected or protected in self.output.parents:
                raise ValueError("output must be outside protected input directories")
        if self.output.exists():
            raise ValueError("audit output must be a new directory; receipts are never overwritten")
        self.output.mkdir(parents=True)
        self.compiler = shutil.which(compiler) or compiler
        self.include_diagnostics = include_diagnostics
        self.repeats, self.compile_timeout, self.run_timeout = repeats, compile_timeout, run_timeout
        self.groups = self.topic.groups + (self.topic.diagnostics if include_diagnostics else ())
        self.temp = TemporaryDirectory(prefix="cpp-topic-coverage-")
        self.work = Path(self.temp.name)
        self.registry_hash = sha256(self.registry.path)
        self.pack_hashes = {
            path.relative_to(PACKAGE).as_posix(): sha256(path)
            for path in sorted(PACKAGE.rglob("*"))
            if path.is_file() and path.suffix in {".py", ".cpp", ".hpp", ".h"}
            and "__pycache__" not in path.parts
        }
        self.reference: dict[str, Any] = {}
        self.version: dict[str, Any] = {}

    def __enter__(self) -> AuditSession:
        try:
            self.version = self._command([self.compiler, "--version"], self.output, "compiler", 10)
            if self.version.get("launch_error") or self.version["returncode"] != 0:
                self.reference = {"status": "invalid", "reason": "compiler_unavailable"}
            else:
                self.reference = self._execute(control_sources(self.binding, self.task_id), "reference")
            write_json(self.output / "reference.json", self.reference)
            return self
        except BaseException:
            self.temp.cleanup()
            raise

    def __exit__(self, *args: Any) -> None:
        self.temp.cleanup()

    def _command(self, argv: list[str], directory: Path, label: str, timeout: float,
                 *, file_limit_mb: int = 4) -> dict:
        directory.mkdir(parents=True, exist_ok=True)
        stdout_path, stderr_path = directory / f"{label}.stdout", directory / f"{label}.stderr"
        started = time.monotonic()
        command = [sys.executable, str(PACKAGE / "limited_exec.py"),
                   str(math.ceil(timeout)), "4096", str(file_limit_mb), *argv]
        record: dict[str, Any] = {"argv": argv, "returncode": None, "timed_out": False}
        # Credentials and user-specific compiler/include overrides are not forwarded.
        environment = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C", "LC_ALL": "C",
                       "TMPDIR": str(self.work), "PYTHONDONTWRITEBYTECODE": "1"}
        try:
            with stdout_path.open("xb") as out, stderr_path.open("xb") as err:
                proc = subprocess.Popen(
                    command, cwd=self.work, env=environment, stdin=subprocess.DEVNULL,
                    stdout=out, stderr=err, start_new_session=True,
                )
                try:
                    proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    record["timed_out"] = True
                finally:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    proc.wait()
                record["returncode"] = proc.returncode
        except OSError as error:
            record["launch_error"] = type(error).__name__
        record["elapsed_seconds"] = round(time.monotonic() - started, 6)
        for kind, path in (("stdout", stdout_path), ("stderr", stderr_path)):
            record[f"{kind}_path"] = str(path)
            record[f"{kind}_sha256"] = sha256(path) if path.exists() else None
            record[f"{kind}_tail"] = (
                path.read_bytes()[-24000:].decode("utf-8", errors="replace") if path.exists() else ""
            )
        return record

    def _execute(self, sources: Mapping[str, str], label: str) -> dict[str, Any]:
        if not re.fullmatch(r"[a-z0-9_-]+", label):
            raise ValueError("unsafe control label")
        names = set(self.binding.manifest["candidate_files"])
        if set(sources) != names or any(len(text.encode()) > MAX_SOURCE_BYTES for text in sources.values()):
            raise ValueError("candidate must contain exactly the two registered editable files")
        directory = self.work / label
        directory.mkdir()
        evidence = self.output / label
        evidence.mkdir()
        for name, text in sources.items():
            (directory / name).write_text(text, encoding="utf-8")
        # Copy trusted probes after the candidate pair, not from a candidate-controlled directory.
        shutil.copy2(PROBES / "coverage.hpp", directory / "coverage.hpp")
        shutil.copy2(PROBES / f"{self.task_id}.cpp", directory / "coverage_probe.cpp")
        auxiliary = []
        for name in self.topic.auxiliary_sources:
            shutil.copy2(PROBES / name, directory / name)
            auxiliary.append(str(directory / name))
        executable = directory / "coverage_probe"
        build = self._command(
            [self.compiler, *FLAGS, "-I", str(directory), str(directory / "coverage_probe.cpp"),
             str(directory / f"{self.task_id.replace('-', '_')}.cpp"), *auxiliary, "-o", str(executable)],
            evidence, "build", self.compile_timeout,
        )
        record: dict[str, Any] = {"build": build, "source_sha256": source_hashes(sources),
                                  "groups": [], "diagnostics": []}
        if build["returncode"] != 0 or build["timed_out"]:
            record.update(status="invalid" if build["timed_out"] or build.get("launch_error") else "fail",
                          reason="build_timeout" if build["timed_out"] else "build_failure")
            return record
        for group in self.groups:
            repetitions = 1 if group in self.topic.diagnostics else self.repeats
            runs = []
            for repeat in range(repetitions):
                command = self._command([str(executable), group], evidence,
                                        f"{group}-{repeat}", self.run_timeout)
                result = parse_result(command, group)
                result["command"] = command
                runs.append(result)
            item = aggregate_group(
                group, runs, diagnostic=group in self.topic.diagnostics,
                variable_sampling=group in self.topic.variable_sampling_groups,
            )
            if group in self.topic.diagnostics:
                record["diagnostics"].append(item)
            else:
                record["groups"].append(item)
        unchanged = all(sha256(directory / name) == digest
                        for name, digest in record["source_sha256"].items())
        record["candidate_source_unchanged"] = unchanged
        statuses = [item["status"] for item in record["groups"]]
        record["status"] = ("invalid" if not unchanged or "invalid" in statuses else
                            "fail" if "fail" in statuses else "pass")
        record["reason"] = "topic_checks" if unchanged else "source_changed_during_audit"
        return record

    def audit(self, sources: Mapping[str, str], label: str = "candidate") -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": 1, "task_id": self.task_id, "audit_only": True,
            "changes_grpo_reward": False, "full_task_correctness_claim": False,
            "scope": asdict(self.topic), "registry_sha256": self.registry_hash,
            "manifest_sha256": self.binding.manifest_sha256, "pack_sha256": self.pack_hashes,
            "compiler": self.version, "reference_status": self.reference["status"],
            "reference_control": self.topic.reference_control or "pinned_fixture/.meta/example",
        }
        if self.reference["status"] != "pass":
            payload.update(status="invalid", reason="reference_control_failed")
        else:
            try:
                if sha256(self.registry.path) != self.registry_hash:
                    raise ValueError("registry changed during audit")
                self.registry.resolve(self.task_id)
                for name, digest in self.pack_hashes.items():
                    if sha256(PACKAGE / name) != digest:
                        raise ValueError("coverage pack changed during audit")
                payload["candidate"] = self._execute(sources, label)
                self.registry.resolve(self.task_id)
                payload.update(status=payload["candidate"]["status"],
                               reason=payload["candidate"]["reason"])
            except (BindingError, OSError, ValueError) as error:
                payload.update(status="invalid", reason="binding_or_audit_failure", detail=str(error))
        write_json(self.output / f"{label}.json", payload)
        return payload

    def compare_generalized(
        self, sources: Mapping[str, str], *, raw_response: str | None = None
    ) -> dict[str, Any]:
        """Run the unchanged baseline in a separate credential-free process."""
        request = self.work / "generalized-request.json"
        response = self.work / "generalized-result.json"
        write_json(request, {
            "metadata": {"problem_id": self.task_id,
                         "generalized_verifier_manifest_sha256": self.binding.manifest_sha256},
            "response": raw_response if raw_response is not None else response_from_sources(sources),
        })
        command = self._command(
            [sys.executable, str(PACKAGE / "compare_worker.py"), str(request), str(response),
             str(self.registry.path)], self.output, "generalized-comparison", 240,
            file_limit_mb=128,  # Catch's object files exceed the lightweight probe's 4 MiB cap.
        )
        if command["returncode"] != 0 or command["timed_out"] or not response.is_file():
            result = {"reason": "comparison_invalid", "infrastructure_error": True}
        else:
            result = json.loads(response.read_text(encoding="utf-8"))
        write_json(self.output / "generalized.json", result)
        write_json(self.output / "generalized-command.json", command)
        return result
