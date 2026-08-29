
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
COMPILE_FLAGS = (
    "-std=c++17",
    "-Wall",
    "-Wextra",
    "-Wpedantic",
    "-Werror",
    "-pthread",
    "-fno-diagnostics-color",
)
HEADER_PROBE = """#include \"bank_account.h\"

int main() {
    return 0;
}
"""
PUBLIC_NAMES_PROBE = """#include \"bank_account.h\"

int main() {
    Bankaccount::Bankaccount account{};
    account.open();
    account.deposit(1);
    account.withdraw(1);
    (void)account.balance();
    account.close();
    return 0;
}
"""
SIGNATURE_PROBE = """#include \"bank_account.h\"

using Account = Bankaccount::Bankaccount;
using NoArgumentVoid = void (Account::*)();
using AmountVoid = void (Account::*)(int);
using NoArgumentInt = int (Account::*)();

constexpr NoArgumentVoid open_method = static_cast<NoArgumentVoid>(&Account::open);
constexpr AmountVoid deposit_method = static_cast<AmountVoid>(&Account::deposit);
constexpr AmountVoid withdraw_method = static_cast<AmountVoid>(&Account::withdraw);
constexpr NoArgumentVoid close_method = static_cast<NoArgumentVoid>(&Account::close);
constexpr NoArgumentInt balance_method = static_cast<NoArgumentInt>(&Account::balance);

int main() {
    (void)open_method;
    (void)deposit_method;
    (void)withdraw_method;
    (void)close_method;
    (void)balance_method;
    return 0;
}
"""
QUALIFIER_PROBE = """#include \"bank_account.h\"
#include <type_traits>
#include <utility>

using Account = Bankaccount::Bankaccount;

static_assert(std::is_default_constructible_v<Account>);
static_assert(std::is_invocable_r_v<void, decltype(&Account::open), Account&>);
static_assert(std::is_invocable_r_v<void, decltype(&Account::deposit), Account&, int>);
static_assert(std::is_invocable_r_v<void, decltype(&Account::withdraw), Account&, int>);
static_assert(std::is_invocable_r_v<void, decltype(&Account::close), Account&>);
static_assert(std::is_invocable_r_v<int, decltype(&Account::balance), Account&>);
static_assert(!std::is_invocable_v<decltype(&Account::open), const Account&>);
static_assert(!std::is_invocable_v<decltype(&Account::deposit), const Account&, int>);
static_assert(!std::is_invocable_v<decltype(&Account::withdraw), const Account&, int>);
static_assert(!std::is_invocable_v<decltype(&Account::close), const Account&>);
static_assert(!std::is_invocable_v<decltype(&Account::balance), const Account&>);
static_assert(!noexcept(std::declval<Account&>().open()));
static_assert(!noexcept(std::declval<Account&>().deposit(1)));
static_assert(!noexcept(std::declval<Account&>().withdraw(1)));
static_assert(!noexcept(std::declval<Account&>().close()));
static_assert(!noexcept(std::declval<Account&>().balance()));

int main() {
    return 0;
}
"""
RUNTIME_PROBE = """#include \"bank_account.h\"

int main() {
    Bankaccount::Bankaccount account{};
    account.open();
    account.deposit(1);
    account.withdraw(1);
    (void)account.balance();
    account.close();
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


def _safe_label(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def _valid_artifact(path: Path, executable: bool = False) -> bool:
    if not path.is_file() or path.is_symlink() or path.stat().st_size <= 0:
        return False
    return not executable or os.access(path, os.X_OK)


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


def _compile_probe(
    ctx: VerifierContext,
    kernel_id: str,
    name: str,
    source: str,
) -> KernelReceipt:
    assets_ok, asset_fact = _assets_valid(ctx)
    if not assets_ok:
        return _invalid(kernel_id, asset_fact)
    probe_dir = ctx.output_dir / "probes"
    probe_dir.mkdir(parents=True, exist_ok=True)
    probe = probe_dir / f"{name}.cpp"
    probe.write_text(source, encoding="utf-8")
    command = [
        ctx.compiler,
        *COMPILE_FLAGS,
        f"-I{ctx.exercise_dir}",
        "-fsyntax-only",
        str(probe),
    ]
    result = _run(ctx, kernel_id, name, command, ctx.compile_timeout_s)
    facts = {"probe": name, "timed_out": result.timed_out}
    if result.return_code == 127:
        return _invalid(kernel_id, "compiler process is unavailable", [result], facts)
    if result.return_code == 0 and _assets_valid(ctx)[0]:
        return _pass(
            kernel_id,
            f"{name} compiled",
            [result],
            facts,
            {probe.name: _sha256(probe)},
        )
    return _fail(kernel_id, f"{name} did not compile", [result], facts)


def verify_3a_header_self_contained(ctx: VerifierContext) -> KernelReceipt:
    return _compile_probe(ctx, "3A", "header_self_contained", HEADER_PROBE)


def verify_3b_public_names(ctx: VerifierContext) -> KernelReceipt:
    return _compile_probe(ctx, "3B", "public_names", PUBLIC_NAMES_PROBE)


def verify_3c_exact_signatures(ctx: VerifierContext) -> KernelReceipt:
    return _compile_probe(ctx, "3C", "exact_signatures", SIGNATURE_PROBE)


def verify_3d_qualifiers_visibility_exceptions(ctx: VerifierContext) -> KernelReceipt:
    return _compile_probe(ctx, "3D", "qualifiers_visibility_exceptions", QUALIFIER_PROBE)


def verify_3e_api_probe_runtime(ctx: VerifierContext) -> KernelReceipt:
    assets_ok, asset_fact = _assets_valid(ctx)
    if not assets_ok:
        return _invalid("3E", asset_fact)
    probe_dir = ctx.output_dir / "probes"
    probe_dir.mkdir(parents=True, exist_ok=True)
    probe = probe_dir / "api_runtime.cpp"
    probe.write_text(RUNTIME_PROBE, encoding="utf-8")
    executable = ctx.output_dir / "bank-account-api-smoke"
    build_command = [
        ctx.compiler,
        "-std=c++17",
        "-pthread",
        "-fno-diagnostics-color",
        f"-I{ctx.exercise_dir}",
        str(ctx.exercise_dir / "bank_account.cpp"),
        str(probe),
        "-o",
        str(executable),
    ]
    build = _run(ctx, "3E", "api_runtime_build", build_command, ctx.compile_timeout_s)
    if build.return_code == 127:
        return _invalid("3E", "compiler process is unavailable", [build])
    if build.return_code != 0 or not _valid_artifact(executable, executable=True):
        return _fail(
            "3E",
            "API smoke executable did not compile or link",
            [build],
            {"failed_stage": "build", "timed_out": build.timed_out},
        )
    run = _run(ctx, "3E", "api_runtime_execute", [str(executable)], ctx.runtime_timeout_s)
    commands = [build, run]
    facts = {
        "build_return_code": build.return_code,
        "runtime_return_code": run.return_code,
        "runtime_timed_out": run.timed_out,
    }
    if run.return_code == 127:
        return _invalid("3E", "linked executable could not be started", commands, facts)
    if run.return_code == 0 and _assets_valid(ctx)[0]:
        return _pass(
            "3E",
            "linked API smoke sequence completed",
            commands,
            facts,
            {probe.name: _sha256(probe), executable.name: _sha256(executable)},
        )
    return _fail("3E", "linked API smoke sequence failed", commands, facts)


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


def verify_policy_3(ctx: VerifierContext) -> dict[str, Any]:
    preflight_ok, preflight_summary, preflight_commands, preflight_facts = _preflight(ctx)
    assets_ok, asset_fact = _assets_valid(ctx)
    if not preflight_ok or not assets_ok:
        reason = preflight_summary if not preflight_ok else asset_fact
        results = [
            _invalid(kernel_id, reason, preflight_commands, preflight_facts)
            for kernel_id in ("3A", "3B", "3C", "3D", "3E")
        ]
    else:
        results = [
            verify_3a_header_self_contained(ctx),
            verify_3b_public_names(ctx),
            verify_3c_exact_signatures(ctx),
            verify_3d_qualifiers_visibility_exceptions(ctx),
            verify_3e_api_probe_runtime(ctx),
        ]
    invalid = any(result.kernel is None for result in results)
    kernel_sum = None if invalid else sum(result.kernel for result in results if result.kernel is not None)
    status = "invalid" if invalid else "pass" if kernel_sum == 5 else "fail"
    return {
        "schema_version": 1,
        "policy_id": "bank-account-policy-03-public-api-contract-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "kernel_model": {"pass": 1, "fail": -1, "infrastructure": "INVALID"},
        "kernel_sum": kernel_sum,
        "kernel_range": [-5, 5],
        "full_pass_required": 5,
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
    parser.add_argument("--runtime-timeout-s", type=int, default=10)
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
    receipt = verify_policy_3(ctx)
    receipt_path = output_dir / "verification_receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: receipt[key] for key in ("status", "kernel_sum", "passed_kernels", "failed_kernels")}, sort_keys=True))
    print(receipt_path)
    return 0 if receipt["status"] == "pass" else 2 if receipt["status"] == "invalid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
