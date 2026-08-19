# Policy 5 verifier: check six independent functional, state, and boundary kernels.
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


REQUIRED_ASSETS = (
    "CMakeLists.txt",
    "bank_account.h",
    "bank_account.cpp",
    "bank_account_test.cpp",
    "test/catch.hpp",
    "test/tests-main.cpp",
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
PINNED_TEST_SHA256 = "3696b9383f62ab639ad0a26610410fb662b6b927f2fe1dee956b849ff8dcf5c8"
PINNED_CATCH_SHA256 = "681e7505a50887c9085539e5135794fc8f66d8e5de28eadf13a30978627b0f47"
PINNED_TEST_MAIN_SHA256 = "5847fda35c1320d94f8d088aaf34229d689f66f1da235f885cbb28c8f17e4260"
LIFECYCLE_PROBE = """#include \"bank_account.h\"
#include <iostream>

int main() {
    try {
        Bankaccount::Bankaccount account{};
        account.open();
        if (account.balance() != 0) return 1;
        account.deposit(41);
        account.close();
        account.open();
        if (account.balance() != 0) return 2;
        account.deposit(7);
        account.close();
        account.open();
        if (account.balance() != 0) return 3;
        account.close();
        std::cout << \"lifecycle-ok\\n\";
        return 0;
    } catch (...) {
        return 10;
    }
}
"""
BOUNDARY_PROBE = """#include \"bank_account.h\"
#include <climits>
#include <iostream>

int main() {
    try {
        Bankaccount::Bankaccount account{};
        account.open();
        if (account.balance() != 0) return 1;
        account.deposit(0);
        if (account.balance() != 0) return 2;
        account.withdraw(0);
        if (account.balance() != 0) return 3;
        account.deposit(1);
        if (account.balance() != 1) return 4;
        account.withdraw(1);
        if (account.balance() != 0) return 5;
        account.deposit(INT_MAX);
        if (account.balance() != INT_MAX) return 6;
        account.withdraw(INT_MAX);
        if (account.balance() != 0) return 7;
        account.close();
        std::cout << \"boundary-ok\\n\";
        return 0;
    } catch (...) {
        return 10;
    }
}
"""
ARITHMETIC_PROBE = """#include \"bank_account.h\"
#include <iostream>
#include <stdexcept>

template <typename Operation>
bool throws_runtime_error(Operation operation) {
    try {
        operation();
    } catch (const std::runtime_error&) {
        return true;
    } catch (...) {
        return false;
    }
    return false;
}

int main() {
    Bankaccount::Bankaccount account{};
    try {
        account.open();
        account.deposit(100);
        account.deposit(50);
        if (account.balance() != 150) return 1;
        account.withdraw(40);
        if (account.balance() != 110) return 2;
        if (!throws_runtime_error([&]() { account.withdraw(111); })) return 3;
        if (account.balance() != 110) return 4;
        if (!throws_runtime_error([&]() { account.deposit(-5); })) return 5;
        if (account.balance() != 110) return 6;
        if (!throws_runtime_error([&]() { account.withdraw(-5); })) return 7;
        if (account.balance() != 110) return 8;
        account.withdraw(110);
        if (account.balance() != 0) return 9;
        account.close();
        std::cout << \"arithmetic-ok\\n\";
        return 0;
    } catch (...) {
        return 10;
    }
}
"""
INVALID_OPERATIONS_PROBE = """#include \"bank_account.h\"
#include <iostream>
#include <stdexcept>

template <typename Operation>
bool throws_runtime_error(Operation operation) {
    try {
        operation();
    } catch (const std::runtime_error&) {
        return true;
    } catch (...) {
        return false;
    }
    return false;
}

int main() {
    Bankaccount::Bankaccount account{};
    if (!throws_runtime_error([&]() { account.deposit(1); })) return 1;
    if (!throws_runtime_error([&]() { account.withdraw(1); })) return 2;
    if (!throws_runtime_error([&]() { (void)account.balance(); })) return 3;
    if (!throws_runtime_error([&]() { account.close(); })) return 4;
    try {
        account.open();
        if (account.balance() != 0) return 5;
        if (!throws_runtime_error([&]() { account.open(); })) return 6;
        if (account.balance() != 0) return 7;
        account.deposit(50);
        if (!throws_runtime_error([&]() { account.deposit(-1); })) return 8;
        if (!throws_runtime_error([&]() { account.withdraw(-1); })) return 9;
        if (!throws_runtime_error([&]() { account.withdraw(51); })) return 10;
        if (account.balance() != 50) return 11;
        account.close();
    } catch (...) {
        return 12;
    }
    if (!throws_runtime_error([&]() { account.deposit(1); })) return 13;
    if (!throws_runtime_error([&]() { account.withdraw(1); })) return 14;
    if (!throws_runtime_error([&]() { (void)account.balance(); })) return 15;
    if (!throws_runtime_error([&]() { account.close(); })) return 16;
    try {
        account.open();
        account.close();
    } catch (...) {
        return 17;
    }
    std::cout << \"invalid-operations-ok\\n\";
    return 0;
}
"""
DETERMINISM_PROBE = """#include \"bank_account.h\"
#include <iostream>

int main() {
    try {
        Bankaccount::Bankaccount account{};
        account.open();
        for (int amount = 1; amount <= 50; ++amount) {
            account.deposit(amount);
        }
        if (account.balance() != 1275) return 1;
        account.withdraw(1275);
        if (account.balance() != 0) return 2;
        account.close();
        account.open();
        if (account.balance() != 0) return 3;
        account.close();
        std::cout << \"deterministic-ok:0\\n\";
        return 0;
    } catch (...) {
        return 10;
    }
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
    expected_test_sha256: str
    expected_catch_sha256: str
    expected_test_main_sha256: str
    compile_timeout_s: int
    runtime_timeout_s: int
    official_timeout_s: int
    determinism_runs: int


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


def _fixed_test_facts(ctx: VerifierContext) -> dict[str, Any]:
    test_path = ctx.exercise_dir / "bank_account_test.cpp"
    catch_path = ctx.exercise_dir / "test/catch.hpp"
    test_main_path = ctx.exercise_dir / "test/tests-main.cpp"
    test_hash = _sha256(test_path)
    catch_hash = _sha256(catch_path)
    test_main_hash = _sha256(test_main_path)
    return {
        "official_test_sha256": test_hash,
        "catch_sha256": catch_hash,
        "test_main_sha256": test_main_hash,
        "official_test_hash_matches": test_hash == ctx.expected_test_sha256,
        "catch_hash_matches": catch_hash == ctx.expected_catch_sha256,
        "test_main_hash_matches": test_main_hash == ctx.expected_test_main_sha256,
    }


def _build_probe(
    ctx: VerifierContext,
    kernel_id: str,
    name: str,
    source: str,
) -> tuple[Path, Path, CommandReceipt]:
    probes = ctx.output_dir / "probes"
    executables = ctx.output_dir / "executables"
    probes.mkdir(parents=True, exist_ok=True)
    executables.mkdir(parents=True, exist_ok=True)
    probe = probes / f"{name}.cpp"
    executable = executables / name
    probe.write_text(source, encoding="utf-8")
    command = [
        ctx.compiler,
        *STRICT_FLAGS,
        f"-I{ctx.exercise_dir}",
        str(ctx.exercise_dir / "bank_account.cpp"),
        str(probe),
        "-o",
        str(executable),
    ]
    result = _run(ctx, kernel_id, f"{name}_build", command, ctx.compile_timeout_s)
    return probe, executable, result


def _verify_single_probe(
    ctx: VerifierContext,
    kernel_id: str,
    name: str,
    source: str,
    success_summary: str,
    failure_summary: str,
) -> KernelReceipt:
    assets_ok, asset_fact = _assets_valid(ctx)
    if not assets_ok:
        return _invalid(kernel_id, asset_fact)
    probe, executable, build = _build_probe(ctx, kernel_id, name, source)
    if build.return_code == 127:
        return _invalid(kernel_id, "compiler process is unavailable", [build])
    if build.return_code != 0 or not _valid_artifact(executable, executable=True):
        return _fail(
            kernel_id,
            f"{failure_summary}: probe did not build",
            [build],
            {"failed_stage": "build", "timed_out": build.timed_out},
        )
    run = _run(ctx, kernel_id, f"{name}_run", [str(executable)], ctx.runtime_timeout_s)
    commands = [build, run]
    facts = {
        "runtime_return_code": run.return_code,
        "runtime_timed_out": run.timed_out,
    }
    if run.return_code == 127:
        return _invalid(kernel_id, "probe executable could not be started", commands, facts)
    if run.return_code == 0 and _assets_valid(ctx)[0]:
        return _pass(
            kernel_id,
            success_summary,
            commands,
            facts,
            {
                probe.name: _sha256(probe),
                executable.name: _sha256(executable),
                f"{name}.stdout": _sha256(Path(run.stdout_log)),
                f"{name}.stderr": _sha256(Path(run.stderr_log)),
            },
        )
    return _fail(kernel_id, failure_summary, commands, facts)


def verify_5a_official_tests(ctx: VerifierContext) -> KernelReceipt:
    assets_ok, asset_fact = _assets_valid(ctx)
    if not assets_ok:
        return _invalid("5A", asset_fact)
    try:
        fixed = _fixed_test_facts(ctx)
    except OSError as error:
        return _invalid("5A", f"fixed test assets could not be read: {error}")
    if not all(
        fixed[key]
        for key in ("official_test_hash_matches", "catch_hash_matches", "test_main_hash_matches")
    ):
        return _invalid("5A", "pinned official test infrastructure does not match", facts=fixed)
    executables = ctx.output_dir / "executables"
    executables.mkdir(parents=True, exist_ok=True)
    executable = executables / "bank-account-official-tests"
    command = [
        ctx.compiler,
        *STRICT_FLAGS,
        "-DEXERCISM_RUN_ALL_TESTS",
        f"-I{ctx.exercise_dir}",
        str(ctx.exercise_dir / "bank_account.cpp"),
        str(ctx.exercise_dir / "bank_account_test.cpp"),
        str(ctx.exercise_dir / "test/tests-main.cpp"),
        "-o",
        str(executable),
    ]
    build = _run(ctx, "5A", "official_build", command, ctx.compile_timeout_s)
    if build.return_code == 127:
        return _invalid("5A", "compiler process is unavailable", [build], fixed)
    if build.return_code != 0 or not _valid_artifact(executable, executable=True):
        return _fail("5A", "official test executable did not build", [build], {**fixed, "failed_stage": "build"})
    inventory = _run(ctx, "5A", "official_list_tests", [str(executable), "--list-tests"], ctx.runtime_timeout_s)
    commands = [build, inventory]
    if inventory.return_code == 127:
        return _invalid("5A", "official test executable could not be started", commands, fixed)
    inventory_text = Path(inventory.stdout_log).read_text(encoding="utf-8", errors="replace")
    inventory_error = Path(inventory.stderr_log).read_text(encoding="utf-8", errors="replace")
    counts = [int(value) for value in re.findall(r"(\d+)\s+test cases?", inventory_text + "\n" + inventory_error)]
    selected_tests = counts[-1] if counts else None
    facts = {**fixed, "selected_test_count": selected_tests, "inventory_return_code": inventory.return_code}
    inventory_exit_ok = inventory.return_code in (0, 17)
    facts["inventory_exit_accepted"] = inventory_exit_ok
    if not inventory_exit_ok or selected_tests != 17:
        return _invalid("5A", "official test inventory is not the pinned 17-case suite", commands, facts)
    run = _run(
        ctx,
        "5A",
        "official_run",
        [str(executable), "--reporter", "compact"],
        ctx.official_timeout_s,
    )
    commands.append(run)
    facts["test_return_code"] = run.return_code
    facts["test_timed_out"] = run.timed_out
    if run.return_code == 127:
        return _invalid("5A", "official test executable could not be started", commands, facts)
    if run.return_code == 0 and _assets_valid(ctx)[0]:
        return _pass(
            "5A",
            "all 17 official Bank Account tests passed",
            commands,
            facts,
            {
                executable.name: _sha256(executable),
                "official_inventory.stdout": _sha256(Path(inventory.stdout_log)),
                "official_run.stdout": _sha256(Path(run.stdout_log)),
                "official_run.stderr": _sha256(Path(run.stderr_log)),
            },
        )
    return _fail("5A", "one or more official Bank Account tests failed", commands, facts)


def verify_5b_lifecycle_transitions(ctx: VerifierContext) -> KernelReceipt:
    return _verify_single_probe(
        ctx,
        "5B",
        "lifecycle_transitions",
        LIFECYCLE_PROBE,
        "legal close and reopen transitions reset balance",
        "lifecycle transition or reopen reset failed",
    )


def verify_5c_supported_boundaries(ctx: VerifierContext) -> KernelReceipt:
    return _verify_single_probe(
        ctx,
        "5C",
        "supported_boundaries",
        BOUNDARY_PROBE,
        "zero, one, exact depletion, and safe INT_MAX boundaries passed",
        "one or more supported numeric boundaries failed",
    )


def verify_5d_arithmetic_invariants(ctx: VerifierContext) -> KernelReceipt:
    return _verify_single_probe(
        ctx,
        "5D",
        "arithmetic_invariants",
        ARITHMETIC_PROBE,
        "exact arithmetic and rejected-operation state preservation passed",
        "arithmetic or rejected-operation state preservation failed",
    )


def verify_5e_invalid_operations(ctx: VerifierContext) -> KernelReceipt:
    return _verify_single_probe(
        ctx,
        "5E",
        "invalid_operations",
        INVALID_OPERATIONS_PROBE,
        "unopened, open, and closed invalid operations behaved correctly",
        "an invalid operation used the wrong exception or corrupted state",
    )


def verify_5f_deterministic_repetition(ctx: VerifierContext) -> KernelReceipt:
    assets_ok, asset_fact = _assets_valid(ctx)
    if not assets_ok:
        return _invalid("5F", asset_fact)
    probe, executable, build = _build_probe(ctx, "5F", "deterministic_repetition", DETERMINISM_PROBE)
    if build.return_code == 127:
        return _invalid("5F", "compiler process is unavailable", [build])
    if build.return_code != 0 or not _valid_artifact(executable, executable=True):
        return _fail(
            "5F",
            "deterministic workload did not build",
            [build],
            {"failed_stage": "build", "timed_out": build.timed_out},
        )
    commands = [build]
    outcomes: list[dict[str, Any]] = []
    artifacts = {probe.name: _sha256(probe), executable.name: _sha256(executable)}
    for index in range(ctx.determinism_runs):
        run = _run(
            ctx,
            "5F",
            f"deterministic_run_{index + 1:02d}",
            [str(executable)],
            ctx.runtime_timeout_s,
        )
        commands.append(run)
        stdout_hash = _sha256(Path(run.stdout_log))
        stderr_hash = _sha256(Path(run.stderr_log))
        artifacts[f"run_{index + 1:02d}.stdout"] = stdout_hash
        artifacts[f"run_{index + 1:02d}.stderr"] = stderr_hash
        outcomes.append(
            {
                "run": index + 1,
                "return_code": run.return_code,
                "timed_out": run.timed_out,
                "stdout_sha256": stdout_hash,
                "stderr_sha256": stderr_hash,
            }
        )
    if any(command.return_code == 127 for command in commands[1:]):
        return _invalid("5F", "deterministic executable could not be started", commands, {"outcomes": outcomes})
    signatures = {
        (outcome["return_code"], outcome["stdout_sha256"], outcome["stderr_sha256"])
        for outcome in outcomes
    }
    facts = {"requested_runs": ctx.determinism_runs, "unique_outcomes": len(signatures), "outcomes": outcomes}
    passed = (
        len(outcomes) == ctx.determinism_runs
        and all(outcome["return_code"] == 0 and not outcome["timed_out"] for outcome in outcomes)
        and len(signatures) == 1
        and _assets_valid(ctx)[0]
    )
    if passed:
        return _pass("5F", f"all {ctx.determinism_runs} deterministic repetitions matched", commands, facts, artifacts)
    return _fail("5F", "fixed workload did not repeat with one successful outcome", commands, facts)


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


def verify_policy_5(ctx: VerifierContext) -> dict[str, Any]:
    preflight_ok, preflight_summary, preflight_commands, preflight_facts = _preflight(ctx)
    assets_ok, asset_fact = _assets_valid(ctx)
    if not preflight_ok or not assets_ok:
        reason = preflight_summary if not preflight_ok else asset_fact
        results = [
            _invalid(kernel_id, reason, preflight_commands, preflight_facts)
            for kernel_id in ("5A", "5B", "5C", "5D", "5E", "5F")
        ]
    else:
        results = [
            verify_5a_official_tests(ctx),
            verify_5b_lifecycle_transitions(ctx),
            verify_5c_supported_boundaries(ctx),
            verify_5d_arithmetic_invariants(ctx),
            verify_5e_invalid_operations(ctx),
            verify_5f_deterministic_repetition(ctx),
        ]
    invalid = any(result.kernel is None for result in results)
    kernel_sum = None if invalid else sum(result.kernel for result in results if result.kernel is not None)
    status = "invalid" if invalid else "pass" if kernel_sum == 6 else "fail"
    return {
        "schema_version": 1,
        "policy_id": "bank-account-policy-05-functional-state-boundary-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "kernel_model": {"pass": 1, "fail": -1, "infrastructure": "INVALID"},
        "kernel_sum": kernel_sum,
        "kernel_range": [-6, 6],
        "full_pass_required": 6,
        "passed_kernels": sum(result.kernel == 1 for result in results),
        "failed_kernels": sum(result.kernel == -1 for result in results),
        "source_sha256": ctx.source_sha256,
        "exercise_dir": str(ctx.exercise_dir),
        "preflight": {
            "status": "pass" if preflight_ok and assets_ok else "invalid",
            "summary": preflight_summary if preflight_ok and assets_ok else asset_fact if not assets_ok else preflight_summary,
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
    parser.add_argument("--expected-test-sha256", default=PINNED_TEST_SHA256)
    parser.add_argument("--expected-catch-sha256", default=PINNED_CATCH_SHA256)
    parser.add_argument("--expected-test-main-sha256", default=PINNED_TEST_MAIN_SHA256)
    parser.add_argument("--compile-timeout-s", type=int, default=120)
    parser.add_argument("--runtime-timeout-s", type=int, default=10)
    parser.add_argument("--official-timeout-s", type=int, default=60)
    parser.add_argument("--determinism-runs", type=int, default=10)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    exercise_dir = args.exercise_dir.resolve()
    output_dir = args.output_dir.resolve()
    if not exercise_dir.is_dir():
        raise SystemExit(f"exercise directory does not exist: {exercise_dir}")
    if args.determinism_runs < 2:
        raise SystemExit("determinism-runs must be at least 2")
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
        expected_test_sha256=args.expected_test_sha256,
        expected_catch_sha256=args.expected_catch_sha256,
        expected_test_main_sha256=args.expected_test_main_sha256,
        compile_timeout_s=args.compile_timeout_s,
        runtime_timeout_s=args.runtime_timeout_s,
        official_timeout_s=args.official_timeout_s,
        determinism_runs=args.determinism_runs,
    )
    receipt = verify_policy_5(ctx)
    receipt_path = output_dir / "verification_receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: receipt[key] for key in ("status", "kernel_sum", "passed_kernels", "failed_kernels")}, sort_keys=True))
    print(receipt_path)
    return 0 if receipt["status"] == "pass" else 2 if receipt["status"] == "invalid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
