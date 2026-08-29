
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
PINNED_TEST_SHA256 = "3696b9383f62ab639ad0a26610410fb662b6b927f2fe1dee956b849ff8dcf5c8"
PINNED_CATCH_SHA256 = "681e7505a50887c9085539e5135794fc8f66d8e5de28eadf13a30978627b0f47"
PINNED_TEST_MAIN_SHA256 = "5847fda35c1320d94f8d088aaf34229d689f66f1da235f885cbb28c8f17e4260"
DEFAULT_CONTAINER_IMAGE = "silkeh/clang@sha256:9388794775d1393c16b6897b4775b6d3e29459319de0bfafec59a20262e1fa68"
DEFAULT_CONTAINER_ID = "sha256:9388794775d1393c16b6897b4775b6d3e29459319de0bfafec59a20262e1fa68"
STRICT_FLAGS = (
    "-std=c++17",
    "-Wall",
    "-Wextra",
    "-Wpedantic",
    "-Werror",
    "-pthread",
    "-fno-color-diagnostics",
)
PREFLIGHT_SOURCE = """#include <thread>

int main() {
    int value = 0;
    std::thread worker([&]() { value = 1; });
    worker.join();
    return value == 1 ? 0 : 1;
}
"""
API_PROBE = """#include "bank_account.h"
#include <type_traits>

using Account = Bankaccount::Bankaccount;
static_assert(std::is_same_v<decltype(&Account::open), void (Account::*)()>);
static_assert(std::is_same_v<decltype(&Account::deposit), void (Account::*)(int)>);
static_assert(std::is_same_v<decltype(&Account::withdraw), void (Account::*)(int)>);
static_assert(std::is_same_v<decltype(&Account::close), void (Account::*)()>);
static_assert(std::is_same_v<decltype(&Account::balance), int (Account::*)()>);

int main() {
    Account account{};
    account.open();
    account.deposit(1);
    account.withdraw(1);
    const int observed = account.balance();
    account.close();
    return observed;
}
"""


@dataclass(frozen=True)
class CommandReceipt:
    label: str
    command: list[str]
    cwd: str
    environment: dict[str, str]
    return_code: int
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
    docker: str
    expected_clang: str
    container_image: str
    expected_container_id: str
    source_sha256: str
    compile_timeout_s: int
    runtime_timeout_s: int
    container_timeout_s: int


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
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"required regular task asset is missing: {relative}")
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
    cwd: Path | None = None,
    input_text: str | None = None,
    environment: dict[str, str] | None = None,
) -> CommandReceipt:
    log_dir = ctx.output_dir / "logs" / group
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / f"{label}.stdout.log"
    stderr_path = log_dir / f"{label}.stderr.log"
    started = time.monotonic()
    timed_out = False
    recorded_environment = environment or {}
    try:
        completed = subprocess.run(
            command,
            cwd=cwd or ctx.output_dir,
            input=input_text,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env={**os.environ, "LC_ALL": "C", "LANG": "C", **recorded_environment},
        )
        return_code = completed.returncode
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
    except subprocess.TimeoutExpired as error:
        timed_out = True
        return_code = 124
        stdout = error.stdout.decode(errors="replace") if isinstance(error.stdout, bytes) else error.stdout or ""
        stderr = error.stderr.decode(errors="replace") if isinstance(error.stderr, bytes) else error.stderr or ""
        stderr = f"{stderr}\ncommand timed out after {timeout_s} seconds\n"
    except OSError as error:
        return_code = 127
        stdout = ""
        stderr = f"{type(error).__name__}: {error}\n"
    duration = time.monotonic() - started
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    return CommandReceipt(
        label=label,
        command=command,
        cwd=str(cwd or ctx.output_dir),
        environment=recorded_environment,
        return_code=return_code,
        timed_out=timed_out,
        duration_seconds=round(duration, 6),
        stdout_log=str(stdout_path),
        stderr_log=str(stderr_path),
    )


def _combined(command: CommandReceipt) -> str:
    return (
        Path(command.stdout_log).read_text(encoding="utf-8", errors="replace")
        + Path(command.stderr_log).read_text(encoding="utf-8", errors="replace")
    )


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


def _asset_facts(ctx: VerifierContext) -> tuple[bool, str, dict[str, Any]]:
    try:
        observed_source = _source_digest(ctx.exercise_dir)
    except (OSError, ValueError) as error:
        return False, str(error), {}
    hashes = {
        "source_sha256": observed_source,
        "official_test_sha256": _sha256(ctx.exercise_dir / "bank_account_test.cpp"),
        "catch_sha256": _sha256(ctx.exercise_dir / "test/catch.hpp"),
        "test_main_sha256": _sha256(ctx.exercise_dir / "test/tests-main.cpp"),
    }
    expected = {
        "official_test_sha256": PINNED_TEST_SHA256,
        "catch_sha256": PINNED_CATCH_SHA256,
        "test_main_sha256": PINNED_TEST_MAIN_SHA256,
    }
    valid = observed_source == ctx.source_sha256 and all(hashes[key] == value for key, value in expected.items())
    summary = "source and pinned official test assets matched" if valid else "source changed or official test asset hash mismatched"
    return valid, summary, hashes


def _test_count(output: str) -> int | None:
    patterns = (
        r"All tests passed \([^\n]*? in (\d+) test cases?\)",
        r"Passed all (\d+) test cases?",
        r"test cases:\s*(\d+)\s*\|\s*(\d+) passed",
    )
    for pattern in patterns:
        match = re.search(pattern, output, flags=re.IGNORECASE)
        if match:
            values = [int(value) for value in match.groups() if value is not None]
            if len(values) == 1 or all(value == values[0] for value in values):
                return values[0]
    return None


def _host_preflight(ctx: VerifierContext) -> tuple[bool, str, list[CommandReceipt], dict[str, Any]]:
    commands: list[CommandReceipt] = []
    assets_ok, assets_summary, facts = _asset_facts(ctx)
    if not assets_ok:
        return False, assets_summary, commands, facts
    version = _run(ctx, "preflight", "clang_version", [ctx.compiler, "--version"], 15)
    macros = _run(
        ctx,
        "preflight",
        "clang_macros",
        [ctx.compiler, "-dM", "-E", "-x", "c++", "-"],
        15,
        input_text="",
    )
    commands.extend((version, macros))
    version_text = Path(version.stdout_log).read_text(encoding="utf-8", errors="replace")
    macro_text = Path(macros.stdout_log).read_text(encoding="utf-8", errors="replace")
    version_ok = version.return_code == 0 and f"clang version {ctx.expected_clang}" in version_text
    identity_ok = macros.return_code == 0 and "#define __clang__ 1" in macro_text
    facts.update(
        {
            "expected_clang": ctx.expected_clang,
            "clang_version_output": version_text.strip(),
            "clang_identity_macro": identity_ok,
        }
    )
    if not version_ok or not identity_ok:
        return False, "expected host Clang toolchain was not available", commands, facts
    preflight_dir = ctx.output_dir / "preflight"
    preflight_dir.mkdir(parents=True, exist_ok=True)
    source = preflight_dir / "pthread_probe.cpp"
    executable = preflight_dir / "pthread_probe"
    source.write_text(PREFLIGHT_SOURCE, encoding="utf-8")
    compile_receipt = _run(
        ctx,
        "preflight",
        "compile_pthread_probe",
        [ctx.compiler, *STRICT_FLAGS, str(source), "-o", str(executable)],
        ctx.compile_timeout_s,
    )
    commands.append(compile_receipt)
    if compile_receipt.return_code != 0 or compile_receipt.timed_out or not _valid_artifact(executable, True):
        return False, "host Clang pthread compile preflight failed", commands, facts
    run_receipt = _run(ctx, "preflight", "run_pthread_probe", [str(executable)], ctx.runtime_timeout_s)
    commands.append(run_receipt)
    if run_receipt.return_code != 0 or run_receipt.timed_out:
        return False, "host Clang pthread runtime preflight failed", commands, facts
    facts["pthread_preflight"] = "pass"
    return True, "host Clang and pthread preflight passed", commands, facts


def verify_10a_clang_warning_clean_compile(ctx: VerifierContext) -> KernelReceipt:
    assets_ok, summary, facts = _asset_facts(ctx)
    if not assets_ok:
        return _invalid("10A", summary, facts=facts)
    build_dir = ctx.output_dir / "builds" / "10a_objects"
    probe_dir = ctx.output_dir / "probes"
    build_dir.mkdir(parents=True, exist_ok=True)
    probe_dir.mkdir(parents=True, exist_ok=True)
    api_probe = probe_dir / "bank_account_api_probe.cpp"
    api_probe.write_text(API_PROBE, encoding="utf-8")
    specifications = (
        ("implementation", ctx.exercise_dir / "bank_account.cpp", build_dir / "bank_account.o", ()),
        ("official_test", ctx.exercise_dir / "bank_account_test.cpp", build_dir / "bank_account_test.o", ("-DEXERCISM_RUN_ALL_TESTS",)),
        ("catch_main", ctx.exercise_dir / "test/tests-main.cpp", build_dir / "catch_main.o", ()),
        ("api_probe", api_probe, build_dir / "api_probe.o", ()),
    )
    commands: list[CommandReceipt] = []
    artifacts: dict[str, str] = {"api_probe.cpp": _sha256(api_probe)}
    failed_units: list[str] = []
    for name, source, output, definitions in specifications:
        command = [
            ctx.compiler,
            *STRICT_FLAGS,
            *definitions,
            f"-I{ctx.exercise_dir}",
            "-c",
            str(source),
            "-o",
            str(output),
        ]
        receipt = _run(ctx, "10a", f"compile_{name}", command, ctx.compile_timeout_s)
        commands.append(receipt)
        if receipt.return_code != 0 or receipt.timed_out or not _valid_artifact(output):
            failed_units.append(name)
        else:
            artifacts[output.name] = _sha256(output)
    facts.update(
        {
            "compiled_units": [name for name, _, _, _ in specifications],
            "failed_units": failed_units,
            "strict_flags": list(STRICT_FLAGS),
            "source_digest_unchanged": _source_digest(ctx.exercise_dir) == ctx.source_sha256,
        }
    )
    if not failed_units and facts["source_digest_unchanged"]:
        return _pass("10A", "all four Clang translation units compiled warning-clean", commands, facts, artifacts)
    return _fail("10A", "one or more Clang translation units failed the warning-clean build", commands, facts)


def verify_10b_clang_link_and_tests(ctx: VerifierContext) -> KernelReceipt:
    assets_ok, summary, facts = _asset_facts(ctx)
    if not assets_ok:
        return _invalid("10B", summary, facts=facts)
    build_dir = ctx.output_dir / "builds" / "10b_full_suite"
    build_dir.mkdir(parents=True, exist_ok=True)
    executable = build_dir / "bank-account-clang-tests"
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
    compile_receipt = _run(ctx, "10b", "compile_and_link", command, ctx.compile_timeout_s)
    commands = [compile_receipt]
    facts.update(
        {
            "compile_return_code": compile_receipt.return_code,
            "compile_timed_out": compile_receipt.timed_out,
            "expected_test_count": 17,
        }
    )
    if compile_receipt.return_code != 0 or compile_receipt.timed_out or not _valid_artifact(executable, True):
        return _fail("10B", "Clang could not build and link the official executable", commands, facts)
    run_receipt = _run(ctx, "10b", "run_official_tests", [str(executable)], ctx.runtime_timeout_s)
    commands.append(run_receipt)
    output = _combined(run_receipt)
    observed_test_count = _test_count(output)
    facts.update(
        {
            "run_return_code": run_receipt.return_code,
            "run_timed_out": run_receipt.timed_out,
            "observed_test_count": observed_test_count,
            "source_digest_unchanged": _source_digest(ctx.exercise_dir) == ctx.source_sha256,
        }
    )
    passed = (
        run_receipt.return_code == 0
        and not run_receipt.timed_out
        and observed_test_count == 17
        and facts["source_digest_unchanged"]
    )
    if passed:
        return _pass(
            "10B",
            "the Clang executable linked and all 17 official tests passed",
            commands,
            facts,
            {
                executable.name: _sha256(executable),
                "official_test": PINNED_TEST_SHA256,
                "test_stdout": _sha256(Path(run_receipt.stdout_log)),
                "test_stderr": _sha256(Path(run_receipt.stderr_log)),
            },
        )
    return _fail("10B", "the Clang executable failed or did not report all 17 passing tests", commands, facts)


def _container_preflight(ctx: VerifierContext) -> tuple[bool, str, list[CommandReceipt], dict[str, Any]]:
    commands: list[CommandReceipt] = []
    version = _run(ctx, "10c_preflight", "docker_version", [ctx.docker, "version", "--format", "{{.Server.Version}}"], 30)
    inspect = _run(ctx, "10c_preflight", "image_identity", [ctx.docker, "image", "inspect", ctx.container_image, "--format", "{{.Id}}"], 30)
    commands.extend((version, inspect))
    observed_id = Path(inspect.stdout_log).read_text(encoding="utf-8", errors="replace").strip()
    facts = {
        "container_image": ctx.container_image,
        "expected_container_id": ctx.expected_container_id,
        "observed_container_id": observed_id,
    }
    if version.return_code != 0 or inspect.return_code != 0 or observed_id != ctx.expected_container_id:
        return False, "Docker or the pinned Clang image is unavailable", commands, facts
    runtime = _run(
        ctx,
        "10c_preflight",
        "container_toolchain",
        [
            ctx.docker,
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            ctx.container_image,
            "sh",
            "-lc",
            "clang++ --version && cmake --version",
        ],
        60,
    )
    commands.append(runtime)
    runtime_output = _combined(runtime)
    facts["container_toolchain_output"] = runtime_output.strip()
    valid = runtime.return_code == 0 and "clang version 18.1.8" in runtime_output and "cmake version 3.25.1" in runtime_output
    if not valid:
        return False, "pinned container Clang/CMake preflight failed", commands, facts
    return True, "pinned Clang container preflight passed", commands, facts


def verify_10c_clean_reproduction(ctx: VerifierContext) -> KernelReceipt:
    assets_ok, summary, facts = _asset_facts(ctx)
    if not assets_ok:
        return _invalid("10C", summary, facts=facts)
    preflight_ok, preflight_summary, preflight_commands, preflight_facts = _container_preflight(ctx)
    facts.update(preflight_facts)
    if not preflight_ok:
        return _invalid("10C", preflight_summary, preflight_commands, facts)
    reproduction_dir = ctx.output_dir / "container_reproduction"
    reproduction_dir.mkdir(parents=True, exist_ok=False)
    build_script = (
        "clang++ --version && cmake --version && "
        "cmake -S /workspace/bank-account -B /out/build "
        "-DEXERCISM_RUN_ALL_TESTS=ON -DCMAKE_CXX_COMPILER=/usr/bin/clang++ && "
        "cmake --build /out/build --target bank-account --clean-first --parallel 2 --verbose && "
        "/out/build/bank-account"
    )
    command = [
        ctx.docker,
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,size=256m",
        "--volume",
        f"{ctx.exercise_dir}:/workspace/bank-account:ro",
        "--volume",
        f"{reproduction_dir}:/out:rw",
        "--workdir",
        "/out",
        ctx.container_image,
        "sh",
        "-lc",
        build_script,
    ]
    run_receipt = _run(ctx, "10c", "clean_container_build_and_test", command, ctx.container_timeout_s)
    commands = preflight_commands + [run_receipt]
    output = _combined(run_receipt)
    observed_test_count = _test_count(output)
    executable = reproduction_dir / "build" / "bank-account"
    facts.update(
        {
            "clean_output_directory": str(reproduction_dir),
            "run_return_code": run_receipt.return_code,
            "run_timed_out": run_receipt.timed_out,
            "expected_test_count": 17,
            "observed_test_count": observed_test_count,
            "source_mount": "read-only",
            "container_user": f"{os.getuid()}:{os.getgid()}",
            "network": "none",
            "source_digest_unchanged": _source_digest(ctx.exercise_dir) == ctx.source_sha256,
        }
    )
    passed = (
        run_receipt.return_code == 0
        and not run_receipt.timed_out
        and observed_test_count == 17
        and _valid_artifact(executable, True)
        and facts["source_digest_unchanged"]
    )
    if passed:
        return _pass(
            "10C",
            "the immutable clean Clang environment rebuilt and passed all 17 tests",
            commands,
            facts,
            {
                executable.name: _sha256(executable),
                "official_test": PINNED_TEST_SHA256,
                "container_run_stdout": _sha256(Path(run_receipt.stdout_log)),
                "container_run_stderr": _sha256(Path(run_receipt.stderr_log)),
            },
        )
    return _fail("10C", "the clean Clang container could not reproduce a complete passing build", commands, facts)


def verify_policy_10(ctx: VerifierContext) -> dict[str, Any]:
    preflight_ok, preflight_summary, preflight_commands, preflight_facts = _host_preflight(ctx)
    if preflight_ok:
        results = [
            verify_10a_clang_warning_clean_compile(ctx),
            verify_10b_clang_link_and_tests(ctx),
            verify_10c_clean_reproduction(ctx),
        ]
    else:
        results = [
            _invalid(kernel_id, preflight_summary, preflight_commands, preflight_facts)
            for kernel_id in ("10A", "10B", "10C")
        ]
    invalid = any(result.kernel is None for result in results)
    kernel_sum = None if invalid else sum(result.kernel for result in results if result.kernel is not None)
    status = "invalid" if invalid else "pass" if kernel_sum == 3 else "fail"
    return {
        "schema_version": 1,
        "policy_id": "bank-account-policy-10-cross-compiler-toolchain-portability-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "kernel_model": {"pass": 1, "fail": -1, "infrastructure": "INVALID"},
        "kernel_sum": kernel_sum,
        "kernel_range": [-3, 3],
        "full_pass_required": 3,
        "applicable_kernel_ids": ["10A", "10B", "10C"],
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
    parser.add_argument("--compiler", default="clang++")
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--expected-clang", default="18.1.3")
    parser.add_argument("--container-image", default=DEFAULT_CONTAINER_IMAGE)
    parser.add_argument("--expected-container-id", default=DEFAULT_CONTAINER_ID)
    parser.add_argument("--expected-source-sha256")
    parser.add_argument("--compile-timeout-s", type=int, default=180)
    parser.add_argument("--runtime-timeout-s", type=int, default=180)
    parser.add_argument("--container-timeout-s", type=int, default=300)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    exercise_dir = args.exercise_dir.resolve()
    output_dir = args.output_dir.resolve()
    if not exercise_dir.is_dir():
        raise SystemExit(f"exercise directory does not exist: {exercise_dir}")
    compiler = shutil.which(args.compiler)
    docker = shutil.which(args.docker)
    if compiler is None or docker is None:
        raise SystemExit("Clang and Docker must both be available")
    try:
        _prepare_output(output_dir, exercise_dir)
        source_sha256 = _source_digest(exercise_dir)
    except (OSError, ValueError) as error:
        raise SystemExit(str(error)) from error
    if args.expected_source_sha256 and source_sha256 != args.expected_source_sha256:
        raise SystemExit(f"source digest mismatch: expected {args.expected_source_sha256}, observed {source_sha256}")
    ctx = VerifierContext(
        exercise_dir=exercise_dir,
        output_dir=output_dir,
        compiler=compiler,
        docker=docker,
        expected_clang=args.expected_clang,
        container_image=args.container_image,
        expected_container_id=args.expected_container_id,
        source_sha256=source_sha256,
        compile_timeout_s=args.compile_timeout_s,
        runtime_timeout_s=args.runtime_timeout_s,
        container_timeout_s=args.container_timeout_s,
    )
    receipt = verify_policy_10(ctx)
    receipt_path = output_dir / "verification_receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: receipt[key] for key in ("status", "kernel_sum", "passed_kernels", "failed_kernels")}, sort_keys=True))
    print(receipt_path)
    return 0 if receipt["status"] == "pass" else 2 if receipt["status"] == "invalid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
