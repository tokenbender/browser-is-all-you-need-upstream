"""G05: optional manifest-driven ASan/UBSan diagnostic."""

from __future__ import annotations

import copy
import re
import shutil
from pathlib import Path, PurePath
from typing import Any, Callable

import g04_functional
from receipt import PolicyReceipt, policy
from sandbox import CommandResult, Limits, executable_missing, result_facts

Execute = Callable[[list[str], Path, Limits, dict[str, str] | None], CommandResult]


def _strings(value: Any) -> list[str] | None:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        return None
    return list(value)


def _safe_assets(values: list[str]) -> bool:
    return all(
        not (path := PurePath(value)).is_absolute() and ".." not in path.parts
        for value in values
    )


def _verify_direct(workspace: Path, manifest: dict[str, Any], execute: Execute,
                   limits: Limits) -> PolicyReceipt:
    build, functional = manifest.get("build", {}), manifest.get("functional", {})
    test_sources_value = functional.get("test_sources")
    if test_sources_value is None and isinstance(functional.get("test_source"), str):
        test_sources_value = [functional["test_source"]]
    sources = _strings(build.get("sources"))
    test_sources = _strings(test_sources_value)
    build_flags = _strings(build.get("flags", []))
    includes = _strings(functional.get("include_dirs", build.get("include_dirs", ["."])))
    defines = _strings(functional.get("defines", []))
    compile_flags = _strings(functional.get("compile_flags", []))
    libraries = _strings(functional.get("libraries", build.get("libraries", [])))
    link_args = _strings(functional.get("link_args", build.get("link_args", [])))
    run_args = _strings(functional.get("run_args", []))
    runtime_assets = _strings(functional.get("runtime_assets", []))
    env_value = functional.get("env", {})
    compiler = build.get("compiler", "g++")
    standard = build.get("standard", "c++17")
    result_pattern = functional.get("result_regex")
    result_stream = functional.get("result_stream", "stdout")
    expected_total = functional.get("expected_total")
    values = (
        sources, test_sources, build_flags, includes, defines, compile_flags,
        libraries, link_args, run_args, runtime_assets,
    )
    if (
        any(value is None for value in values)
        or not sources or not test_sources
        or not isinstance(compiler, str) or not compiler
        or not isinstance(standard, str) or not standard
        or not isinstance(env_value, dict)
        or not all(isinstance(key, str) and isinstance(value, str)
                   for key, value in env_value.items())
        or not isinstance(result_pattern, str)
        or result_stream not in {"stdout", "stderr"}
        or not isinstance(expected_total, int) or expected_total < 1
    ):
        return policy("G05", "INVALID", "SAFETY_WORKLOAD_MISSING")
    assert all(value is not None for value in values)
    if not _safe_assets([*sources, *test_sources, *runtime_assets]):
        return policy("G05", "INVALID", "SAFETY_WORKLOAD_MISSING")
    try:
        result_regex = re.compile(result_pattern)
    except re.error as error:
        return policy("G05", "INVALID", "INVALID_TEST_RECEIPT_PATTERN", error=str(error))
    if not {"passed", "total"}.issubset(result_regex.groupindex):
        return policy("G05", "INVALID", "INVALID_TEST_RECEIPT_PATTERN",
                      required_groups=["passed", "total"])

    (workspace / ".gv2").mkdir(exist_ok=True)
    binary = ".gv2/safety_tests"
    command = [
        compiler, f"-std={standard}", *build_flags, *compile_flags,
        "-O1", "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
        *(f"-I{value}" for value in includes), *(f"-D{value}" for value in defines),
        *sources, *test_sources, *(f"-l{value}" for value in libraries),
        *link_args, "-o", binary,
    ]
    compiled = execute(command, workspace, limits, None)
    if (
        compiled.launch_error or compiled.timed_out
        or executable_missing(compiled) or compiled.returncode == 127
    ):
        return policy("G05", "INVALID", "SANITIZER_TOOLCHAIN_UNAVAILABLE",
                      compile=result_facts(compiled))
    if compiled.returncode != 0:
        return policy("G05", "FAIL", "SANITIZER_BUILD_FAIL", compile=result_facts(compiled))

    runtime = workspace / ".gv2/safety_runtime"
    runtime.mkdir()
    try:
        shutil.copy2(workspace / binary, runtime / "safety_tests")
        for name in runtime_assets:
            destination = runtime / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(workspace / name, destination)
    except OSError as error:
        return policy("G05", "INVALID", "SAFETY_WORKLOAD_MISSING", error=str(error))

    run_env = dict(env_value)
    run_env.update({
        "ASAN_OPTIONS": "halt_on_error=1:detect_leaks=1",
        "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
    })
    run = execute(["./safety_tests", *run_args], runtime, limits, run_env)
    if run.launch_error:
        return policy("G05", "INVALID", "SANITIZER_RUNTIME_UNAVAILABLE",
                      run=result_facts(run))
    if run.timed_out:
        return policy("G05", "FAIL", "SANITIZER_TIMEOUT", run=result_facts(run))
    if run.returncode != 0:
        return policy("G05", "FAIL", "SANITIZER_FAIL",
                      compile=result_facts(compiled), run=result_facts(run))
    if run.stdout_truncated or run.stderr_truncated:
        return policy("G05", "FAIL", "TEST_OUTPUT_LIMIT_EXCEEDED",
                      compile=result_facts(compiled), run=result_facts(run))

    stream = run.stdout if result_stream == "stdout" else run.stderr
    matches = list(result_regex.finditer(stream))
    if not matches:
        return policy("G05", "FAIL", "TEST_RECEIPT_MISSING",
                      compile=result_facts(compiled), run=result_facts(run))
    if len(matches) != 1:
        return policy("G05", "FAIL", "TEST_RECEIPT_DUPLICATED",
                      receipt_count=len(matches), compile=result_facts(compiled),
                      run=result_facts(run))
    try:
        passed = int(matches[0].group("passed"))
        total = int(matches[0].group("total"))
    except (TypeError, ValueError):
        return policy("G05", "INVALID", "MALFORMED_TEST_COUNT",
                      compile=result_facts(compiled), run=result_facts(run))
    if total < 1 or passed < 0 or passed > total or total != expected_total:
        return policy("G05", "INVALID", "MALFORMED_TEST_COUNT",
                      tests_passed=passed, tests_total=total,
                      expected_total=expected_total, compile=result_facts(compiled),
                      run=result_facts(run))
    status = "PASS" if passed == total else "FAIL"
    return policy(
        "G05", status, "SAFETY_PASS" if status == "PASS" else "SANITIZER_FAIL",
        tests_passed=passed, tests_total=total, score=passed / total,
        compile=result_facts(compiled), run=result_facts(run),
    )


_G04_GENERATED_DIRECTORIES = (
    ".gv2/probe_sources",
    ".gv2/bridge_objects",
    ".gv2/test_objects",
    ".gv2/runtime",
    ".gv2/external_runtime",
)
_G04_GENERATED_FILES = (
    ".gv2/runtime_guard.cpp",
    ".gv2/trusted_child.cpp",
    ".gv2/trusted_supervisor.cpp",
    ".gv2/candidate_child",
    ".gv2/trusted_supervisor",
    ".gv2/candidate_probe",
)
_SANITIZER_FLAGS = (
    "-O1",
    "-g",
    "-fsanitize=address,undefined",
    "-fno-omit-frame-pointer",
)


def _clear_g04_materializations(workspace: Path) -> str | None:
    try:
        for name in _G04_GENERATED_DIRECTORIES:
            path = workspace / name
            if path.is_symlink() or (path.exists() and not path.is_dir()):
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
        for name in _G04_GENERATED_FILES:
            path = workspace / name
            if path.exists() or path.is_symlink():
                path.unlink()
    except OSError as error:
        return f"{type(error).__name__}: {error}"
    return None


def _external_contract_ready(
    workspace: Path, trusted_assets: Path | None, manifest: dict[str, Any],
) -> Path | None:
    functional = manifest.get("functional", {})
    bridges = _strings(functional.get("bridge_sources"))
    bridge_flags = _strings(functional.get("bridge_compile_flags", []))
    oracle = functional.get("oracle_cases")
    expected_total = functional.get("expected_total")
    protected = manifest.get("protected_files", {})
    if (
        trusted_assets is None or not isinstance(functional, dict)
        or not bridges or bridge_flags is None
        or functional.get("bridge_source_encoding", "plain") not in {"plain", "gzip"}
        or not isinstance(oracle, str) or not oracle
        or functional.get("oracle_cases_encoding") != "gzip"
        or not isinstance(expected_total, int) or expected_total < 1
        or not isinstance(protected, dict) or oracle not in protected
        or not _safe_assets([*bridges, oracle])
    ):
        return None
    if not all((workspace / name).is_file() for name in bridges):
        return None
    # Optional policies recompile candidate sources, so the protected oracle
    # must remain outside the candidate-facing preprocessing tree.
    candidate_oracle = workspace / oracle
    if candidate_oracle.exists() or candidate_oracle.is_symlink():
        return None
    try:
        candidate_root = workspace.resolve(strict=True)
        trusted_root = trusted_assets.resolve(strict=True)
    except OSError:
        return None
    trusted_oracle = trusted_root / oracle
    if (
        candidate_root == trusted_root or trusted_root.is_relative_to(candidate_root)
        or not trusted_oracle.is_file() or trusted_oracle.is_symlink()
    ):
        return None
    return trusted_root


def _compile_external_candidates(
    workspace: Path, manifest: dict[str, Any], execute: Execute, limits: Limits,
) -> tuple[list[str], list[dict[str, object]], PolicyReceipt | None]:
    build = manifest.get("build", {})
    sources = _strings(build.get("sources"))
    flags = _strings(build.get("flags", []))
    includes = _strings(build.get("include_dirs", ["."]))
    defines = _strings(build.get("defines", []))
    compiler = build.get("compiler")
    standard = build.get("standard", "c++17")
    if (
        not sources or any(value is None for value in (flags, includes, defines))
        or not isinstance(compiler, str) or not compiler
        or not isinstance(standard, str) or not standard
        or not _safe_assets(sources)
    ):
        return [], [], policy("G05", "INVALID", "EXTERNAL_ORACLE_SAFETY_NOT_READY")
    if (workspace / ".gv2/probe_sources").exists():
        return [], [], policy("G05", "INVALID", "EXTERNAL_PROBE_MATERIALIZATION_PRESENT")
    target = workspace / ".gv2/g05_candidate_objects"
    try:
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
    except OSError as error:
        return [], [], policy(
            "G05", "INVALID", "EXTERNAL_ORACLE_SAFETY_NOT_READY", error=str(error)
        )

    objects: list[str] = []
    commands: list[dict[str, object]] = []
    for index, source in enumerate(sources):
        output = (target / f"source_{index}.o").relative_to(workspace).as_posix()
        command = [
            compiler, f"-std={standard}", *flags,
            *(f"-I{value}" for value in includes),
            *(f"-D{value}" for value in defines),
            "-c", source, "-o", output,
        ]
        result = execute(command, workspace, limits, None)
        commands.append(result_facts(result))
        if (
            result.launch_error or result.timed_out
            or executable_missing(result) or result.returncode == 127
        ):
            return [], commands, policy(
                "G05", "INVALID", "SANITIZER_TOOLCHAIN_UNAVAILABLE",
                phase="candidate", compile_commands=commands,
            )
        if result.returncode != 0:
            return [], commands, policy(
                "G05", "FAIL", "SANITIZER_BUILD_FAIL",
                phase="candidate", compile_commands=commands,
            )
        objects.append(output)
    return objects, commands, None


def _verify_external(
    workspace: Path, manifest: dict[str, Any], execute: Execute, limits: Limits,
    trusted_assets: Path | None,
) -> PolicyReceipt:
    cleanup_error = _clear_g04_materializations(workspace)
    if cleanup_error:
        return policy(
            "G05", "INVALID", "EXTERNAL_ORACLE_CLEANUP_FAILED", error=cleanup_error
        )
    trusted_root = _external_contract_ready(workspace, trusted_assets, manifest)
    if trusted_root is None:
        return policy("G05", "INVALID", "EXTERNAL_ORACLE_SAFETY_NOT_READY")

    isolated = copy.deepcopy(manifest)
    build = isolated.setdefault("build", {})
    build_flags = _strings(build.get("flags", []))
    if build_flags is None:
        return policy("G05", "INVALID", "EXTERNAL_ORACLE_SAFETY_NOT_READY")
    build["flags"] = [*build_flags, *_SANITIZER_FLAGS]
    isolated_functional = isolated.setdefault("functional", {})
    environment = isolated_functional.get("env", {})
    if not isinstance(environment, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in environment.items()
    ):
        return policy("G05", "INVALID", "EXTERNAL_ORACLE_SAFETY_NOT_READY")
    isolated_functional["env"] = {
        **environment,
        "ASAN_OPTIONS": "halt_on_error=1:detect_leaks=1",
        "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
    }

    objects, candidate_commands, failed = _compile_external_candidates(
        workspace, isolated, execute, limits
    )
    if failed is not None:
        return failed

    functional_receipt: PolicyReceipt | None = None
    execution_error: str | None = None
    try:
        functional_receipt = g04_functional.verify(
            workspace, isolated, objects, execute, limits,
            trusted_assets=trusted_root,
        )
    except (OSError, ValueError) as error:
        execution_error = f"{type(error).__name__}: {error}"
    finally:
        cleanup_error = _clear_g04_materializations(workspace)
    if cleanup_error:
        return policy(
            "G05", "INVALID", "EXTERNAL_ORACLE_CLEANUP_FAILED",
            error=cleanup_error, candidate_compile=candidate_commands,
        )
    if execution_error or functional_receipt is None:
        return policy(
            "G05", "INVALID", "EXTERNAL_ORACLE_SAFETY_NOT_READY",
            error=execution_error, candidate_compile=candidate_commands,
        )

    facts = {
        "candidate_compile": candidate_commands,
        "functional_status": functional_receipt.status,
        "functional_reason": functional_receipt.reason,
        "functional": functional_receipt.facts,
        "authoritative": (
            functional_receipt.facts.get("authoritative") is True
            and functional_receipt.facts.get("trusted_assets_isolated") is True
            and functional_receipt.facts.get("trust_boundary")
            == "python-compares-raw-observations-v1"
        ),
    }
    if functional_receipt.status == "INVALID":
        return policy("G05", "INVALID", "EXTERNAL_ORACLE_SAFETY_NOT_READY", **facts)
    if functional_receipt.status != "PASS":
        return policy("G05", "FAIL", "SANITIZER_FAIL", **facts)
    if not facts["authoritative"]:
        return policy("G05", "INVALID", "EXTERNAL_ORACLE_SAFETY_NOT_READY", **facts)
    return policy(
        "G05", "PASS", "SAFETY_PASS",
        tests_passed=functional_receipt.facts.get("tests_passed"),
        tests_total=functional_receipt.facts.get("tests_total"),
        score=functional_receipt.facts.get("score"),
        **facts,
    )


def verify(
    workspace: Path, manifest: dict[str, Any], execute: Execute, limits: Limits,
    *, trusted_assets: Path | None = None,
) -> PolicyReceipt:
    mode = manifest.get("functional", {}).get("mode")
    if mode == "external_oracle_v1":
        return _verify_external(
            workspace, manifest, execute, limits, trusted_assets
        )
    if mode in {None, "diagnostic_direct_v1"}:
        return _verify_direct(workspace, manifest, execute, limits)
    return policy("G05", "INVALID", "SAFETY_MODE_NOT_READY", mode=mode)
