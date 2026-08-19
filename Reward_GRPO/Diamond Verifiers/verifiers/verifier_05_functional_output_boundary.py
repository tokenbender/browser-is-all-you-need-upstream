# Policy 5 verifier: build, inventory, execute, and repeatedly check the complete official Diamond suite.
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


TASK_ID = "diamond"
POLICY_ID = "05"
PINNED = {
    "diamond_test.cpp": "235fc2baac052df9b1efd981d93924b37a738dc85e5b056547a78eeb8840da3f",
    "test/catch.hpp": "681e7505a50887c9085539e5135794fc8f66d8e5de28eadf13a30978627b0f47",
    "test/tests-main.cpp": "5847fda35c1320d94f8d088aaf34229d689f66f1da235f885cbb28c8f17e4260",
}
EXPECTED_TESTS = [
    "Degenerate case with a single 'A' row",
    "Degenerate case with no row containing 3 distinct groups of spaces",
    "Smallest non-degenerate case with odd diamond side length",
    "Smallest non-degenerate case with even diamond side length",
    "Largest possible diamond",
]
STRICT = ["-std=c++17", "-Wall", "-Wextra", "-Wpedantic", "-Werror"]


class InvalidEvidence(RuntimeError):
    pass


@dataclass
class Context:
    exercise: Path
    output: Path
    compiler: str
    compile_timeout: int
    runtime_timeout: int
    determinism_runs: int
    commands: list[dict[str, Any]] = field(default_factory=list)
    source_before: dict[str, str] = field(default_factory=dict)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bytes_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def manifest(exercise: Path) -> dict[str, str]:
    return {name: sha256(exercise / name) for name in ("diamond.cpp", "diamond.h")}


def run(ctx: Context, kernel_id: str, label: str, args: list[str], timeout: int) -> dict[str, Any]:
    try:
        completed = subprocess.run(args, capture_output=True, timeout=timeout, check=False)
        returncode, timed_out, stdout, stderr = completed.returncode, False, completed.stdout, completed.stderr
    except subprocess.TimeoutExpired as exc:
        returncode, timed_out, stdout, stderr = None, True, exc.stdout or b"", exc.stderr or b""
    except OSError as exc:
        raise InvalidEvidence(f"could not start tool: {exc}") from exc
    stdout_path = ctx.output / f"{kernel_id}_{label}.stdout"
    stderr_path = ctx.output / f"{kernel_id}_{label}.stderr"
    stdout_path.write_bytes(stdout)
    stderr_path.write_bytes(stderr)
    record = {"kernel": kernel_id, "label": label, "args": args, "returncode": returncode, "timed_out": timed_out, "stdout_sha256": bytes_sha256(stdout), "stderr_sha256": bytes_sha256(stderr)}
    ctx.commands.append(record)
    return record


def result(kernel_id: str, function: str, passed: bool, summary: str, facts: dict[str, Any]) -> dict[str, Any]:
    return {"kernel_id": kernel_id, "verifier_function": function, "status": "pass" if passed else "fail", "score": 1 if passed else -1, "applicable": True, "summary": summary, "facts": facts}


def verify_5a_official_build(ctx: Context) -> tuple[dict[str, Any], Path | None]:
    executable = ctx.output / "diamond"
    record = run(ctx, "5A", "official_build", [ctx.compiler, *STRICT, "-DEXERCISM_RUN_ALL_TESTS", "-I", str(ctx.exercise), str(ctx.exercise / "diamond.cpp"), str(ctx.exercise / "diamond_test.cpp"), str(ctx.exercise / "test/tests-main.cpp"), "-o", str(executable)], ctx.compile_timeout)
    passed = record["returncode"] == 0 and not record["timed_out"] and executable.is_file() and executable.stat().st_size > 0
    return result("5A", "verify_5a_official_build", passed, "official executable built" if passed else "candidate did not build with official suite", {"returncode": record["returncode"], "timed_out": record["timed_out"], "executable_sha256": sha256(executable) if passed else None}), executable if passed else None


def verify_5b_official_test_inventory(ctx: Context, executable: Path | None) -> dict[str, Any]:
    if executable is None:
        return result("5B", "verify_5b_official_test_inventory", False, "blocked by candidate official-build failure", {"blocked_by": "5A"})
    record = run(ctx, "5B", "list_tests", [str(executable), "--list-tests"], ctx.runtime_timeout)
    text = (ctx.output / "5B_list_tests.stdout").read_text(errors="replace")
    present = [name for name in EXPECTED_TESTS if name in text]
    inventory_returncode_ok = record["returncode"] in (0, 5)
    if inventory_returncode_ok and (len(present) != 5 or "5 test cases" not in text):
        raise InvalidEvidence("authenticated official test inventory is not exactly the pinned five cases")
    passed = inventory_returncode_ok and not record["timed_out"] and len(present) == 5 and "5 test cases" in text
    return result("5B", "verify_5b_official_test_inventory", passed, "official inventory contains exactly five expected cases" if passed else "official inventory could not be read", {"returncode": record["returncode"], "accepted_catch_inventory_returncodes": [0, 5], "present": present, "reported_five": "5 test cases" in text})


def official_pass(text: str, returncode: int | None, timed_out: bool) -> bool:
    return returncode == 0 and not timed_out and "All tests passed" in text and "5 assertions in 5 test cases" in text


def verify_5c_official_tests(ctx: Context, executable: Path | None) -> dict[str, Any]:
    if executable is None:
        return result("5C", "verify_5c_official_tests", False, "blocked by candidate official-build failure", {"blocked_by": "5A"})
    record = run(ctx, "5C", "official_tests", [str(executable)], ctx.runtime_timeout)
    text = (ctx.output / "5C_official_tests.stdout").read_text(errors="replace")
    passed = official_pass(text, record["returncode"], record["timed_out"])
    return result("5C", "verify_5c_official_tests", passed, "all five official cases passed" if passed else "candidate failed the official suite", {"returncode": record["returncode"], "timed_out": record["timed_out"], "five_assertions": "5 assertions in 5 test cases" in text})


def verify_5d_deterministic_repetition(ctx: Context, executable: Path | None) -> dict[str, Any]:
    if executable is None:
        return result("5D", "verify_5d_deterministic_repetition", False, "blocked by candidate official-build failure", {"blocked_by": "5A"})
    hashes: list[dict[str, Any]] = []
    all_pass = True
    for index in range(ctx.determinism_runs):
        record = run(ctx, "5D", f"run_{index + 1:02d}", [str(executable)], ctx.runtime_timeout)
        text = (ctx.output / f"5D_run_{index + 1:02d}.stdout").read_text(errors="replace")
        passed = official_pass(text, record["returncode"], record["timed_out"])
        all_pass = all_pass and passed
        hashes.append({"run": index + 1, "stdout_sha256": record["stdout_sha256"], "stderr_sha256": record["stderr_sha256"], "passed": passed})
    unique = {(item["stdout_sha256"], item["stderr_sha256"]) for item in hashes}
    passed = all_pass and len(unique) == 1
    return result("5D", "verify_5d_deterministic_repetition", passed, "official output was deterministic" if passed else "candidate output or status varied across repetitions", {"run_count": ctx.determinism_runs, "unique_output_pairs": len(unique), "runs": hashes})


def preflight(ctx: Context, expected_source: str | None) -> dict[str, Any]:
    if ctx.exercise.name != TASK_ID or not ctx.exercise.is_dir():
        raise InvalidEvidence("exercise directory must be named diamond")
    for name in ("diamond.cpp", "diamond.h", *PINNED):
        path = ctx.exercise / name
        if path.is_symlink() or not path.is_file():
            raise InvalidEvidence(f"missing or unsafe required file: {name}")
    fixed = {name: sha256(ctx.exercise / name) for name in PINNED}
    if fixed != PINNED:
        raise InvalidEvidence("pinned official test asset mismatch")
    ctx.source_before = manifest(ctx.exercise)
    combined = hashlib.sha256(json.dumps(ctx.source_before, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if expected_source and expected_source != combined:
        raise InvalidEvidence("candidate source digest mismatch")
    version = run(ctx, "preflight", "gcc_version", [ctx.compiler, "--version"], 10)
    text = (ctx.output / "preflight_gcc_version.stdout").read_text(errors="replace")
    if version["returncode"] != 0 or "13.3" not in text:
        raise InvalidEvidence("GNU GCC 13.3 unavailable")
    return {"candidate_files": ctx.source_before, "candidate_combined_sha256": combined, "fixed_assets": fixed, "gcc": text.splitlines()[0]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exercise-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--compiler", default="g++")
    parser.add_argument("--expected-source-sha256")
    parser.add_argument("--compile-timeout-s", type=int, default=120)
    parser.add_argument("--official-timeout-s", type=int, default=60)
    parser.add_argument("--determinism-runs", type=int, default=10)
    args = parser.parse_args()
    exercise_absolute = args.exercise_dir.absolute()
    output_absolute = args.output_dir.absolute()
    if any(path.is_symlink() for path in (exercise_absolute, *exercise_absolute.parents)):
        print(json.dumps({"overall_status": "INVALID", "reason": "exercise path must not contain symlinks"}))
        return 2
    if args.output_dir.exists() or any(path.is_symlink() for path in (output_absolute, *output_absolute.parents)):
        print(json.dumps({"overall_status": "INVALID", "reason": "output path must be new and contain no symlinks"}))
        return 2
    exercise = args.exercise_dir.resolve()
    output = args.output_dir.resolve()
    if output == exercise or exercise in output.parents:
        print(json.dumps({"overall_status": "INVALID", "reason": "output directory must be outside the candidate tree"}))
        return 2
    args.output_dir.mkdir(parents=True)
    compiler = shutil.which(args.compiler)
    ctx = Context(exercise, output, compiler or args.compiler, args.compile_timeout_s, args.official_timeout_s, args.determinism_runs)
    receipt: dict[str, Any] = {"schema_version": 1, "task_id": TASK_ID, "contract_variant": "pristine-original-v1", "policy_id": POLICY_ID, "policy_name": "functional_output_boundary", "verifier_source_sha256": sha256(Path(__file__))}
    started = time.time()
    try:
        if compiler is None:
            raise InvalidEvidence("GCC is unavailable")
        if ctx.determinism_runs < 2:
            raise InvalidEvidence("determinism-runs must be at least two")
        receipt["preflight"] = preflight(ctx, args.expected_source_sha256)
        build_result, executable = verify_5a_official_build(ctx)
        kernels = [build_result, verify_5b_official_test_inventory(ctx, executable), verify_5c_official_tests(ctx, executable), verify_5d_deterministic_repetition(ctx, executable)]
        if manifest(ctx.exercise) != ctx.source_before:
            raise InvalidEvidence("candidate source changed during verification")
        receipt.update({"kernels": kernels, "commands": ctx.commands, "kernel_sum": sum(item["score"] for item in kernels), "applicable_kernel_count": 4, "overall_status": "pass" if all(item["score"] == 1 for item in kernels) else "fail"})
        exit_code = 0 if receipt["overall_status"] == "pass" else 1
    except InvalidEvidence as exc:
        receipt.update({"overall_status": "INVALID", "reason": str(exc), "commands": ctx.commands})
        exit_code = 2
    receipt["started_at"] = started
    if isinstance(receipt.get("kernels"), list):
        applicable = [item for item in receipt["kernels"] if item.get("applicable", True)]
        receipt["passed_kernel_count"] = sum(item.get("score") == 1 for item in applicable)
        receipt["failed_kernel_count"] = sum(item.get("score") == -1 for item in applicable)
    receipt["duration_seconds"] = round(time.time() - started, 6)
    receipt["source_immutable"] = manifest(ctx.exercise) == ctx.source_before if ctx.source_before else None
    (ctx.output / "verification_receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
