# Policy 4 verifier: check five independent include and dependency kernels.
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
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
PINNED_CMAKE_SHA256 = "9f97b18ee31d7b22e34c8334d28f45947f7f34548f3659cead93fac35bb33636"
PINNED_CATCH_SHA256 = "681e7505a50887c9085539e5135794fc8f66d8e5de28eadf13a30978627b0f47"
PINNED_TEST_MAIN_SHA256 = "5847fda35c1320d94f8d088aaf34229d689f66f1da235f885cbb28c8f17e4260"
HEADER_PROBE = """#include \"bank_account.h\"

int main() {
    return 0;
}
"""
SYMBOL_OWNERS = (
    ("std::mutex", "mutex"),
    ("std::lock_guard", "mutex"),
    ("std::unique_lock", "mutex"),
    ("std::scoped_lock", "mutex"),
    ("std::shared_mutex", "shared_mutex"),
    ("std::shared_lock", "shared_mutex"),
    ("std::condition_variable", "condition_variable"),
    ("std::runtime_error", "stdexcept"),
    ("std::logic_error", "stdexcept"),
    ("std::atomic", "atomic"),
    ("std::thread", "thread"),
    ("std::vector", "vector"),
)
FORBIDDEN_TASK_DEPENDENCIES = {
    "bank_account_test.cpp",
    "test/catch.hpp",
    "test/tests-main.cpp",
}


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
    expected_cmake_sha256: str
    expected_catch_sha256: str
    expected_test_main_sha256: str
    configure_timeout_s: int
    compile_timeout_s: int


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
) -> KernelReceipt:
    return KernelReceipt(kernel_id, -1, "fail", summary, commands, facts, {})


def _invalid(
    kernel_id: str,
    summary: str,
    commands: list[CommandReceipt] | None = None,
    facts: dict[str, Any] | None = None,
) -> KernelReceipt:
    return KernelReceipt(kernel_id, None, "invalid", summary, commands or [], facts or {}, {})


def _strip_noncode(source: str) -> str:
    pattern = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', re.DOTALL)
    return pattern.sub(" ", source)


def _direct_includes(source: str) -> list[str]:
    matches = re.findall(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]', source, flags=re.MULTILINE)
    return sorted(set(matches))


def _include_ownership(ctx: VerifierContext) -> dict[str, Any]:
    header_source = (ctx.exercise_dir / "bank_account.h").read_text(encoding="utf-8")
    implementation_source = (ctx.exercise_dir / "bank_account.cpp").read_text(encoding="utf-8")
    raw_sources = {"bank_account.h": header_source, "bank_account.cpp": implementation_source}
    code_sources = {name: _strip_noncode(source) for name, source in raw_sources.items()}
    direct = {name: _direct_includes(source) for name, source in raw_sources.items()}
    header_owned = {
        owner
        for symbol, owner in SYMBOL_OWNERS
        if symbol in code_sources["bank_account.h"] and owner in direct["bank_account.h"]
    }
    observations: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []
    for filename, code in code_sources.items():
        for symbol, owner in SYMBOL_OWNERS:
            if symbol not in code:
                continue
            direct_owner = owner in direct[filename]
            project_owner = (
                filename == "bank_account.cpp"
                and "bank_account.h" in direct[filename]
                and owner in header_owned
            )
            valid = direct_owner or project_owner
            observations.append(
                {
                    "file": filename,
                    "symbol": symbol,
                    "owner": f"<{owner}>",
                    "ownership": "direct" if direct_owner else "public-header" if project_owner else "missing",
                }
            )
            if not valid:
                missing.append({"file": filename, "symbol": symbol, "required_include": f"<{owner}>"})
    return {
        "direct_includes": direct,
        "observations": observations,
        "missing_owners": missing,
    }


def verify_4a_direct_include_ownership(ctx: VerifierContext) -> KernelReceipt:
    assets_ok, asset_fact = _assets_valid(ctx)
    if not assets_ok:
        return _invalid("4A", asset_fact)
    try:
        facts = _include_ownership(ctx)
    except OSError as error:
        return _invalid("4A", f"candidate source could not be inspected: {error}")
    facts["source_sha256"] = ctx.source_sha256
    if not facts["missing_owners"]:
        return _pass("4A", "all mapped standard-library symbols have intentional include owners", [], facts)
    return _fail("4A", "one or more mapped standard-library symbols lack an include owner", [], facts)


def verify_4b_header_self_contained(ctx: VerifierContext) -> KernelReceipt:
    assets_ok, asset_fact = _assets_valid(ctx)
    if not assets_ok:
        return _invalid("4B", asset_fact)
    probes = ctx.output_dir / "probes"
    objects = ctx.output_dir / "objects"
    probes.mkdir(parents=True, exist_ok=True)
    objects.mkdir(parents=True, exist_ok=True)
    probe = probes / "header_self_contained.cpp"
    target = objects / "header_self_contained.o"
    probe.write_text(HEADER_PROBE, encoding="utf-8")
    command = [
        ctx.compiler,
        *STRICT_FLAGS,
        f"-I{ctx.exercise_dir}",
        "-c",
        str(probe),
        "-o",
        str(target),
    ]
    result = _run(ctx, "4B", "header_self_contained", command, ctx.compile_timeout_s)
    facts = {"timed_out": result.timed_out, "probe": probe.name}
    if result.return_code == 127:
        return _invalid("4B", "compiler process is unavailable", [result], facts)
    if result.return_code == 0 and _valid_artifact(target) and _assets_valid(ctx)[0]:
        return _pass(
            "4B",
            "bank_account.h compiled as the only included header",
            [result],
            facts,
            {probe.name: _sha256(probe), target.name: _sha256(target)},
        )
    return _fail("4B", "bank_account.h is not self-contained", [result], facts)


def _parse_depfile(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace").replace("\\\n", " ")
    separator = text.find(":")
    if separator < 0:
        raise ValueError(f"dependency file has no target separator: {path}")
    return shlex.split(text[separator + 1 :])


def _task_relative_dependencies(ctx: VerifierContext, dependencies: list[str]) -> list[str]:
    results: set[str] = set()
    root = ctx.exercise_dir.resolve()
    for item in dependencies:
        path = Path(item)
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        else:
            path = path.resolve()
        try:
            results.add(path.relative_to(root).as_posix())
        except ValueError:
            continue
    return sorted(results)


def verify_4c_dependency_graph(ctx: VerifierContext) -> KernelReceipt:
    assets_ok, asset_fact = _assets_valid(ctx)
    if not assets_ok:
        return _invalid("4C", asset_fact)
    probes = ctx.output_dir / "probes"
    objects = ctx.output_dir / "dependency_objects"
    dependencies_dir = ctx.output_dir / "dependencies"
    probes.mkdir(parents=True, exist_ok=True)
    objects.mkdir(parents=True, exist_ok=True)
    dependencies_dir.mkdir(parents=True, exist_ok=True)
    probe = probes / "dependency_header_probe.cpp"
    probe.write_text(HEADER_PROBE, encoding="utf-8")
    specifications = (
        ("header", probe, objects / "header.o", dependencies_dir / "header.d"),
        ("implementation", ctx.exercise_dir / "bank_account.cpp", objects / "implementation.o", dependencies_dir / "implementation.d"),
    )
    commands: list[CommandReceipt] = []
    artifacts: dict[str, str] = {probe.name: _sha256(probe)}
    task_dependencies: dict[str, list[str]] = {}
    for label, source, target, depfile in specifications:
        command = [
            ctx.compiler,
            *STRICT_FLAGS,
            f"-I{ctx.exercise_dir}",
            "-MD",
            "-MF",
            str(depfile),
            "-c",
            str(source),
            "-o",
            str(target),
        ]
        result = _run(ctx, "4C", f"dependency_{label}", command, ctx.compile_timeout_s)
        commands.append(result)
        if result.return_code == 127:
            return _invalid("4C", "compiler process is unavailable", commands)
        if result.return_code != 0 or not _valid_artifact(target):
            return _fail(
                "4C",
                f"{label} dependency compilation failed",
                commands,
                {"failed_stage": label, "timed_out": result.timed_out},
            )
        if not _valid_artifact(depfile):
            return _invalid("4C", f"compiler did not produce {depfile.name}", commands)
        try:
            parsed = _parse_depfile(depfile)
        except (OSError, ValueError) as error:
            return _invalid("4C", f"dependency file could not be parsed: {error}", commands)
        task_dependencies[label] = _task_relative_dependencies(ctx, parsed)
        artifacts[target.name] = _sha256(target)
        artifacts[depfile.name] = _sha256(depfile)
    try:
        ownership = _include_ownership(ctx)
        direct = ownership["direct_includes"]
    except OSError as error:
        return _invalid("4C", f"candidate includes could not be inspected: {error}", commands)
    forbidden_direct = sorted(
        {
            include
            for includes in direct.values()
            for include in includes
            if "catch" in include.lower()
            or include.endswith("bank_account_test.cpp")
            or include.endswith("tests-main.cpp")
        }
    )
    forbidden_graph = sorted(
        {
            dependency
            for dependencies in task_dependencies.values()
            for dependency in dependencies
            if dependency in FORBIDDEN_TASK_DEPENDENCIES
        }
    )
    implementation_reaches_header = "bank_account.h" in task_dependencies.get("implementation", [])
    facts = {
        "task_dependencies": task_dependencies,
        "forbidden_direct_includes": forbidden_direct,
        "forbidden_graph_dependencies": forbidden_graph,
        "missing_owners": ownership["missing_owners"],
        "implementation_reaches_public_header": implementation_reaches_header,
    }
    passed = (
        not forbidden_direct
        and not forbidden_graph
        and not ownership["missing_owners"]
        and implementation_reaches_header
        and _assets_valid(ctx)[0]
    )
    if passed:
        return _pass("4C", "compiler dependency graph is isolated from tests and has declared owners", commands, facts, artifacts)
    return _fail("4C", "dependency graph contains a missing owner or forbidden task dependency", commands, facts)


def _compiler_record(build_dir: Path) -> str:
    candidates = list(build_dir.glob("CMakeFiles/*/CMakeCXXCompiler.cmake"))
    if not candidates:
        return ""
    return candidates[0].read_text(encoding="utf-8", errors="replace")


def _fixed_dependency_facts(ctx: VerifierContext) -> dict[str, Any]:
    cmake_path = ctx.exercise_dir / "CMakeLists.txt"
    catch_path = ctx.exercise_dir / "test/catch.hpp"
    test_main_path = ctx.exercise_dir / "test/tests-main.cpp"
    cmake_source = cmake_path.read_text(encoding="utf-8")
    cmake_hash = _sha256(cmake_path)
    catch_hash = _sha256(catch_path)
    test_main_hash = _sha256(test_main_path)
    return {
        "cmake_sha256": cmake_hash,
        "catch_sha256": catch_hash,
        "test_main_sha256": test_main_hash,
        "cmake_hash_matches": cmake_hash == ctx.expected_cmake_sha256,
        "catch_hash_matches": catch_hash == ctx.expected_catch_sha256,
        "test_main_hash_matches": test_main_hash == ctx.expected_test_main_sha256,
        "threads_required": bool(re.search(r"find_package\s*\(\s*Threads\s+REQUIRED\s*\)", cmake_source)),
        "threads_linked": "Threads::Threads" in cmake_source,
        "cxx17_declared": bool(re.search(r"CXX_STANDARD\s+17", cmake_source)),
    }


def verify_4d_pinned_dependencies(ctx: VerifierContext) -> KernelReceipt:
    assets_ok, asset_fact = _assets_valid(ctx)
    if not assets_ok:
        return _invalid("4D", asset_fact)
    try:
        facts = _fixed_dependency_facts(ctx)
    except OSError as error:
        return _invalid("4D", f"fixed dependency assets could not be read: {error}")
    commands: list[CommandReceipt] = []
    version = _run(ctx, "4D", "cmake_version", [ctx.cmake, "--version"], ctx.configure_timeout_s)
    commands.append(version)
    if version.return_code != 0:
        return _invalid("4D", "CMake is unavailable", commands, facts)
    version_text = Path(version.stdout_log).read_text(encoding="utf-8", errors="replace").splitlines()
    facts["cmake_version"] = version_text[0] if version_text else "unknown"
    fixed_contract_ok = all(
        facts[key]
        for key in (
            "cmake_hash_matches",
            "catch_hash_matches",
            "test_main_hash_matches",
            "threads_required",
            "threads_linked",
            "cxx17_declared",
        )
    )
    build_dir = ctx.output_dir / "build_4d"
    if build_dir.exists():
        return _invalid("4D", f"configuration directory is not fresh: {build_dir}", commands, facts)
    configure = _run(
        ctx,
        "4D",
        "dependency_configure",
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
        if fixed_contract_ok:
            return _invalid("4D", "pinned CMake or Threads configuration failed in the evaluator", commands, facts)
        return _fail("4D", "fixed dependency contract drifted and configuration failed", commands, facts)
    compile_commands_path = build_dir / "compile_commands.json"
    try:
        compile_commands = compile_commands_path.read_text(encoding="utf-8")
        compiler_record = _compiler_record(build_dir)
    except OSError as error:
        return _invalid("4D", f"generated CMake evidence could not be read: {error}", commands, facts)
    facts["compiler_id_gnu"] = 'set(CMAKE_CXX_COMPILER_ID "GNU")' in compiler_record
    facts["generated_cxx17"] = "-std=c++17" in compile_commands or "-std=gnu++17" in compile_commands
    facts["all_tests_enabled"] = "EXERCISM_RUN_ALL_TESTS" in compile_commands
    passed = (
        fixed_contract_ok
        and facts["compiler_id_gnu"]
        and facts["generated_cxx17"]
        and facts["all_tests_enabled"]
        and _assets_valid(ctx)[0]
    )
    artifacts = {
        "CMakeLists.txt": facts["cmake_sha256"],
        "test/catch.hpp": facts["catch_sha256"],
        "test/tests-main.cpp": facts["test_main_sha256"],
        "compile_commands.json": _sha256(compile_commands_path),
    }
    if passed:
        return _pass("4D", "fixed dependencies, Threads, C++17, and all-tests configuration match", commands, facts, artifacts)
    return _fail("4D", "one or more fixed dependency identities or declarations do not match", commands, facts)


def _find_built_executable(build_dir: Path, name: str) -> Path | None:
    direct = build_dir / name
    if _valid_artifact(direct, executable=True):
        return direct
    matches = [path for path in build_dir.rglob(name) if _valid_artifact(path, executable=True)]
    return matches[0] if len(matches) == 1 else None


def verify_4e_empty_directory_rebuild(ctx: VerifierContext) -> KernelReceipt:
    assets_ok, asset_fact = _assets_valid(ctx)
    if not assets_ok:
        return _invalid("4E", asset_fact)
    commands: list[CommandReceipt] = []
    version = _run(ctx, "4E", "cmake_version", [ctx.cmake, "--version"], ctx.configure_timeout_s)
    commands.append(version)
    if version.return_code != 0:
        return _invalid("4E", "CMake is unavailable", commands)
    build_dir = ctx.output_dir / "build_4e"
    if build_dir.exists():
        return _invalid("4E", f"clean-build directory is not fresh: {build_dir}", commands)
    configure = _run(
        ctx,
        "4E",
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
        try:
            fixed_contract_ok = all(
                _fixed_dependency_facts(ctx)[key]
                for key in (
                    "cmake_hash_matches",
                    "catch_hash_matches",
                    "test_main_hash_matches",
                    "threads_required",
                    "threads_linked",
                    "cxx17_declared",
                )
            )
        except OSError:
            fixed_contract_ok = False
        if fixed_contract_ok:
            return _invalid("4E", "fresh evaluator configuration failed with an intact fixed contract", commands)
        return _fail("4E", "fresh configuration failed after dependency contract drift", commands, {})
    target_name = ctx.exercise_dir.name
    build = _run(
        ctx,
        "4E",
        "fresh_target_build",
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
    if build.return_code == 127:
        return _invalid("4E", "CMake build process is unavailable", commands, facts)
    if build.return_code == 0 and executable is not None and _assets_valid(ctx)[0]:
        facts["executable_bytes"] = executable.stat().st_size
        return _pass(
            "4E",
            "empty-directory executable rebuild succeeded",
            commands,
            facts,
            {str(executable.relative_to(ctx.output_dir)): _sha256(executable)},
        )
    return _fail("4E", "empty-directory executable rebuild failed", commands, facts)


def _preflight(ctx: VerifierContext) -> tuple[bool, str, list[CommandReceipt], dict[str, Any]]:
    commands: list[CommandReceipt] = []
    version = _run(
        ctx,
        "preflight",
        "gcc_version",
        [ctx.compiler, "-dumpfullversion", "-dumpversion"],
        ctx.configure_timeout_s,
    )
    commands.append(version)
    if version.return_code != 0:
        return False, "GNU compiler identity could not be read", commands, {}
    macros = _run(
        ctx,
        "preflight",
        "gcc_macros",
        [ctx.compiler, "-dM", "-E", "-x", "c++", "-"],
        ctx.configure_timeout_s,
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


def verify_policy_4(ctx: VerifierContext) -> dict[str, Any]:
    preflight_ok, preflight_summary, preflight_commands, preflight_facts = _preflight(ctx)
    assets_ok, asset_fact = _assets_valid(ctx)
    if not preflight_ok or not assets_ok:
        reason = preflight_summary if not preflight_ok else asset_fact
        results = [
            _invalid(kernel_id, reason, preflight_commands, preflight_facts)
            for kernel_id in ("4A", "4B", "4C", "4D", "4E")
        ]
    else:
        results = [
            verify_4a_direct_include_ownership(ctx),
            verify_4b_header_self_contained(ctx),
            verify_4c_dependency_graph(ctx),
            verify_4d_pinned_dependencies(ctx),
            verify_4e_empty_directory_rebuild(ctx),
        ]
    invalid = any(result.kernel is None for result in results)
    kernel_sum = None if invalid else sum(result.kernel for result in results if result.kernel is not None)
    status = "invalid" if invalid else "pass" if kernel_sum == 5 else "fail"
    return {
        "schema_version": 1,
        "policy_id": "bank-account-policy-04-include-dependency-integrity-v1",
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
    parser.add_argument("--cmake", default="cmake")
    parser.add_argument("--expected-gcc", default="13.3")
    parser.add_argument("--expected-source-sha256")
    parser.add_argument("--expected-cmake-sha256", default=PINNED_CMAKE_SHA256)
    parser.add_argument("--expected-catch-sha256", default=PINNED_CATCH_SHA256)
    parser.add_argument("--expected-test-main-sha256", default=PINNED_TEST_MAIN_SHA256)
    parser.add_argument("--configure-timeout-s", type=int, default=30)
    parser.add_argument("--compile-timeout-s", type=int, default=120)
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
        cmake=shutil.which(args.cmake) or args.cmake,
        expected_gcc=args.expected_gcc,
        source_sha256=source_sha256,
        expected_cmake_sha256=args.expected_cmake_sha256,
        expected_catch_sha256=args.expected_catch_sha256,
        expected_test_main_sha256=args.expected_test_main_sha256,
        configure_timeout_s=args.configure_timeout_s,
        compile_timeout_s=args.compile_timeout_s,
    )
    receipt = verify_policy_4(ctx)
    receipt_path = output_dir / "verification_receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: receipt[key] for key in ("status", "kernel_sum", "passed_kernels", "failed_kernels")}, sort_keys=True))
    print(receipt_path)
    return 0 if receipt["status"] == "pass" else 2 if receipt["status"] == "invalid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
