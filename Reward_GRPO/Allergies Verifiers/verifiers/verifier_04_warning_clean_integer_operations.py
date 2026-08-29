
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


POLICY_ID = "E04"
TASK_ID = "local-aider-cpp/allergies"
FIXED_ASSETS = {
    "allergies_test.cpp": "1eb815ad37a6792bba827c994d0db4cc0edaa57c4428271bef002901e43da798",
    "test/catch.hpp": "681e7505a50887c9085539e5135794fc8f66d8e5de28eadf13a30978627b0f47",
    "test/tests-main.cpp": "5847fda35c1320d94f8d088aaf34229d689f66f1da235f885cbb28c8f17e4260",
    "CMakeLists.txt": "53d531120e650972adf19a2a42aa2d5bc716c93700ffac74c1c2868fdce633ff",
}
SOURCE_FILES = ("allergies.cpp", "allergies.h")


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
    timeout: float
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


def _preflight(exercise_dir: Path, output_dir: Path, compiler: str, timeout: float) -> Context:
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
        version = subprocess.run([resolved, "--version"], capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PreflightError(f"compiler identity check failed: {error}") from error
    identity = (version.stdout + version.stderr).strip()
    if version.returncode != 0 or re.search(r"\b13\.3(?:\.0)?\b", identity) is None:
        raise PreflightError("GNU GCC 13.3 is required")
    source_files, combined = _source_digest(exercise_dir)
    return Context(exercise_dir, output_dir, resolved, identity, timeout, source_files, combined, assets)


def _run(ctx: Context, label: str, argv: list[str]) -> CommandReceipt:
    logs = ctx.output_dir / "logs"
    logs.mkdir(exist_ok=True)
    stdout_path = logs / f"{label}.stdout"
    stderr_path = logs / f"{label}.stderr"
    env = {"PATH": os.environ.get("PATH", ""), "LC_ALL": "C", "LANG": "C"}
    timed_out = False
    returncode: int | None
    try:
        completed = subprocess.run(argv, cwd=ctx.output_dir, env=env, capture_output=True, timeout=ctx.timeout, check=False)
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
    stdout_path.write_bytes(stdout)
    stderr_path.write_bytes(stderr)
    return CommandReceipt(argv, str(ctx.output_dir), returncode, timed_out, str(stdout_path), str(stderr_path), _sha256(stdout_path), _sha256(stderr_path))


def _artifact(path: Path) -> dict[str, str]:
    return {path.name: _sha256(path)} if not path.is_symlink() and path.is_file() and path.stat().st_size else {}


def _diagnostics(path: Path) -> list[dict[str, Any]]:
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as error:
        raise PreflightError(f"GCC JSON diagnostic stream is malformed: {error}") from error
    if not isinstance(parsed, list) or any(not isinstance(item, dict) for item in parsed):
        raise PreflightError("GCC JSON diagnostic stream must be a list of objects")
    return parsed


def _diagnostic_options(value: Any) -> list[str]:
    options: list[str] = []
    if isinstance(value, dict):
        option = value.get("option")
        if isinstance(option, str):
            options.append(option)
        for child in value.values():
            options.extend(_diagnostic_options(child))
    elif isinstance(value, list):
        for child in value:
            options.extend(_diagnostic_options(child))
    return options


def verify_4a_sign_compare_diagnostics(ctx: Context) -> KernelReceipt:
    obj = ctx.output_dir / "objects" / "4a_diagnostics.o"
    obj.parent.mkdir(parents=True, exist_ok=True)
    argv = [ctx.compiler, "-std=c++17", "-Wall", "-Wextra", "-Wpedantic", "-Wno-error", "-fdiagnostics-format=json", "-I", str(ctx.exercise_dir), "-c", str(ctx.exercise_dir / "allergies.cpp"), "-o", str(obj)]
    try:
        command = _run(ctx, "4a_diagnostics", argv)
    except CommandStartError as error:
        return KernelReceipt("4A", None, "INVALID", f"compiler process could not start: {error}")
    try:
        diagnostics = _diagnostics(Path(command.stderr_path))
    except PreflightError as error:
        return KernelReceipt("4A", None, "INVALID", str(error), [command])
    options = sorted(set(_diagnostic_options(diagnostics)))
    artifacts = _artifact(obj)
    facts = {"diagnostic_count": len(diagnostics), "diagnostic_options": options, "sign_compare_count": options.count("-Wsign-compare")}
    if command.timed_out:
        return KernelReceipt("4A", -1, "FAIL", "candidate diagnostic compilation timed out", [command], artifacts, facts)
    if command.returncode != 0:
        return KernelReceipt("4A", -1, "FAIL", "candidate implementation did not compile during diagnostic pass", [command], artifacts, facts)
    if "-Wsign-compare" in options:
        return KernelReceipt("4A", -1, "FAIL", "candidate emitted the observed signedness warning", [command], artifacts, facts)
    if not artifacts:
        return KernelReceipt("4A", -1, "FAIL", "diagnostic compile produced no object", [command], artifacts, facts)
    return KernelReceipt("4A", 1, "PASS", "no signedness warning was emitted", [command], artifacts, facts)


def verify_4b_strict_werror_compile(ctx: Context) -> KernelReceipt:
    obj = ctx.output_dir / "objects" / "4b_strict.o"
    obj.parent.mkdir(parents=True, exist_ok=True)
    argv = [ctx.compiler, "-std=c++17", "-Wall", "-Wextra", "-Wpedantic", "-Werror", "-I", str(ctx.exercise_dir), "-c", str(ctx.exercise_dir / "allergies.cpp"), "-o", str(obj)]
    try:
        command = _run(ctx, "4b_strict", argv)
    except CommandStartError as error:
        return KernelReceipt("4B", None, "INVALID", f"compiler process could not start: {error}")
    artifacts = _artifact(obj)
    if command.returncode == 0 and not command.timed_out and artifacts:
        return KernelReceipt("4B", 1, "PASS", "implementation compiled with warnings treated as errors", [command], artifacts)
    return KernelReceipt("4B", -1, "FAIL", "implementation failed strict warning-as-error compilation", [command], artifacts, {"timed_out": command.timed_out})


def _receipt(ctx: Context, kernels: list[KernelReceipt]) -> dict[str, Any]:
    current_files, current_combined = _source_digest(ctx.exercise_dir)
    unchanged = current_files == ctx.source_files and current_combined == ctx.source_combined_sha256
    invalid = sum(item.verdict == "INVALID" for item in kernels) + (0 if unchanged else 1)
    failed = sum(item.verdict == "FAIL" for item in kernels)
    status = "INVALID" if invalid else "FAIL" if failed else "PASS"
    return {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(), "task_id": TASK_ID, "policy_id": POLICY_ID, "verifier_sha256": _sha256(Path(__file__)), "compiler": {"path": ctx.compiler, "identity": ctx.compiler_identity}, "fixed_assets_sha256": ctx.fixed_assets, "candidate_source_sha256": ctx.source_files | {"combined": ctx.source_combined_sha256}, "kernel_model": {"pass": 1, "fail": -1, "infrastructure": "INVALID"}, "kernels": [asdict(item) for item in kernels], "applicable_kernel_count": len(kernels), "passed_count": sum(item.verdict == "PASS" for item in kernels), "failed_count": failed, "invalid_count": invalid, "kernel_sum": sum(item.score or 0 for item in kernels), "overall_status": status, "source_unchanged": unchanged}


def _invalid_receipt(error: str) -> dict[str, Any]:
    return {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(), "task_id": TASK_ID, "policy_id": POLICY_ID, "verifier_sha256": _sha256(Path(__file__)), "kernel_model": {"pass": 1, "fail": -1, "infrastructure": "INVALID"}, "kernels": [], "applicable_kernel_count": 2, "passed_count": 0, "failed_count": 0, "invalid_count": 1, "kernel_sum": 0, "overall_status": "INVALID", "preflight_error": error, "source_unchanged": None}


def _write_receipt(output_dir: Path, receipt: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "verification_receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exercise-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--compiler", default="g++")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--expected-source-sha256")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    output_dir = args.output_dir.absolute()
    try:
        ctx = _preflight(args.exercise_dir, output_dir, args.compiler, args.timeout)
        if args.expected_source_sha256 and ctx.source_combined_sha256 != args.expected_source_sha256:
            raise PreflightError("candidate source digest does not match --expected-source-sha256")
    except PreflightError as error:
        if str(error).startswith(("output directory", "output path")):
            return 2
        if output_dir.exists() and output_dir.is_dir() and not any(output_dir.iterdir()):
            _write_receipt(output_dir, _invalid_receipt(str(error)))
        return 2
    kernels = [verify_4a_sign_compare_diagnostics(ctx), verify_4b_strict_werror_compile(ctx)]
    receipt = _receipt(ctx, kernels)
    _write_receipt(output_dir, receipt)
    return 0 if receipt["overall_status"] == "PASS" else 1 if receipt["overall_status"] == "FAIL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
