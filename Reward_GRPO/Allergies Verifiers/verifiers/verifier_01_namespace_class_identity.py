
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


POLICY_ID = "E01"
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


def _regular_file(path: Path, label: str) -> None:
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


def _compiler_identity(compiler: str, timeout: float) -> tuple[str, str]:
    resolved = shutil.which(compiler)
    if resolved is None:
        raise PreflightError(f"compiler is unavailable: {compiler}")
    try:
        completed = subprocess.run([resolved, "--version"], capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PreflightError(f"compiler identity check failed: {error}") from error
    identity = (completed.stdout + completed.stderr).strip()
    if completed.returncode != 0 or re.search(r"\b13\.3(?:\.0)?\b", identity) is None:
        raise PreflightError("GNU GCC 13.3 is required")
    return resolved, identity


def _preflight(exercise_dir: Path, output_dir: Path, compiler: str, timeout: float) -> Context:
    if not exercise_dir.is_dir():
        raise PreflightError("exercise directory does not exist")
    if _path_has_symlink(output_dir):
        raise PreflightError("output path must not contain a symlink")
    exercise_dir = exercise_dir.resolve()
    output_dir = output_dir.resolve()
    _prepare_output(exercise_dir, output_dir)
    for name in SOURCE_FILES:
        _regular_file(exercise_dir / name, name)
    observed_assets: dict[str, str] = {}
    for name, expected in FIXED_ASSETS.items():
        path = exercise_dir / name
        _regular_file(path, name)
        observed = _sha256(path)
        observed_assets[name] = observed
        if observed != expected:
            raise PreflightError(f"fixed asset hash mismatch: {name}")
    resolved_compiler, identity = _compiler_identity(compiler, timeout)
    source_files, combined = _source_digest(exercise_dir)
    return Context(exercise_dir, output_dir, resolved_compiler, identity, timeout, source_files, combined, observed_assets)


def _write_probe(ctx: Context, name: str, source: str) -> Path:
    probe_dir = ctx.output_dir / "probes"
    probe_dir.mkdir(exist_ok=True)
    path = probe_dir / name
    path.write_text(source, encoding="utf-8")
    return path


def _run(ctx: Context, label: str, argv: list[str], cwd: Path | None = None) -> CommandReceipt:
    log_dir = ctx.output_dir / "logs"
    log_dir.mkdir(exist_ok=True)
    stdout_path = log_dir / f"{label}.stdout"
    stderr_path = log_dir / f"{label}.stderr"
    env = {"PATH": os.environ.get("PATH", ""), "LC_ALL": "C", "LANG": "C"}
    timed_out = False
    returncode: int | None
    stdout = b""
    stderr = b""
    try:
        completed = subprocess.run(argv, cwd=cwd or ctx.output_dir, env=env, capture_output=True, timeout=ctx.timeout, check=False)
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
    return CommandReceipt(argv, str(cwd or ctx.output_dir), returncode, timed_out, str(stdout_path), str(stderr_path), _sha256(stdout_path), _sha256(stderr_path))


def _compile(ctx: Context, label: str, source: Path, output: Path) -> CommandReceipt:
    output.parent.mkdir(parents=True, exist_ok=True)
    argv = [ctx.compiler, "-std=c++17", "-Wall", "-Wextra", "-Wpedantic", "-Werror", "-I", str(ctx.exercise_dir), "-c", str(source), "-o", str(output)]
    return _run(ctx, label, argv)


def _artifact(path: Path) -> dict[str, str]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
        return {}
    return {path.name: _sha256(path)}


def _passed(kernel_id: str, summary: str, commands: list[CommandReceipt], artifacts: dict[str, str], facts: dict[str, Any] | None = None) -> KernelReceipt:
    return KernelReceipt(kernel_id, 1, "PASS", summary, commands, artifacts, facts or {})


def _failed(kernel_id: str, summary: str, commands: list[CommandReceipt], artifacts: dict[str, str] | None = None, facts: dict[str, Any] | None = None) -> KernelReceipt:
    return KernelReceipt(kernel_id, -1, "FAIL", summary, commands, artifacts or {}, facts or {})


def _invalid(kernel_id: str, summary: str) -> KernelReceipt:
    return KernelReceipt(kernel_id, None, "INVALID", summary)


def verify_1a_required_qualified_name(ctx: Context) -> KernelReceipt:
    probe = _write_probe(ctx, "1a_required_qualified_name.cpp", """#include \"allergies.h\"

using required_allergy_type = allergies::allergy_test;

int main()
{
    return 0;
}
""")
    obj = ctx.output_dir / "objects" / "1a_required_qualified_name.o"
    try:
        command = _compile(ctx, "1a_compile", probe, obj)
    except CommandStartError as error:
        return _invalid("1A", f"compiler process could not start: {error}")
    artifacts = {probe.name: _sha256(probe)} | _artifact(obj)
    if command.returncode == 0 and not command.timed_out and _artifact(obj):
        return _passed("1A", "required qualified type is public", [command], artifacts)
    return _failed("1A", "required allergies::allergy_test type did not compile", [command], artifacts, {"timed_out": command.timed_out})


def verify_1b_unsigned_constructor(ctx: Context) -> KernelReceipt:
    probe = _write_probe(ctx, "1b_unsigned_constructor.cpp", """#include \"allergies.h\"
#include <type_traits>

static_assert(std::is_constructible_v<allergies::allergy_test, unsigned int>);

int main()
{
    allergies::allergy_test value{0u};
    (void)value;
    return 0;
}
""")
    obj = ctx.output_dir / "objects" / "1b_unsigned_constructor.o"
    try:
        command = _compile(ctx, "1b_compile", probe, obj)
    except CommandStartError as error:
        return _invalid("1B", f"compiler process could not start: {error}")
    artifacts = {probe.name: _sha256(probe)} | _artifact(obj)
    if command.returncode == 0 and not command.timed_out and _artifact(obj):
        return _passed("1B", "required type is constructible from unsigned int", [command], artifacts)
    return _failed("1B", "unsigned constructor contract did not compile", [command], artifacts, {"timed_out": command.timed_out})


def verify_1c_external_construction_link(ctx: Context) -> KernelReceipt:
    probe = _write_probe(ctx, "1c_external_construction.cpp", """#include \"allergies.h\"

int main()
{
    allergies::allergy_test value{0u};
    (void)value;
    return 0;
}
""")
    objects = ctx.output_dir / "objects"
    implementation_obj = objects / "1c_allergies.o"
    caller_obj = objects / "1c_caller.o"
    executable = ctx.output_dir / "executables" / "1c_external_construction"
    executable.parent.mkdir(parents=True, exist_ok=True)
    commands: list[CommandReceipt] = []
    try:
        commands.append(_compile(ctx, "1c_implementation_compile", ctx.exercise_dir / "allergies.cpp", implementation_obj))
        if commands[-1].returncode != 0 or commands[-1].timed_out:
            return _failed("1C", "candidate implementation did not compile", commands, {probe.name: _sha256(probe)}, {"blocked_stage": "implementation_compile"})
        commands.append(_compile(ctx, "1c_caller_compile", probe, caller_obj))
        if commands[-1].returncode != 0 or commands[-1].timed_out:
            return _failed("1C", "external construction caller did not compile", commands, {probe.name: _sha256(probe)}, {"blocked_stage": "caller_compile"})
        commands.append(_run(ctx, "1c_link", [ctx.compiler, str(implementation_obj), str(caller_obj), "-o", str(executable)]))
        if commands[-1].returncode != 0 or commands[-1].timed_out or not _artifact(executable):
            return _failed("1C", "required constructor did not link", commands, {probe.name: _sha256(probe)}, {"blocked_stage": "link"})
        commands.append(_run(ctx, "1c_run", [str(executable)]))
    except CommandStartError as error:
        return _invalid("1C", f"required process could not start: {error}")
    artifacts = {probe.name: _sha256(probe)} | _artifact(implementation_obj) | _artifact(caller_obj) | _artifact(executable)
    if commands[-1].returncode == 0 and not commands[-1].timed_out:
        return _passed("1C", "external construction compiled, linked, and ran", commands, artifacts)
    return _failed("1C", "external construction executable failed", commands, artifacts, {"timed_out": commands[-1].timed_out})


def _receipt(ctx: Context, kernels: list[KernelReceipt]) -> dict[str, Any]:
    current_files, current_combined = _source_digest(ctx.exercise_dir)
    source_unchanged = current_files == ctx.source_files and current_combined == ctx.source_combined_sha256
    invalid_count = sum(kernel.verdict == "INVALID" for kernel in kernels) + (0 if source_unchanged else 1)
    failed_count = sum(kernel.verdict == "FAIL" for kernel in kernels)
    passed_count = sum(kernel.verdict == "PASS" for kernel in kernels)
    status = "INVALID" if invalid_count else "FAIL" if failed_count else "PASS"
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
        "kernels": [asdict(kernel) for kernel in kernels],
        "applicable_kernel_count": len(kernels),
        "passed_count": passed_count,
        "failed_count": failed_count,
        "invalid_count": invalid_count,
        "kernel_sum": sum(kernel.score or 0 for kernel in kernels),
        "overall_status": status,
        "source_unchanged": source_unchanged,
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
        "applicable_kernel_count": 3,
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
    kernels = [verify_1a_required_qualified_name(ctx), verify_1b_unsigned_constructor(ctx), verify_1c_external_construction_link(ctx)]
    receipt = _receipt(ctx, kernels)
    _write_receipt(output_dir, receipt)
    return 0 if receipt["overall_status"] == "PASS" else 1 if receipt["overall_status"] == "FAIL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
