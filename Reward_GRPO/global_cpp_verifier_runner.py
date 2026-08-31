"""Run the global C++ verifier package directly from one authenticated manifest.

This entry point deliberately has no multi-environment registry dependency.  A
caller supplies the candidate, the trusted manifest and its out-of-band digest,
and chooses either the semantic live gate or the complete diagnostic profile.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile
from types import ModuleType
from typing import Any, BinaryIO, Sequence


SHA256 = re.compile(r"[0-9a-f]{64}")
PROFILE_POLICIES = {
    "live": ("G01", "G02", "G03", "G04", "G05"),
    "full": ("G01", "G02", "G03", "G04", "G05", "G06", "G07"),
}
SEMANTIC_POLICIES = ("G01", "G02", "G03", "G04", "G05")
DIAGNOSTIC_POLICIES = ("G06", "G07")
PACKAGE = Path("Generalized Cpp Verifiers")
AGGREGATE_RECEIPT = "global_cpp_verification_receipt.json"
MAX_WRAPPER_LOG_BYTES = 1024 * 1024


class RunnerError(ValueError):
    """The evaluator could not establish trustworthy verification evidence."""


@dataclass(frozen=True)
class Prepared:
    candidate_dir: Path
    manifest_path: Path
    output_dir: Path
    reward_root: Path
    manifest: dict[str, Any]
    manifest_sha256: str
    candidate_sha256: str
    validator_path: Path
    common_path: Path
    schema_path: Path
    wrappers: dict[str, Path]


@dataclass(frozen=True)
class CapturedProcess:
    return_code: int
    stdout: bytes
    stderr: bytes
    stdout_bytes: int
    stderr_bytes: int
    stdout_sha256: str
    stderr_sha256: str


def _sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _drain_bounded(
    stream: BinaryIO,
    destination: dict[str, tuple[bytes, int, str, OSError | None]],
    key: str,
) -> None:
    digest = hashlib.sha256()
    tail = bytearray()
    total = 0
    error: OSError | None = None
    try:
        for block in iter(lambda: stream.read(64 * 1024), b""):
            digest.update(block)
            total += len(block)
            if len(block) >= MAX_WRAPPER_LOG_BYTES:
                tail = bytearray(block[-MAX_WRAPPER_LOG_BYTES:])
            else:
                tail.extend(block)
                overflow = len(tail) - MAX_WRAPPER_LOG_BYTES
                if overflow > 0:
                    del tail[:overflow]
    except OSError as caught:
        error = caught
    finally:
        stream.close()
    destination[key] = (bytes(tail), total, digest.hexdigest(), error)


def _capture_process(command: list[str], env: dict[str, str]) -> CapturedProcess:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    if process.stdout is None or process.stderr is None:  # pragma: no cover
        process.kill()
        process.wait()
        raise OSError("wrapper output pipes are unavailable")
    captured: dict[str, tuple[bytes, int, str, OSError | None]] = {}
    threads = [
        threading.Thread(
            target=_drain_bounded, args=(process.stdout, captured, "stdout")
        ),
        threading.Thread(
            target=_drain_bounded, args=(process.stderr, captured, "stderr")
        ),
    ]
    for thread in threads:
        thread.start()
    return_code = process.wait()
    for thread in threads:
        thread.join()
    stdout, stdout_bytes, stdout_sha256, stdout_error = captured["stdout"]
    stderr, stderr_bytes, stderr_sha256, stderr_error = captured["stderr"]
    if stdout_error is not None or stderr_error is not None:
        raise OSError(f"wrapper output capture failed: {stdout_error or stderr_error}")
    return CapturedProcess(
        return_code,
        stdout,
        stderr,
        stdout_bytes,
        stderr_bytes,
        stdout_sha256,
        stderr_sha256,
    )

def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _assert_no_symlinks(path: Path, label: str) -> Path:
    absolute = _absolute(path)
    for cursor in reversed((absolute, *absolute.parents)):
        if cursor.is_symlink():
            raise RunnerError(f"{label} uses a symlink: {cursor}")
    return absolute


def _regular_file(path: Path, label: str) -> Path:
    absolute = _assert_no_symlinks(path, label)
    if not absolute.is_file():
        raise RunnerError(f"{label} is unavailable or not a regular file")
    return absolute.resolve()


def _regular_directory(path: Path, label: str) -> Path:
    absolute = _assert_no_symlinks(path, label)
    if not absolute.is_dir():
        raise RunnerError(f"{label} is unavailable or not a regular directory")
    return absolute.resolve()


def _prepare_output(args: argparse.Namespace) -> Path:
    output = _assert_no_symlinks(args.output_dir, "output directory")
    candidate = _assert_no_symlinks(args.candidate_dir, "candidate directory")
    manifest = _assert_no_symlinks(args.manifest, "manifest")
    reward_root = _assert_no_symlinks(args.reward_root, "reward root")
    if output == candidate or output.is_relative_to(candidate):
        raise RunnerError("output directory must be outside candidate source")
    if output == manifest or output == manifest.parent:
        raise RunnerError("output directory has an unsafe relationship to manifest")
    if output == reward_root or output.is_relative_to(reward_root):
        raise RunnerError("output directory must be outside the trusted reward root")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise RunnerError("output directory must be absent or empty")
    output.mkdir(parents=True, exist_ok=True)
    return output.resolve()


def _trusted_assets(reward_root: Path) -> tuple[Path, Path, Path, Path]:
    package = _regular_directory(reward_root / PACKAGE, "global verifier package")
    verifier_dir = _regular_directory(package / "verifiers", "global verifier directory")
    validator = _regular_file(
        verifier_dir / "_manifest_validation.py", "manifest validator"
    )
    common = _regular_file(verifier_dir / "_global_common.py", "global verifier common")
    schema = _regular_file(
        package / "global_verifier_manifest.schema.json", "manifest schema"
    )
    return verifier_dir, validator, common, schema


def _load_validator(path: Path) -> ModuleType:
    name = f"_direct_global_cpp_manifest_validation_{_sha256(path)}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RunnerError("manifest validator cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as error:
        raise RunnerError(f"manifest validator cannot be loaded: {error}") from error
    if not callable(getattr(module, "validate_manifest", None)):
        raise RunnerError("manifest validator has no validate_manifest entry point")
    return module


def _resolve_wrapper(verifier_dir: Path, policy_id: str) -> Path:
    number = int(policy_id[1:])
    matches = sorted(verifier_dir.glob(f"verifier_{number:02d}_*.py"))
    if len(matches) != 1:
        raise RunnerError(
            f"expected exactly one verifier wrapper for {policy_id}, found {len(matches)}"
        )
    return _regular_file(matches[0], f"{policy_id} verifier wrapper")


def _candidate_file(root: Path, relative: str) -> Path:
    value = PurePosixPath(relative)
    raw = root.joinpath(*value.parts)
    cursor = raw
    while cursor != root:
        if cursor.is_symlink():
            raise RunnerError(f"candidate file uses a symlink: {relative}")
        cursor = cursor.parent
    resolved = raw.resolve()
    if resolved == root or root not in resolved.parents or not resolved.is_file():
        raise RunnerError(f"candidate file is unavailable: {relative}")
    return resolved


def _candidate_digest(root: Path, relatives: list[str]) -> str:
    value = hashlib.sha256()
    for relative in sorted(relatives):
        path = _candidate_file(root, relative)
        value.update(relative.encode("utf-8"))
        value.update(b"\0")
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                value.update(block)
        value.update(b"\0")
    return value.hexdigest()


def _prepare(args: argparse.Namespace, output: Path) -> Prepared:
    if SHA256.fullmatch(args.expected_manifest_sha256) is None:
        raise RunnerError("expected manifest digest is malformed")
    candidate = _regular_directory(args.candidate_dir, "candidate directory")
    manifest_path = _regular_file(args.manifest, "manifest")
    reward_root = _regular_directory(args.reward_root, "reward root")
    if manifest_path.is_relative_to(candidate):
        raise RunnerError("trusted manifest must be outside candidate source")

    observed_manifest = _sha256(manifest_path)
    if observed_manifest != args.expected_manifest_sha256:
        raise RunnerError("trusted manifest digest does not match")

    verifier_dir, validator_path, common_path, schema_path = _trusted_assets(
        reward_root
    )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RunnerError(f"manifest is not valid JSON: {error}") from error
    validator = _load_validator(validator_path)
    try:
        validator.validate_manifest(manifest)
    except Exception as error:
        raise RunnerError(f"manifest validation failed: {error}") from error

    requested = PROFILE_POLICIES[args.profile]
    policies = manifest.get("policies")
    if not isinstance(policies, dict):
        raise RunnerError("manifest policy map is invalid")
    missing = [policy for policy in requested if policy != "G01" and policy not in policies]
    if missing:
        raise RunnerError(
            "manifest lacks policies required by profile: " + ", ".join(missing)
        )
    wrappers = {
        policy: _resolve_wrapper(verifier_dir, policy) for policy in requested
    }
    candidate_files = manifest.get("candidate_files")
    if not isinstance(candidate_files, list) or not all(
        isinstance(item, str) for item in candidate_files
    ):
        raise RunnerError("manifest candidate_files is invalid")
    candidate_sha256 = _candidate_digest(candidate, candidate_files)
    return Prepared(
        candidate,
        manifest_path,
        output,
        reward_root,
        manifest,
        observed_manifest,
        candidate_sha256,
        validator_path,
        common_path,
        schema_path,
        wrappers,
    )


def _status(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"pass", "passed"}:
        return "pass"
    if normalized in {"fail", "failed"}:
        return "fail"
    if normalized == "invalid":
        return "invalid"
    return "invalid"


def _valid_duration(value: Any) -> bool:
    return value is None or (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _normalize_kernel(
    policy_id: str, index: int, raw: Any
) -> tuple[dict[str, Any] | None, list[str]]:
    if not isinstance(raw, dict):
        return None, [f"kernel {index} is not an object"]
    errors: list[str] = []
    verdict = _status(raw.get("status") or raw.get("verdict"))
    value = raw.get("kernel", raw.get("score"))
    # A wrapper may mark a kernel not_run (e.g. G03's candidate kernel when
    # G02 already scored the build failure): value must be null and the
    # kernel is excluded from kernel_sum, not an invalid-kernel error.
    if str(raw.get("status") or "").strip().lower() == "not_run" and value is None:
        verdict = "not_run"
        expected_value = None
    else:
        expected_value = {"pass": 1, "fail": -1, "invalid": None}[verdict]
    if value != expected_value or isinstance(value, bool):
        errors.append(f"kernel {index} verdict/value mismatch")
        verdict = "invalid"
        value = None
    command = raw.get("command")
    if command is not None and not (
        isinstance(command, list) and all(isinstance(item, str) for item in command)
    ):
        errors.append(f"kernel {index} command is malformed")
        command = None
    duration = raw.get("duration_seconds")
    if not _valid_duration(duration):
        errors.append(f"kernel {index} duration is malformed")
        duration = None
    facts = raw.get("facts")
    if not isinstance(facts, dict):
        errors.append(f"kernel {index} facts are malformed")
        facts = {}
    return (
        {
            "kernel_id": str(raw.get("kernel_id") or f"{policy_id}-{index}"),
            "kernel": value,
            "status": verdict,
            "summary": str(raw.get("summary") or ""),
            "facts": facts,
            "command": command,
            "duration_seconds": duration,
            "stdout_log": raw.get("stdout_log")
            if isinstance(raw.get("stdout_log"), str)
            else None,
            "stderr_log": raw.get("stderr_log")
            if isinstance(raw.get("stderr_log"), str)
            else None,
        },
        errors,
    )


def _receipt_fact_fields(receipt: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "generated_at",
        "verifier_source_sha256",
        "verifier_wrapper_sha256",
        "verifier_common_sha256",
        "manifest_schema_sha256",
        "manifest_sha256",
        "candidate_source_sha256",
        "candidate_source_sha256_before",
        "candidate_source_sha256_after",
        "candidate_source_unchanged",
        "excluded_conditions",
        "reason",
    )
    return {field: receipt.get(field) for field in fields}


def _normalize_receipt(
    policy_id: str,
    receipt: Any,
    prepared: Prepared,
    wrapper_sha256: str,
) -> dict[str, Any]:
    if not isinstance(receipt, dict):
        raise RunnerError("verifier receipt is not a JSON object")
    errors: list[str] = []
    receipt_status = _status(receipt.get("status") or receipt.get("overall_status"))
    if receipt.get("schema_version") != 2:
        errors.append("unsupported verifier receipt schema")
    if receipt.get("task_id") != prepared.manifest.get("task_id"):
        errors.append("receipt task identity mismatch")
    if receipt.get("policy_id") != policy_id:
        errors.append("receipt policy identity mismatch")

    raw_kernels = receipt.get("kernel_results")
    if not isinstance(raw_kernels, list):
        raw_kernels = receipt.get("kernels")
    if not isinstance(raw_kernels, list) or not raw_kernels:
        errors.append("receipt has no kernel results")
        raw_kernels = []
    kernels: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_kernels, start=1):
        kernel, kernel_errors = _normalize_kernel(policy_id, index, raw)
        errors.extend(kernel_errors)
        if kernel is not None:
            kernels.append(kernel)

    numeric = [item for item in kernels if item["kernel"] in {-1, 1}]
    computed_sum = sum(int(item["kernel"]) for item in numeric)
    computed_total = len(numeric)
    if receipt_status == "invalid":
        if receipt.get("kernel_sum") is not None:
            errors.append("invalid receipt has a numeric kernel sum")
        maximum = receipt.get("maximum_kernel_sum")
        if (
            not isinstance(maximum, int)
            or isinstance(maximum, bool)
            or maximum != computed_total
        ):
            errors.append("invalid receipt kernel maximum is inconsistent")
        normalized_sum: int | None = None
    else:
        if any(item["status"] == "invalid" for item in kernels):
            errors.append("non-invalid receipt contains an invalid kernel")
        derived = "pass" if numeric and computed_sum == computed_total else "fail"
        if receipt_status != derived:
            errors.append("receipt status disagrees with kernel verdicts")
        raw_sum = receipt.get("kernel_sum")
        raw_maximum = receipt.get("maximum_kernel_sum")
        if (
            not isinstance(raw_sum, int)
            or isinstance(raw_sum, bool)
            or raw_sum != computed_sum
        ):
            errors.append("receipt kernel sum is inconsistent")
        if (
            not isinstance(raw_maximum, int)
            or isinstance(raw_maximum, bool)
            or raw_maximum != computed_total
        ):
            errors.append("receipt kernel maximum is inconsistent")
        normalized_sum = computed_sum

    expected_hashes = {
        "verifier_source_sha256": wrapper_sha256,
        "verifier_wrapper_sha256": wrapper_sha256,
        "verifier_common_sha256": _sha256(prepared.common_path),
        "manifest_schema_sha256": _sha256(prepared.schema_path),
        "manifest_sha256": prepared.manifest_sha256,
    }
    for field, expected in expected_hashes.items():
        observed = receipt.get(field)
        if not isinstance(observed, str) or SHA256.fullmatch(observed) is None:
            errors.append(f"receipt {field} is missing or malformed")
        elif observed != expected:
            errors.append(f"receipt {field} mismatch")

    if receipt_status != "invalid":
        before = receipt.get("candidate_source_sha256_before")
        primary = receipt.get("candidate_source_sha256")
        after = receipt.get("candidate_source_sha256_after")
        if before != prepared.candidate_sha256 or primary != prepared.candidate_sha256:
            errors.append("receipt candidate source-before hash mismatch")
        if after != prepared.candidate_sha256:
            errors.append("receipt candidate source-after hash mismatch")
        if receipt.get("candidate_source_unchanged") is not True:
            errors.append("receipt does not authenticate unchanged candidate source")

    status = "invalid" if errors else receipt_status
    return {
        "policy_id": policy_id,
        "status": status,
        "kernel_sum": None if status == "invalid" else normalized_sum,
        "kernel_total": computed_total,
        "kernels": kernels,
        "receipt_schema_version": receipt.get("schema_version"),
        **_receipt_fact_fields(receipt),
        **({"receipt_errors": errors} if errors else {}),
    }


def _invalid_policy(policy_id: str, reason: str, **facts: Any) -> dict[str, Any]:
    return {
        "policy_id": policy_id,
        "status": "invalid",
        "kernel_sum": None,
        "kernel_total": 0,
        "kernels": [],
        "receipt_error": reason,
        **facts,
    }


def _not_run_policy(policy_id: str, blocked_by: str) -> dict[str, Any]:
    return {
        "policy_id": policy_id,
        "status": "not_run",
        "kernel_sum": None,
        "kernel_total": 0,
        "kernels": [],
        "blocked_by_policy": blocked_by,
        "excluded_reason": f"{blocked_by} prerequisite did not pass",
        "return_code": None,
        "duration_seconds": None,
    }


def _run_policy(prepared: Prepared, policy_id: str) -> dict[str, Any]:
    wrapper = prepared.wrappers[policy_id]
    wrapper_sha256 = _sha256(wrapper)
    policy_output = prepared.output_dir / policy_id.lower()
    stdout_path = prepared.output_dir / f"{policy_id.lower()}.stdout.log"
    stderr_path = prepared.output_dir / f"{policy_id.lower()}.stderr.log"
    command = [
        sys.executable,
        str(wrapper),
        "--candidate-dir",
        str(prepared.candidate_dir),
        "--manifest",
        str(prepared.manifest_path),
        "--expected-manifest-sha256",
        prepared.manifest_sha256,
        "--output-dir",
        str(policy_output),
    ]
    started = time.monotonic()
    try:
        completed = _capture_process(
            command,
            {
                **os.environ,
                "LC_ALL": "C",
                "LANG": "C",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
    except OSError as error:
        duration = round(time.monotonic() - started, 6)
        return _invalid_policy(
            policy_id,
            f"verifier wrapper could not be executed: {error}",
            return_code=None,
            duration_seconds=duration,
            verifier_path=str(wrapper.relative_to(prepared.reward_root)),
            verifier_sha256=wrapper_sha256,
        )
    duration = round(time.monotonic() - started, 6)
    stdout_path.write_bytes(completed.stdout)
    stderr_path.write_bytes(completed.stderr)
    execution_facts = {
        "return_code": completed.return_code,
        "duration_seconds": duration,
        "verifier_path": str(wrapper.relative_to(prepared.reward_root)),
        "verifier_sha256": wrapper_sha256,
        "stdout_log": stdout_path.name,
        "stderr_log": stderr_path.name,
        "stdout_sha256": completed.stdout_sha256,
        "stderr_sha256": completed.stderr_sha256,
        "stdout_log_sha256": _sha256(stdout_path),
        "stderr_log_sha256": _sha256(stderr_path),
        "stdout_bytes": completed.stdout_bytes,
        "stderr_bytes": completed.stderr_bytes,
        "stdout_captured_bytes": len(completed.stdout),
        "stderr_captured_bytes": len(completed.stderr),
        "stdout_truncated": completed.stdout_bytes > len(completed.stdout),
        "stderr_truncated": completed.stderr_bytes > len(completed.stderr),
    }
    receipt_path = policy_output / "verification_receipt.json"
    if not receipt_path.is_file() or receipt_path.is_symlink():
        return _invalid_policy(
            policy_id,
            "verifier did not produce a regular receipt",
            **execution_facts,
        )
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        normalized = _normalize_receipt(
            policy_id, receipt, prepared, wrapper_sha256
        )
    except (OSError, UnicodeError, json.JSONDecodeError, RunnerError) as error:
        return _invalid_policy(
            policy_id, f"verifier receipt is invalid: {error}", **execution_facts
        )
    normalized.update(
        **execution_facts,
        receipt_path=str(receipt_path.relative_to(prepared.output_dir)),
        receipt_sha256=_sha256(receipt_path),
    )
    expected_return = {"pass": 0, "fail": 1, "invalid": 2}[normalized["status"]]
    if completed.return_code != expected_return:
        normalized["status"] = "invalid"
        normalized["kernel_sum"] = None
        normalized.setdefault("receipt_errors", []).append(
            "wrapper return code disagrees with normalized receipt status"
        )
    return normalized


def _aggregate(results: dict[str, dict[str, Any]], policies: Sequence[str]) -> str:
    statuses = [results[policy]["status"] for policy in policies]
    if any(status == "invalid" for status in statuses):
        return "invalid"
    if any(status == "fail" for status in statuses):
        return "fail"
    if statuses and all(status == "pass" for status in statuses):
        return "pass"
    return "not_run"


def _base_payload(args: argparse.Namespace) -> dict[str, Any]:
    requested = list(PROFILE_POLICIES[args.profile])
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "profile": args.profile,
        "requested_policies": requested,
        "semantic_policies": list(SEMANTIC_POLICIES),
        "diagnostic_policies": list(DIAGNOSTIC_POLICIES)
        if args.profile == "full"
        else [],
    }


def _write_payload(output: Path, payload: dict[str, Any]) -> Path:
    receipt = output / AGGREGATE_RECEIPT
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=output,
            prefix=f".{AGGREGATE_RECEIPT}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, receipt)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return receipt


def _setup_invalid(
    args: argparse.Namespace, output: Path, error: Exception, started: float
) -> int:
    payload = {
        **_base_payload(args),
        "task_id": None,
        "source": None,
        "status": "invalid",
        "semantic_status": "invalid",
        "semantic_pass": False,
        "diagnostic_status": None if args.profile == "live" else "not_run",
        "diagnostic_pass": None if args.profile == "live" else False,
        "official_functional_status": "not_run",
        "profile_pass": False,
        "full_pass": None if args.profile == "live" else False,
        "executed_policies": [],
        "not_run_policies": list(PROFILE_POLICIES[args.profile]),
        "policy_results": [],
        "manifest_sha256": None,
        "expected_manifest_sha256": args.expected_manifest_sha256,
        "candidate_source_sha256_before": None,
        "candidate_source_sha256_after": None,
        "candidate_source_unchanged": None,
        "duration_seconds": round(time.monotonic() - started, 6),
        "infrastructure_error": f"{type(error).__name__}: {error}",
    }
    receipt = _write_payload(output, payload)
    print(json.dumps({"status": "invalid", "receipt": str(receipt)}, sort_keys=True))
    return 2


def run(args: argparse.Namespace) -> int:
    started = time.monotonic()
    output = _prepare_output(args)
    try:
        prepared = _prepare(args, output)
    except (OSError, UnicodeError, RunnerError) as error:
        return _setup_invalid(args, output, error, started)

    requested = list(PROFILE_POLICIES[args.profile])
    results: dict[str, dict[str, Any]] = {}
    executed: list[str] = []
    source_changed = False
    for policy_id in requested:
        if policy_id != "G01" and results["G01"]["status"] != "pass":
            results[policy_id] = _not_run_policy(policy_id, "G01")
            continue
        if source_changed:
            results[policy_id] = _not_run_policy(policy_id, executed[-1])
            continue
        result = _run_policy(prepared, policy_id)
        results[policy_id] = result
        executed.append(policy_id)
        try:
            observed_source = _candidate_digest(
                prepared.candidate_dir, prepared.manifest["candidate_files"]
            )
        except (OSError, RunnerError) as error:
            observed_source = None
            result["status"] = "invalid"
            result["kernel_sum"] = None
            result.setdefault("receipt_errors", []).append(
                f"candidate source cannot be authenticated after wrapper: {error}"
            )
        if observed_source != prepared.candidate_sha256:
            source_changed = True
            result["status"] = "invalid"
            result["kernel_sum"] = None
            result.setdefault("receipt_errors", []).append(
                "candidate source changed across direct verification"
            )

    semantic_status = _aggregate(results, SEMANTIC_POLICIES)
    diagnostic_status = (
        _aggregate(results, DIAGNOSTIC_POLICIES)
        if args.profile == "full"
        else None
    )
    executed_statuses = [results[policy]["status"] for policy in executed]
    status = (
        "invalid"
        if any(value == "invalid" for value in executed_statuses)
        else "fail"
        if any(value == "fail" for value in executed_statuses)
        else "pass"
        if len(executed) == len(requested)
        and all(value == "pass" for value in executed_statuses)
        else "fail"
    )
    profile_pass = status == "pass"
    try:
        candidate_after = _candidate_digest(
            prepared.candidate_dir, prepared.manifest["candidate_files"]
        )
    except (OSError, RunnerError):
        candidate_after = None
    source_unchanged = candidate_after == prepared.candidate_sha256
    if not source_unchanged:
        status = "invalid"
        semantic_status = "invalid"
        profile_pass = False

    payload = {
        **_base_payload(args),
        "task_id": prepared.manifest["task_id"],
        "source": prepared.manifest.get("source"),
        "status": status,
        "semantic_status": semantic_status,
        "semantic_pass": semantic_status == "pass",
        "diagnostic_status": diagnostic_status,
        "diagnostic_pass": (
            diagnostic_status == "pass" if args.profile == "full" else None
        ),
        "official_functional_status": results["G03"]["status"],
        "profile_pass": profile_pass,
        "full_pass": profile_pass if args.profile == "full" else None,
        "executed_policies": executed,
        "not_run_policies": [
            policy for policy in requested if results[policy]["status"] == "not_run"
        ],
        "policy_results": [results[policy] for policy in requested],
        "manifest_sha256": prepared.manifest_sha256,
        "expected_manifest_sha256": args.expected_manifest_sha256,
        "manifest_validator_sha256": _sha256(prepared.validator_path),
        "manifest_schema_sha256": _sha256(prepared.schema_path),
        "verifier_common_sha256": _sha256(prepared.common_path),
        "runner_source_sha256": _sha256(Path(__file__)),
        "candidate_source_sha256_before": prepared.candidate_sha256,
        "candidate_source_sha256_after": candidate_after,
        "candidate_source_unchanged": source_unchanged,
        "duration_seconds": round(time.monotonic() - started, 6),
    }
    receipt = _write_payload(output, payload)
    print(json.dumps({"status": status, "receipt": str(receipt)}, sort_keys=True))
    return 2 if status == "invalid" else 0 if profile_pass else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--reward-root", type=Path, required=True)
    parser.add_argument("--profile", choices=sorted(PROFILE_POLICIES), required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return run(args)
    except (OSError, UnicodeError, RunnerError) as error:
        print(f"INVALID: {type(error).__name__}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
