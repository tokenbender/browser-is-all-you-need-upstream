
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import time
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
PINNED_TEST_SHA256 = "3696b9383f62ab639ad0a26610410fb662b6b927f2fe1dee956b849ff8dcf5c8"
PINNED_CATCH_SHA256 = "681e7505a50887c9085539e5135794fc8f66d8e5de28eadf13a30978627b0f47"
PINNED_TEST_MAIN_SHA256 = "5847fda35c1320d94f8d088aaf34229d689f66f1da235f885cbb28c8f17e4260"
STRICT_FLAGS = (
    "-std=c++17",
    "-Wall",
    "-Wextra",
    "-Wpedantic",
    "-Werror",
    "-pthread",
    "-fno-diagnostics-color",
)
ASAN_FLAGS = (
    "-O1",
    "-g",
    "-fsanitize=address",
    "-fno-omit-frame-pointer",
    "-Wno-error=maybe-uninitialized",
)
UBSAN_FLAGS = (
    "-O1",
    "-g",
    "-fsanitize=undefined",
    "-fno-sanitize-recover=all",
    "-fno-omit-frame-pointer",
)
TSAN_FLAGS = ("-O1", "-g", "-fsanitize=thread", "-fno-omit-frame-pointer")
ASAN_OPTIONS = "halt_on_error=1:abort_on_error=1:detect_leaks=1"
UBSAN_OPTIONS = "halt_on_error=1:print_stacktrace=1"
TSAN_OPTIONS = "halt_on_error=1:second_deadlock_stack=1"
ASAN_MARKERS = ("addresssanitizer", "leaksanitizer")
UBSAN_MARKERS = ("undefinedbehaviorsanitizer", "runtime error:")
TSAN_MARKERS = ("threadsanitizer", "data race")
STRESS_SEEDS = (1, 3, 7, 11, 19, 29, 47, 73, 101, 151, 211, 307)
PREFLIGHT_PROBE = """#include <thread>

int main() {
    int value = 0;
    std::thread worker([&]() { value = 1; });
    worker.join();
    return value == 1 ? 0 : 1;
}
"""
TSAN_PROBE = """#include "bank_account.h"
#include <atomic>
#include <iostream>
#include <thread>
#include <vector>

int main() {
    constexpr int thread_count = 16;
    constexpr int iterations = 250;
    constexpr int expected = thread_count * iterations;
    Bankaccount::Bankaccount account{};
    account.open();
    std::atomic<bool> failed{false};
    std::vector<std::thread> workers;
    workers.reserve(thread_count);
    for (int thread_id = 0; thread_id < thread_count; ++thread_id) {
        workers.emplace_back([&, thread_id]() {
            try {
                for (int index = 0; index < iterations; ++index) {
                    account.deposit(2);
                    if ((index + thread_id) % 11 == 0) std::this_thread::yield();
                    account.withdraw(1);
                    if ((index + thread_id) % 17 == 0) (void)account.balance();
                }
            } catch (...) {
                failed.store(true, std::memory_order_relaxed);
            }
        });
    }
    for (auto& worker : workers) worker.join();
    if (failed.load(std::memory_order_relaxed)) return 1;
    const int observed = account.balance();
    if (observed != expected) return 2;
    std::cout << "tsan-ok:" << observed << '\\n';
    return 0;
}
"""
STRESS_PROBE = """#include "bank_account.h"
#include <atomic>
#include <cstdlib>
#include <iostream>
#include <thread>
#include <vector>

int main(int argc, char** argv) {
    constexpr int thread_count = 24;
    constexpr int iterations = 500;
    constexpr int expected = thread_count * iterations * 2;
    const unsigned seed = argc == 2 ? static_cast<unsigned>(std::strtoul(argv[1], nullptr, 10)) : 1U;
    Bankaccount::Bankaccount account{};
    account.open();
    std::atomic<bool> failed{false};
    std::vector<std::thread> workers;
    workers.reserve(thread_count);
    for (int thread_id = 0; thread_id < thread_count; ++thread_id) {
        workers.emplace_back([&, thread_id]() {
            try {
                for (int index = 0; index < iterations; ++index) {
                    const unsigned selector = seed + static_cast<unsigned>(thread_id * 17 + index * 31);
                    account.deposit(3);
                    if (selector % 5U == 0U) std::this_thread::yield();
                    account.withdraw(1);
                    account.deposit(1);
                    if (selector % 7U == 0U) std::this_thread::yield();
                    account.withdraw(1);
                    if (selector % 37U == 0U) (void)account.balance();
                }
            } catch (...) {
                failed.store(true, std::memory_order_relaxed);
            }
        });
    }
    for (auto& worker : workers) worker.join();
    if (failed.load(std::memory_order_relaxed)) return 1;
    const int observed = account.balance();
    if (observed != expected) return 2;
    std::cout << "stress-ok:" << seed << ':' << observed << '\\n';
    return 0;
}
"""


@dataclass(frozen=True)
class CommandReceipt:
    label: str
    command: list[str]
    environment: dict[str, str]
    return_code: int | None
    timed_out: bool
    duration_seconds: float
    stdout_log: str
    stderr_log: str


@dataclass(frozen=True)
class KernelReceipt:
    kernel_id: str
    kernel: int | None
    verdict: str
    summary: str
    commands: list[CommandReceipt] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)
    artifact_sha256: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class VerifierContext:
    exercise_dir: Path
    output_dir: Path
    compiler: str
    setarch: str
    architecture: str
    expected_gcc: str
    source_sha256: str
    compile_timeout_s: int
    runtime_timeout_s: int
    stress_timeout_s: int


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for relative in REQUIRED_ASSETS:
        path = root / relative
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_sha256(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _valid_artifact(path: Path, executable: bool = False) -> bool:
    return (
        path.is_file()
        and not path.is_symlink()
        and path.stat().st_size > 0
        and (not executable or os.access(path, os.X_OK))
    )


def _run(
    ctx: VerifierContext,
    group: str,
    label: str,
    command: list[str],
    timeout_s: int,
    environment: dict[str, str] | None = None,
) -> CommandReceipt:
    log_dir = ctx.output_dir / "logs" / group
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / f"{label}.stdout.log"
    stderr_path = log_dir / f"{label}.stderr.log"
    started = time.monotonic()
    return_code: int | None = None
    timed_out = False
    stdout = ""
    stderr = ""
    recorded_environment = environment or {}
    try:
        completed = subprocess.run(
            command,
            cwd=ctx.output_dir,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env={**os.environ, **recorded_environment},
        )
        return_code = completed.returncode
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
    except subprocess.TimeoutExpired as error:
        timed_out = True
        stdout = error.stdout.decode(errors="replace") if isinstance(error.stdout, bytes) else error.stdout or ""
        stderr = error.stderr.decode(errors="replace") if isinstance(error.stderr, bytes) else error.stderr or ""
    duration = time.monotonic() - started
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    return CommandReceipt(
        label=label,
        command=command,
        environment=recorded_environment,
        return_code=return_code,
        timed_out=timed_out,
        duration_seconds=duration,
        stdout_log=str(stdout_path),
        stderr_log=str(stderr_path),
    )


def _combined(command: CommandReceipt) -> str:
    return (
        Path(command.stdout_log).read_text(encoding="utf-8", errors="replace")
        + Path(command.stderr_log).read_text(encoding="utf-8", errors="replace")
    )


def _has_marker(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in markers)


def _pass(
    kernel_id: str,
    summary: str,
    commands: list[CommandReceipt],
    facts: dict[str, Any],
    artifacts: dict[str, str],
) -> KernelReceipt:
    return KernelReceipt(kernel_id, 1, "pass", summary, commands, facts, artifacts)


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


def _assets_valid(ctx: VerifierContext) -> tuple[bool, str, dict[str, Any]]:
    missing = [relative for relative in REQUIRED_ASSETS if not (ctx.exercise_dir / relative).is_file()]
    if missing:
        return False, f"missing required assets: {missing}", {"missing_assets": missing}
    hashes = {
        "official_test_sha256": _sha256(ctx.exercise_dir / "bank_account_test.cpp"),
        "catch_sha256": _sha256(ctx.exercise_dir / "test/catch.hpp"),
        "test_main_sha256": _sha256(ctx.exercise_dir / "test/tests-main.cpp"),
    }
    expected = {
        "official_test_sha256": PINNED_TEST_SHA256,
        "catch_sha256": PINNED_CATCH_SHA256,
        "test_main_sha256": PINNED_TEST_MAIN_SHA256,
    }
    matches = hashes == expected
    return matches, "pinned official test assets matched" if matches else "official test asset hash mismatch", hashes


def _compile_command(
    ctx: VerifierContext,
    sources: list[Path],
    executable: Path,
    extra_flags: tuple[str, ...],
    definitions: tuple[str, ...] = (),
) -> list[str]:
    return [
        ctx.compiler,
        *STRICT_FLAGS,
        *extra_flags,
        *definitions,
        f"-I{ctx.exercise_dir}",
        *(str(source) for source in sources),
        "-o",
        str(executable),
    ]


def _runtime_command(ctx: VerifierContext, executable: Path, tsan: bool = False, args: list[str] | None = None) -> list[str]:
    suffix = args or []
    if tsan:
        return [ctx.setarch, ctx.architecture, "-R", str(executable), *suffix]
    return [str(executable), *suffix]


def _preflight(ctx: VerifierContext) -> tuple[bool, str, list[CommandReceipt], dict[str, Any]]:
    commands: list[CommandReceipt] = []
    assets_ok, assets_summary, assets_facts = _assets_valid(ctx)
    if not assets_ok:
        return False, assets_summary, commands, assets_facts
    version = _run(ctx, "preflight", "gcc_version", [ctx.compiler, "-dumpfullversion", "-dumpversion"], 15)
    commands.append(version)
    version_text = Path(version.stdout_log).read_text(encoding="utf-8").strip()
    version_ok = version.return_code == 0 and (version_text == ctx.expected_gcc or version_text.startswith(f"{ctx.expected_gcc}."))
    if not version_ok:
        return False, "expected GNU GCC 13.3", commands, {**assets_facts, "compiler_version": version_text}
    preflight_dir = ctx.output_dir / "preflight"
    preflight_dir.mkdir(parents=True, exist_ok=True)
    source = preflight_dir / "probe.cpp"
    source.write_text(PREFLIGHT_PROBE, encoding="utf-8")
    specifications = (
        ("asan", ASAN_FLAGS, {"ASAN_OPTIONS": ASAN_OPTIONS}, False, ASAN_MARKERS),
        ("ubsan", UBSAN_FLAGS, {"UBSAN_OPTIONS": UBSAN_OPTIONS}, False, UBSAN_MARKERS),
        ("tsan", TSAN_FLAGS, {"TSAN_OPTIONS": TSAN_OPTIONS}, True, TSAN_MARKERS),
    )
    facts: dict[str, Any] = {**assets_facts, "compiler_version": version_text}
    for name, flags, environment, use_setarch, markers in specifications:
        executable = preflight_dir / f"probe_{name}"
        compile_receipt = _run(
            ctx,
            "preflight",
            f"compile_{name}",
            _compile_command(ctx, [source], executable, flags),
            ctx.compile_timeout_s,
        )
        commands.append(compile_receipt)
        if compile_receipt.return_code != 0 or compile_receipt.timed_out or not _valid_artifact(executable, True):
            return False, f"{name} compiler preflight failed", commands, facts
        run_receipt = _run(
            ctx,
            "preflight",
            f"run_{name}",
            _runtime_command(ctx, executable, use_setarch),
            ctx.runtime_timeout_s,
            environment,
        )
        commands.append(run_receipt)
        logs = _combined(run_receipt)
        if run_receipt.return_code != 0 or run_receipt.timed_out or _has_marker(logs, markers):
            return False, f"{name} runtime preflight failed", commands, facts
        facts[f"{name}_preflight"] = "pass"
    facts["architecture"] = ctx.architecture
    facts["setarch"] = ctx.setarch
    return True, "GCC and all sanitizer runtime preflights passed", commands, facts


def _verify_official_sanitizer(
    ctx: VerifierContext,
    kernel_id: str,
    name: str,
    flags: tuple[str, ...],
    environment: dict[str, str],
    markers: tuple[str, ...],
) -> KernelReceipt:
    build_dir = ctx.output_dir / "builds" / name
    build_dir.mkdir(parents=True, exist_ok=True)
    executable = build_dir / "bank-account-tests"
    sources = [
        ctx.exercise_dir / "bank_account.cpp",
        ctx.exercise_dir / "bank_account_test.cpp",
        ctx.exercise_dir / "test/tests-main.cpp",
    ]
    compile_receipt = _run(
        ctx,
        kernel_id,
        f"compile_{name}",
        _compile_command(ctx, sources, executable, flags, ("-DEXERCISM_RUN_ALL_TESTS",)),
        ctx.compile_timeout_s,
    )
    commands = [compile_receipt]
    facts: dict[str, Any] = {
        "sanitizer": name,
        "official_test_count": 17,
        "compile_return_code": compile_receipt.return_code,
        "compile_timed_out": compile_receipt.timed_out,
    }
    if compile_receipt.return_code != 0 or compile_receipt.timed_out or not _valid_artifact(executable, True):
        return _fail(kernel_id, f"candidate did not build under {name}", commands, facts)
    run_receipt = _run(
        ctx,
        kernel_id,
        f"run_{name}",
        _runtime_command(ctx, executable),
        ctx.runtime_timeout_s,
        environment,
    )
    commands.append(run_receipt)
    logs = _combined(run_receipt)
    marker_found = _has_marker(logs, markers)
    facts.update(
        {
            "run_return_code": run_receipt.return_code,
            "run_timed_out": run_receipt.timed_out,
            "sanitizer_marker_found": marker_found,
            "source_digest_unchanged": _source_digest(ctx.exercise_dir) == ctx.source_sha256,
        }
    )
    passed = (
        run_receipt.return_code == 0
        and not run_receipt.timed_out
        and not marker_found
        and facts["source_digest_unchanged"]
    )
    if passed:
        return _pass(
            kernel_id,
            f"all 17 official tests passed cleanly under {name}",
            commands,
            facts,
            {
                executable.name: _sha256(executable),
                "official_test": PINNED_TEST_SHA256,
                f"{name}.stdout": _sha256(Path(run_receipt.stdout_log)),
                f"{name}.stderr": _sha256(Path(run_receipt.stderr_log)),
            },
        )
    return _fail(kernel_id, f"candidate failed or reported an error under {name}", commands, facts)


def verify_9a_asan(ctx: VerifierContext) -> KernelReceipt:
    return _verify_official_sanitizer(
        ctx,
        "9A",
        "asan",
        ASAN_FLAGS,
        {"ASAN_OPTIONS": ASAN_OPTIONS},
        ASAN_MARKERS,
    )


def verify_9b_ubsan(ctx: VerifierContext) -> KernelReceipt:
    return _verify_official_sanitizer(
        ctx,
        "9B",
        "ubsan",
        UBSAN_FLAGS,
        {"UBSAN_OPTIONS": UBSAN_OPTIONS},
        UBSAN_MARKERS,
    )


def verify_9c_tsan(ctx: VerifierContext) -> KernelReceipt:
    probe_dir = ctx.output_dir / "probes"
    build_dir = ctx.output_dir / "builds" / "tsan"
    probe_dir.mkdir(parents=True, exist_ok=True)
    build_dir.mkdir(parents=True, exist_ok=True)
    probe = probe_dir / "tsan_concurrency.cpp"
    probe.write_text(TSAN_PROBE, encoding="utf-8")
    executable = build_dir / "bank-account-tsan"
    compile_receipt = _run(
        ctx,
        "9C",
        "compile_tsan_candidate",
        _compile_command(
            ctx,
            [ctx.exercise_dir / "bank_account.cpp", probe],
            executable,
            TSAN_FLAGS,
        ),
        ctx.compile_timeout_s,
    )
    commands = [compile_receipt]
    facts: dict[str, Any] = {
        "thread_count": 16,
        "iterations_per_thread": 250,
        "expected_balance": 4000,
        "compile_return_code": compile_receipt.return_code,
    }
    if compile_receipt.return_code != 0 or compile_receipt.timed_out or not _valid_artifact(executable, True):
        return _fail("9C", "candidate TSAN probe did not build", commands, facts)
    run_receipt = _run(
        ctx,
        "9C",
        "run_tsan_candidate",
        _runtime_command(ctx, executable, True),
        ctx.runtime_timeout_s,
        {"TSAN_OPTIONS": TSAN_OPTIONS},
    )
    commands.append(run_receipt)
    stdout = Path(run_receipt.stdout_log).read_text(encoding="utf-8", errors="replace")
    logs = _combined(run_receipt)
    marker_found = _has_marker(logs, TSAN_MARKERS)
    facts.update(
        {
            "run_return_code": run_receipt.return_code,
            "run_timed_out": run_receipt.timed_out,
            "expected_output": "tsan-ok:4000\n",
            "observed_output": stdout,
            "tsan_marker_found": marker_found,
            "source_digest_unchanged": _source_digest(ctx.exercise_dir) == ctx.source_sha256,
        }
    )
    passed = (
        run_receipt.return_code == 0
        and not run_receipt.timed_out
        and stdout == "tsan-ok:4000\n"
        and not marker_found
        and facts["source_digest_unchanged"]
    )
    if passed:
        return _pass(
            "9C",
            "TSAN found no race and the concurrent balance was exact",
            commands,
            facts,
            {
                probe.name: _sha256(probe),
                executable.name: _sha256(executable),
                "tsan.stdout": _sha256(Path(run_receipt.stdout_log)),
                "tsan.stderr": _sha256(Path(run_receipt.stderr_log)),
            },
        )
    return _fail("9C", "TSAN reported a candidate failure or the balance was wrong", commands, facts)


def verify_9d_contention_stress(ctx: VerifierContext) -> KernelReceipt:
    probe_dir = ctx.output_dir / "probes"
    build_dir = ctx.output_dir / "builds" / "stress"
    probe_dir.mkdir(parents=True, exist_ok=True)
    build_dir.mkdir(parents=True, exist_ok=True)
    probe = probe_dir / "contention_stress.cpp"
    probe.write_text(STRESS_PROBE, encoding="utf-8")
    executable = build_dir / "bank-account-stress"
    compile_receipt = _run(
        ctx,
        "9D",
        "compile_stress_candidate",
        _compile_command(
            ctx,
            [ctx.exercise_dir / "bank_account.cpp", probe],
            executable,
            ("-O2",),
        ),
        ctx.compile_timeout_s,
    )
    commands = [compile_receipt]
    facts: dict[str, Any] = {
        "thread_count": 24,
        "iterations_per_thread": 500,
        "operations_per_iteration": 4,
        "expected_balance": 24000,
        "seeds": list(STRESS_SEEDS),
        "completed_runs": 0,
    }
    if compile_receipt.return_code != 0 or compile_receipt.timed_out or not _valid_artifact(executable, True):
        return _fail("9D", "candidate contention probe did not build", commands, facts)
    run_hashes: dict[str, str] = {}
    passed = True
    for seed in STRESS_SEEDS:
        run_receipt = _run(
            ctx,
            "9D",
            f"stress_seed_{seed}",
            _runtime_command(ctx, executable, False, [str(seed)]),
            ctx.stress_timeout_s,
        )
        commands.append(run_receipt)
        stdout = Path(run_receipt.stdout_log).read_text(encoding="utf-8", errors="replace")
        expected = f"stress-ok:{seed}:24000\n"
        if run_receipt.return_code != 0 or run_receipt.timed_out or stdout != expected:
            passed = False
            facts["first_failed_seed"] = seed
            facts["first_failed_output"] = stdout
            break
        facts["completed_runs"] += 1
        run_hashes[f"seed_{seed}.stdout"] = _sha256(Path(run_receipt.stdout_log))
        run_hashes[f"seed_{seed}.stderr"] = _sha256(Path(run_receipt.stderr_log))
    facts["source_digest_unchanged"] = _source_digest(ctx.exercise_dir) == ctx.source_sha256
    passed = passed and facts["completed_runs"] == len(STRESS_SEEDS) and facts["source_digest_unchanged"]
    if passed:
        return _pass(
            "9D",
            "all 12 high-contention schedules produced the exact balance",
            commands,
            facts,
            {probe.name: _sha256(probe), executable.name: _sha256(executable), **run_hashes},
        )
    return _fail("9D", "a contention schedule failed, timed out, or produced a wrong balance", commands, facts)


def verify_policy_9(ctx: VerifierContext) -> dict[str, Any]:
    preflight_ok, preflight_summary, preflight_commands, preflight_facts = _preflight(ctx)
    if preflight_ok:
        results = [
            verify_9a_asan(ctx),
            verify_9b_ubsan(ctx),
            verify_9c_tsan(ctx),
            verify_9d_contention_stress(ctx),
        ]
    else:
        results = [
            _invalid(kernel_id, preflight_summary, preflight_commands, preflight_facts)
            for kernel_id in ("9A", "9B", "9C", "9D")
        ]
    invalid = any(result.kernel is None for result in results)
    kernel_sum = None if invalid else sum(result.kernel for result in results if result.kernel is not None)
    status = "invalid" if invalid else "pass" if kernel_sum == 4 else "fail"
    return {
        "schema_version": 1,
        "policy_id": "bank-account-policy-09-concurrency-memory-ub-safety-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "kernel_model": {"pass": 1, "fail": -1, "infrastructure": "INVALID"},
        "kernel_sum": kernel_sum,
        "kernel_range": [-4, 4],
        "full_pass_required": 4,
        "applicable_kernel_ids": ["9A", "9B", "9C", "9D"],
        "excluded_conditions": {},
        "passed_kernels": sum(result.kernel == 1 for result in results),
        "failed_kernels": sum(result.kernel == -1 for result in results),
        "source_sha256": ctx.source_sha256,
        "exercise_dir": str(ctx.exercise_dir),
        "preflight": {
            "status": "pass" if preflight_ok else "invalid",
            "summary": preflight_summary,
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
    parser.add_argument("--setarch", default="setarch")
    parser.add_argument("--expected-gcc", default="13.3")
    parser.add_argument("--expected-source-sha256")
    parser.add_argument("--compile-timeout-s", type=int, default=120)
    parser.add_argument("--runtime-timeout-s", type=int, default=120)
    parser.add_argument("--stress-timeout-s", type=int, default=30)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    exercise_dir = args.exercise_dir.resolve()
    output_dir = args.output_dir.resolve()
    if not exercise_dir.is_dir():
        raise SystemExit(f"exercise directory does not exist: {exercise_dir}")
    compiler = shutil.which(args.compiler)
    setarch = shutil.which(args.setarch)
    if compiler is None or setarch is None:
        raise SystemExit("compiler and setarch must both be available")
    try:
        _prepare_output(output_dir, exercise_dir)
        missing = [relative for relative in REQUIRED_ASSETS if not (exercise_dir / relative).is_file()]
        if missing:
            raise ValueError(f"missing required assets: {missing}")
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
        compiler=compiler,
        setarch=setarch,
        architecture=platform.machine(),
        expected_gcc=args.expected_gcc,
        source_sha256=source_sha256,
        compile_timeout_s=args.compile_timeout_s,
        runtime_timeout_s=args.runtime_timeout_s,
        stress_timeout_s=args.stress_timeout_s,
    )
    receipt = verify_policy_9(ctx)
    receipt_path = output_dir / "verification_receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: receipt[key] for key in ("status", "kernel_sum", "passed_kernels", "failed_kernels")}, sort_keys=True))
    print(receipt_path)
    return 0 if receipt["status"] == "pass" else 2 if receipt["status"] == "invalid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
