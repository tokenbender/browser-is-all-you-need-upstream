
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUIRED_ASSETS = (
    "CMakeLists.txt",
    "bank_account.h",
    "bank_account.cpp",
    "bank_account_test.cpp",
    "test/catch.hpp",
    "test/tests-main.cpp",
)
BASE_FLAGS = (
    "-std=c++17",
    "-pthread",
    "-fdiagnostics-format=json",
    "-fdiagnostics-show-option",
    "-fno-diagnostics-color",
)
STRICT_FLAGS = (
    "-std=c++17",
    "-Wall",
    "-Wextra",
    "-Wpedantic",
    "-Werror",
    "-pthread",
    "-fno-diagnostics-color",
)
HEADER_CONSUMER = """#include \"bank_account.h\"

int main() {
    Bankaccount::Bankaccount account{};
    (void)account;
    return 0;
}
"""


@dataclass(frozen=True)
class CommandReceipt:
    command: list[str]
    cwd: str
    return_code: int
    timed_out: bool
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
class VerifierContext:
    exercise_dir: Path
    output_dir: Path
    compiler: str
    expected_gcc: str
    source_sha256: str
    compile_timeout_s: int
    link_timeout_s: int


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _source_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for relative in REQUIRED_ASSETS:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"required regular task asset is missing: {relative}")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _assets_valid(ctx: VerifierContext) -> tuple[bool, str]:
    try:
        observed = _source_digest(ctx.exercise_dir)
    except (OSError, ValueError) as error:
        return False, str(error)
    if observed != ctx.source_sha256:
        return False, "task source digest changed after verification started"
    return True, observed


def _valid_artifact(path: Path, executable: bool = False) -> bool:
    if not path.is_file() or path.is_symlink() or path.stat().st_size <= 0:
        return False
    return not executable or os.access(path, os.X_OK)


def _safe_label(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def _run(
    ctx: VerifierContext,
    kernel_id: str,
    label: str,
    command: list[str],
    timeout_s: int,
    input_text: str | None = None,
) -> CommandReceipt:
    logs = ctx.output_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    stem = f"{kernel_id.lower()}_{_safe_label(label)}"
    stdout_path = logs / f"{stem}.stdout.log"
    stderr_path = logs / f"{stem}.stderr.log"
    started = time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(
            command,
            input=input_text,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env={**os.environ, "LC_ALL": "C", "LANG": "C"},
        )
        return_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as error:
        timed_out = True
        return_code = 124
        stdout_value = error.stdout or ""
        stderr_value = error.stderr or ""
        stdout = stdout_value.decode(errors="replace") if isinstance(stdout_value, bytes) else stdout_value
        stderr = stderr_value.decode(errors="replace") if isinstance(stderr_value, bytes) else stderr_value
        stderr = f"{stderr}\ncommand timed out after {timeout_s} seconds\n"
    except OSError as error:
        return_code = 127
        stdout = ""
        stderr = f"{type(error).__name__}: {error}\n"
    duration = time.monotonic() - started
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    return CommandReceipt(
        command=command,
        cwd=str(Path.cwd()),
        return_code=return_code,
        timed_out=timed_out,
        duration_seconds=round(duration, 6),
        stdout_log=str(stdout_path),
        stderr_log=str(stderr_path),
    )


def _pass(
    kernel_id: str,
    summary: str,
    commands: list[CommandReceipt],
    facts: dict[str, Any],
    artifacts: dict[str, str] | None = None,
) -> KernelReceipt:
    return KernelReceipt(kernel_id, 1, "pass", summary, commands, facts, artifacts or {})


def _fail(
    kernel_id: str,
    summary: str,
    commands: list[CommandReceipt],
    facts: dict[str, Any],
) -> KernelReceipt:
    return KernelReceipt(kernel_id, -1, "fail", summary, commands, facts, {})


def _invalid(
    kernel_id: str,
    summary: str,
    commands: list[CommandReceipt] | None = None,
    facts: dict[str, Any] | None = None,
) -> KernelReceipt:
    return KernelReceipt(kernel_id, None, "invalid", summary, commands or [], facts or {}, {})


def _diagnostics(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return []
    value = json.loads(text)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError("GCC diagnostic output is not a JSON list")
    return value


def _warning_fingerprint(diagnostic: dict[str, Any]) -> str:
    locations = diagnostic.get("locations") or []
    caret: dict[str, Any] = {}
    if locations and isinstance(locations[0], dict):
        raw_caret = locations[0].get("caret") or {}
        if isinstance(raw_caret, dict):
            caret = raw_caret
    value = {
        "kind": diagnostic.get("kind"),
        "option": diagnostic.get("option"),
        "message": diagnostic.get("message"),
        "file": caret.get("file"),
        "line": caret.get("line"),
        "column": caret.get("column"),
    }
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _warnings_from(commands: list[CommandReceipt]) -> tuple[list[dict[str, Any]], str | None]:
    warnings: list[dict[str, Any]] = []
    for command in commands:
        if command.return_code != 0:
            return warnings, "candidate translation unit did not compile"
        try:
            diagnostics = _diagnostics(Path(command.stderr_log))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            return warnings, f"GCC diagnostics could not be parsed: {error}"
        warnings.extend(item for item in diagnostics if item.get("kind") == "warning")
    return warnings, None


def _compile_tier(
    ctx: VerifierContext,
    kernel_id: str,
    tier: str,
    warning_flags: tuple[str, ...],
) -> list[CommandReceipt]:
    consumer = ctx.output_dir / "bank_account_header_consumer.cpp"
    consumer.write_text(HEADER_CONSUMER, encoding="utf-8")
    units = (
        ("implementation", ctx.exercise_dir / "bank_account.cpp"),
        ("header_consumer", consumer),
    )
    commands: list[CommandReceipt] = []
    for unit_name, source in units:
        command = [
            ctx.compiler,
            *BASE_FLAGS,
            *warning_flags,
            f"-I{ctx.exercise_dir}",
            "-fsyntax-only",
            str(source),
        ]
        commands.append(
            _run(
                ctx,
                kernel_id,
                f"{tier}_{unit_name}",
                command,
                ctx.compile_timeout_s,
            )
        )
    return commands


def _warning_delta_kernel(
    ctx: VerifierContext,
    kernel_id: str,
    label: str,
    baseline_flags: tuple[str, ...],
    selected_flags: tuple[str, ...],
) -> KernelReceipt:
    assets_ok, asset_fact = _assets_valid(ctx)
    if not assets_ok:
        return _invalid(kernel_id, asset_fact)
    baseline_commands = _compile_tier(ctx, kernel_id, "baseline", baseline_flags)
    selected_commands = _compile_tier(ctx, kernel_id, "selected", selected_flags)
    commands = baseline_commands + selected_commands
    if any(command.return_code == 127 for command in commands):
        return _invalid(kernel_id, "compiler process is unavailable", commands)
    baseline_warnings, baseline_error = _warnings_from(baseline_commands)
    selected_warnings, selected_error = _warnings_from(selected_commands)
    facts: dict[str, Any] = {
        "baseline_flags": list(baseline_flags),
        "selected_flags": list(selected_flags),
        "baseline_warning_count": len(baseline_warnings),
        "selected_warning_count": len(selected_warnings),
    }
    if baseline_error or selected_error:
        parse_error = baseline_error or selected_error or "candidate compile failure"
        if "diagnostics could not be parsed" in parse_error:
            return _invalid(kernel_id, parse_error, commands, facts)
        facts["compile_failure"] = parse_error
        return _fail(kernel_id, f"{label} could not be verified because candidate compilation failed", commands, facts)
    baseline_counts = Counter(_warning_fingerprint(item) for item in baseline_warnings)
    selected_counts = Counter(_warning_fingerprint(item) for item in selected_warnings)
    delta = selected_counts - baseline_counts
    delta_details: list[dict[str, Any]] = []
    selected_by_fingerprint: dict[str, dict[str, Any]] = {
        _warning_fingerprint(item): item for item in selected_warnings
    }
    for fingerprint, count in sorted(delta.items()):
        detail = selected_by_fingerprint[fingerprint]
        delta_details.extend(detail for _ in range(count))
    facts["new_warning_count"] = sum(delta.values())
    facts["new_warnings"] = delta_details
    if not delta and _assets_valid(ctx)[0]:
        return _pass(kernel_id, f"{label} introduced no warning", commands, facts)
    return _fail(kernel_id, f"{label} introduced one or more warnings", commands, facts)


def verify_2a_wall(ctx: VerifierContext) -> KernelReceipt:
    return _warning_delta_kernel(ctx, "2A", "-Wall", (), ("-Wall",))


def verify_2b_wextra(ctx: VerifierContext) -> KernelReceipt:
    return _warning_delta_kernel(ctx, "2B", "-Wextra", ("-Wall",), ("-Wall", "-Wextra"))


def verify_2c_wpedantic(ctx: VerifierContext) -> KernelReceipt:
    return _warning_delta_kernel(
        ctx,
        "2C",
        "-Wpedantic",
        ("-Wall", "-Wextra"),
        ("-Wall", "-Wextra", "-Wpedantic"),
    )


def verify_2d_complete_werror_build(ctx: VerifierContext) -> KernelReceipt:
    assets_ok, asset_fact = _assets_valid(ctx)
    if not assets_ok:
        return _invalid("2D", asset_fact)
    objects = ctx.output_dir / "strict_objects"
    objects.mkdir(parents=True, exist_ok=True)
    specifications = (
        (
            "implementation",
            ctx.exercise_dir / "bank_account.cpp",
            objects / "bank_account.o",
            (),
            (f"-I{ctx.exercise_dir}",),
        ),
        (
            "official_test",
            ctx.exercise_dir / "bank_account_test.cpp",
            objects / "bank_account_test.o",
            ("-DEXERCISM_RUN_ALL_TESTS",),
            (f"-I{ctx.exercise_dir}",),
        ),
        (
            "catch_main",
            ctx.exercise_dir / "test/tests-main.cpp",
            objects / "catch_main.o",
            (),
            (f"-I{ctx.exercise_dir / 'test'}",),
        ),
    )
    commands: list[CommandReceipt] = []
    artifacts: dict[str, str] = {}
    for label, source, target, definitions, includes in specifications:
        command = [
            ctx.compiler,
            *STRICT_FLAGS,
            *definitions,
            *includes,
            "-c",
            str(source),
            "-o",
            str(target),
        ]
        result = _run(ctx, "2D", f"strict_{label}", command, ctx.compile_timeout_s)
        commands.append(result)
        if result.return_code == 127:
            return _invalid("2D", "compiler process is unavailable", commands)
        if result.return_code != 0 or not _valid_artifact(target):
            return _fail(
                "2D",
                f"strict warning-as-error compilation failed for {label}",
                commands,
                {"failed_stage": label, "timed_out": result.timed_out},
            )
        artifacts[target.name] = _sha256(target)
    executable = ctx.output_dir / "bank-account-warning-clean-tests"
    link_command = [
        ctx.compiler,
        str(objects / "bank_account.o"),
        str(objects / "bank_account_test.o"),
        str(objects / "catch_main.o"),
        "-pthread",
        "-o",
        str(executable),
    ]
    link = _run(ctx, "2D", "strict_link", link_command, ctx.link_timeout_s)
    commands.append(link)
    if link.return_code == 127:
        return _invalid("2D", "linker process is unavailable", commands)
    if link.return_code == 0 and _valid_artifact(executable, executable=True) and _assets_valid(ctx)[0]:
        artifacts[executable.name] = _sha256(executable)
        return _pass(
            "2D",
            "complete warning-as-error compile and link succeeded",
            commands,
            {"compiled_units": 3, "linked": True, "executable_bytes": executable.stat().st_size},
            artifacts,
        )
    return _fail(
        "2D",
        "complete warning-as-error executable did not link",
        commands,
        {"failed_stage": "link", "timed_out": link.timed_out},
    )


def _preflight(ctx: VerifierContext) -> tuple[bool, str, list[CommandReceipt], dict[str, Any]]:
    commands: list[CommandReceipt] = []
    version = _run(
        ctx,
        "preflight",
        "gcc_version",
        [ctx.compiler, "-dumpfullversion", "-dumpversion"],
        ctx.compile_timeout_s,
    )
    commands.append(version)
    if version.return_code != 0:
        return False, "GNU compiler identity could not be read", commands, {}
    macros = _run(
        ctx,
        "preflight",
        "gcc_macros",
        [ctx.compiler, "-dM", "-E", "-x", "c++", "-"],
        ctx.compile_timeout_s,
        input_text="",
    )
    commands.append(macros)
    version_text = Path(version.stdout_log).read_text(encoding="utf-8").strip()
    macro_text = Path(macros.stdout_log).read_text(encoding="utf-8", errors="replace")
    facts = {
        "compiler_version": version_text,
        "is_gnu": "#define __GNUC__ " in macro_text,
        "is_clang": "#define __clang__ " in macro_text,
    }
    version_ok = version_text == ctx.expected_gcc or version_text.startswith(f"{ctx.expected_gcc}.")
    passed = macros.return_code == 0 and version_ok and facts["is_gnu"] and not facts["is_clang"]
    return passed, "GNU GCC preflight passed" if passed else "expected GNU GCC 13.3", commands, facts


def verify_policy_2(ctx: VerifierContext) -> dict[str, Any]:
    preflight_ok, preflight_summary, preflight_commands, preflight_facts = _preflight(ctx)
    assets_ok, asset_fact = _assets_valid(ctx)
    if not preflight_ok or not assets_ok:
        reason = preflight_summary if not preflight_ok else asset_fact
        results = [
            _invalid(kernel_id, reason, preflight_commands, preflight_facts)
            for kernel_id in ("2A", "2B", "2C", "2D")
        ]
    else:
        results = [
            verify_2a_wall(ctx),
            verify_2b_wextra(ctx),
            verify_2c_wpedantic(ctx),
            verify_2d_complete_werror_build(ctx),
        ]
    invalid = any(result.kernel is None for result in results)
    kernel_sum = None if invalid else sum(result.kernel for result in results if result.kernel is not None)
    status = "invalid" if invalid else "pass" if kernel_sum == 4 else "fail"
    preflight_receipt_summary = (
        preflight_summary
        if not preflight_ok or assets_ok
        else asset_fact
    )
    return {
        "schema_version": 1,
        "policy_id": "bank-account-policy-02-warning-clean-build-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "kernel_model": {"pass": 1, "fail": -1, "infrastructure": "INVALID"},
        "kernel_sum": kernel_sum,
        "kernel_range": [-4, 4],
        "full_pass_required": 4,
        "passed_kernels": sum(result.kernel == 1 for result in results),
        "failed_kernels": sum(result.kernel == -1 for result in results),
        "source_sha256": ctx.source_sha256,
        "exercise_dir": str(ctx.exercise_dir),
        "preflight": {
            "status": "pass" if preflight_ok and assets_ok else "invalid",
            "summary": preflight_receipt_summary,
            "commands": [asdict(command) for command in preflight_commands],
            "facts": preflight_facts,
        },
        "checks": {result.kernel_id: asdict(result) for result in results},
    }


def _prepare_output(path: Path, exercise_dir: Path) -> None:
    resolved = path.resolve()
    if resolved == exercise_dir or exercise_dir in resolved.parents:
        raise ValueError("output directory must be outside the task source directory")
    if resolved.exists() and any(resolved.iterdir()):
        raise ValueError(f"output directory must be absent or empty: {resolved}")
    resolved.mkdir(parents=True, exist_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exercise-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--compiler", default="g++")
    parser.add_argument("--expected-gcc", default="13.3")
    parser.add_argument("--expected-source-sha256")
    parser.add_argument("--compile-timeout-s", type=int, default=120)
    parser.add_argument("--link-timeout-s", type=int, default=60)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    exercise_dir = args.exercise_dir.resolve()
    output_dir = args.output_dir.resolve()
    if not exercise_dir.is_dir():
        raise SystemExit(f"exercise directory does not exist: {exercise_dir}")
    try:
        _prepare_output(output_dir, exercise_dir)
        source_sha256 = _source_digest(exercise_dir)
    except (OSError, ValueError) as error:
        raise SystemExit(str(error)) from error
    if args.expected_source_sha256 and source_sha256 != args.expected_source_sha256:
        raise SystemExit(
            f"source digest mismatch: expected {args.expected_source_sha256}, observed {source_sha256}"
        )
    ctx = VerifierContext(
        exercise_dir=exercise_dir,
        output_dir=output_dir,
        compiler=shutil.which(args.compiler) or args.compiler,
        expected_gcc=args.expected_gcc,
        source_sha256=source_sha256,
        compile_timeout_s=args.compile_timeout_s,
        link_timeout_s=args.link_timeout_s,
    )
    receipt = verify_policy_2(ctx)
    receipt_path = output_dir / "verification_receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: receipt[key] for key in ("status", "kernel_sum", "passed_kernels", "failed_kernels")}, sort_keys=True))
    print(receipt_path)
    return 0 if receipt["status"] == "pass" else 2 if receipt["status"] == "invalid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
