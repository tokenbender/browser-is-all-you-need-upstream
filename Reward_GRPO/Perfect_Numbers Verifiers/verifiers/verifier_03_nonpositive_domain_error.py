
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

sys.dont_write_bytecode = True

from verifier_01_exact_public_api import Context
from verifier_01_exact_public_api import KernelReceipt
from verifier_01_exact_public_api import PreflightError
from verifier_01_exact_public_api import _fail
from verifier_01_exact_public_api import _invalid
from verifier_01_exact_public_api import _pass
from verifier_01_exact_public_api import _prepare
from verifier_01_exact_public_api import _run
from verifier_01_exact_public_api import _sha256
from verifier_01_exact_public_api import _source_unchanged
from verifier_01_exact_public_api import _write_probe


TASK_ID = "perfect-numbers"
POLICY_ID = "PN-E03"
STRICT_FLAGS = (
    "-std=c++17",
    "-Wall",
    "-Wextra",
    "-Wpedantic",
    "-Werror",
    "-fno-diagnostics-color",
)


def _probe(values: str, count: int) -> str:
    return f"""#include \"perfect_numbers.h\"
#include <array>
#include <climits>
#include <iostream>
#include <stdexcept>

int classify_exception(const int number) {{
    try {{
        (void)perfect_numbers::classify(number);
        return 1;
    }} catch (const std::domain_error&) {{
        return 0;
    }} catch (...) {{
        return 2;
    }}
}}

int main() {{
    const std::array<int, {count}> values{{{values}}};
    for (const int number : values) {{
        const int result = classify_exception(number);
        if (result != 0) {{
            std::cerr << \"input=\" << number << \" exception_result=\" << result << '\\n';
            return result;
        }}
    }}
    std::cout << \"ok={count}\\n\";
    return 0;
}}
"""


def _compile_and_run(
    ctx: Context,
    kernel_id: str,
    label: str,
    values: str,
    count: int,
) -> KernelReceipt:
    content = _probe(values, count)
    probe = _write_probe(ctx, f"{kernel_id.lower().replace('-', '_')}_{label}.cpp", content)
    executable = ctx.output_dir / "artifacts" / f"{kernel_id.lower().replace('-', '_')}_{label}"
    executable.parent.mkdir(parents=True, exist_ok=True)
    compile_command = [
        ctx.compiler,
        *STRICT_FLAGS,
        "-I",
        str(ctx.exercise_dir),
        str(probe),
        str(ctx.exercise_dir / "perfect_numbers.cpp"),
        "-o",
        str(executable),
    ]
    compile_receipt = _run(ctx, kernel_id, f"{label}_compile", compile_command, ctx.compile_timeout_s)
    facts: dict[str, Any] = {"case_count": count, "probe_sha256": _sha256(probe)}
    if not compile_receipt.started:
        return _invalid(kernel_id, "compiler process could not start", [compile_receipt], facts)
    if compile_receipt.return_code != 0 or not executable.is_file() or executable.is_symlink() or executable.stat().st_size == 0:
        return _fail(kernel_id, f"{label} exception probe did not compile and link", [compile_receipt], facts)
    run_receipt = _run(ctx, kernel_id, f"{label}_run", [str(executable)], ctx.link_timeout_s)
    commands = [compile_receipt, run_receipt]
    if not run_receipt.started:
        return _invalid(kernel_id, "exception probe process could not start", commands, facts)
    observed_stdout = Path(run_receipt.stdout_log).read_text(encoding="utf-8")
    expected_stdout = f"ok={count}\n"
    facts["expected_stdout"] = expected_stdout
    facts["observed_stdout"] = observed_stdout
    if run_receipt.return_code != 0 or observed_stdout != expected_stdout:
        return _fail(kernel_id, f"{label} did not throw std::domain_error for every input", commands, facts)
    if not _source_unchanged(ctx):
        return _invalid(kernel_id, "candidate source changed during verification", commands, facts)
    return _pass(
        kernel_id,
        f"{label} threw std::domain_error for every input",
        commands,
        facts,
        {"probe": _sha256(probe), "executable": _sha256(executable)},
    )


def verify_e03_a_zero(ctx: Context) -> KernelReceipt:
    return _compile_and_run(ctx, "E03-A", "zero", "0", 1)


def verify_e03_b_negative_one(ctx: Context) -> KernelReceipt:
    return _compile_and_run(ctx, "E03-B", "negative_one", "-1", 1)


def verify_e03_c_negative_partition(ctx: Context) -> KernelReceipt:
    return _compile_and_run(ctx, "E03-C", "negative_partition", "-2, -7, -28, -33550336, INT_MIN", 5)


def _write_receipt(
    output_dir: Path,
    source_sha256: str | None,
    fixed_hashes: dict[str, str],
    results: list[KernelReceipt],
    preflight_error: str | None,
) -> dict[str, Any]:
    invalid = preflight_error is not None or any(result.kernel is None for result in results)
    kernel_sum = None if invalid else sum(result.kernel or 0 for result in results)
    status = "invalid" if invalid else "pass" if all(result.kernel == 1 for result in results) else "fail"
    payload: dict[str, Any] = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "policy_id": POLICY_ID,
        "status": status,
        "preflight_error": preflight_error,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "verifier_source_sha256": _sha256(Path(__file__).resolve()),
        "verifier_dependency_sha256": {
            "verifier_01_exact_public_api.py": _sha256(Path(__file__).resolve().with_name("verifier_01_exact_public_api.py"))
        },
        "candidate_source_sha256": source_sha256,
        "fixed_asset_sha256": fixed_hashes,
        "kernel_results": [asdict(result) for result in results],
        "passed_count": sum(result.kernel == 1 for result in results),
        "failed_count": sum(result.kernel == -1 for result in results),
        "invalid_count": sum(result.kernel is None for result in results),
        "kernel_sum": kernel_sum,
        "maximum_kernel_sum": 3,
        "excluded_conditions": [{"condition": "exception_message", "reason": "not_contractual"}],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "verification_receipt.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exercise-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--compiler", default="g++")
    parser.add_argument("--expected-gcc", default="13.3")
    parser.add_argument("--compile-timeout-s", type=int, default=120)
    parser.add_argument("--link-timeout-s", type=int, default=30)
    return parser


def main() -> int:
    args = _parser().parse_args()
    output_dir = args.output_dir.resolve()
    try:
        ctx = _prepare(args)
    except (OSError, subprocess.SubprocessError, PreflightError) as error:
        exercise_dir = args.exercise_dir.resolve()
        unsafe_output = (
            args.output_dir.is_symlink()
            or output_dir == exercise_dir
            or output_dir.is_relative_to(exercise_dir)
        )
        if unsafe_output or (output_dir.exists() and output_dir.is_dir() and any(output_dir.iterdir())):
            print(f"INVALID: {error}", file=sys.stderr)
            return 2
        payload = _write_receipt(output_dir, None, {}, [], str(error))
        print(json.dumps({"status": payload["status"], "receipt": str(output_dir / "verification_receipt.json")}))
        return 2
    checks: tuple[Callable[[Context], KernelReceipt], ...] = (
        verify_e03_a_zero,
        verify_e03_b_negative_one,
        verify_e03_c_negative_partition,
    )
    results = [check(ctx) for check in checks]
    payload = _write_receipt(ctx.output_dir, ctx.source_sha256, ctx.fixed_hashes, results, None)
    print(json.dumps({"status": payload["status"], "kernel_sum": payload["kernel_sum"], "receipt": str(ctx.output_dir / "verification_receipt.json")}))
    return 0 if payload["status"] == "pass" else 2 if payload["status"] == "invalid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
