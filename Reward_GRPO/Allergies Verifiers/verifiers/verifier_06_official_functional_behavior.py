
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


POLICY_ID = "E06"
TASK_ID = "local-aider-cpp/allergies"
FIXED_ASSETS = {
    "allergies_test.cpp": "1eb815ad37a6792bba827c994d0db4cc0edaa57c4428271bef002901e43da798",
    "test/catch.hpp": "681e7505a50887c9085539e5135794fc8f66d8e5de28eadf13a30978627b0f47",
    "test/tests-main.cpp": "5847fda35c1320d94f8d088aaf34229d689f66f1da235f885cbb28c8f17e4260",
    "CMakeLists.txt": "53d531120e650972adf19a2a42aa2d5bc716c93700ffac74c1c2868fdce633ff",
}
SOURCE_FILES = ("allergies.cpp", "allergies.h")
SUCCESS_SUMMARY = "All tests passed (50 assertions in 50 test cases)"


class PreflightError(RuntimeError):
    pass


class CommandStartError(RuntimeError):
    pass


@dataclass
class CommandReceipt:
    argv: list[str]
    cwd: str
    returncode: int | None
    timed_out: bool
    duration_seconds: float
    stdout_path: str
    stderr_path: str
    stdout_sha256: str
    stderr_sha256: str


@dataclass
class KernelReceipt:
    kernel_id: str
    score: int | None
    verdict: str
    summary: str
    commands: list[CommandReceipt] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)
    facts: dict[str, Any] = field(default_factory=dict)


@dataclass
class Context:
    exercise_dir: Path
    output_dir: Path
    compiler: str
    compiler_identity: str
    compile_timeout: float
    runtime_timeout: float
    source_files: dict[str, str]
    source_combined_sha256: str
    fixed_assets: dict[str, str]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_digest(exercise_dir: Path) -> tuple[dict[str, str], str]:
    files = {name: _sha256(exercise_dir / name) for name in SOURCE_FILES}
    canonical = b"".join(name.encode() + b"\0" + files[name].encode() + b"\n" for name in sorted(files))
    return files, hashlib.sha256(canonical).hexdigest()


def _regular(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise PreflightError(f"{label} must be a regular non-symlink file")


def _path_has_symlink(path: Path) -> bool:
    absolute = path.absolute()
    cursor = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        cursor /= part
        if cursor.is_symlink():
            return True
    return False


def _prepare_output(exercise_dir: Path, output_dir: Path) -> None:
    if output_dir == exercise_dir or exercise_dir in output_dir.parents:
        raise PreflightError("output directory must be outside the candidate exercise directory")
    if output_dir.exists():
        if output_dir.is_symlink() or not output_dir.is_dir():
            raise PreflightError("output path must be a non-symlink directory")
        if any(output_dir.iterdir()):
            raise PreflightError("output directory must be empty")
    else:
        output_dir.mkdir(parents=True)


def _preflight(exercise_dir: Path, output_dir: Path, compiler: str, compile_timeout: float, runtime_timeout: float) -> Context:
    if not exercise_dir.is_dir():
        raise PreflightError("exercise directory does not exist")
    if _path_has_symlink(output_dir):
        raise PreflightError("output path must not contain a symlink")
    exercise_dir = exercise_dir.resolve()
    output_dir = output_dir.resolve()
    _prepare_output(exercise_dir, output_dir)
    for name in SOURCE_FILES:
        _regular(exercise_dir / name, name)
    assets: dict[str, str] = {}
    for name, expected in FIXED_ASSETS.items():
        path = exercise_dir / name
        _regular(path, name)
        assets[name] = _sha256(path)
        if assets[name] != expected:
            raise PreflightError(f"fixed asset hash mismatch: {name}")
    resolved = shutil.which(compiler)
    if resolved is None:
        raise PreflightError(f"compiler is unavailable: {compiler}")
    try:
        version = subprocess.run([resolved, "--version"], capture_output=True, text=True, timeout=compile_timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PreflightError(f"compiler identity check failed: {error}") from error
    identity = (version.stdout + version.stderr).strip()
    if version.returncode != 0 or re.search(r"\b13\.3(?:\.0)?\b", identity) is None:
        raise PreflightError("GNU GCC 13.3 is required")
    source_files, combined = _source_digest(exercise_dir)
    return Context(exercise_dir, output_dir, resolved, identity, compile_timeout, runtime_timeout, source_files, combined, assets)


def _run(ctx: Context, label: str, argv: list[str], timeout: float) -> CommandReceipt:
    logs = ctx.output_dir / "logs"
    logs.mkdir(exist_ok=True)
    stdout_path = logs / f"{label}.stdout"
    stderr_path = logs / f"{label}.stderr"
    env = {"PATH": os.environ.get("PATH", ""), "LC_ALL": "C", "LANG": "C"}
    started = time.monotonic()
    timed_out = False
    returncode: int | None
    try:
        completed = subprocess.run(argv, cwd=ctx.output_dir, env=env, capture_output=True, timeout=timeout, check=False)
        returncode = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as error:
        timed_out = True
        returncode = None
        stdout = error.stdout or b""
        stderr = error.stderr or b""
    except OSError as error:
        raise CommandStartError(str(error)) from error
    duration = time.monotonic() - started
    stdout_path.write_bytes(stdout)
    stderr_path.write_bytes(stderr)
    return CommandReceipt(argv, str(ctx.output_dir), returncode, timed_out, duration, str(stdout_path), str(stderr_path), _sha256(stdout_path), _sha256(stderr_path))


def _artifact(path: Path) -> dict[str, str]:
    return {path.name: _sha256(path)} if not path.is_symlink() and path.is_file() and path.stat().st_size else {}


def verify_6a_complete_official_suite(ctx: Context) -> KernelReceipt:
    executable = ctx.output_dir / "executables" / "allergies_official"
    executable.parent.mkdir(parents=True, exist_ok=True)
    compile_argv = [
        ctx.compiler,
        "-std=c++17",
        "-Wall",
        "-Wextra",
        "-Wpedantic",
        "-Werror",
        "-fno-diagnostics-color",
        "-DEXERCISM_RUN_ALL_TESTS",
        "-I",
        str(ctx.exercise_dir),
        str(ctx.exercise_dir / "allergies_test.cpp"),
        str(ctx.exercise_dir / "allergies.cpp"),
        str(ctx.exercise_dir / "test/tests-main.cpp"),
        "-o",
        str(executable),
    ]
    commands: list[CommandReceipt] = []
    try:
        commands.append(_run(ctx, "6a_official_compile_link", compile_argv, ctx.compile_timeout))
    except CommandStartError as error:
        return KernelReceipt("6A", None, "INVALID", f"compiler process could not start: {error}")
    artifacts = _artifact(executable)
    if commands[-1].timed_out:
        return KernelReceipt("6A", -1, "FAIL", "candidate official-suite compilation timed out", commands, artifacts, {"blocked_stage": "compile_link"})
    if commands[-1].returncode != 0 or not artifacts:
        return KernelReceipt("6A", -1, "FAIL", "candidate did not compile and link with the complete official suite", commands, artifacts, {"blocked_stage": "compile_link"})
    try:
        commands.append(_run(ctx, "6a_official_run", [str(executable)], ctx.runtime_timeout))
    except CommandStartError as error:
        return KernelReceipt("6A", None, "INVALID", f"official test process could not start: {error}", commands, artifacts)
    stdout = Path(commands[-1].stdout_path).read_text(encoding="utf-8", errors="replace")
    stderr = Path(commands[-1].stderr_path).read_text(encoding="utf-8", errors="replace")
    output = stdout + stderr
    match = re.search(r"All tests passed \((\d+) assertions in (\d+) test cases\)", output)
    failure_tests = re.search(r"test cases:\s*(\d+)\s*\|\s*(\d+) passed\s*\|\s*(\d+) failed", output)
    failure_assertions = re.search(r"assertions:\s*(\d+)\s*\|\s*(\d+) passed\s*\|\s*(\d+) failed", output)
    assertions = int(match.group(1)) if match else int(failure_assertions.group(1)) if failure_assertions else None
    assertions_passed = int(match.group(1)) if match else int(failure_assertions.group(2)) if failure_assertions else None
    assertions_failed = 0 if match else int(failure_assertions.group(3)) if failure_assertions else None
    test_cases = int(match.group(2)) if match else int(failure_tests.group(1)) if failure_tests else None
    test_cases_passed = int(match.group(2)) if match else int(failure_tests.group(2)) if failure_tests else None
    test_cases_failed = 0 if match else int(failure_tests.group(3)) if failure_tests else None
    facts = {
        "assertions_total": assertions,
        "assertions_passed": assertions_passed,
        "assertions_failed": assertions_failed,
        "test_cases_total": test_cases,
        "test_cases_passed": test_cases_passed,
        "test_cases_failed": test_cases_failed,
        "expected_assertions": 50,
        "expected_test_cases": 50,
        "success_summary_present": SUCCESS_SUMMARY in output,
        "timed_out": commands[-1].timed_out,
    }
    if commands[-1].returncode == 0 and not commands[-1].timed_out and SUCCESS_SUMMARY in output and assertions == 50 and test_cases == 50:
        return KernelReceipt("6A", 1, "PASS", "all 50 protected official assertions passed", commands, artifacts, facts)
    if commands[-1].timed_out:
        return KernelReceipt("6A", -1, "FAIL", "candidate timed out in the complete official suite", commands, artifacts, facts)
    return KernelReceipt("6A", -1, "FAIL", "candidate failed or did not complete all 50 protected official assertions", commands, artifacts, facts)


def _receipt(ctx: Context, kernels: list[KernelReceipt]) -> dict[str, Any]:
    current_files, current_combined = _source_digest(ctx.exercise_dir)
    unchanged = current_files == ctx.source_files and current_combined == ctx.source_combined_sha256
    invalid = sum(item.verdict == "INVALID" for item in kernels) + (0 if unchanged else 1)
    failed = sum(item.verdict == "FAIL" for item in kernels)
    status = "INVALID" if invalid else "FAIL" if failed else "PASS"
    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "task_id": TASK_ID,
        "policy_id": POLICY_ID,
        "verifier_sha256": _sha256(Path(__file__)),
        "compiler": {"path": ctx.compiler, "identity": ctx.compiler_identity},
        "fixed_assets_sha256": ctx.fixed_assets,
        "candidate_source_sha256": ctx.source_files | {"combined": ctx.source_combined_sha256},
        "kernel_model": {"pass": 1, "fail": -1, "infrastructure": "INVALID"},
        "kernels": [asdict(item) for item in kernels],
        "applicable_kernel_count": 1,
        "passed_count": sum(item.verdict == "PASS" for item in kernels),
        "failed_count": failed,
        "invalid_count": invalid,
        "kernel_sum": sum(item.score or 0 for item in kernels),
        "overall_status": status,
        "source_unchanged": unchanged,
    }


def _invalid_receipt(error: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "task_id": TASK_ID,
        "policy_id": POLICY_ID,
        "verifier_sha256": _sha256(Path(__file__)),
        "kernel_model": {"pass": 1, "fail": -1, "infrastructure": "INVALID"},
        "kernels": [],
        "applicable_kernel_count": 1,
        "passed_count": 0,
        "failed_count": 0,
        "invalid_count": 1,
        "kernel_sum": 0,
        "overall_status": "INVALID",
        "preflight_error": error,
        "source_unchanged": None,
    }


def _write_receipt(output_dir: Path, receipt: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "verification_receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exercise-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--compiler", default="g++")
    parser.add_argument("--compile-timeout", type=float, default=60.0)
    parser.add_argument("--runtime-timeout", type=float, default=20.0)
    parser.add_argument("--expected-source-sha256")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    output_dir = args.output_dir.absolute()
    try:
        ctx = _preflight(args.exercise_dir, output_dir, args.compiler, args.compile_timeout, args.runtime_timeout)
        if args.expected_source_sha256 and ctx.source_combined_sha256 != args.expected_source_sha256:
            raise PreflightError("candidate source digest does not match --expected-source-sha256")
    except PreflightError as error:
        if str(error).startswith(("output directory", "output path")):
            return 2
        if output_dir.exists() and output_dir.is_dir() and not any(output_dir.iterdir()):
            _write_receipt(output_dir, _invalid_receipt(str(error)))
        return 2
    kernels = [verify_6a_complete_official_suite(ctx)]
    receipt = _receipt(ctx, kernels)
    _write_receipt(output_dir, receipt)
    return 0 if receipt["overall_status"] == "PASS" else 1 if receipt["overall_status"] == "FAIL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
