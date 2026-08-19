# Policy 1 verifier: build five independent +1/-1 compile and linker kernels.
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
API_PROBE = """#include \"bank_account.h\"
#include <type_traits>

using Account = Bankaccount::Bankaccount;

static_assert(std::is_same_v<decltype(&Account::open), void (Account::*)()>);
static_assert(std::is_same_v<decltype(&Account::deposit), void (Account::*)(int)>);
static_assert(std::is_same_v<decltype(&Account::withdraw), void (Account::*)(int)>);
static_assert(std::is_same_v<decltype(&Account::close), void (Account::*)()>);
static_assert(std::is_same_v<decltype(&Account::balance), int (Account::*)()>);

int main() {
    Account account;
    account.open();
    account.deposit(1);
    account.withdraw(1);
    const int result = account.balance();
    account.close();
    return result;
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
    cmake: str
    expected_gcc: str
    source_sha256: str
    configure_timeout_s: int
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
    cwd: Path | None = None,
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
            cwd=cwd,
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
        cwd=str(cwd or Path.cwd()),
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
    status: str = "fail",
) -> KernelReceipt:
    return KernelReceipt(kernel_id, -1, status, summary, commands, facts, {})


def _invalid(
    kernel_id: str,
    summary: str,
    commands: list[CommandReceipt] | None = None,
    facts: dict[str, Any] | None = None,
) -> KernelReceipt:
    return KernelReceipt(kernel_id, None, "invalid", summary, commands or [], facts or {}, {})


def _assets_valid(ctx: VerifierContext) -> tuple[bool, str]:
    try:
        observed = _source_digest(ctx.exercise_dir)
    except (OSError, ValueError) as error:
        return False, str(error)
    if observed != ctx.source_sha256:
        return False, "task source digest changed after verification started"
    return True, observed


def _compiler_record(build_dir: Path) -> str:
    candidates = list(build_dir.glob("CMakeFiles/*/CMakeCXXCompiler.cmake"))
    if not candidates:
        return ""
    return candidates[0].read_text(encoding="utf-8", errors="replace")


def verify_1a_toolchain(ctx: VerifierContext) -> KernelReceipt:
    commands: list[CommandReceipt] = []
    assets_ok, asset_fact = _assets_valid(ctx)
    if not assets_ok:
        return _invalid("1A", asset_fact)
    version = _run(
        ctx,
        "1A",
        "gcc_version",
        [ctx.compiler, "-dumpfullversion", "-dumpversion"],
        ctx.configure_timeout_s,
    )
    commands.append(version)
    if version.return_code != 0:
        return _invalid("1A", "GNU compiler identity could not be read", commands)
    version_text = Path(version.stdout_log).read_text(encoding="utf-8").strip()
    macros = _run(
        ctx,
        "1A",
        "gcc_macros",
        [ctx.compiler, "-dM", "-E", "-x", "c++", "-"],
        ctx.configure_timeout_s,
        input_text="",
    )
    commands.append(macros)
    if macros.return_code != 0:
        return _invalid("1A", "compiler predefined macros could not be read", commands)
    macro_text = Path(macros.stdout_log).read_text(encoding="utf-8")
    gcc_ok = version_text == ctx.expected_gcc or version_text.startswith(f"{ctx.expected_gcc}.")
    is_gnu = "#define __GNUC__ " in macro_text
    is_clang = "#define __clang__ " in macro_text
    if not gcc_ok or not is_gnu or is_clang:
        return _invalid(
            "1A",
            f"expected GNU GCC {ctx.expected_gcc}, observed {version_text or 'unknown'}",
            commands,
            {"compiler_version": version_text, "is_gnu": is_gnu, "is_clang": is_clang},
        )
    cmake_version = _run(
        ctx,
        "1A",
        "cmake_version",
        [ctx.cmake, "--version"],
        ctx.configure_timeout_s,
    )
    commands.append(cmake_version)
    if cmake_version.return_code != 0:
        return _invalid("1A", "CMake is unavailable", commands)
    build_dir = ctx.output_dir / "build_1a"
    if build_dir.exists():
        return _invalid("1A", f"configuration directory is not fresh: {build_dir}", commands)
    configure = _run(
        ctx,
        "1A",
        "cmake_configure",
        [
            ctx.cmake,
            "-S",
            str(ctx.exercise_dir),
            "-B",
            str(build_dir),
            "-DEXERCISM_RUN_ALL_TESTS=ON",
            f"-DCMAKE_CXX_COMPILER={ctx.compiler}",
            "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
        ],
        ctx.configure_timeout_s,
    )
    commands.append(configure)
    if configure.return_code != 0:
        return _invalid("1A", "fresh CMake configuration failed", commands)
    compile_commands_path = build_dir / "compile_commands.json"
    compiler_record = _compiler_record(build_dir)
    cmake_source = (ctx.exercise_dir / "CMakeLists.txt").read_text(encoding="utf-8")
    try:
        compile_commands = compile_commands_path.read_text(encoding="utf-8")
    except OSError as error:
        return _invalid("1A", f"compile commands were not generated: {error}", commands)
    compiler_id_gnu = 'set(CMAKE_CXX_COMPILER_ID "GNU")' in compiler_record
    cxx17_enabled = "-std=c++17" in compile_commands or "-std=gnu++17" in compile_commands
    all_tests_enabled = "EXERCISM_RUN_ALL_TESTS" in compile_commands
    threads_required = bool(re.search(r"find_package\s*\(\s*Threads\s+REQUIRED\s*\)", cmake_source))
    threads_linked = "Threads::Threads" in cmake_source
    unchanged, final_digest = _assets_valid(ctx)
    facts = {
        "compiler_version": version_text,
        "compiler_id_gnu": compiler_id_gnu,
        "cxx17_enabled": cxx17_enabled,
        "all_tests_enabled": all_tests_enabled,
        "threads_required": threads_required,
        "threads_linked": threads_linked,
        "source_sha256": final_digest,
    }
    if all((compiler_id_gnu, cxx17_enabled, all_tests_enabled, threads_required, threads_linked, unchanged)):
        return _pass("1A", "GNU GCC 13.3, C++17, all-tests, and Threads configured", commands, facts)
    return _invalid("1A", "configured task contract or generated compiler configuration drifted", commands, facts)


def verify_1b_implementation_compile(ctx: VerifierContext) -> KernelReceipt:
    assets_ok, asset_fact = _assets_valid(ctx)
    if not assets_ok:
        return _invalid("1B", asset_fact)
    objects = ctx.output_dir / "objects"
    objects.mkdir(parents=True, exist_ok=True)
    target = objects / "bank_account.o"
    command = [
        ctx.compiler,
        *STRICT_FLAGS,
        f"-I{ctx.exercise_dir}",
        "-c",
        str(ctx.exercise_dir / "bank_account.cpp"),
        "-o",
        str(target),
    ]
    result = _run(ctx, "1B", "implementation_compile", command, ctx.compile_timeout_s)
    if result.return_code == 127:
        return _invalid("1B", "compiler process is unavailable", [result])
    facts = {"translation_unit": "bank_account.cpp", "timed_out": result.timed_out}
    if result.return_code == 0 and _valid_artifact(target) and _assets_valid(ctx)[0]:
        facts["object_bytes"] = target.stat().st_size
        return _pass(
            "1B",
            "bank_account.cpp compiled to a valid object",
            [result],
            facts,
            {"bank_account.o": _sha256(target)},
        )
    return _fail("1B", "bank_account.cpp did not compile cleanly", [result], facts)


def verify_1c_consumers_compile(ctx: VerifierContext) -> KernelReceipt:
    assets_ok, asset_fact = _assets_valid(ctx)
    if not assets_ok:
        return _invalid("1C", asset_fact)
    objects = ctx.output_dir / "objects"
    objects.mkdir(parents=True, exist_ok=True)
    probe_path = ctx.output_dir / "bank_account_api_probe.cpp"
    probe_path.write_text(API_PROBE, encoding="utf-8")
    test_object = objects / "bank_account_test.o"
    probe_object = objects / "bank_account_api_probe.o"
    test_command = [
        ctx.compiler,
        *STRICT_FLAGS,
        "-DEXERCISM_RUN_ALL_TESTS",
        f"-I{ctx.exercise_dir}",
        "-c",
        str(ctx.exercise_dir / "bank_account_test.cpp"),
        "-o",
        str(test_object),
    ]
    probe_command = [
        ctx.compiler,
        *STRICT_FLAGS,
        f"-I{ctx.exercise_dir}",
        "-c",
        str(probe_path),
        "-o",
        str(probe_object),
    ]
    test_result = _run(ctx, "1C", "official_test_compile", test_command, ctx.compile_timeout_s)
    probe_result = _run(ctx, "1C", "api_probe_compile", probe_command, ctx.compile_timeout_s)
    commands = [test_result, probe_result]
    if any(result.return_code == 127 for result in commands):
        return _invalid("1C", "compiler process is unavailable", commands)
    test_ok = test_result.return_code == 0 and _valid_artifact(test_object)
    probe_ok = probe_result.return_code == 0 and _valid_artifact(probe_object)
    facts = {
        "official_test_compiled": test_ok,
        "api_probe_compiled": probe_ok,
        "official_tests_enabled": True,
    }
    if test_ok and probe_ok and _assets_valid(ctx)[0]:
        return _pass(
            "1C",
            "official test and exact API probe compiled",
            commands,
            facts,
            {
                "bank_account_test.o": _sha256(test_object),
                "bank_account_api_probe.o": _sha256(probe_object),
            },
        )
    return _fail("1C", "one or more candidate consumers did not compile", commands, facts)


def verify_1d_link(
    ctx: VerifierContext,
    implementation_result: KernelReceipt,
    consumer_result: KernelReceipt,
) -> KernelReceipt:
    if implementation_result.kernel != 1 or consumer_result.kernel != 1:
        return _fail(
            "1D",
            "linking blocked because required candidate objects were not produced",
            [],
            {"blocked_by": [result.kernel_id for result in (implementation_result, consumer_result) if result.kernel != 1]},
            status="blocked",
        )
    assets_ok, asset_fact = _assets_valid(ctx)
    if not assets_ok:
        return _invalid("1D", asset_fact)
    objects = ctx.output_dir / "objects"
    catch_object = objects / "catch_main.o"
    catch_command = [
        ctx.compiler,
        *STRICT_FLAGS,
        f"-I{ctx.exercise_dir / 'test'}",
        "-c",
        str(ctx.exercise_dir / "test/tests-main.cpp"),
        "-o",
        str(catch_object),
    ]
    catch_result = _run(ctx, "1D", "catch_main_compile", catch_command, ctx.compile_timeout_s)
    if catch_result.return_code == 127:
        return _invalid("1D", "compiler process is unavailable", [catch_result])
    if catch_result.return_code != 0 or not _valid_artifact(catch_object):
        return _invalid("1D", "fixed Catch entry point did not compile", [catch_result])
    executable = ctx.output_dir / "bank-account-tests"
    link_command = [
        ctx.compiler,
        str(objects / "bank_account.o"),
        str(objects / "bank_account_test.o"),
        str(catch_object),
        "-pthread",
        "-o",
        str(executable),
    ]
    link_result = _run(ctx, "1D", "official_executable_link", link_command, ctx.link_timeout_s)
    commands = [catch_result, link_result]
    facts = {
        "thread_link_flag": "-pthread" in link_command,
        "timed_out": link_result.timed_out,
    }
    if link_result.return_code == 0 and _valid_artifact(executable, executable=True) and _assets_valid(ctx)[0]:
        facts["executable_bytes"] = executable.stat().st_size
        return _pass(
            "1D",
            "official Bank Account test executable linked",
            commands,
            facts,
            {"bank-account-tests": _sha256(executable)},
        )
    return _fail("1D", "official Bank Account test executable did not link", commands, facts)


def _find_built_executable(build_dir: Path, name: str) -> Path | None:
    direct = build_dir / name
    if _valid_artifact(direct, executable=True):
        return direct
    matches = [path for path in build_dir.rglob(name) if _valid_artifact(path, executable=True)]
    return matches[0] if len(matches) == 1 else None


def verify_1e_clean_build(ctx: VerifierContext) -> KernelReceipt:
    commands: list[CommandReceipt] = []
    assets_ok, asset_fact = _assets_valid(ctx)
    if not assets_ok:
        return _invalid("1E", asset_fact)
    cmake_version = _run(
        ctx,
        "1E",
        "cmake_version",
        [ctx.cmake, "--version"],
        ctx.configure_timeout_s,
    )
    commands.append(cmake_version)
    if cmake_version.return_code != 0:
        return _invalid("1E", "CMake is unavailable", commands)
    build_dir = ctx.output_dir / "build_1e"
    if build_dir.exists():
        return _invalid("1E", f"clean-build directory is not fresh: {build_dir}", commands)
    configure = _run(
        ctx,
        "1E",
        "fresh_configure",
        [
            ctx.cmake,
            "-S",
            str(ctx.exercise_dir),
            "-B",
            str(build_dir),
            "-DEXERCISM_RUN_ALL_TESTS=ON",
            f"-DCMAKE_CXX_COMPILER={ctx.compiler}",
        ],
        ctx.configure_timeout_s,
    )
    commands.append(configure)
    if configure.return_code != 0:
        return _invalid("1E", "fresh CMake configuration failed", commands)
    target_name = ctx.exercise_dir.name
    build = _run(
        ctx,
        "1E",
        "clean_executable_build",
        [
            ctx.cmake,
            "--build",
            str(build_dir),
            "--target",
            target_name,
            "--clean-first",
            "--parallel",
            "2",
            "--verbose",
        ],
        ctx.compile_timeout_s,
    )
    commands.append(build)
    executable = _find_built_executable(build_dir, target_name)
    facts = {
        "build_directory_was_fresh": True,
        "target": target_name,
        "timed_out": build.timed_out,
    }
    if build.return_code == 0 and executable is not None and _assets_valid(ctx)[0]:
        facts["executable_bytes"] = executable.stat().st_size
        return _pass(
            "1E",
            "independent clean executable build succeeded",
            commands,
            facts,
            {str(executable.relative_to(ctx.output_dir)): _sha256(executable)},
        )
    return _fail("1E", "independent clean executable build failed", commands, facts)


def verify_category_1(ctx: VerifierContext) -> dict[str, Any]:
    result_1a = verify_1a_toolchain(ctx)
    result_1b = verify_1b_implementation_compile(ctx)
    result_1c = verify_1c_consumers_compile(ctx)
    result_1d = verify_1d_link(ctx, result_1b, result_1c)
    result_1e = verify_1e_clean_build(ctx)
    results = [result_1a, result_1b, result_1c, result_1d, result_1e]
    invalid = any(result.kernel is None for result in results)
    kernel_sum = None if invalid else sum(result.kernel for result in results if result.kernel is not None)
    passed = sum(result.kernel == 1 for result in results)
    failed = sum(result.kernel == -1 for result in results)
    status = "invalid" if invalid else "pass" if kernel_sum == 5 else "fail"
    return {
        "schema_version": 1,
        "policy_id": "bank-account-policy-01-compile-api-linker-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "kernel_model": {"pass": 1, "fail": -1, "infrastructure": "INVALID"},
        "kernel_sum": kernel_sum,
        "kernel_range": [-5, 5],
        "full_pass_required": 5,
        "passed_kernels": passed,
        "failed_kernels": failed,
        "source_sha256": ctx.source_sha256,
        "exercise_dir": str(ctx.exercise_dir),
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
    parser.add_argument("--cmake", default="cmake")
    parser.add_argument("--expected-gcc", default="13.3")
    parser.add_argument("--expected-source-sha256")
    parser.add_argument("--configure-timeout-s", type=int, default=30)
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
    compiler = shutil.which(args.compiler) or args.compiler
    cmake = shutil.which(args.cmake) or args.cmake
    ctx = VerifierContext(
        exercise_dir=exercise_dir,
        output_dir=output_dir,
        compiler=compiler,
        cmake=cmake,
        expected_gcc=args.expected_gcc,
        source_sha256=source_sha256,
        configure_timeout_s=args.configure_timeout_s,
        compile_timeout_s=args.compile_timeout_s,
        link_timeout_s=args.link_timeout_s,
    )
    receipt = verify_category_1(ctx)
    receipt_path = output_dir / "verification_receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: receipt[key] for key in ("status", "kernel_sum", "passed_kernels", "failed_kernels")}, sort_keys=True))
    print(receipt_path)
    return 0 if receipt["status"] == "pass" else 2 if receipt["status"] == "invalid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
