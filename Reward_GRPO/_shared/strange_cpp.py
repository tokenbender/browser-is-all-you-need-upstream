
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
from typing import Any, Callable, Sequence


STRICT_FLAGS = (
    "-std=c++17",
    "-Wall",
    "-Wextra",
    "-Wpedantic",
    "-Werror",
    "-fno-diagnostics-color",
)


@dataclass(frozen=True)
class Contract:
    task_id: str
    prefix: str
    source_files: tuple[str, ...]
    implementation_files: tuple[str, ...]
    fixed_hashes: dict[str, str]
    test_file: str


@dataclass(frozen=True)
class CommandReceipt:
    command: list[str]
    cwd: str
    return_code: int
    timed_out: bool
    started: bool
    duration_seconds: float
    stdout_log: str
    stderr_log: str


@dataclass(frozen=True)
class KernelReceipt:
    kernel_id: str
    kernel: int | None
    status: str
    summary: str
    commands: list[CommandReceipt] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Context:
    contract: Contract
    exercise_dir: Path
    output_dir: Path
    compiler: str
    compiler_version: str
    source_sha256: str
    compile_timeout_s: int
    run_timeout_s: int


class PreflightError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def combined_digest(root: Path, relatives: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for relative in relatives:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise PreflightError(f"required regular file is missing or symlinked: {relative}")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def base_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exercise-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--compiler", default="g++")
    parser.add_argument("--expected-gcc", default="13.3")
    parser.add_argument("--compile-timeout-s", type=int, default=120)
    parser.add_argument("--run-timeout-s", type=int, default=120)
    return parser


def prepare(args: argparse.Namespace, contract: Contract) -> Context:
    exercise_input = args.exercise_dir
    output_input = args.output_dir
    if exercise_input.is_symlink():
        raise PreflightError("exercise directory must not be a symlink")
    exercise_dir = exercise_input.resolve()
    if not exercise_dir.is_dir():
        raise PreflightError("exercise directory does not exist")
    if output_input.is_symlink():
        raise PreflightError("output directory must not be a symlink")
    output_dir = output_input.resolve()
    if output_dir == exercise_dir or output_dir.is_relative_to(exercise_dir):
        raise PreflightError("output directory must be outside candidate source")
    if output_dir.exists() and (not output_dir.is_dir() or any(output_dir.iterdir())):
        raise PreflightError("output directory must be new or empty")
    output_dir.mkdir(parents=True, exist_ok=True)
    for relative, expected in contract.fixed_hashes.items():
        path = exercise_dir / relative
        if not path.is_file() or path.is_symlink():
            raise PreflightError(f"fixed contract asset is missing or symlinked: {relative}")
        observed = sha256(path)
        if observed != expected:
            raise PreflightError(f"fixed contract asset hash mismatch: {relative}")
    source_sha256 = combined_digest(exercise_dir, contract.source_files)
    compiler = shutil.which(args.compiler)
    if compiler is None:
        raise PreflightError(f"compiler not found: {args.compiler}")
    try:
        version = subprocess.run(
            [compiler, "-dumpfullversion", "-dumpversion"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            env={**os.environ, "LC_ALL": "C", "LANG": "C"},
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise PreflightError(f"compiler identity check failed: {error}") from error
    compiler_version = version.stdout.strip()
    if version.returncode != 0 or not compiler_version.startswith(args.expected_gcc):
        raise PreflightError(
            f"expected GCC {args.expected_gcc}, observed {compiler_version or 'unknown'}"
        )
    return Context(
        contract=contract,
        exercise_dir=exercise_dir,
        output_dir=output_dir,
        compiler=compiler,
        compiler_version=compiler_version,
        source_sha256=source_sha256,
        compile_timeout_s=args.compile_timeout_s,
        run_timeout_s=args.run_timeout_s,
    )


def _safe_label(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def run_command(
    ctx: Context,
    kernel_id: str,
    label: str,
    command: list[str],
    timeout_s: int,
) -> CommandReceipt:
    logs_dir = ctx.output_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{_safe_label(kernel_id.lower())}_{_safe_label(label)}"
    stdout_path = logs_dir / f"{stem}.stdout.log"
    stderr_path = logs_dir / f"{stem}.stderr.log"
    started_at = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=ctx.exercise_dir,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env={**os.environ, "LC_ALL": "C", "LANG": "C"},
        )
        return_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
        started = True
        timed_out = False
    except subprocess.TimeoutExpired as error:
        stdout_value = error.stdout or ""
        stderr_value = error.stderr or ""
        stdout = stdout_value.decode(errors="replace") if isinstance(stdout_value, bytes) else stdout_value
        stderr = stderr_value.decode(errors="replace") if isinstance(stderr_value, bytes) else stderr_value
        stderr = f"{stderr}\ncommand timed out after {timeout_s} seconds\n"
        return_code = 124
        started = True
        timed_out = True
    except OSError as error:
        stdout = ""
        stderr = f"{type(error).__name__}: {error}\n"
        return_code = 127
        started = False
        timed_out = False
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    return CommandReceipt(
        command=command,
        cwd=str(ctx.exercise_dir),
        return_code=return_code,
        timed_out=timed_out,
        started=started,
        duration_seconds=round(time.monotonic() - started_at, 6),
        stdout_log=str(stdout_path),
        stderr_log=str(stderr_path),
    )


def passed(
    kernel_id: str,
    summary: str,
    commands: list[CommandReceipt] | None = None,
    facts: dict[str, Any] | None = None,
    artifacts: dict[str, str] | None = None,
) -> KernelReceipt:
    return KernelReceipt(kernel_id, 1, "pass", summary, commands or [], facts or {}, artifacts or {})


def failed(
    kernel_id: str,
    summary: str,
    commands: list[CommandReceipt] | None = None,
    facts: dict[str, Any] | None = None,
) -> KernelReceipt:
    return KernelReceipt(kernel_id, -1, "fail", summary, commands or [], facts or {}, {})


def invalid(
    kernel_id: str,
    summary: str,
    commands: list[CommandReceipt] | None = None,
    facts: dict[str, Any] | None = None,
) -> KernelReceipt:
    return KernelReceipt(kernel_id, None, "invalid", summary, commands or [], facts or {}, {})


def source_unchanged(ctx: Context) -> bool:
    try:
        return combined_digest(ctx.exercise_dir, ctx.contract.source_files) == ctx.source_sha256
    except (OSError, PreflightError):
        return False


def write_probe(ctx: Context, filename: str, content: str) -> Path:
    probes_dir = ctx.output_dir / "probes"
    probes_dir.mkdir(parents=True, exist_ok=True)
    path = probes_dir / filename
    path.write_text(content, encoding="utf-8")
    return path


def implementation_paths(ctx: Context) -> list[str]:
    return [str(ctx.exercise_dir / relative) for relative in ctx.contract.implementation_files]


def compile_only(
    ctx: Context,
    kernel_id: str,
    label: str,
    filename: str,
    content: str,
) -> KernelReceipt:
    probe = write_probe(ctx, filename, content)
    artifact = ctx.output_dir / "artifacts" / f"{Path(filename).stem}.o"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ctx.compiler,
        *STRICT_FLAGS,
        "-pthread",
        "-I",
        str(ctx.exercise_dir),
        "-c",
        str(probe),
        "-o",
        str(artifact),
    ]
    receipt = run_command(ctx, kernel_id, label, command, ctx.compile_timeout_s)
    facts = {"compiler_version": ctx.compiler_version, "probe_sha256": sha256(probe)}
    if not receipt.started:
        return invalid(kernel_id, "compiler process could not start", [receipt], facts)
    if receipt.return_code != 0 or not artifact.is_file() or artifact.is_symlink() or artifact.stat().st_size == 0:
        return failed(kernel_id, f"{label} did not compile", [receipt], facts)
    if not source_unchanged(ctx):
        return invalid(kernel_id, "candidate source changed during verification", [receipt], facts)
    return passed(
        kernel_id,
        f"{label} compiled",
        [receipt],
        facts,
        {"probe": sha256(probe), "object": sha256(artifact)},
    )


def compile_and_run(
    ctx: Context,
    kernel_id: str,
    label: str,
    filename: str,
    content: str,
    expected_stdout: str,
    compiler: str | None = None,
    extra_flags: Sequence[str] = (),
) -> KernelReceipt:
    probe = write_probe(ctx, filename, content)
    executable = ctx.output_dir / "artifacts" / Path(filename).stem
    executable.parent.mkdir(parents=True, exist_ok=True)
    selected_compiler = compiler or ctx.compiler
    command = [
        selected_compiler,
        *STRICT_FLAGS,
        *extra_flags,
        "-pthread",
        "-I",
        str(ctx.exercise_dir),
        str(probe),
        *implementation_paths(ctx),
        "-o",
        str(executable),
    ]
    compile_receipt = run_command(ctx, kernel_id, f"{label}_compile", command, ctx.compile_timeout_s)
    facts: dict[str, Any] = {"probe_sha256": sha256(probe), "expected_stdout": expected_stdout}
    if not compile_receipt.started:
        return invalid(kernel_id, "compiler process could not start", [compile_receipt], facts)
    if compile_receipt.return_code != 0 or not executable.is_file() or executable.is_symlink() or executable.stat().st_size == 0:
        return failed(kernel_id, f"{label} did not compile and link", [compile_receipt], facts)
    run_receipt = run_command(ctx, kernel_id, f"{label}_run", [str(executable)], ctx.run_timeout_s)
    commands = [compile_receipt, run_receipt]
    if not run_receipt.started:
        return invalid(kernel_id, "probe process could not start", commands, facts)
    observed_stdout = Path(run_receipt.stdout_log).read_text(encoding="utf-8")
    facts["observed_stdout"] = observed_stdout
    if run_receipt.return_code != 0 or observed_stdout != expected_stdout:
        return failed(kernel_id, f"{label} behavior check failed", commands, facts)
    if not source_unchanged(ctx):
        return invalid(kernel_id, "candidate source changed during verification", commands, facts)
    return passed(
        kernel_id,
        f"{label} passed",
        commands,
        facts,
        {"probe": sha256(probe), "executable": sha256(executable)},
    )


def official_checks(ctx: Context, policy_id: str) -> list[KernelReceipt]:
    prefix = policy_id
    authenticated = passed(
        f"{prefix}-A",
        "the pinned official suite and build assets are authenticated",
        facts={"fixed_asset_count": len(ctx.contract.fixed_hashes)},
    )
    executable = ctx.output_dir / "artifacts" / "official-tests"
    executable.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ctx.compiler,
        "-std=c++17",
        "-O0",
        "-fno-diagnostics-color",
        "-DEXERCISM_RUN_ALL_TESTS",
        "-pthread",
        "-I",
        str(ctx.exercise_dir),
        str(ctx.exercise_dir / "test/tests-main.cpp"),
        str(ctx.exercise_dir / ctx.contract.test_file),
        *implementation_paths(ctx),
        "-o",
        str(executable),
    ]
    compile_receipt = run_command(ctx, f"{prefix}-B", "official_compile", command, ctx.compile_timeout_s)
    if not compile_receipt.started:
        build = invalid(f"{prefix}-B", "compiler process could not start", [compile_receipt])
        execute = invalid(f"{prefix}-C", "official execution unavailable after infrastructure failure")
        return [authenticated, build, execute]
    if compile_receipt.return_code != 0 or not executable.is_file() or executable.is_symlink() or executable.stat().st_size == 0:
        build = failed(f"{prefix}-B", "official suite did not compile and link", [compile_receipt])
        execute = failed(f"{prefix}-C", "official suite execution was blocked by candidate build failure")
        return [authenticated, build, execute]
    build = passed(
        f"{prefix}-B",
        "official suite compiled and linked",
        [compile_receipt],
        artifacts={"executable": sha256(executable)},
    )
    run_receipt = run_command(ctx, f"{prefix}-C", "official_run", [str(executable)], ctx.run_timeout_s)
    commands = [run_receipt]
    if not run_receipt.started:
        execute = invalid(f"{prefix}-C", "official executable could not start", commands)
    else:
        stdout = Path(run_receipt.stdout_log).read_text(encoding="utf-8")
        stderr = Path(run_receipt.stderr_log).read_text(encoding="utf-8")
        facts = {"stdout": stdout, "stderr": stderr}
        if run_receipt.return_code == 0 and "All tests passed" in stdout and "failed" not in stdout.lower():
            execute = passed(f"{prefix}-C", "every selected official test passed", commands, facts)
        else:
            execute = failed(f"{prefix}-C", "one or more official tests failed", commands, facts)
    if not source_unchanged(ctx):
        execute = invalid(f"{prefix}-C", "candidate source changed during official verification", commands)
    return [authenticated, build, execute]


def finish(
    ctx: Context,
    policy_id: str,
    verifier_path: Path,
    results: list[KernelReceipt],
    excluded_conditions: Sequence[str] = (),
) -> dict[str, Any]:
    invalid_run = any(result.kernel is None for result in results)
    status = "invalid" if invalid_run else "pass" if all(result.kernel == 1 for result in results) else "fail"
    payload: dict[str, Any] = {
        "schema_version": 1,
        "task_id": ctx.contract.task_id,
        "policy_id": policy_id,
        "status": status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "verifier_source_sha256": sha256(verifier_path.resolve()),
        "candidate_source_sha256": ctx.source_sha256,
        "fixed_asset_sha256": ctx.contract.fixed_hashes,
        "compiler_version": ctx.compiler_version,
        "kernel_results": [asdict(result) for result in results],
        "passed_count": sum(result.kernel == 1 for result in results),
        "failed_count": sum(result.kernel == -1 for result in results),
        "invalid_count": sum(result.kernel is None for result in results),
        "kernel_sum": None if invalid_run else sum(result.kernel or 0 for result in results),
        "maximum_kernel_sum": len(results),
        "excluded_conditions": list(excluded_conditions),
    }
    (ctx.output_dir / "verification_receipt.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def finish_invalid(
    output_dir: Path,
    exercise_dir: Path,
    contract: Contract,
    policy_id: str,
    verifier_path: Path,
    error: Exception,
) -> dict[str, Any] | None:
    resolved = output_dir.resolve()
    exercise_resolved = exercise_dir.resolve()
    unsafe_location = resolved == exercise_resolved or resolved.is_relative_to(exercise_resolved)
    if output_dir.is_symlink() or unsafe_location or (resolved.exists() and (not resolved.is_dir() or any(resolved.iterdir()))):
        return None
    resolved.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "task_id": contract.task_id,
        "policy_id": policy_id,
        "status": "invalid",
        "preflight_error": str(error),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "verifier_source_sha256": sha256(verifier_path.resolve()),
        "candidate_source_sha256": None,
        "fixed_asset_sha256": {},
        "kernel_results": [],
        "passed_count": 0,
        "failed_count": 0,
        "invalid_count": 1,
        "kernel_sum": None,
        "maximum_kernel_sum": 0,
        "excluded_conditions": [],
    }
    (resolved / "verification_receipt.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def execute(
    contract: Contract,
    policy_id: str,
    verifier_path: Path,
    build_results: Callable[[Context], list[KernelReceipt]],
) -> int:
    args = base_parser().parse_args()
    try:
        ctx = prepare(args, contract)
    except (OSError, subprocess.SubprocessError, PreflightError) as error:
        payload = finish_invalid(args.output_dir, args.exercise_dir, contract, policy_id, verifier_path, error)
        if payload is None:
            print(f"INVALID: {error}")
        else:
            print(json.dumps({"status": "invalid", "receipt": str(args.output_dir.resolve() / "verification_receipt.json")}))
        return 2
    results = build_results(ctx)
    payload = finish(ctx, policy_id, verifier_path, results)
    print(
        json.dumps(
            {
                "status": payload["status"],
                "kernel_sum": payload["kernel_sum"],
                "receipt": str(ctx.output_dir / "verification_receipt.json"),
            }
        )
    )
    return 0 if payload["status"] == "pass" else 2 if payload["status"] == "invalid" else 1
