
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable

TASK_ID = "local-aider-cpp/sublist"
SOURCE_REVISION = "7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f"
EDITABLE = ("sublist.cpp", "sublist.h")
FIXED = {
    ".docs/instructions.md": "87fec6e1b999116669e838100fe3e1b3880317b667b8948f6a4f85de07a81288",
    "sublist_test.cpp": "7120a4a2fa383db1f2f0184c5cb58c46960b39458d37bb3965dfb382ed4f0d00",
    "CMakeLists.txt": "53d531120e650972adf19a2a42aa2d5bc716c93700ffac74c1c2868fdce633ff",
    "test/catch.hpp": "681e7505a50887c9085539e5135794fc8f66d8e5de28eadf13a30978627b0f47",
    "test/tests-main.cpp": "5847fda35c1320d94f8d088aaf34229d689f66f1da235f885cbb28c8f17e4260",
}
MANIFEST_SHA256 = "d45dc8c37c869f3c28248fe6aa3f4db2bf616cafa2e37b2a38b337ced4e1d0cf"
PARSER_SHA256 = "82558ec14d4ed56ff88b170e36b196a15654e08b624857daf755e530641b3705"
STRICT = ("-std=c++17", "-Wall", "-Wextra", "-Wpedantic", "-Werror")
POLICY_NAMES = {
    1: "build_stage_link_completion",
    2: "warning_clean_candidate_build",
    3: "exact_public_api_caller_contract",
    4: "header_include_dependency_ownership",
    5: "official_functional_classification",
    6: "contiguous_sublist_relational_semantics",
    7: "feedback_repair_two_turn_convergence",
    8: "response_context_harness_integrity",
    9: "memory_undefined_behavior_safety",
    10: "cross_compiler_portability",
}


@dataclass
class KernelResult:
    kernel_id: str
    kernel: int | None
    verdict: str
    summary: str
    facts: dict[str, Any] = field(default_factory=dict)
    command_ids: list[str] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)


@dataclass
class Context:
    policy: int
    output_dir: Path
    verifier_path: Path
    candidate_dir: Path | None = None
    bundle_dir: Path | None = None
    manifest_path: Path | None = None
    compiler: str | None = None
    source_hash_before: dict[str, str] = field(default_factory=dict)
    fixed_hashes: dict[str, str] = field(default_factory=dict)
    commands: list[dict[str, Any]] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)
    preflight_error: str | None = None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pass_result(kernel_id: str, summary: str, **facts: Any) -> KernelResult:
    return KernelResult(kernel_id, 1, "pass", summary, facts)


def fail_result(kernel_id: str, summary: str, **facts: Any) -> KernelResult:
    return KernelResult(kernel_id, -1, "fail", summary, facts)


def invalid_result(kernel_id: str, summary: str, **facts: Any) -> KernelResult:
    return KernelResult(kernel_id, None, "INVALID", summary, facts)


def excluded_result(kernel_id: str, reason: str) -> KernelResult:
    return KernelResult(kernel_id, None, "excluded", reason, {"reason": reason})


def path_has_symlink(path: Path) -> bool:
    absolute = path.absolute()
    cursor = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        cursor /= part
        if cursor.is_symlink():
            return True
    return False


def safe_relative(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise ValueError(f"unsafe relative path: {relative}")
    raw = root.joinpath(*pure.parts)
    cursor = raw
    while cursor != root:
        if cursor.is_symlink():
            raise ValueError(f"symlink is not allowed: {relative}")
        cursor = cursor.parent
    resolved_root = root.resolve()
    resolved = raw.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ValueError(f"path escapes root: {relative}")
    return raw


def write_text(ctx: Context, relative: str, content: str) -> Path:
    path = safe_relative(ctx.output_dir, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def run_command(
    ctx: Context,
    label: str,
    args: list[str],
    cwd: Path | None = None,
    timeout: int = 60,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    command_id = f"cmd-{len(ctx.commands) + 1:03d}-{label}"
    stdout_path = ctx.output_dir / "logs" / f"{command_id}.stdout.txt"
    stderr_path = ctx.output_dir / "logs" / f"{command_id}.stderr.txt"
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    record: dict[str, Any] = {
        "id": command_id,
        "argv": args,
        "cwd": str((cwd or ctx.output_dir).resolve()),
        "timeout_seconds": timeout,
        "stdout": str(stdout_path.relative_to(ctx.output_dir)),
        "stderr": str(stderr_path.relative_to(ctx.output_dir)),
    }
    try:
        completed = subprocess.run(
            args,
            cwd=cwd or ctx.output_dir,
            text=True,
            capture_output=True,
            timeout=timeout,
            env=env,
            check=False,
        )
        stdout_path.write_text(completed.stdout, encoding="utf-8", errors="replace")
        stderr_path.write_text(completed.stderr, encoding="utf-8", errors="replace")
        record.update(
            returncode=completed.returncode,
            timed_out=False,
            start_error=None,
            duration_seconds=round(time.monotonic() - started, 6),
        )
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout.decode(errors="replace") if isinstance(error.stdout, bytes) else error.stdout or ""
        stderr = error.stderr.decode(errors="replace") if isinstance(error.stderr, bytes) else error.stderr or ""
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8")
        record.update(returncode=None, timed_out=True, start_error=None, duration_seconds=round(time.monotonic() - started, 6))
    except OSError as error:
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text(str(error), encoding="utf-8")
        record.update(returncode=None, timed_out=False, start_error=str(error), duration_seconds=round(time.monotonic() - started, 6))
    record["stdout_sha256"] = sha256(stdout_path)
    record["stderr_sha256"] = sha256(stderr_path)
    ctx.commands.append(record)
    return record


def command_verdict(kernel_id: str, record: dict[str, Any], success: str, failure: str) -> KernelResult:
    if record["start_error"]:
        result = invalid_result(kernel_id, f"process could not start: {record['start_error']}")
    elif record["timed_out"]:
        result = fail_result(kernel_id, f"candidate command timed out: {failure}")
    elif record["returncode"] != 0:
        result = fail_result(kernel_id, failure, returncode=record["returncode"])
    else:
        result = pass_result(kernel_id, success)
    result.command_ids.append(record["id"])
    return result


def repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def candidate_preflight(ctx: Context) -> None:
    assert ctx.candidate_dir is not None
    candidate = ctx.candidate_dir
    if not candidate.is_dir() or candidate.is_symlink():
        raise ValueError("candidate directory is missing or is a symlink")
    for name in EDITABLE:
        path = safe_relative(candidate, name)
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"candidate file is missing, non-regular, or symlinked: {name}")
        ctx.source_hash_before[name] = sha256(path)
    for name, expected in FIXED.items():
        path = safe_relative(candidate, name)
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"fixed file is missing, non-regular, or symlinked: {name}")
        observed = sha256(path)
        ctx.fixed_hashes[name] = observed
        if observed != expected:
            raise ValueError(f"fixed-file hash mismatch: {name}")
    manifest = ctx.manifest_path
    if manifest is None or not manifest.is_file() or manifest.is_symlink():
        raise ValueError("task manifest is unavailable")
    if sha256(manifest) != MANIFEST_SHA256:
        raise ValueError("task manifest hash mismatch")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if data.get("task_id") != TASK_ID or data.get("source_revision") != SOURCE_REVISION or data.get("editable_files") != list(EDITABLE):
        raise ValueError("task manifest identity mismatch")
    compiler_name = "clang++" if ctx.policy == 10 else os.environ.get("SUBLIST_CXX", "g++")
    ctx.compiler = shutil.which(compiler_name)
    if ctx.compiler is None:
        raise ValueError(f"required compiler is unavailable: {compiler_name}")


def bundle_preflight(ctx: Context) -> None:
    assert ctx.bundle_dir is not None
    if not ctx.bundle_dir.is_dir() or ctx.bundle_dir.is_symlink():
        raise ValueError("bundle directory is missing or symlinked")
    manifest = safe_relative(ctx.bundle_dir, "bundle_manifest.json")
    if not manifest.is_file() or manifest.is_symlink():
        raise ValueError("bundle_manifest.json is missing")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or data.get("task_id") != TASK_ID:
        raise ValueError("bundle identity mismatch")
    if not isinstance(data.get("artifacts"), dict):
        raise ValueError("bundle artifacts map is missing")
    ctx.state["bundle_manifest"] = data
    ctx.state["bundle_manifest_sha256"] = sha256(manifest)


def artifact(ctx: Context, name: str, optional: bool = False) -> Path | None:
    assert ctx.bundle_dir is not None
    reference = ctx.state["bundle_manifest"]["artifacts"].get(name)
    if reference is None and optional:
        return None
    if not isinstance(reference, dict) or not isinstance(reference.get("path"), str) or not re.fullmatch(r"[0-9a-f]{64}", str(reference.get("sha256", ""))):
        raise ValueError(f"bundle artifact reference is malformed: {name}")
    path = safe_relative(ctx.bundle_dir, reference["path"])
    if not path.is_file() or path.is_symlink() or sha256(path) != reference["sha256"]:
        raise ValueError(f"bundle artifact is missing or hash-mismatched: {name}")
    return path


def json_artifact(ctx: Context, name: str, optional: bool = False) -> dict[str, Any] | None:
    path = artifact(ctx, name, optional)
    if path is None:
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON artifact is not an object: {name}")
    return value


def compile_args(ctx: Context, source: Path, output: Path, flags: tuple[str, ...] = STRICT, compile_only: bool = False) -> list[str]:
    assert ctx.compiler is not None and ctx.candidate_dir is not None
    args = [ctx.compiler, *flags, "-I", str(ctx.candidate_dir), str(source)]
    if not compile_only and source.resolve() != (ctx.candidate_dir / "sublist.cpp").resolve():
        args.append(str(ctx.candidate_dir / "sublist.cpp"))
    if compile_only:
        args.extend(["-c", "-o", str(output)])
    else:
        args.extend(["-o", str(output)])
    return args


def run_probe(
    ctx: Context,
    kernel_id: str,
    label: str,
    source: str,
    flags: tuple[str, ...] = STRICT,
    run: bool = True,
    timeout: int = 60,
    env: dict[str, str] | None = None,
) -> KernelResult:
    source_path = write_text(ctx, f"probes/{label}.cpp", source)
    executable = ctx.output_dir / "artifacts" / label
    executable.parent.mkdir(parents=True, exist_ok=True)
    compile_record = run_command(ctx, f"{label}-compile", compile_args(ctx, source_path, executable, flags), timeout=timeout)
    result = command_verdict(kernel_id, compile_record, f"{label} compiled", f"{label} did not compile")
    if result.kernel != 1 or not run:
        return result
    run_record = run_command(ctx, f"{label}-run", [str(executable)], timeout=timeout, env=env)
    result = command_verdict(kernel_id, run_record, f"{label} passed", f"{label} failed")
    result.command_ids.insert(0, compile_record["id"])
    if executable.is_file():
        result.artifacts[str(executable.relative_to(ctx.output_dir))] = sha256(executable)
    return result


def official_build(ctx: Context, label: str, flags: tuple[str, ...] = STRICT) -> tuple[KernelResult, Path | None]:
    assert ctx.compiler is not None and ctx.candidate_dir is not None
    executable = ctx.output_dir / "artifacts" / label
    executable.parent.mkdir(parents=True, exist_ok=True)
    args = [
        ctx.compiler,
        *flags,
        "-DEXERCISM_RUN_ALL_TESTS",
        "-I",
        str(ctx.candidate_dir),
        str(ctx.candidate_dir / "sublist_test.cpp"),
        str(ctx.candidate_dir / "test/tests-main.cpp"),
        str(ctx.candidate_dir / "sublist.cpp"),
        "-o",
        str(executable),
    ]
    record = run_command(ctx, f"{label}-compile", args, timeout=120)
    result = command_verdict("", record, "official executable compiled", "official executable did not compile")
    if result.kernel == 1:
        result.artifacts[str(executable.relative_to(ctx.output_dir))] = sha256(executable)
        return result, executable
    return result, None


def execute_official(ctx: Context, kernel_id: str, label: str, flags: tuple[str, ...] = STRICT) -> KernelResult:
    built, executable = official_build(ctx, label, flags)
    built.kernel_id = kernel_id
    if built.kernel != 1 or executable is None:
        return built
    record = run_command(ctx, f"{label}-run", [str(executable)], timeout=120)
    result = command_verdict(kernel_id, record, "all 18 official tests passed", "official tests failed")
    result.command_ids = built.command_ids + result.command_ids
    result.artifacts.update(built.artifacts)
    return result


def enum_probe(body: str, includes: str = "") -> str:
    body = body.replace("; if", ";\nif")
    return f'''#include "sublist.h"\n#include <vector>\n{includes}\nusing L = sublist::List_comparison;\nint main() {{\n{body}\nreturn 0;\n}}\n'''


def blocked(ctx: Context, kernel_id: str, dependencies: list[str]) -> KernelResult:
    invalid = any(ctx.state.get(item) == "INVALID" for item in dependencies)
    if invalid:
        return invalid_result(kernel_id, "blocked by an invalid prerequisite", blocked_by=dependencies, status="blocked_infrastructure")
    return fail_result(kernel_id, "blocked by a candidate-caused prerequisite failure", blocked_by=dependencies, status="blocked_candidate")


def _k1a(ctx: Context) -> KernelResult:
    record = run_command(ctx, "primary-compiler-version", [str(ctx.compiler), "--version"])
    return command_verdict("1a", record, "primary compiler and pinned fixtures are usable", "primary compiler identity failed")


def _k1b(ctx: Context) -> KernelResult:
    assert ctx.candidate_dir is not None
    output = ctx.output_dir / "artifacts/sublist.o"
    output.parent.mkdir(parents=True, exist_ok=True)
    record = run_command(ctx, "candidate-tu", compile_args(ctx, ctx.candidate_dir / "sublist.cpp", output, ("-std=c++17",), True))
    result = command_verdict("1b", record, "candidate translation unit compiled", "candidate translation unit failed")
    if result.kernel == 1:
        result.artifacts["artifacts/sublist.o"] = sha256(output)
    ctx.state["1b"] = result.verdict
    return result


def _k1c(ctx: Context) -> KernelResult:
    assert ctx.candidate_dir is not None and ctx.compiler is not None
    official_object = ctx.output_dir / "artifacts/official-caller.o"
    external_object = ctx.output_dir / "artifacts/external-caller.o"
    source = write_text(ctx, "probes/external-caller.cpp", enum_probe("if (sublist::sublist({}, {}) != L::equal) return 1;"))
    records = [
        run_command(ctx, "official-caller", [ctx.compiler, "-std=c++17", "-DEXERCISM_RUN_ALL_TESTS", "-I", str(ctx.candidate_dir), "-c", str(ctx.candidate_dir / "sublist_test.cpp"), "-o", str(official_object)], timeout=120),
        run_command(ctx, "external-caller", [ctx.compiler, "-std=c++17", "-I", str(ctx.candidate_dir), "-c", str(source), "-o", str(external_object)]),
    ]
    for record in records:
        result = command_verdict("1c", record, "caller compiled", "caller compilation failed")
        if result.kernel != 1:
            result.command_ids = [item["id"] for item in records]
            ctx.state["1c"] = result.verdict
            return result
    result = pass_result("1c", "official and external callers compiled")
    result.command_ids = [item["id"] for item in records]
    result.artifacts = {"artifacts/official-caller.o": sha256(official_object), "artifacts/external-caller.o": sha256(external_object)}
    ctx.state["1c"] = result.verdict
    return result


def _k1d(ctx: Context) -> KernelResult:
    if ctx.state.get("1b") != "pass" or ctx.state.get("1c") != "pass":
        return blocked(ctx, "1d", ["1b", "1c"])
    built, executable = official_build(ctx, "linked-sublist", ("-std=c++17",))
    built.kernel_id = "1d"
    if built.kernel == 1 and executable is not None:
        built.summary = "official executable linked"
    return built


def _k1e(ctx: Context) -> KernelResult:
    cmake = shutil.which("cmake")
    if cmake is None:
        return invalid_result("1e", "CMake is unavailable")
    assert ctx.candidate_dir is not None
    staged = ctx.output_dir / "staging/sublist"
    shutil.copytree(ctx.candidate_dir, staged)
    build = ctx.output_dir / "artifacts/cmake-build"
    configure = run_command(ctx, "cmake-configure", [cmake, "-S", str(staged), "-B", str(build), "-DEXERCISM_RUN_ALL_TESTS=ON"], timeout=120)
    result = command_verdict("1e", configure, "CMake configured", "CMake configuration failed")
    if result.kernel != 1:
        return result
    build_record = run_command(ctx, "cmake-test-target", [cmake, "--build", str(build), "--target", "test_sublist"], timeout=180)
    result = command_verdict("1e", build_record, "clean CMake test target passed", "clean CMake build or tests failed")
    result.command_ids.insert(0, configure["id"])
    return result


def _warning_family(ctx: Context, kernel_id: str, label: str, flags: tuple[str, ...], full: bool = False) -> KernelResult:
    if full:
        return execute_official(ctx, kernel_id, f"warning-{label}", flags)
    assert ctx.candidate_dir is not None and ctx.compiler is not None
    (ctx.output_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    header = write_text(ctx, f"probes/warning-{label}-header.cpp", '#include "sublist.h"\nint main() { return 0; }\n')
    records: list[dict[str, Any]] = []
    for name, source in (("implementation", ctx.candidate_dir / "sublist.cpp"), ("header", header)):
        output = ctx.output_dir / "artifacts" / f"warning-{label}-{name}.o"
        records.append(run_command(ctx, f"warning-{label}-{name}", [ctx.compiler, *flags, "-I", str(ctx.candidate_dir), "-c", str(source), "-o", str(output)]))
    for record in records:
        result = command_verdict(kernel_id, record, f"{label} clean", f"candidate emitted or triggered a {label} diagnostic")
        if result.kernel != 1:
            result.command_ids = [item["id"] for item in records]
            return result
    result = pass_result(kernel_id, f"candidate and header consumer are {label} clean")
    result.command_ids = [item["id"] for item in records]
    return result


def _k2a(ctx: Context) -> KernelResult:
    return _warning_family(ctx, "2a", "Wall", ("-std=c++17", "-Wall", "-Werror"))


def _k2b(ctx: Context) -> KernelResult:
    return _warning_family(ctx, "2b", "Wextra", ("-std=c++17", "-Wextra", "-Werror"))


def _k2c(ctx: Context) -> KernelResult:
    return _warning_family(ctx, "2c", "Wpedantic", ("-std=c++17", "-Wpedantic", "-Werror"))


def _k2d(ctx: Context) -> KernelResult:
    return _warning_family(ctx, "2d", "complete-Werror", STRICT, True)


def _k3a(ctx: Context) -> KernelResult:
    return run_probe(ctx, "3a", "api-enum-type", enum_probe("static_assert(std::is_enum_v<L>); static_assert(!std::is_convertible_v<L, int>);", "#include <type_traits>"))


def _k3b(ctx: Context) -> KernelResult:
    positive = run_probe(ctx, "3b", "api-lowercase-enumerators", enum_probe("auto a=L::equal; auto b=L::sublist; auto c=L::superlist; auto d=L::unequal; (void)a;(void)b;(void)c;(void)d;"), run=False)
    if positive.kernel != 1:
        return positive
    command_ids = list(positive.command_ids)
    for index, name in enumerate(("EQUAL", "SUBLIST", "SUPERLIST", "UNEQUAL", "NOT_EQUAL")):
        source = write_text(ctx, f"probes/api-forbidden-{index}.cpp", enum_probe(f"auto value=L::{name}; (void)value;"))
        output = ctx.output_dir / "artifacts" / f"api-forbidden-{index}.o"
        record = run_command(ctx, f"api-forbidden-{name}", compile_args(ctx, source, output, ("-std=c++17",), True))
        command_ids.append(record["id"])
        if record["start_error"] or record["timed_out"]:
            result = invalid_result("3b", "negative API probe could not complete")
            result.command_ids = command_ids
            return result
        if record["returncode"] == 0:
            result = fail_result("3b", f"forbidden uppercase enumerator is publicly available: {name}")
            result.command_ids = command_ids
            return result
    result = pass_result("3b", "required lowercase enumerators exist and known wrong aliases are absent")
    result.command_ids = command_ids
    return result


def _k3c(ctx: Context) -> KernelResult:
    source = enum_probe("using Expected=L (*)(const std::vector<int>&, const std::vector<int>&); static_assert(std::is_same_v<decltype(&sublist::sublist), Expected>);", "#include <type_traits>")
    return run_probe(ctx, "3c", "api-exact-signature", source)


def _k3d(ctx: Context) -> KernelResult:
    return run_probe(ctx, "3d", "api-braced-calls", enum_probe("(void)sublist::sublist({}, {}); (void)sublist::sublist({1}, {1,2});"))


def _k3e(ctx: Context) -> KernelResult:
    body = "if (L::equal==L::sublist || L::equal==L::superlist || L::equal==L::unequal || L::sublist==L::superlist || L::sublist==L::unequal || L::superlist==L::unequal) return 1; if (sublist::sublist({}, {}) != L::equal) return 2;"
    return run_probe(ctx, "3e", "api-distinct-smoke", enum_probe(body))


def _k4a(ctx: Context) -> KernelResult:
    assert ctx.candidate_dir is not None
    text = (ctx.candidate_dir / "sublist.h").read_text(encoding="utf-8")
    if re.search(r"^\s*#\s*include\s*<vector>", text, re.MULTILINE):
        return pass_result("4a", "sublist.h directly owns its vector dependency")
    return fail_result("4a", "sublist.h does not directly include <vector>")


def _k4b(ctx: Context) -> KernelResult:
    return run_probe(ctx, "4b", "header-self-contained", '#include "sublist.h"\nint main() { return 0; }\n', run=False)


def _k4c(ctx: Context) -> KernelResult:
    assert ctx.candidate_dir is not None and ctx.compiler is not None
    source_text = "\n".join((ctx.candidate_dir / name).read_text(encoding="utf-8") for name in EDITABLE)
    if re.search(r"(?:catch\.hpp|sublist_test\.cpp|tests-main\.cpp)", source_text, re.IGNORECASE):
        return fail_result("4c", "candidate depends on test or Catch source")
    if re.search(r'^\s*#\s*include\s*[\"](?:/|\.\./)', source_text, re.MULTILINE):
        return fail_result("4c", "candidate contains an unsafe project include")
    depfile = ctx.output_dir / "artifacts/sublist.d"
    output = ctx.output_dir / "artifacts/dependency-check.o"
    record = run_command(ctx, "dependency-graph", [ctx.compiler, "-std=c++17", "-MMD", "-MF", str(depfile), "-I", str(ctx.candidate_dir), "-c", str(ctx.candidate_dir / "sublist.cpp"), "-o", str(output)])
    result = command_verdict("4c", record, "candidate dependency graph is isolated", "candidate dependency graph failed")
    if result.kernel != 1:
        return result
    if not depfile.is_file() or depfile.is_symlink():
        evidence = invalid_result("4c", "compiler did not produce a trustworthy dependency file")
        evidence.command_ids = list(result.command_ids)
        return evidence
    try:
        dependency_text = depfile.read_text(encoding="utf-8").replace("\\\n", " ")
        _, separator, payload = dependency_text.partition(":")
        if not separator:
            raise ValueError("dependency file has no target separator")
        dependencies = shlex.split(payload)
    except (OSError, UnicodeError, ValueError) as error:
        evidence = invalid_result("4c", f"dependency file is malformed: {error}")
        evidence.command_ids = list(result.command_ids)
        return evidence
    candidate_root = ctx.candidate_dir.resolve()
    extras: list[str] = []
    for dependency in dependencies:
        path = Path(dependency)
        resolved = (path if path.is_absolute() else ctx.output_dir / path).resolve()
        try:
            relative = resolved.relative_to(candidate_root).as_posix()
        except ValueError:
            continue
        if relative not in EDITABLE:
            extras.append(relative)
    if extras:
        failure = fail_result("4c", "candidate depends on unauthorized project files", extra_dependencies=sorted(set(extras)))
        failure.command_ids = list(result.command_ids)
        failure.artifacts["artifacts/sublist.d"] = sha256(depfile)
        return failure
    result.artifacts["artifacts/sublist.d"] = sha256(depfile)
    result.facts["candidate_dependencies"] = sorted(EDITABLE)
    return result


def _k4d(ctx: Context) -> KernelResult:
    if ctx.fixed_hashes == FIXED:
        return pass_result("4d", "all fixed dependencies match pinned hashes", fixed_hashes=ctx.fixed_hashes)
    return invalid_result("4d", "fixed dependencies are incomplete or changed", fixed_hashes=ctx.fixed_hashes)


def _k4e(ctx: Context) -> KernelResult:
    assert ctx.candidate_dir is not None
    staged = ctx.output_dir / "staging/empty-rebuild"
    for name in (*EDITABLE, *FIXED.keys()):
        source = safe_relative(ctx.candidate_dir, name)
        target = staged / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    original = ctx.candidate_dir
    ctx.candidate_dir = staged
    try:
        result = execute_official(ctx, "4e", "empty-workspace-rebuild")
    finally:
        ctx.candidate_dir = original
    return result


def _k5a(ctx: Context) -> KernelResult:
    assert ctx.candidate_dir is not None
    inventory = len(re.findall(r"\bTEST_CASE\s*\(", (ctx.candidate_dir / "sublist_test.cpp").read_text(encoding="utf-8")))
    if inventory != 18:
        return invalid_result("5a", "authenticated official test inventory is not 18", observed=inventory)
    result = execute_official(ctx, "5a", "official-18-tests")
    if result.kernel == 1:
        result.facts["test_cases"] = 18
    return result


def _k5b(ctx: Context) -> KernelResult:
    body = "if(sublist::sublist({}, {})!=L::equal)return 1; if(sublist::sublist({}, {1,2,3})!=L::sublist)return 2; if(sublist::sublist({1,2,3}, {})!=L::superlist)return 3; if(sublist::sublist({1,2,3}, {1,2,3})!=L::equal)return 4;"
    return run_probe(ctx, "5b", "functional-equality-empty", enum_probe(body))


def _k5c(ctx: Context) -> KernelResult:
    body = "if(sublist::sublist({0,1,2},{0,1,2,3,4,5})!=L::sublist)return 1; if(sublist::sublist({2,3,4},{0,1,2,3,4,5})!=L::sublist)return 2; if(sublist::sublist({3,4,5},{0,1,2,3,4,5})!=L::sublist)return 3; if(sublist::sublist({1,2,5},{0,1,2,3,1,2,5,6})!=L::sublist)return 4; if(sublist::sublist({1,1,2},{0,1,1,1,2,1,2})!=L::sublist)return 5;"
    return run_probe(ctx, "5c", "functional-sublist-positions", enum_probe(body))


def _k5d(ctx: Context) -> KernelResult:
    body = "if(sublist::sublist({0,1,2,3,4,5},{0,1,2})!=L::superlist)return 1; if(sublist::sublist({0,1,2,3,4,5},{2,3})!=L::superlist)return 2; if(sublist::sublist({0,1,2,3,4,5},{3,4,5})!=L::superlist)return 3;"
    return run_probe(ctx, "5d", "functional-superlist-positions", enum_probe(body))


def _k5e(ctx: Context) -> KernelResult:
    body = "if(sublist::sublist({1,3},{1,2,3})!=L::unequal)return 1; if(sublist::sublist({1,2,3},{1,3})!=L::unequal)return 2; if(sublist::sublist({1,2},{1,22})!=L::unequal)return 3; if(sublist::sublist({1,2,3},{3,2,1})!=L::unequal)return 4; if(sublist::sublist({1,0,1},{10,1})!=L::unequal)return 5;"
    return run_probe(ctx, "5e", "functional-unequal-values", enum_probe(body))


def _k5f(ctx: Context) -> KernelResult:
    built, executable = official_build(ctx, "official-repeat")
    built.kernel_id = "5f"
    if built.kernel != 1 or executable is None:
        return built
    command_ids = list(built.command_ids)
    for index in range(5):
        record = run_command(ctx, f"official-repeat-{index + 1}", [str(executable)], timeout=120)
        command_ids.append(record["id"])
        result = command_verdict("5f", record, "repeat passed", "official repetition failed")
        if result.kernel != 1:
            result.command_ids = command_ids
            return result
    result = pass_result("5f", "five fresh official executions passed deterministically", repetitions=5)
    result.command_ids = command_ids
    return result


def _k6a(ctx: Context) -> KernelResult:
    source = enum_probe(r'''
std::vector<std::vector<int>> lists;
std::vector<int> current;
auto generate = [&](auto&& self, int depth) -> void {
    lists.push_back(current);
    if (depth == 4) return;
    for (int value : {-1,0,1,2}) { current.push_back(value); self(self, depth + 1); current.pop_back(); }
};
generate(generate, 0);
auto contains = [](const std::vector<int>& haystack, const std::vector<int>& needle) {
    if (needle.size() > haystack.size()) return false;
    for (std::size_t start=0; start+needle.size()<=haystack.size(); ++start) {
        bool same=true;
        for (std::size_t i=0; i<needle.size(); ++i) if (haystack[start+i]!=needle[i]) { same=false; break; }
        if (same) return true;
    }
    return false;
};
for (const auto& a : lists) for (const auto& b : lists) {
    L expected = a==b ? L::equal : contains(b,a) ? L::sublist : contains(a,b) ? L::superlist : L::unequal;
    if (sublist::sublist(a,b) != expected) return 1;
}
if (lists.size()!=341) return 2;
''')
    result = run_probe(ctx, "6a", "semantic-exhaustive-oracle", source, timeout=120)
    if result.kernel == 1:
        result.facts.update(lists=341, ordered_pairs=116281, domain=[-1, 0, 1, 2], maximum_length=4)
    return result


def _k6b(ctx: Context) -> KernelResult:
    body = "if(sublist::sublist({1,3},{1,2,3})!=L::unequal)return 1; if(sublist::sublist({1,2,3},{1,3,2})!=L::unequal)return 2; if(sublist::sublist({1,2},{1,22})!=L::unequal)return 3; if(sublist::sublist({1,0,1},{10,1})!=L::unequal)return 4; if(sublist::sublist({-1,0},{2,-1,0,2})!=L::sublist)return 5;"
    return run_probe(ctx, "6b", "semantic-contiguity-order-identity", enum_probe(body))


def _k6c(ctx: Context) -> KernelResult:
    body = "if(sublist::sublist({1,2,5},{0,1,2,3,1,2,5,6})!=L::sublist)return 1; if(sublist::sublist({1,1,2},{0,1,1,1,2,1,2})!=L::sublist)return 2; if(sublist::sublist({1,1,1,2},{1,1,1,1,2})!=L::sublist)return 3; if(sublist::sublist({1,2,1,2,3},{1,2,1,2,1,2,3})!=L::sublist)return 4;"
    return run_probe(ctx, "6c", "semantic-false-start-overlap", enum_probe(body))


def _k6d(ctx: Context) -> KernelResult:
    source = enum_probe(r'''
std::vector<std::pair<std::vector<int>,std::vector<int>>> cases={{{},{}},{{},{1}},{{1},{1,2}},{{1,2},{1}},{{1,3},{1,2,3}},{{1,2},{3,4}}};
for (const auto& item: cases) {
    L ab=sublist::sublist(item.first,item.second), ba=sublist::sublist(item.second,item.first);
    if (ab==L::equal && ba!=L::equal) return 1;
    if (ab==L::unequal && ba!=L::unequal) return 2;
    if (ab==L::sublist && ba!=L::superlist) return 3;
    if (ab==L::superlist && ba!=L::sublist) return 4;
}
''', "#include <utility>")
    return run_probe(ctx, "6d", "semantic-swap-relations", source)


def _k6e(ctx: Context) -> KernelResult:
    source = enum_probe(r'''
std::vector<int> a={1,2,5}, b={0,1,2,3,1,2,5,6};
const auto acopy=a, bcopy=b;
const L first=sublist::sublist(a,b);
for(int i=0;i<100;++i) if(sublist::sublist(a,b)!=first)return 1;
if(a!=acopy || b!=bcopy)return 2;
''')
    return run_probe(ctx, "6e", "semantic-input-preservation", source)


def evaluation_passed(value: dict[str, Any]) -> bool:
    status = str(value.get("status", value.get("verdict", ""))).lower()
    passed = value.get("tests_passed", value.get("passed_tests"))
    total = value.get("tests_total", value.get("total_tests"))
    failed = value.get("tests_failed", value.get("failed_tests"))
    return status in {"pass", "passed", "success"} and passed == 18 and total == 18 and failed == 0


def _turn_one(ctx: Context) -> tuple[dict[str, Any], dict[str, Any]]:
    parser = json_artifact(ctx, "turn_1_parser_receipt")
    evaluation = json_artifact(ctx, "turn_1_evaluation_receipt")
    assert parser is not None and evaluation is not None
    ctx.state["turn_1_passed"] = evaluation_passed(evaluation)
    return parser, evaluation


def _k7a(ctx: Context) -> KernelResult:
    try:
        response = artifact(ctx, "turn_1_response")
        parser, evaluation = _turn_one(ctx)
    except (ValueError, OSError, UnicodeError, json.JSONDecodeError) as error:
        return invalid_result("7a", str(error))
    assert response is not None
    if not response.read_text(encoding="utf-8").strip():
        return fail_result("7a", "turn-one response is empty")
    healthy = parser.get("status") in {"pass", "passed", "success"} and parser.get("format_valid", True) is True
    exhausted = bool(parser.get("context_exhausted", False) or parser.get("truncated", False) or evaluation.get("context_exhausted", False))
    if not healthy or exhausted:
        return fail_result("7a", "turn-one response is malformed, truncated, or context-exhausted", parser=parser)
    return pass_result("7a", "turn-one response evidence is healthy")


def _k7b(ctx: Context) -> KernelResult:
    if ctx.state.get("turn_1_passed"):
        return excluded_result("7b", "repair_not_required")
    try:
        generated = artifact(ctx, "feedback_generated")
        delivered = artifact(ctx, "feedback_delivered")
    except (ValueError, OSError) as error:
        return invalid_result("7b", str(error))
    assert generated is not None and delivered is not None
    if generated.stat().st_size == 0:
        return fail_result("7b", "generated feedback is empty")
    if generated.read_bytes() != delivered.read_bytes():
        return fail_result("7b", "generated and delivered feedback differ")
    return pass_result("7b", "generated feedback was delivered byte-for-byte", feedback_sha256=sha256(generated))


def _k7c(ctx: Context) -> KernelResult:
    if ctx.state.get("turn_1_passed"):
        return excluded_result("7c", "repair_not_required")
    try:
        diff = json_artifact(ctx, "turn_2_diff")
        artifact(ctx, "turn_2_response")
        artifact(ctx, "turn_2_parser_receipt")
        artifact(ctx, "turn_1_source_snapshot")
        artifact(ctx, "turn_2_source_snapshot")
    except (ValueError, OSError, json.JSONDecodeError) as error:
        return invalid_result("7c", str(error))
    assert diff is not None
    changed = diff.get("changed_files")
    if not isinstance(changed, list) or not changed or any(name not in EDITABLE for name in changed):
        return fail_result("7c", "turn-two repair is empty or leaves the authorized file boundary", changed_files=changed)
    return pass_result("7c", "turn-two repair targets authorized Sublist source", changed_files=changed)


def _k7d(ctx: Context) -> KernelResult:
    if ctx.state.get("turn_1_passed"):
        return excluded_result("7d", "repair_not_required")
    try:
        first = json_artifact(ctx, "turn_1_evaluation_receipt")
        second = json_artifact(ctx, "turn_2_evaluation_receipt")
    except (ValueError, OSError, json.JSONDecodeError) as error:
        return invalid_result("7d", str(error))
    assert first is not None and second is not None
    if evaluation_passed(second):
        return pass_result("7d", "turn two removed the first-turn failure")
    ranks = {"parse": 0, "configure": 1, "compile": 2, "link": 3, "test": 4, "pass": 5}
    first_stage = str(first.get("stage", "parse")).lower()
    second_stage = str(second.get("stage", "parse")).lower()
    first_count = first.get("diagnostic_count")
    second_count = second.get("diagnostic_count")
    progressed = ranks.get(second_stage, -1) > ranks.get(first_stage, -1)
    reduced = isinstance(first_count, int) and isinstance(second_count, int) and second_count < first_count
    if progressed or reduced:
        return pass_result("7d", "turn two reduced diagnostics or advanced the evaluation stage", first_stage=first_stage, second_stage=second_stage)
    return fail_result("7d", "turn two did not reduce the diagnosed failure", first_stage=first_stage, second_stage=second_stage)


def _k7e(ctx: Context) -> KernelResult:
    try:
        first = json_artifact(ctx, "turn_1_evaluation_receipt")
        if first is not None and evaluation_passed(first):
            return pass_result("7e", "candidate passed 18/18 on turn one", successful_turn=1)
        second = json_artifact(ctx, "turn_2_evaluation_receipt")
    except (ValueError, OSError, json.JSONDecodeError) as error:
        return invalid_result("7e", str(error))
    assert second is not None
    if evaluation_passed(second):
        return pass_result("7e", "candidate passed 18/18 on turn two", successful_turn=2)
    return fail_result("7e", "candidate did not pass all 18 tests within two turns")


def load_pinned_parser() -> Any:
    parser_path = repository_root() / "src/glm47_posttraining/aider_polyglot/parser.py"
    if not parser_path.is_file() or sha256(parser_path) != PARSER_SHA256:
        raise ValueError("repository-root Aider parser is missing or hash-mismatched")
    spec = importlib.util.spec_from_file_location("sublist_pinned_aider_parser", parser_path)
    if spec is None or spec.loader is None:
        raise ValueError("pinned parser cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _parse_bundle_response(ctx: Context) -> tuple[dict[str, str], bool]:
    response_path = artifact(ctx, "response")
    assert response_path is not None
    module = load_pinned_parser()
    try:
        parsed = module.parse_whole_file_response(response_path.read_text(encoding="utf-8"), EDITABLE)
    except module.AiderResponseError as error:
        ctx.state["parse_error"] = error.reason
        return {}, False
    ctx.state["parsed_files"] = dict(parsed.files)
    ctx.state["format_valid"] = bool(parsed.format_valid)
    return dict(parsed.files), bool(parsed.format_valid)


def _k8a(ctx: Context) -> KernelResult:
    try:
        files, valid = _parse_bundle_response(ctx)
    except (ValueError, OSError, UnicodeError) as error:
        return invalid_result("8a", str(error))
    if not files or not valid:
        return fail_result("8a", "raw Aider response is malformed", reason=ctx.state.get("parse_error"), parsed_files=sorted(files))
    return pass_result("8a", "pinned Aider parser accepted the raw response", parsed_files=sorted(files), parser_sha256=PARSER_SHA256)


def _k8b(ctx: Context) -> KernelResult:
    try:
        if "parsed_files" not in ctx.state:
            _parse_bundle_response(ctx)
        changed_record = json_artifact(ctx, "changed_files")
        before = {name: artifact(ctx, f"before_{name.replace('.', '_')}") for name in EDITABLE}
        after = {name: artifact(ctx, f"after_{name.replace('.', '_')}") for name in EDITABLE}
    except (ValueError, OSError, UnicodeError, json.JSONDecodeError) as error:
        return invalid_result("8b", str(error))
    assert changed_record is not None
    actual = sorted(name for name in EDITABLE if before[name].read_bytes() != after[name].read_bytes())
    declared = changed_record.get("changed_files")
    parsed = ctx.state.get("parsed_files", {})
    if not isinstance(declared, list) or sorted(declared) != actual or sorted(parsed) != actual:
        return fail_result("8b", "parsed, declared, and actual changed-file sets disagree", parsed=sorted(parsed), declared=declared, actual=actual)
    for name in actual:
        if parsed[name] != after[name].read_text(encoding="utf-8"):
            return fail_result("8b", f"parsed content does not equal delivered after-tree content: {name}")
    return pass_result("8b", "response changes exactly the authorized delivered files", changed_files=actual)


def _k8c(ctx: Context) -> KernelResult:
    try:
        counters = json_artifact(ctx, "response_counters")
    except (ValueError, OSError, json.JSONDecodeError) as error:
        return invalid_result("8c", str(error))
    assert counters is not None
    bad = {name: counters.get(name, 0) for name in ("malformed_outputs", "truncations", "duplicate_listings", "noop_listings", "exhausted_context_windows") if counters.get(name, 0) != 0}
    if bad:
        return fail_result("8c", "response or context health counters are nonzero", counters=bad)
    return pass_result("8c", "response and context health counters are clean", counters=counters)


def _k8d(ctx: Context) -> KernelResult:
    try:
        harness = json_artifact(ctx, "harness_receipt")
    except (ValueError, OSError, json.JSONDecodeError) as error:
        return invalid_result("8d", str(error))
    assert harness is not None
    if harness.get("terminal") is not True or str(harness.get("status", "")).lower() not in {"pass", "fail", "failed", "candidate_failure"}:
        return invalid_result("8d", "harness receipt does not prove a terminal evaluation")
    return pass_result("8d", "harness reached a trustworthy terminal result", harness_status=harness.get("status"))


def _k8e(ctx: Context) -> KernelResult:
    try:
        task = artifact(ctx, "task_manifest")
        harness = json_artifact(ctx, "harness_receipt")
        artifact(ctx, "response")
        artifact(ctx, "changed_files")
        artifact(ctx, "response_counters")
    except (ValueError, OSError, json.JSONDecodeError) as error:
        return invalid_result("8e", str(error))
    assert task is not None and harness is not None
    if sha256(task) != MANIFEST_SHA256:
        return invalid_result("8e", "bundle task manifest does not match the pinned task")
    commands = harness.get("commands")
    if not isinstance(commands, list) or not commands or not all(isinstance(item, dict) and isinstance(item.get("argv"), list) and isinstance(item.get("returncode"), (int, type(None))) for item in commands):
        return invalid_result("8e", "harness command evidence is malformed")
    if not isinstance(harness.get("started_at"), str) or not isinstance(harness.get("finished_at"), str):
        return invalid_result("8e", "harness timing evidence is missing")
    return pass_result("8e", "task, parser, response, source, counters, commands, and timing are hash-bound", bundle_manifest_sha256=ctx.state["bundle_manifest_sha256"])


def sanitizer_control(ctx: Context, kernel_id: str, label: str, flags: tuple[str, ...]) -> KernelResult:
    assert ctx.compiler is not None
    source = write_text(ctx, f"probes/{label}-control.cpp", "int main() { return 0; }\n")
    executable = ctx.output_dir / "artifacts" / f"{label}-control"
    executable.parent.mkdir(parents=True, exist_ok=True)
    compile_record = run_command(ctx, f"{label}-control-compile", [ctx.compiler, "-std=c++17", *flags, str(source), "-o", str(executable)])
    if compile_record["start_error"] or compile_record["timed_out"] or compile_record["returncode"] != 0:
        result = invalid_result(kernel_id, f"{label} compiler/runtime control could not be built")
        result.command_ids = [compile_record["id"]]
        return result
    run_record = run_command(ctx, f"{label}-control-run", [str(executable)])
    if run_record["start_error"] or run_record["timed_out"] or run_record["returncode"] != 0:
        result = invalid_result(kernel_id, f"{label} compiler/runtime control failed")
        result.command_ids = [compile_record["id"], run_record["id"]]
        return result
    result = pass_result(kernel_id, f"{label} control passed")
    result.command_ids = [compile_record["id"], run_record["id"]]
    return result


def sanitizer_candidate(ctx: Context, kernel_id: str, label: str, sanitizer_flags: tuple[str, ...]) -> KernelResult:
    control = sanitizer_control(ctx, kernel_id, label, sanitizer_flags)
    if control.kernel != 1:
        return control
    flags = ("-std=c++17", "-Wall", "-Wextra", "-Wpedantic", "-Werror", "-fno-omit-frame-pointer", *sanitizer_flags)
    official = execute_official(ctx, kernel_id, f"{label}-official", flags)
    official.command_ids = control.command_ids + official.command_ids
    if official.kernel != 1:
        return official
    stress_body = r'''
for(int repetition=0; repetition<200; ++repetition) {
    std::vector<int> a(64,1), b(256,1);
    b[192]=2; a[63]=2;
    if(sublist::sublist(a,b)!=L::sublist)return 1;
    if(sublist::sublist({},b)!=L::sublist)return 2;
    if(sublist::sublist(b,{})!=L::superlist)return 3;
    if(sublist::sublist({1,3},{1,2,3})!=L::unequal)return 4;
}
'''
    stress = run_probe(ctx, kernel_id, f"{label}-generated", enum_probe(stress_body), flags=flags, timeout=120)
    stress.command_ids = official.command_ids + stress.command_ids
    if stress.kernel == 1:
        stress.summary = f"official and generated workloads are {label}-clean"
    return stress


def _k9a(ctx: Context) -> KernelResult:
    return sanitizer_candidate(ctx, "9a", "asan", ("-fsanitize=address",))


def _k9b(ctx: Context) -> KernelResult:
    return sanitizer_candidate(ctx, "9b", "ubsan", ("-fsanitize=undefined", "-fno-sanitize-recover=all"))


def _k9c(ctx: Context) -> KernelResult:
    flags = ("-fsanitize=address,undefined", "-fno-sanitize-recover=all")
    control = sanitizer_control(ctx, "9c", "combined-sanitizer", flags)
    if control.kernel != 1:
        return control
    compile_flags = ("-std=c++17", "-Wall", "-Wextra", "-Wpedantic", "-Werror", "-fno-omit-frame-pointer", *flags)
    body = r'''
for(int repetition=0; repetition<500; ++repetition) {
    std::vector<int> needle(128,repetition%3), haystack(1024,repetition%3);
    haystack[700]=9; needle[127]=9;
    if(sublist::sublist(needle,haystack)!=L::sublist)return 1;
    if(sublist::sublist({1,2,5},{0,1,2,3,1,2,5,6})!=L::sublist)return 2;
}
'''
    result = run_probe(ctx, "9c", "combined-sanitized-stress", enum_probe(body), flags=compile_flags, timeout=180)
    result.command_ids = control.command_ids + result.command_ids
    if result.kernel == 1:
        result.summary = "repeated sanitized stress remained clean"
        result.facts["repetitions"] = 500
    return result


def _k10a(ctx: Context) -> KernelResult:
    return _warning_family(ctx, "10a", "Clang-strict", STRICT)


def _k10b(ctx: Context) -> KernelResult:
    return execute_official(ctx, "10b", "clang-official", STRICT)


def _k10c(ctx: Context) -> KernelResult:
    assert ctx.candidate_dir is not None
    staged = ctx.output_dir / "staging/clang-clean"
    for name in (*EDITABLE, *FIXED.keys()):
        source = safe_relative(ctx.candidate_dir, name)
        target = staged / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    original = ctx.candidate_dir
    ctx.candidate_dir = staged
    try:
        result = execute_official(ctx, "10c", "clang-clean-reproduction", STRICT)
    finally:
        ctx.candidate_dir = original
    if result.kernel == 1:
        version = run_command(ctx, "clang-version", [str(ctx.compiler), "--version"])
        result.command_ids.append(version["id"])
        result.facts["compiler"] = ctx.compiler
    return result


KERNEL_IMPLEMENTATIONS: dict[str, Callable[[Context], KernelResult]] = {
    "1a": _k1a, "1b": _k1b, "1c": _k1c, "1d": _k1d, "1e": _k1e,
    "2a": _k2a, "2b": _k2b, "2c": _k2c, "2d": _k2d,
    "3a": _k3a, "3b": _k3b, "3c": _k3c, "3d": _k3d, "3e": _k3e,
    "4a": _k4a, "4b": _k4b, "4c": _k4c, "4d": _k4d, "4e": _k4e,
    "5a": _k5a, "5b": _k5b, "5c": _k5c, "5d": _k5d, "5e": _k5e, "5f": _k5f,
    "6a": _k6a, "6b": _k6b, "6c": _k6c, "6d": _k6d, "6e": _k6e,
    "7a": _k7a, "7b": _k7b, "7c": _k7c, "7d": _k7d, "7e": _k7e,
    "8a": _k8a, "8b": _k8b, "8c": _k8c, "8d": _k8d, "8e": _k8e,
    "9a": _k9a, "9b": _k9b, "9c": _k9c,
    "10a": _k10a, "10b": _k10b, "10c": _k10c,
}


def run_kernel(ctx: Context, kernel_id: str) -> KernelResult:
    if ctx.preflight_error is not None:
        return invalid_result(kernel_id, ctx.preflight_error)
    try:
        return KERNEL_IMPLEMENTATIONS[kernel_id](ctx)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        return invalid_result(kernel_id, f"verifier evidence failure: {error}")
    except Exception as error:
        return invalid_result(kernel_id, f"unexpected verifier failure: {type(error).__name__}: {error}")


def run_policy(policy: int, functions: list[Callable[[Context], KernelResult]], verifier_path: str) -> int:
    parser = argparse.ArgumentParser()
    if policy in {7, 8}:
        parser.add_argument("--bundle-dir", required=True, type=Path)
    else:
        parser.add_argument("--candidate-dir", required=True, type=Path)
        parser.add_argument("--manifest", type=Path, default=repository_root() / ".glm47-posttraining/imported_aider_data/tasks/train/sublist.json")
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    raw_output = args.output_dir.absolute()
    if path_has_symlink(raw_output):
        print("output path must not contain a symlink", file=sys.stderr)
        return 2
    output = raw_output.resolve()
    if output.exists():
        print("output directory must be new and absent", file=sys.stderr)
        return 2
    raw_input = (args.bundle_dir if policy in {7, 8} else args.candidate_dir).absolute()
    input_has_symlink = path_has_symlink(raw_input)
    input_path = raw_input if input_has_symlink else raw_input.resolve()
    if output == input_path or input_path in output.parents:
        print("output directory must be outside the candidate or bundle workspace", file=sys.stderr)
        return 2
    output.mkdir(parents=True)
    ctx = Context(policy=policy, output_dir=output, verifier_path=Path(verifier_path).resolve())
    if input_has_symlink:
        ctx.preflight_error = "input path must not contain a symlink"
    if policy in {7, 8}:
        ctx.bundle_dir = input_path
    else:
        ctx.candidate_dir = input_path
        raw_manifest = args.manifest.absolute()
        if path_has_symlink(raw_manifest):
            ctx.preflight_error = "manifest path must not contain a symlink"
            ctx.manifest_path = raw_manifest
        else:
            ctx.manifest_path = raw_manifest.resolve()
    try:
        if ctx.preflight_error is None:
            bundle_preflight(ctx) if policy in {7, 8} else candidate_preflight(ctx)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        ctx.preflight_error = f"preflight failed: {error}"
    results = [function(ctx) for function in functions]
    source_hash_after: dict[str, str] = {}
    integrity_error: str | None = None
    if ctx.candidate_dir is not None and ctx.candidate_dir.is_dir():
        for name in EDITABLE:
            path = ctx.candidate_dir / name
            if path.is_file() and not path.is_symlink():
                source_hash_after[name] = sha256(path)
        if ctx.source_hash_before and source_hash_after != ctx.source_hash_before:
            integrity_error = "verifier execution changed candidate source"
    invalid = any(item.verdict == "INVALID" for item in results) or integrity_error is not None
    failed = any(item.kernel == -1 for item in results)
    status = "INVALID" if invalid else "fail" if failed else "pass"
    applicable = [item for item in results if item.verdict != "excluded"]
    receipt = {
        "schema_version": 1,
        "task": {"task_id": TASK_ID, "source_revision": SOURCE_REVISION, "editable_files": list(EDITABLE)},
        "policy": {"number": policy, "name": POLICY_NAMES[policy]},
        "kernel_model": {"pass": 1, "fail": -1, "infrastructure": "INVALID", "excluded": "not_in_denominator"},
        "status": status,
        "kernel_sum": sum(item.kernel for item in applicable if isinstance(item.kernel, int)),
        "applicable_kernel_count": len(applicable),
        "passed_count": sum(item.kernel == 1 for item in applicable),
        "failed_count": sum(item.kernel == -1 for item in applicable),
        "invalid_count": sum(item.verdict == "INVALID" for item in applicable),
        "excluded_conditions": {item.kernel_id: item.summary for item in results if item.verdict == "excluded"},
        "kernels": [asdict(item) for item in results],
        "commands": ctx.commands,
        "candidate_source_sha256_before": ctx.source_hash_before,
        "candidate_source_sha256_after": source_hash_after,
        "fixed_file_sha256": ctx.fixed_hashes,
        "verifier_sha256": sha256(ctx.verifier_path),
        "shared_runtime_sha256": sha256(Path(__file__)),
        "bundle_manifest_sha256": ctx.state.get("bundle_manifest_sha256"),
        "preflight_error": ctx.preflight_error,
        "integrity_error": integrity_error,
    }
    receipt_path = output / "verification_receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "kernel_sum": receipt["kernel_sum"], "applicable": len(applicable), "receipt": str(receipt_path)}, sort_keys=True))
    return 2 if status == "INVALID" else 1 if status == "fail" else 0
