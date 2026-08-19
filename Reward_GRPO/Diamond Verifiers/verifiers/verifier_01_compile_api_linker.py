# Policy 1 verifier: check five independent Diamond compile, consumer, linker, and clean-build kernels.
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


TASK_ID = "diamond"
POLICY_ID = "01"
POLICY_NAME = "compile_api_linker"
PINNED = {
    "CMakeLists.txt": "53d531120e650972adf19a2a42aa2d5bc716c93700ffac74c1c2868fdce633ff",
    "diamond_test.cpp": "235fc2baac052df9b1efd981d93924b37a738dc85e5b056547a78eeb8840da3f",
    "test/catch.hpp": "681e7505a50887c9085539e5135794fc8f66d8e5de28eadf13a30978627b0f47",
    "test/tests-main.cpp": "5847fda35c1320d94f8d088aaf34229d689f66f1da235f885cbb28c8f17e4260",
}
STRICT = ["-std=c++17", "-Wall", "-Wextra", "-Wpedantic", "-Werror"]
API_PROBE = r'''#include "diamond.h"
#include <string>
#include <vector>
int main() {
    auto fn = static_cast<std::vector<std::string> (*)(char)>(&diamond::rows);
    const auto value = fn('A');
    return value == std::vector<std::string>{"A"} ? 0 : 1;
}
'''
TOOLCHAIN_PROBE = "int main() { return 0; }\n"


class InvalidEvidence(RuntimeError):
    pass


@dataclass
class Context:
    exercise: Path
    output: Path
    compiler: str
    cmake: str
    compile_timeout: int
    runtime_timeout: int
    commands: list[dict[str, Any]] = field(default_factory=list)
    source_before: dict[str, str] = field(default_factory=dict)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_manifest(exercise: Path) -> dict[str, str]:
    return {name: sha256(exercise / name) for name in ("diamond.cpp", "diamond.h")}


def artifact(path: Path) -> dict[str, Any]:
    return {"path": str(path), "sha256": sha256(path), "size": path.stat().st_size}


def run(ctx: Context, kernel: str, label: str, args: list[str], timeout: int, cwd: Path | None = None) -> dict[str, Any]:
    started = time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(args, cwd=cwd, capture_output=True, timeout=timeout, check=False)
        returncode = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        returncode = None
        stdout = exc.stdout or b""
        stderr = exc.stderr or b""
    except OSError as exc:
        raise InvalidEvidence(f"could not start {args[0]}: {exc}") from exc
    stdout_path = ctx.output / f"{kernel}_{label}.stdout"
    stderr_path = ctx.output / f"{kernel}_{label}.stderr"
    stdout_path.write_bytes(stdout)
    stderr_path.write_bytes(stderr)
    record = {
        "kernel": kernel,
        "label": label,
        "args": args,
        "cwd": str(cwd) if cwd else None,
        "returncode": returncode,
        "timed_out": timed_out,
        "duration_seconds": round(time.monotonic() - started, 6),
        "stdout": artifact(stdout_path),
        "stderr": artifact(stderr_path),
    }
    ctx.commands.append(record)
    return record


def kernel(kernel_id: str, function: str, passed: bool, summary: str, facts: dict[str, Any], artifacts: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "kernel_id": kernel_id,
        "verifier_function": function,
        "status": "pass" if passed else "fail",
        "score": 1 if passed else -1,
        "applicable": True,
        "summary": summary,
        "facts": facts,
        "artifacts": artifacts or {},
    }


def require_regular(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise InvalidEvidence(f"required regular file is missing or unsafe: {path}")


def preflight(ctx: Context, expected_source: str | None) -> dict[str, Any]:
    if ctx.exercise.name != TASK_ID or not ctx.exercise.is_dir():
        raise InvalidEvidence("exercise directory must be a real directory named diamond")
    for name in ("diamond.cpp", "diamond.h", *PINNED):
        require_regular(ctx.exercise / name)
    fixed = {name: sha256(ctx.exercise / name) for name in PINNED}
    mismatches = {name: {"expected": PINNED[name], "actual": value} for name, value in fixed.items() if value != PINNED[name]}
    if mismatches:
        raise InvalidEvidence(f"pinned evaluator asset mismatch: {json.dumps(mismatches, sort_keys=True)}")
    ctx.source_before = source_manifest(ctx.exercise)
    combined = hashlib.sha256(json.dumps(ctx.source_before, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if expected_source and expected_source != combined:
        raise InvalidEvidence("candidate source digest does not match --expected-source-sha256")
    return {"fixed_assets": fixed, "candidate_files": ctx.source_before, "candidate_combined_sha256": combined}


def verify_1a_toolchain(ctx: Context) -> dict[str, Any]:
    version = run(ctx, "1A", "gcc_version", [ctx.compiler, "--version"], 10)
    cmake_version = run(ctx, "1A", "cmake_version", [ctx.cmake, "--version"], 10)
    version_text = (ctx.output / "1A_gcc_version.stdout").read_text(errors="replace")
    cmake_text = (ctx.output / "1A_cmake_version.stdout").read_text(errors="replace")
    if version["returncode"] != 0 or "13.3" not in version_text:
        raise InvalidEvidence("GNU GCC 13.3 preflight failed")
    match = re.search(r"cmake version (\d+)\.(\d+)\.(\d+)", cmake_text)
    if cmake_version["returncode"] != 0 or match is None or tuple(map(int, match.groups())) < (3, 5, 1):
        raise InvalidEvidence("CMake 3.5.1 or newer is unavailable")
    probe = ctx.output / "toolchain_probe.cpp"
    probe.write_text(TOOLCHAIN_PROBE)
    probe_bin = ctx.output / "toolchain_probe"
    compile_result = run(ctx, "1A", "compile_probe", [ctx.compiler, *STRICT, str(probe), "-o", str(probe_bin)], ctx.compile_timeout)
    if compile_result["returncode"] != 0 or compile_result["timed_out"] or not probe_bin.is_file():
        raise InvalidEvidence("harmless GCC C++17 preflight failed")
    configure_dir = ctx.output / "configure_probe"
    configure = run(ctx, "1A", "configure", [ctx.cmake, "-S", str(ctx.exercise), "-B", str(configure_dir), "-DEXERCISM_RUN_ALL_TESTS=ON", f"-DCMAKE_CXX_COMPILER={ctx.compiler}"], ctx.compile_timeout)
    passed = configure["returncode"] == 0 and not configure["timed_out"] and (configure_dir / "CMakeCache.txt").is_file()
    return kernel("1A", "verify_1a_toolchain", passed, "toolchain and configure passed" if passed else "candidate CMake configure failed", {"gcc": version_text.splitlines()[0], "cmake": cmake_text.splitlines()[0]}, {"probe": artifact(probe_bin)} if probe_bin.is_file() else {})


def verify_1b_implementation_compile(ctx: Context) -> tuple[dict[str, Any], Path | None]:
    obj = ctx.output / "diamond.o"
    result = run(ctx, "1B", "implementation_compile", [ctx.compiler, *STRICT, "-I", str(ctx.exercise), "-c", str(ctx.exercise / "diamond.cpp"), "-o", str(obj)], ctx.compile_timeout)
    passed = result["returncode"] == 0 and not result["timed_out"] and obj.is_file() and obj.stat().st_size > 0
    return kernel("1B", "verify_1b_implementation_compile", passed, "implementation compiled" if passed else "candidate implementation did not compile", {"returncode": result["returncode"], "timed_out": result["timed_out"]}, {"object": artifact(obj)} if passed else {}), obj if passed else None


def verify_1c_consumers_compile(ctx: Context) -> tuple[dict[str, Any], list[Path]]:
    probe = ctx.output / "api_consumer.cpp"
    probe.write_text(API_PROBE)
    official_obj = ctx.output / "diamond_test.o"
    probe_obj = ctx.output / "api_consumer.o"
    official = run(ctx, "1C", "official_consumer", [ctx.compiler, *STRICT, "-DEXERCISM_RUN_ALL_TESTS", "-I", str(ctx.exercise), "-c", str(ctx.exercise / "diamond_test.cpp"), "-o", str(official_obj)], ctx.compile_timeout)
    consumer = run(ctx, "1C", "api_consumer", [ctx.compiler, *STRICT, "-I", str(ctx.exercise), "-c", str(probe), "-o", str(probe_obj)], ctx.compile_timeout)
    passed = all(item["returncode"] == 0 and not item["timed_out"] for item in (official, consumer)) and all(path.is_file() and path.stat().st_size > 0 for path in (official_obj, probe_obj))
    artifacts = {path.name: artifact(path) for path in (official_obj, probe_obj) if path.is_file()}
    return kernel("1C", "verify_1c_consumers_compile", passed, "official and API consumers compiled" if passed else "candidate public declarations rejected a consumer", {"official_returncode": official["returncode"], "api_returncode": consumer["returncode"]}, artifacts), [official_obj, probe_obj] if passed else []


def verify_1d_link(ctx: Context, implementation: Path | None, consumers: list[Path]) -> dict[str, Any]:
    if implementation is None or len(consumers) != 2:
        return kernel("1D", "verify_1d_link", False, "blocked by candidate compile failure", {"blocked_by": ["1B", "1C"]})
    main_obj = ctx.output / "tests-main.o"
    main_compile = run(ctx, "1D", "catch_main", [ctx.compiler, *STRICT, "-DEXERCISM_RUN_ALL_TESTS", "-I", str(ctx.exercise), "-c", str(ctx.exercise / "test/tests-main.cpp"), "-o", str(main_obj)], ctx.compile_timeout)
    if main_compile["returncode"] != 0 or not main_obj.is_file():
        raise InvalidEvidence("protected Catch main failed to compile in evaluator preflight")
    executable = ctx.output / "diamond"
    link_result = run(ctx, "1D", "link", [ctx.compiler, str(implementation), str(consumers[0]), str(main_obj), "-o", str(executable)], ctx.compile_timeout)
    passed = link_result["returncode"] == 0 and not link_result["timed_out"] and executable.is_file() and executable.stat().st_size > 0
    return kernel("1D", "verify_1d_link", passed, "official executable linked" if passed else "candidate symbols did not link", {"returncode": link_result["returncode"], "timed_out": link_result["timed_out"]}, {"executable": artifact(executable)} if passed else {})


def verify_1e_clean_build(ctx: Context) -> dict[str, Any]:
    build = ctx.output / "clean_build"
    configure = run(ctx, "1E", "configure", [ctx.cmake, "-S", str(ctx.exercise), "-B", str(build), "-DEXERCISM_RUN_ALL_TESTS=ON", f"-DCMAKE_CXX_COMPILER={ctx.compiler}"], ctx.compile_timeout)
    if configure["returncode"] != 0 or configure["timed_out"]:
        return kernel("1E", "verify_1e_clean_build", False, "candidate clean configure failed", {"configure_returncode": configure["returncode"]})
    build_result = run(ctx, "1E", "build", [ctx.cmake, "--build", str(build), "--target", "diamond", "--clean-first", "--parallel", "1"], ctx.compile_timeout)
    executable = build / "diamond"
    passed = build_result["returncode"] == 0 and not build_result["timed_out"] and executable.is_file() and executable.stat().st_size > 0
    return kernel("1E", "verify_1e_clean_build", passed, "clean CMake build produced diamond" if passed else "candidate clean build failed", {"returncode": build_result["returncode"], "timed_out": build_result["timed_out"]}, {"executable": artifact(executable)} if passed else {})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exercise-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--compiler", default="g++")
    parser.add_argument("--cmake", default="cmake")
    parser.add_argument("--expected-source-sha256")
    parser.add_argument("--compile-timeout-s", type=int, default=180)
    parser.add_argument("--runtime-timeout-s", type=int, default=10)
    args = parser.parse_args()
    exercise_absolute = args.exercise_dir.absolute()
    output_absolute = args.output_dir.absolute()
    if any(path.is_symlink() for path in (exercise_absolute, *exercise_absolute.parents)):
        print(json.dumps({"overall_status": "INVALID", "reason": "exercise path must not contain symlinks"}))
        return 2
    if args.output_dir.exists() or any(path.is_symlink() for path in (output_absolute, *output_absolute.parents)):
        print(json.dumps({"overall_status": "INVALID", "reason": "output path must be new and contain no symlinks"}))
        return 2
    exercise = args.exercise_dir.resolve()
    output = args.output_dir.resolve()
    if output == exercise or exercise in output.parents:
        print(json.dumps({"overall_status": "INVALID", "reason": "output directory must be outside the candidate tree"}))
        return 2
    args.output_dir.mkdir(parents=True)
    compiler = shutil.which(args.compiler)
    cmake = shutil.which(args.cmake)
    started = time.time()
    ctx = Context(exercise, output, compiler or args.compiler, cmake or args.cmake, args.compile_timeout_s, args.runtime_timeout_s)
    receipt: dict[str, Any] = {"schema_version": 1, "task_id": TASK_ID, "contract_variant": "pristine-original-v1", "policy_id": POLICY_ID, "policy_name": POLICY_NAME, "verifier_source_sha256": sha256(Path(__file__)), "started_at": started}
    try:
        if compiler is None or cmake is None:
            raise InvalidEvidence("required GCC or CMake executable is unavailable")
        receipt["preflight"] = preflight(ctx, args.expected_source_sha256)
        results = [verify_1a_toolchain(ctx)]
        implementation_result, implementation = verify_1b_implementation_compile(ctx)
        results.append(implementation_result)
        consumer_result, consumers = verify_1c_consumers_compile(ctx)
        results.append(consumer_result)
        results.append(verify_1d_link(ctx, implementation, consumers))
        results.append(verify_1e_clean_build(ctx))
        if source_manifest(ctx.exercise) != ctx.source_before:
            raise InvalidEvidence("candidate source changed during verification")
        receipt["kernels"] = results
        receipt["commands"] = ctx.commands
        receipt["kernel_sum"] = sum(item["score"] for item in results)
        receipt["applicable_kernel_count"] = len(results)
        receipt["overall_status"] = "pass" if all(item["score"] == 1 for item in results) else "fail"
        exit_code = 0 if receipt["overall_status"] == "pass" else 1
    except InvalidEvidence as exc:
        receipt["overall_status"] = "INVALID"
        receipt["reason"] = str(exc)
        receipt["commands"] = ctx.commands
        exit_code = 2
    receipt["started_at"] = started
    if isinstance(receipt.get("kernels"), list):
        applicable = [item for item in receipt["kernels"] if item.get("applicable", True)]
        receipt["passed_kernel_count"] = sum(item.get("score") == 1 for item in applicable)
        receipt["failed_kernel_count"] = sum(item.get("score") == -1 for item in applicable)
    receipt["duration_seconds"] = round(time.time() - started, 6)
    receipt["source_immutable"] = source_manifest(ctx.exercise) == ctx.source_before if ctx.source_before else None
    (ctx.output / "verification_receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
