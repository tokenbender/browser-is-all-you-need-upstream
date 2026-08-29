"""G07: optional alternate-toolchain build and functional diagnostic."""

from __future__ import annotations

import copy
import re
import shutil
from pathlib import Path, PurePath
from typing import Any, Callable

import g04_functional
from g05_safety import _clear_g04_materializations, _external_contract_ready
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
    compilers = _strings(
        manifest.get("portability", {}).get("compilers", ["g++", "clang++"])
    )
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
    standard = build.get("standard", "c++17")
    result_pattern = functional.get("result_regex")
    result_stream = functional.get("result_stream", "stdout")
    expected_total = functional.get("expected_total")
    values = (
        sources, test_sources, build_flags, includes, defines, compile_flags,
        libraries, link_args, run_args, runtime_assets,
    )
    if (
        compilers is None or len(compilers) < 2
        or any(value is None for value in values)
        or not sources or not test_sources
        or not isinstance(standard, str) or not standard
        or not isinstance(env_value, dict)
        or not all(isinstance(key, str) and isinstance(value, str)
                   for key, value in env_value.items())
        or not isinstance(result_pattern, str)
        or result_stream not in {"stdout", "stderr"}
        or not isinstance(expected_total, int) or expected_total < 1
    ):
        return policy("G07", "INVALID", "PORTABILITY_CONTRACT_MISSING")
    assert all(value is not None for value in values)
    if not _safe_assets([*sources, *test_sources, *runtime_assets]):
        return policy("G07", "INVALID", "PORTABILITY_CONTRACT_MISSING")
    try:
        result_regex = re.compile(result_pattern)
    except re.error as error:
        return policy("G07", "INVALID", "INVALID_TEST_RECEIPT_PATTERN", error=str(error))
    if not {"passed", "total"}.issubset(result_regex.groupindex):
        return policy("G07", "INVALID", "INVALID_TEST_RECEIPT_PATTERN",
                      required_groups=["passed", "total"])

    (workspace / ".gv2").mkdir(exist_ok=True)
    runs: list[dict[str, object]] = []
    for index, compiler in enumerate(compilers):
        binary = f".gv2/portability_{index}"
        command = [
            compiler, f"-std={standard}", *build_flags, *compile_flags,
            *(f"-I{value}" for value in includes), *(f"-D{value}" for value in defines),
            *sources, *test_sources, *(f"-l{value}" for value in libraries),
            *link_args, "-o", binary,
        ]
        compiled = execute(command, workspace, limits, None)
        if (
            compiled.launch_error or compiled.timed_out
            or executable_missing(compiled) or compiled.returncode == 127
        ):
            return policy("G07", "INVALID", "PORTABILITY_TOOLCHAIN_UNAVAILABLE",
                          compiler=compiler, compile=result_facts(compiled), runs=runs)
        if compiled.returncode != 0:
            return policy("G07", "FAIL", "PORTABILITY_BUILD_FAIL",
                          compiler=compiler, compile=result_facts(compiled), runs=runs)

        runtime = workspace / f".gv2/portability_runtime_{index}"
        runtime.mkdir()
        try:
            shutil.copy2(workspace / binary, runtime / "portability_tests")
            for name in runtime_assets:
                destination = runtime / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(workspace / name, destination)
        except OSError as error:
            return policy("G07", "INVALID", "PORTABILITY_CONTRACT_MISSING",
                          compiler=compiler, error=str(error), runs=runs)

        run = execute(
            ["./portability_tests", *run_args], runtime, limits, dict(env_value)
        )
        entry: dict[str, object] = {
            "compiler": compiler,
            "compile": result_facts(compiled),
            "run": result_facts(run),
        }
        runs.append(entry)
        if run.launch_error:
            return policy("G07", "INVALID", "PORTABILITY_RUNTIME_UNAVAILABLE", runs=runs)
        if run.timed_out or run.returncode != 0:
            return policy("G07", "FAIL", "PORTABILITY_FUNCTIONAL_FAIL", runs=runs)
        if run.stdout_truncated or run.stderr_truncated:
            return policy("G07", "FAIL", "TEST_OUTPUT_LIMIT_EXCEEDED", runs=runs)

        stream = run.stdout if result_stream == "stdout" else run.stderr
        matches = list(result_regex.finditer(stream))
        if not matches:
            return policy("G07", "FAIL", "TEST_RECEIPT_MISSING", runs=runs)
        if len(matches) != 1:
            return policy("G07", "FAIL", "TEST_RECEIPT_DUPLICATED",
                          receipt_count=len(matches), runs=runs)
        try:
            passed = int(matches[0].group("passed"))
            total = int(matches[0].group("total"))
        except (TypeError, ValueError):
            return policy("G07", "INVALID", "MALFORMED_TEST_COUNT", runs=runs)
        if total < 1 or passed < 0 or passed > total or total != expected_total:
            return policy("G07", "INVALID", "MALFORMED_TEST_COUNT",
                          tests_passed=passed, tests_total=total,
                          expected_total=expected_total, runs=runs)
        entry.update({
            "tests_passed": passed,
            "tests_total": total,
            "score": passed / total,
        })
        if passed != total:
            return policy("G07", "FAIL", "PORTABILITY_FUNCTIONAL_FAIL", runs=runs)
    return policy("G07", "PASS", "PORTABILITY_PASS", runs=runs)



def _compile_external_candidates(
    workspace: Path, manifest: dict[str, Any], compiler: str, index: int,
    execute: Execute, limits: Limits,
) -> tuple[list[str], list[dict[str, object]], PolicyReceipt | None]:
    build = manifest.get("build", {})
    sources = _strings(build.get("sources"))
    flags = _strings(build.get("flags", []))
    includes = _strings(build.get("include_dirs", ["."]))
    defines = _strings(build.get("defines", []))
    standard = build.get("standard", "c++17")
    if (
        not sources or any(value is None for value in (flags, includes, defines))
        or not isinstance(standard, str) or not standard
        or not _safe_assets(sources)
    ):
        return [], [], policy(
            "G07", "INVALID", "EXTERNAL_ORACLE_PORTABILITY_NOT_READY"
        )
    if (workspace / ".gv2/probe_sources").exists():
        return [], [], policy("G07", "INVALID", "EXTERNAL_PROBE_MATERIALIZATION_PRESENT")
    target = workspace / f".gv2/g07_candidate_objects_{index}"
    try:
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
    except OSError as error:
        return [], [], policy(
            "G07", "INVALID", "EXTERNAL_ORACLE_PORTABILITY_NOT_READY",
            compiler=compiler, error=str(error),
        )

    objects: list[str] = []
    commands: list[dict[str, object]] = []
    for source_index, source in enumerate(sources):
        output = (target / f"source_{source_index}.o").relative_to(workspace).as_posix()
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
                "G07", "INVALID", "PORTABILITY_TOOLCHAIN_UNAVAILABLE",
                compiler=compiler, phase="candidate", compile_commands=commands,
            )
        if result.returncode != 0:
            return [], commands, policy(
                "G07", "FAIL", "PORTABILITY_BUILD_FAIL",
                compiler=compiler, phase="candidate", compile_commands=commands,
            )
        objects.append(output)
    return objects, commands, None


def _verify_external(
    workspace: Path, manifest: dict[str, Any], execute: Execute, limits: Limits,
    trusted_assets: Path | None,
) -> PolicyReceipt:
    compilers = _strings(
        manifest.get("portability", {}).get("compilers", ["g++", "clang++"])
    )
    cleanup_error = _clear_g04_materializations(workspace)
    if cleanup_error:
        return policy(
            "G07", "INVALID", "EXTERNAL_ORACLE_CLEANUP_FAILED",
            error=cleanup_error, runs=[],
        )
    trusted_root = _external_contract_ready(workspace, trusted_assets, manifest)
    if (
        compilers is None or len(compilers) < 2 or trusted_root is None
    ):
        return policy("G07", "INVALID", "EXTERNAL_ORACLE_PORTABILITY_NOT_READY")

    runs: list[dict[str, object]] = []
    for index, compiler in enumerate(compilers):
        cleanup_error = _clear_g04_materializations(workspace)
        if cleanup_error:
            return policy(
                "G07", "INVALID", "EXTERNAL_ORACLE_CLEANUP_FAILED",
                compiler=compiler, error=cleanup_error, runs=runs,
            )

        isolated = copy.deepcopy(manifest)
        isolated.setdefault("build", {})["compiler"] = compiler
        objects, candidate_commands, failed = _compile_external_candidates(
            workspace, isolated, compiler, index, execute, limits
        )
        if failed is not None:
            failed.facts["runs"] = runs
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
                "G07", "INVALID", "EXTERNAL_ORACLE_CLEANUP_FAILED",
                compiler=compiler, error=cleanup_error,
                candidate_compile=candidate_commands, runs=runs,
            )
        if execution_error or functional_receipt is None:
            return policy(
                "G07", "INVALID", "EXTERNAL_ORACLE_PORTABILITY_NOT_READY",
                compiler=compiler, error=execution_error,
                candidate_compile=candidate_commands, runs=runs,
            )

        entry: dict[str, object] = {
            "compiler": compiler,
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
        runs.append(entry)
        if functional_receipt.status == "INVALID":
            return policy(
                "G07", "INVALID", "EXTERNAL_ORACLE_PORTABILITY_NOT_READY", runs=runs
            )
        if functional_receipt.status != "PASS":
            return policy("G07", "FAIL", "PORTABILITY_FUNCTIONAL_FAIL", runs=runs)
        if not entry["authoritative"]:
            return policy(
                "G07", "INVALID", "EXTERNAL_ORACLE_PORTABILITY_NOT_READY", runs=runs
            )
        entry.update({
            "tests_passed": functional_receipt.facts.get("tests_passed"),
            "tests_total": functional_receipt.facts.get("tests_total"),
            "score": functional_receipt.facts.get("score"),
        })
    return policy("G07", "PASS", "PORTABILITY_PASS", runs=runs, authoritative=True)


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
    return policy("G07", "INVALID", "PORTABILITY_MODE_NOT_READY", mode=mode)
