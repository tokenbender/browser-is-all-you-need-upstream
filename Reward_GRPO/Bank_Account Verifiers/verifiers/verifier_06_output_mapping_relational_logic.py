
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
EXACT_OBSERVABLES_OUTPUT = """unopened_balance=runtime_error
open=ok
balance=0
deposit100=ok
balance=100
deposit50=ok
balance=150
withdraw40=ok
balance=110
withdraw111=runtime_error
balance=110
close=ok
closed_balance=runtime_error
reopen=ok
balance=0
"""
EXACT_OBSERVABLES_PROBE = """#include \"bank_account.h\"
#include <iostream>
#include <stdexcept>
#include <string>

template <typename Operation>
std::string void_result(Operation operation) {
    try {
        operation();
        return \"ok\";
    } catch (const std::runtime_error&) {
        return \"runtime_error\";
    } catch (...) {
        return \"other_exception\";
    }
}

std::string balance_result(Bankaccount::Bankaccount& account) {
    try {
        return std::to_string(account.balance());
    } catch (const std::runtime_error&) {
        return \"runtime_error\";
    } catch (...) {
        return \"other_exception\";
    }
}

int main() {
    Bankaccount::Bankaccount account{};
    std::cout << \"unopened_balance=\" << balance_result(account) << '\\n';
    std::cout << \"open=\" << void_result([&]() { account.open(); }) << '\\n';
    std::cout << \"balance=\" << balance_result(account) << '\\n';
    std::cout << \"deposit100=\" << void_result([&]() { account.deposit(100); }) << '\\n';
    std::cout << \"balance=\" << balance_result(account) << '\\n';
    std::cout << \"deposit50=\" << void_result([&]() { account.deposit(50); }) << '\\n';
    std::cout << \"balance=\" << balance_result(account) << '\\n';
    std::cout << \"withdraw40=\" << void_result([&]() { account.withdraw(40); }) << '\\n';
    std::cout << \"balance=\" << balance_result(account) << '\\n';
    std::cout << \"withdraw111=\" << void_result([&]() { account.withdraw(111); }) << '\\n';
    std::cout << \"balance=\" << balance_result(account) << '\\n';
    std::cout << \"close=\" << void_result([&]() { account.close(); }) << '\\n';
    std::cout << \"closed_balance=\" << balance_result(account) << '\\n';
    std::cout << \"reopen=\" << void_result([&]() { account.open(); }) << '\\n';
    std::cout << \"balance=\" << balance_result(account) << '\\n';
    return 0;
}
"""
ORDER_MAPPING_PROBE = """#include \"bank_account.h\"
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
    try {
        Bankaccount::Bankaccount first{};
        first.open();
        first.deposit(100);
        first.withdraw(37);
        first.deposit(3);
        if (first.balance() != 66) return 1;
        first.close();

        Bankaccount::Bankaccount second{};
        second.open();
        second.deposit(100);
        second.withdraw(100);
        second.deposit(3);
        if (second.balance() != 3) return 2;
        second.close();

        Bankaccount::Bankaccount third{};
        third.open();
        if (!throws_runtime_error([&]() { third.withdraw(37); })) return 3;
        if (third.balance() != 0) return 4;
        third.deposit(100);
        if (third.balance() != 100) return 5;
        third.close();

        Bankaccount::Bankaccount fourth{};
        fourth.open();
        fourth.deposit(19);
        fourth.close();
        fourth.open();
        if (fourth.balance() != 0) return 6;
        fourth.close();
        std::cout << \"order-mapping-ok\\n\";
        return 0;
    } catch (...) {
        return 10;
    }
}
"""
INPUT_PARTITIONS_PROBE = """#include \"bank_account.h\"
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
        if (!throws_runtime_error([&]() { account.deposit(-1); })) return 5;
        if (account.balance() != 0) return 6;
        account.deposit(0);
        if (account.balance() != 0) return 7;
        if (!throws_runtime_error([&]() { account.withdraw(-1); })) return 8;
        if (account.balance() != 0) return 9;
        account.withdraw(0);
        if (account.balance() != 0) return 10;
        account.deposit(5);
        if (!throws_runtime_error([&]() { account.withdraw(6); })) return 11;
        if (account.balance() != 5) return 12;
        account.withdraw(5);
        if (account.balance() != 0) return 13;
        account.close();
    } catch (...) {
        return 14;
    }
    if (!throws_runtime_error([&]() { account.deposit(1); })) return 15;
    if (!throws_runtime_error([&]() { account.withdraw(1); })) return 16;
    if (!throws_runtime_error([&]() { (void)account.balance(); })) return 17;
    if (!throws_runtime_error([&]() { account.close(); })) return 18;
    std::cout << \"input-partitions-ok\\n\";
    return 0;
}
"""
BALANCE_RELATIONS_PROBE = """#include \"bank_account.h\"
#include <array>
#include <iostream>
#include <stdexcept>
#include <utility>

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
    const std::array<int, 4> bases{0, 1, 5, 100};
    const std::array<int, 6> amounts{0, 1, 2, 5, 100, 101};
    int relation_count = 0;
    try {
        for (const int base : bases) {
            for (const int amount : amounts) {
                Bankaccount::Bankaccount account{};
                account.open();
                account.deposit(base);
                if (amount <= base) {
                    account.withdraw(amount);
                    if (account.balance() != base - amount) return 1;
                    account.deposit(amount);
                    if (account.balance() != base) return 2;
                } else {
                    if (!throws_runtime_error([&]() { account.withdraw(amount); })) return 3;
                    if (account.balance() != base) return 4;
                }
                account.close();
                ++relation_count;
            }
        }
        const std::array<std::pair<int, int>, 4> pairs{{{1, 2}, {2, 5}, {7, 9}, {10, 0}}};
        for (const auto& [left, right] : pairs) {
            Bankaccount::Bankaccount first{};
            Bankaccount::Bankaccount second{};
            first.open();
            second.open();
            first.deposit(left);
            first.deposit(right);
            second.deposit(right);
            second.deposit(left);
            if (first.balance() != left + right) return 5;
            if (second.balance() != left + right) return 6;
            if (first.balance() != second.balance()) return 7;
            first.close();
            second.close();
            ++relation_count;
        }
        std::cout << \"balance-relations-ok:\" << relation_count << '\\n';
        return relation_count == 28 ? 0 : 8;
    } catch (...) {
        return 10;
    }
}
"""
WHOLE_STATE_PROBE = """#include \"bank_account.h\"
#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <utility>

enum class ErrorKind { none, runtime, other };

struct CandidateResult {
    ErrorKind error{ErrorKind::none};
    bool has_value{false};
    int value{0};
};

int main() {
    Bankaccount::Bankaccount account{};
    bool model_open = false;
    int model_balance = 0;
    auto candidate_step = [&](int operation, int amount) {
        CandidateResult result{};
        try {
            if (operation == 0) account.open();
            if (operation == 1) account.close();
            if (operation == 2) account.deposit(amount);
            if (operation == 3) account.withdraw(amount);
            if (operation == 4) {
                result.has_value = true;
                result.value = account.balance();
            }
        } catch (const std::runtime_error&) {
            result.error = ErrorKind::runtime;
        } catch (...) {
            result.error = ErrorKind::other;
        }
        return result;
    };
    auto verify_step = [&](int operation, int amount) {
        bool expected_error = false;
        bool expected_value = false;
        int expected_observation = 0;
        if (operation == 0) {
            if (model_open) {
                expected_error = true;
            } else {
                model_open = true;
                model_balance = 0;
            }
        }
        if (operation == 1) {
            if (!model_open) {
                expected_error = true;
            } else {
                model_open = false;
            }
        }
        if (operation == 2) {
            if (!model_open || amount < 0) {
                expected_error = true;
            } else {
                model_balance += amount;
            }
        }
        if (operation == 3) {
            if (!model_open || amount < 0 || amount > model_balance) {
                expected_error = true;
            } else {
                model_balance -= amount;
            }
        }
        if (operation == 4) {
            if (!model_open) {
                expected_error = true;
            } else {
                expected_value = true;
                expected_observation = model_balance;
            }
        }
        const CandidateResult observed = candidate_step(operation, amount);
        if (observed.error == ErrorKind::other) return 1;
        if (expected_error != (observed.error == ErrorKind::runtime)) return 2;
        if (!expected_error && observed.error != ErrorKind::none) return 3;
        if (expected_value && (!observed.has_value || observed.value != expected_observation)) return 4;
        if (model_open) {
            try {
                if (account.balance() != model_balance) return 5;
            } catch (...) {
                return 6;
            }
        }
        return 0;
    };
    const std::array<std::pair<int, int>, 9> prelude{{
        {0, 0}, {2, 23}, {3, 24}, {2, 17}, {3, 7}, {4, 0}, {1, 0}, {0, 0}, {4, 0}
    }};
    int steps = 0;
    for (const auto& [operation, amount] : prelude) {
        if (verify_step(operation, amount) != 0) return 10;
        ++steps;
    }
    std::uint32_t generator = 0x00C0FFEEu;
    for (int index = 0; index < 256; ++index) {
        generator = generator * 1664525u + 1013904223u;
        const int operation = static_cast<int>(generator % 5u);
        generator = generator * 1664525u + 1013904223u;
        const int amount = static_cast<int>((generator >> 8u) % 13u) - 2;
        if (verify_step(operation, amount) != 0) return 11;
        ++steps;
    }
    std::cout << \"state-model-ok:\" << steps << '\\n';
    return steps == 265 ? 0 : 12;
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
    runtime_timeout_s: int


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


def _verify_probe(
    ctx: VerifierContext,
    kernel_id: str,
    name: str,
    source: str,
    expected_stdout: str,
    success_summary: str,
    failure_summary: str,
) -> KernelReceipt:
    assets_ok, asset_fact = _assets_valid(ctx)
    if not assets_ok:
        return _invalid(kernel_id, asset_fact)
    probes = ctx.output_dir / "probes"
    executables = ctx.output_dir / "executables"
    probes.mkdir(parents=True, exist_ok=True)
    executables.mkdir(parents=True, exist_ok=True)
    probe = probes / f"{name}.cpp"
    executable = executables / name
    probe.write_text(source, encoding="utf-8")
    build = _run(
        ctx,
        kernel_id,
        f"{name}_build",
        [
            ctx.compiler,
            *STRICT_FLAGS,
            f"-I{ctx.exercise_dir}",
            str(ctx.exercise_dir / "bank_account.cpp"),
            str(probe),
            "-o",
            str(executable),
        ],
        ctx.compile_timeout_s,
    )
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
    stdout_path = Path(run.stdout_log)
    stderr_path = Path(run.stderr_log)
    actual_stdout = stdout_path.read_text(encoding="utf-8", errors="replace")
    actual_stderr = stderr_path.read_text(encoding="utf-8", errors="replace")
    facts = {
        "runtime_return_code": run.return_code,
        "runtime_timed_out": run.timed_out,
        "expected_stdout_sha256": hashlib.sha256(expected_stdout.encode("utf-8")).hexdigest(),
        "actual_stdout_sha256": _sha256(stdout_path),
        "actual_stderr_sha256": _sha256(stderr_path),
        "stdout_exact": actual_stdout == expected_stdout,
        "stderr_empty": actual_stderr == "",
    }
    if run.return_code == 127:
        return _invalid(kernel_id, "probe executable could not be started", commands, facts)
    passed = (
        run.return_code == 0
        and not run.timed_out
        and actual_stdout == expected_stdout
        and actual_stderr == ""
        and _assets_valid(ctx)[0]
    )
    if passed:
        return _pass(
            kernel_id,
            success_summary,
            commands,
            facts,
            {
                probe.name: _sha256(probe),
                executable.name: _sha256(executable),
                f"{name}.stdout": _sha256(stdout_path),
                f"{name}.stderr": _sha256(stderr_path),
            },
        )
    return _fail(kernel_id, failure_summary, commands, facts)


def verify_6a_exact_observables(ctx: VerifierContext) -> KernelReceipt:
    return _verify_probe(
        ctx,
        "6A",
        "exact_observables",
        EXACT_OBSERVABLES_PROBE,
        EXACT_OBSERVABLES_OUTPUT,
        "golden balances and exception outputs matched byte-for-byte",
        "one or more golden observable results differed",
    )


def verify_6b_order_and_state_mapping(ctx: VerifierContext) -> KernelReceipt:
    return _verify_probe(
        ctx,
        "6B",
        "order_and_state_mapping",
        ORDER_MAPPING_PROBE,
        "order-mapping-ok\n",
        "all ordered operation sequences reached the expected state",
        "an ordered operation sequence mapped to the wrong state",
    )


def verify_6c_input_partitions(ctx: VerifierContext) -> KernelReceipt:
    return _verify_probe(
        ctx,
        "6C",
        "input_partitions",
        INPUT_PARTITIONS_PROBE,
        "input-partitions-ok\n",
        "all state and amount partitions were classified correctly",
        "one or more state or amount partitions were misclassified",
    )


def verify_6d_balance_relations(ctx: VerifierContext) -> KernelReceipt:
    return _verify_probe(
        ctx,
        "6D",
        "balance_relations",
        BALANCE_RELATIONS_PROBE,
        "balance-relations-ok:28\n",
        "all 28 balance relations passed",
        "one or more balance relations failed",
    )


def verify_6f_whole_state_consistency(ctx: VerifierContext) -> KernelReceipt:
    result = _verify_probe(
        ctx,
        "6F",
        "whole_state_consistency",
        WHOLE_STATE_PROBE,
        "state-model-ok:265\n",
        "all 265 state-model steps matched",
        "candidate behavior diverged from the state-machine oracle",
    )
    result.facts["oracle_seed"] = "0x00C0FFEE"
    result.facts["prelude_steps"] = 9
    result.facts["generated_steps"] = 256
    return result


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
        [ctx.compiler, "-dM", "-E", "-x", "c++", "/dev/null"],
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


def verify_policy_6(ctx: VerifierContext) -> dict[str, Any]:
    preflight_ok, preflight_summary, preflight_commands, preflight_facts = _preflight(ctx)
    assets_ok, asset_fact = _assets_valid(ctx)
    if not preflight_ok or not assets_ok:
        reason = preflight_summary if not preflight_ok else asset_fact
        results = [
            _invalid(kernel_id, reason, preflight_commands, preflight_facts)
            for kernel_id in ("6A", "6B", "6C", "6D", "6F")
        ]
    else:
        results = [
            verify_6a_exact_observables(ctx),
            verify_6b_order_and_state_mapping(ctx),
            verify_6c_input_partitions(ctx),
            verify_6d_balance_relations(ctx),
            verify_6f_whole_state_consistency(ctx),
        ]
    invalid = any(result.kernel is None for result in results)
    kernel_sum = None if invalid else sum(result.kernel for result in results if result.kernel is not None)
    status = "invalid" if invalid else "pass" if kernel_sum == 5 else "fail"
    return {
        "schema_version": 1,
        "policy_id": "bank-account-policy-06-output-mapping-relational-logic-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "kernel_model": {"pass": 1, "fail": -1, "infrastructure": "INVALID"},
        "kernel_sum": kernel_sum,
        "kernel_range": [-5, 5],
        "full_pass_required": 5,
        "applicable_kernel_ids": ["6A", "6B", "6C", "6D", "6F"],
        "excluded_conditions": {
            "6E": {
                "status": "not_applicable",
                "reason": "Bank Account has no uniqueness or finite-namespace exhaustion behavior",
                "included_in_kernel_sum": False,
            }
        },
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
    parser.add_argument("--compile-timeout-s", type=int, default=120)
    parser.add_argument("--runtime-timeout-s", type=int, default=15)
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
        runtime_timeout_s=args.runtime_timeout_s,
    )
    receipt = verify_policy_6(ctx)
    receipt_path = output_dir / "verification_receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: receipt[key] for key in ("status", "kernel_sum", "passed_kernels", "failed_kernels")}, sort_keys=True))
    print(receipt_path)
    return 0 if receipt["status"] == "pass" else 2 if receipt["status"] == "invalid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
