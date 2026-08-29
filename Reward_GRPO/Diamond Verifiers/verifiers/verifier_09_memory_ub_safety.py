
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


TASK_ID = "diamond"
POLICY_ID = "09"
PINNED = {
    "diamond_test.cpp": "235fc2baac052df9b1efd981d93924b37a738dc85e5b056547a78eeb8840da3f",
    "test/catch.hpp": "681e7505a50887c9085539e5135794fc8f66d8e5de28eadf13a30978627b0f47",
    "test/tests-main.cpp": "5847fda35c1320d94f8d088aaf34229d689f66f1da235f885cbb28c8f17e4260",
}
COMMON = ["-std=c++17", "-Wall", "-Wextra", "-Wpedantic", "-O0", "-g", "-fno-omit-frame-pointer", "-D_GLIBCXX_ASSERTIONS"]
SANITIZERS = {
    "asan": {"flags": ["-fsanitize=address"], "environment": {"ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1"}, "markers": ["addresssanitizer", "leaksanitizer"]},
    "ubsan": {"flags": ["-fsanitize=undefined", "-fno-sanitize-recover=all"], "environment": {"UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"}, "markers": ["undefinedbehaviorsanitizer", "runtime error:"]},
}
DOMAIN_PROBE = r'''#include "diamond.h"
#include <algorithm>
#include <cstddef>
#include <iostream>
#include <string>
#include <vector>
std::vector<std::string> oracle(char letter) {
    const int n = letter - 'A';
    const int side = 2 * n + 1;
    std::vector<std::string> output;
    for (int row = 0; row < side; ++row) {
        const int level = std::min(row, 2 * n - row);
        const int outer = n - level;
        std::string line(static_cast<std::size_t>(side), ' ');
        line.at(static_cast<std::size_t>(outer)) = static_cast<char>('A' + level);
        if (level > 0) line.at(static_cast<std::size_t>(outer + 2 * level)) = static_cast<char>('A' + level);
        output.push_back(line);
    }
    return output;
}
int main() {
    int checked = 0;
    for (char letter = 'A'; letter <= 'Z'; ++letter) {
        if (diamond::rows(letter) != oracle(letter)) return 1;
        ++checked;
    }
    std::cout << "checked=" << checked << '\n';
    return 0;
}
'''


class InvalidEvidence(RuntimeError):
    pass


@dataclass
class Context:
    exercise: Path
    output: Path
    compiler: str
    compile_timeout: int
    runtime_timeout: int
    commands: list[dict[str, Any]] = field(default_factory=list)
    source_before: dict[str, str] = field(default_factory=dict)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest(exercise: Path) -> dict[str, str]:
    return {name: sha256(exercise / name) for name in ("diamond.cpp", "diamond.h")}


def run(ctx: Context, kernel_id: str, label: str, args: list[str], timeout: int, environment: dict[str, str] | None = None) -> dict[str, Any]:
    env = os.environ.copy()
    if environment:
        env.update(environment)
    try:
        completed = subprocess.run(args, capture_output=True, timeout=timeout, check=False, env=env)
        returncode, timed_out, stdout, stderr = completed.returncode, False, completed.stdout, completed.stderr
    except subprocess.TimeoutExpired as exc:
        returncode, timed_out, stdout, stderr = None, True, exc.stdout or b"", exc.stderr or b""
    except OSError as exc:
        raise InvalidEvidence(f"could not start compiler or sanitizer binary: {exc}") from exc
    stdout_path = ctx.output / f"{kernel_id}_{label}.stdout"
    stderr_path = ctx.output / f"{kernel_id}_{label}.stderr"
    stdout_path.write_bytes(stdout)
    stderr_path.write_bytes(stderr)
    record = {"kernel": kernel_id, "label": label, "args": args, "environment": environment or {}, "returncode": returncode, "timed_out": timed_out, "stdout_sha256": sha256(stdout_path), "stderr_sha256": sha256(stderr_path)}
    ctx.commands.append(record)
    return record


def result(kernel_id: str, function: str, passed: bool, summary: str, facts: dict[str, Any]) -> dict[str, Any]:
    return {"kernel_id": kernel_id, "verifier_function": function, "status": "pass" if passed else "fail", "score": 1 if passed else -1, "applicable": True, "summary": summary, "facts": facts}


def marker_found(ctx: Context, kernel_id: str, sanitizer: str) -> list[str]:
    combined = b""
    for suffix in ("run.stdout", "run.stderr"):
        path = ctx.output / f"{kernel_id}_{suffix}"
        if path.is_file():
            combined += path.read_bytes().lower()
    return [marker for marker in SANITIZERS[sanitizer]["markers"] if marker.encode() in combined]


def verify_sanitizer(ctx: Context, kernel_id: str, function: str, sanitizer: str, official: bool) -> dict[str, Any]:
    config = SANITIZERS[sanitizer]
    executable = ctx.output / f"{kernel_id}_diamond"
    args = [ctx.compiler, *COMMON, *config["flags"], "-I", str(ctx.exercise)]
    if official:
        args.extend(["-DEXERCISM_RUN_ALL_TESTS", str(ctx.exercise / "diamond.cpp"), str(ctx.exercise / "diamond_test.cpp"), str(ctx.exercise / "test/tests-main.cpp")])
    else:
        probe = ctx.output / f"{kernel_id}_domain_probe.cpp"
        probe.write_text(DOMAIN_PROBE)
        args.extend([str(ctx.exercise / "diamond.cpp"), str(probe)])
    args.extend(["-o", str(executable)])
    build = run(ctx, kernel_id, "build", args, ctx.compile_timeout)
    if build["returncode"] != 0 or build["timed_out"] or not executable.is_file():
        return result(kernel_id, function, False, "candidate failed sanitizer compilation", {"build_returncode": build["returncode"], "timed_out": build["timed_out"]})
    execution = run(ctx, kernel_id, "run", [str(executable)], ctx.runtime_timeout, config["environment"])
    output_text = (ctx.output / f"{kernel_id}_run.stdout").read_text(errors="replace")
    markers = marker_found(ctx, kernel_id, sanitizer)
    expected = "5 assertions in 5 test cases" if official else "checked=26"
    passed = execution["returncode"] == 0 and not execution["timed_out"] and not markers and expected in output_text
    return result(kernel_id, function, passed, "sanitized workload passed" if passed else "candidate failed workload or sanitizer reported an issue", {"sanitizer": sanitizer, "official": official, "build_returncode": build["returncode"], "run_returncode": execution["returncode"], "timed_out": execution["timed_out"], "markers": markers, "expected_marker": expected, "executable_sha256": sha256(executable)})


def verify_9a_asan_official(ctx: Context) -> dict[str, Any]:
    return verify_sanitizer(ctx, "9A", "verify_9a_asan_official", "asan", True)


def verify_9b_asan_full_domain(ctx: Context) -> dict[str, Any]:
    return verify_sanitizer(ctx, "9B", "verify_9b_asan_full_domain", "asan", False)


def verify_9c_ubsan_official(ctx: Context) -> dict[str, Any]:
    return verify_sanitizer(ctx, "9C", "verify_9c_ubsan_official", "ubsan", True)


def verify_9d_ubsan_full_domain(ctx: Context) -> dict[str, Any]:
    return verify_sanitizer(ctx, "9D", "verify_9d_ubsan_full_domain", "ubsan", False)


def sanitizer_preflight(ctx: Context, name: str) -> dict[str, Any]:
    config = SANITIZERS[name]
    source = ctx.output / f"preflight_{name}.cpp"
    source.write_text("int main() { return 0; }\n")
    executable = ctx.output / f"preflight_{name}"
    build = run(ctx, "preflight", f"{name}_build", [ctx.compiler, *COMMON, *config["flags"], str(source), "-o", str(executable)], ctx.compile_timeout)
    execution = run(ctx, "preflight", f"{name}_run", [str(executable)], ctx.runtime_timeout, config["environment"]) if build["returncode"] == 0 and executable.is_file() else {"returncode": None, "timed_out": False}
    if build["returncode"] != 0 or execution["returncode"] != 0 or build["timed_out"] or execution["timed_out"]:
        raise InvalidEvidence(f"{name} compiler/runtime preflight failed")
    return {"build_returncode": build["returncode"], "run_returncode": execution["returncode"], "executable_sha256": sha256(executable)}


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
    return {"candidate_files": ctx.source_before, "candidate_combined_sha256": combined, "fixed_assets": fixed, "gcc": text.splitlines()[0], "asan": sanitizer_preflight(ctx, "asan"), "ubsan": sanitizer_preflight(ctx, "ubsan")}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exercise-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--compiler", default="g++")
    parser.add_argument("--expected-source-sha256")
    parser.add_argument("--compile-timeout-s", type=int, default=120)
    parser.add_argument("--runtime-timeout-s", type=int, default=60)
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
    ctx = Context(exercise, output, compiler or args.compiler, args.compile_timeout_s, args.runtime_timeout_s)
    receipt: dict[str, Any] = {"schema_version": 1, "task_id": TASK_ID, "contract_variant": "pristine-original-v1", "policy_id": POLICY_ID, "policy_name": "memory_ub_safety", "verifier_source_sha256": sha256(Path(__file__)), "excluded_conditions": [{"condition": "thread_sanitizer", "reason": "no_concurrency_contract"}, {"condition": "contention_stress", "reason": "no_concurrency_contract"}]}
    started = time.time()
    try:
        if compiler is None:
            raise InvalidEvidence("GCC is unavailable")
        receipt["preflight"] = preflight(ctx, args.expected_source_sha256)
        kernels = [verify_9a_asan_official(ctx), verify_9b_asan_full_domain(ctx), verify_9c_ubsan_official(ctx), verify_9d_ubsan_full_domain(ctx)]
        if manifest(ctx.exercise) != ctx.source_before:
            raise InvalidEvidence("candidate source changed during verification")
        receipt.update({"kernels": kernels, "commands": ctx.commands, "applicable_kernel_count": 4, "kernel_sum": sum(item["score"] for item in kernels), "overall_status": "pass" if all(item["score"] == 1 for item in kernels) else "fail"})
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
