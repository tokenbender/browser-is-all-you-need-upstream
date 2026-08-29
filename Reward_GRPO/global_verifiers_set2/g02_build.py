"""G02: compile candidate translation units once and classify diagnostics."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from receipt import PolicyReceipt, policy
from sandbox import CommandResult, Limits, executable_missing, result_facts

Execute = Callable[[list[str], Path, Limits, dict[str, str] | None], CommandResult]


def _invalid(result: CommandResult) -> str | None:
    if result.launch_error_kind == "DOCKER_EXECUTABLE_MISSING":
        return "BUILD_EXECUTOR_UNAVAILABLE"
    if executable_missing(result) or result.returncode == 127:
        return "COMPILER_UNAVAILABLE"
    if result.launch_error:
        return "BUILD_EXECUTOR_UNAVAILABLE"
    if result.timed_out:
        return "VERIFIER_TIMEOUT"
    return None


def verify(workspace: Path, artifacts: Path, manifest: dict[str, Any], execute: Execute,
           limits: Limits) -> tuple[PolicyReceipt, list[str]]:
    build = manifest.get("build", {})
    compiler = str(build.get("compiler", "g++"))
    standard = str(build.get("standard", "c++17"))
    flags = build.get("flags", [])
    sources = build.get("sources", [])
    includes = build.get("include_dirs", ["."])
    if not all(isinstance(value, str) for value in [*flags, *sources, *includes]) or not sources:
        return policy("G02", "INVALID", "INVALID_BUILD_CONTRACT"), []
    artifacts.mkdir(parents=True, exist_ok=True)
    objects: list[str] = []
    receipts: list[dict[str, object]] = []
    for index, source in enumerate(sources):
        obj = f".gv2/objects/candidate_{index}.o"
        (workspace / ".gv2/objects").mkdir(parents=True, exist_ok=True)
        command = [compiler, f"-std={standard}", *flags,
                   *(f"-I{value}" for value in includes), "-c", source, "-o", obj]
        result = execute(command, workspace, limits, None)
        receipts.append(result_facts(result))
        invalid = _invalid(result)
        if invalid:
            return policy("G02", "INVALID", invalid, commands=receipts), []
        if result.returncode != 0:
            warning_as_error = re.search(
                r"\[-Werror(?:=|\])|all warnings being treated as errors", result.stderr
            )
            reason = "WARNING_FAIL" if warning_as_error else "COMPILE_FAIL"
            return policy("G02", "FAIL", reason, commands=receipts), []
        objects.append(obj)
    return policy("G02", "PASS", "OBJECTS_COMPILED", commands=receipts,
                  object_files=objects), objects
