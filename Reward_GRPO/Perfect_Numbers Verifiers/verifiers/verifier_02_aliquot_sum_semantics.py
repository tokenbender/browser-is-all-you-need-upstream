# Policy 2 verifier: check the unit edge, official positives, square divisors, and a deterministic proper-divisor oracle.
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
from verifier_01_exact_public_api import _invalid
from verifier_01_exact_public_api import _pass
from verifier_01_exact_public_api import _fail
from verifier_01_exact_public_api import _prepare
from verifier_01_exact_public_api import _run
from verifier_01_exact_public_api import _sha256
from verifier_01_exact_public_api import _source_unchanged
from verifier_01_exact_public_api import _write_probe


TASK_ID = "perfect-numbers"
POLICY_ID = "PN-E02"
STRICT_FLAGS = (
    "-std=c++17",
    "-Wall",
    "-Wextra",
    "-Wpedantic",
    "-Werror",
    "-fno-diagnostics-color",
)
ORACLE = """#include <cstdint>

std::int64_t proper_divisor_sum(const int number) {
    if (number == 1) return 0;
    std::int64_t sum = 1;
    for (int divisor = 2; divisor <= number / divisor; ++divisor) {
        if (number % divisor != 0) continue;
        sum += divisor;
        const int pair = number / divisor;
        if (pair != divisor) sum += pair;
    }
    return sum;
}

perfect_numbers::classification oracle_classify(const int number) {
    const std::int64_t sum = proper_divisor_sum(number);
    if (sum < number) return perfect_numbers::classification::deficient;
    if (sum > number) return perfect_numbers::classification::abundant;
    return perfect_numbers::classification::perfect;
}
"""
NUMBER_ONE_PROBE = """#include \"perfect_numbers.h\"
#include <iostream>

int main() {
    try {
        if (perfect_numbers::classify(1) != perfect_numbers::classification::deficient) return 1;
    } catch (...) {
        return 2;
    }
    std::cout << \"ok=1\\n\";
    return 0;
}
"""
OFFICIAL_POSITIVE_PROBE = """#include \"perfect_numbers.h\"
#include <array>
#include <iostream>
#include <utility>

int main() {
    using perfect_numbers::classification;
    const std::array<std::pair<int, classification>, 10> cases{{
        {6, classification::perfect},
        {28, classification::perfect},
        {33550336, classification::perfect},
        {12, classification::abundant},
        {30, classification::abundant},
        {33550335, classification::abundant},
        {2, classification::deficient},
        {4, classification::deficient},
        {32, classification::deficient},
        {33550337, classification::deficient},
    }};
    try {
        for (const auto& entry : cases) {
            if (perfect_numbers::classify(entry.first) != entry.second) {
                std::cerr << \"mismatch=\" << entry.first << '\\n';
                return 1;
            }
        }
    } catch (...) {
        return 2;
    }
    std::cout << \"ok=10\\n\";
    return 0;
}
"""
SQUARE_PROBE = """#include \"perfect_numbers.h\"
#include <array>
#include <iostream>
""" + ORACLE + """
int main() {
    const std::array<int, 14> cases{9, 16, 25, 36, 49, 64, 81, 100, 121, 144, 169, 196, 225, 256};
    try {
        for (const int number : cases) {
            if (perfect_numbers::classify(number) != oracle_classify(number)) {
                std::cerr << \"mismatch=\" << number << '\\n';
                return 1;
            }
        }
    } catch (...) {
        return 2;
    }
    std::cout << \"ok=14\\n\";
    return 0;
}
"""
GENERATED_PROBE = """#include \"perfect_numbers.h\"
#include <iostream>
""" + ORACLE + """
bool is_square(const int number) {
    for (int root = 1; root <= number / root; ++root) {
        if (root * root == number) return true;
    }
    return false;
}

bool is_official_case(const int number) {
    switch (number) {
        case 2:
        case 4:
        case 6:
        case 12:
        case 28:
        case 30:
        case 32:
            return true;
        default:
            return false;
    }
}

int main() {
    int checked = 0;
    try {
        for (int number = 2; number <= 4096; ++number) {
            if (is_square(number) || is_official_case(number)) continue;
            ++checked;
            if (perfect_numbers::classify(number) != oracle_classify(number)) {
                std::cerr << \"mismatch=\" << number << '\\n';
                return 1;
            }
        }
    } catch (...) {
        return 2;
    }
    std::cout << \"ok=\" << checked << '\\n';
    return 0;
}
"""


def _compile_and_run(
    ctx: Context,
    kernel_id: str,
    label: str,
    content: str,
    expected_stdout: str,
    case_count: int,
) -> KernelReceipt:
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
    facts: dict[str, Any] = {"case_count": case_count, "probe_sha256": _sha256(probe)}
    if not compile_receipt.started:
        return _invalid(kernel_id, "compiler process could not start", [compile_receipt], facts)
    if compile_receipt.return_code != 0 or not executable.is_file() or executable.is_symlink() or executable.stat().st_size == 0:
        return _fail(kernel_id, f"{label} probe did not compile and link", [compile_receipt], facts)
    run_receipt = _run(ctx, kernel_id, f"{label}_run", [str(executable)], ctx.link_timeout_s)
    commands = [compile_receipt, run_receipt]
    if not run_receipt.started:
        return _invalid(kernel_id, "probe process could not start", commands, facts)
    observed_stdout = Path(run_receipt.stdout_log).read_text(encoding="utf-8")
    facts["expected_stdout"] = expected_stdout
    facts["observed_stdout"] = observed_stdout
    if run_receipt.return_code != 0 or observed_stdout != expected_stdout:
        return _fail(kernel_id, f"{label} semantic check failed", commands, facts)
    if not _source_unchanged(ctx):
        return _invalid(kernel_id, "candidate source changed during verification", commands, facts)
    return _pass(
        kernel_id,
        f"{label} semantic check passed",
        commands,
        facts,
        {"probe": _sha256(probe), "executable": _sha256(executable)},
    )


def verify_e02_a_number_one(ctx: Context) -> KernelReceipt:
    return _compile_and_run(ctx, "E02-A", "number_one", NUMBER_ONE_PROBE, "ok=1\n", 1)


def verify_e02_b_official_positive_cases(ctx: Context) -> KernelReceipt:
    return _compile_and_run(ctx, "E02-B", "official_positive", OFFICIAL_POSITIVE_PROBE, "ok=10\n", 10)


def verify_e02_c_square_divisors(ctx: Context) -> KernelReceipt:
    return _compile_and_run(ctx, "E02-C", "square_divisors", SQUARE_PROBE, "ok=14\n", 14)


def verify_e02_d_generated_oracle(ctx: Context) -> KernelReceipt:
    return _compile_and_run(ctx, "E02-D", "generated_oracle", GENERATED_PROBE, "ok=4026\n", 4026)


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
        "maximum_kernel_sum": 4,
        "excluded_conditions": [],
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
        verify_e02_a_number_one,
        verify_e02_b_official_positive_cases,
        verify_e02_c_square_divisors,
        verify_e02_d_generated_oracle,
    )
    results = [check(ctx) for check in checks]
    payload = _write_receipt(ctx.output_dir, ctx.source_sha256, ctx.fixed_hashes, results, None)
    print(json.dumps({"status": payload["status"], "kernel_sum": payload["kernel_sum"], "receipt": str(ctx.output_dir / "verification_receipt.json")}))
    return 0 if payload["status"] == "pass" else 2 if payload["status"] == "invalid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
