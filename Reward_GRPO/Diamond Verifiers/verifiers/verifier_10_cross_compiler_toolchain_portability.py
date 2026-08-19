# Policy 10 verifier: prove Diamond portability with host Clang and an immutable offline Clang container.
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


TASK_ID = "diamond"
POLICY_ID = "10"
PINNED = {
    "CMakeLists.txt": "53d531120e650972adf19a2a42aa2d5bc716c93700ffac74c1c2868fdce633ff",
    "diamond_test.cpp": "235fc2baac052df9b1efd981d93924b37a738dc85e5b056547a78eeb8840da3f",
    "test/catch.hpp": "681e7505a50887c9085539e5135794fc8f66d8e5de28eadf13a30978627b0f47",
    "test/tests-main.cpp": "5847fda35c1320d94f8d088aaf34229d689f66f1da235f885cbb28c8f17e4260",
}
STRICT = ["-std=c++17", "-Wall", "-Wextra", "-Wpedantic", "-Werror"]
DEFAULT_IMAGE = "silkeh/clang@sha256:9388794775d1393c16b6897b4775b6d3e29459319de0bfafec59a20262e1fa68"
IMAGE_DIGEST = "sha256:9388794775d1393c16b6897b4775b6d3e29459319de0bfafec59a20262e1fa68"
API_PROBE = r'''#include "diamond.h"
#include <string>
#include <vector>
int main() {
    auto fn = static_cast<std::vector<std::string> (*)(char)>(&diamond::rows);
    return fn('A') == std::vector<std::string>{"A"} ? 0 : 1;
}
'''


class InvalidEvidence(RuntimeError):
    pass


@dataclass
class Context:
    exercise: Path
    output: Path
    compiler: str
    docker: str
    image: str
    compile_timeout: int
    runtime_timeout: int
    container_timeout: int
    commands: list[dict[str, Any]] = field(default_factory=list)
    source_before: dict[str, str] = field(default_factory=dict)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest(exercise: Path) -> dict[str, str]:
    return {name: sha256(exercise / name) for name in ("diamond.cpp", "diamond.h")}


def run(ctx: Context, kernel_id: str, label: str, args: list[str], timeout: int) -> dict[str, Any]:
    try:
        completed = subprocess.run(args, capture_output=True, timeout=timeout, check=False)
        returncode, timed_out, stdout, stderr = completed.returncode, False, completed.stdout, completed.stderr
    except subprocess.TimeoutExpired as exc:
        returncode, timed_out, stdout, stderr = None, True, exc.stdout or b"", exc.stderr or b""
    except OSError as exc:
        raise InvalidEvidence(f"could not start tool: {exc}") from exc
    stdout_path = ctx.output / f"{kernel_id}_{label}.stdout"
    stderr_path = ctx.output / f"{kernel_id}_{label}.stderr"
    stdout_path.write_bytes(stdout)
    stderr_path.write_bytes(stderr)
    record = {"kernel": kernel_id, "label": label, "args": args, "returncode": returncode, "timed_out": timed_out, "stdout_sha256": sha256(stdout_path), "stderr_sha256": sha256(stderr_path)}
    ctx.commands.append(record)
    return record


def result(kernel_id: str, function: str, passed: bool, summary: str, facts: dict[str, Any]) -> dict[str, Any]:
    return {"kernel_id": kernel_id, "verifier_function": function, "status": "pass" if passed else "fail", "score": 1 if passed else -1, "applicable": True, "summary": summary, "facts": facts}


def verify_10a_clang_warning_clean_compile(ctx: Context) -> tuple[dict[str, Any], list[Path]]:
    probe = ctx.output / "api_probe.cpp"
    probe.write_text(API_PROBE)
    units = [
        ("implementation", ctx.exercise / "diamond.cpp", []),
        ("official", ctx.exercise / "diamond_test.cpp", ["-DEXERCISM_RUN_ALL_TESTS"]),
        ("catch_main", ctx.exercise / "test/tests-main.cpp", ["-DEXERCISM_RUN_ALL_TESTS"]),
        ("api_probe", probe, []),
    ]
    objects: list[Path] = []
    facts: list[dict[str, Any]] = []
    passed = True
    for label, source, extra in units:
        obj = ctx.output / f"10A_{label}.o"
        record = run(ctx, "10A", label, [ctx.compiler, *STRICT, *extra, "-I", str(ctx.exercise), "-c", str(source), "-o", str(obj)], ctx.compile_timeout)
        okay = record["returncode"] == 0 and not record["timed_out"] and obj.is_file() and obj.stat().st_size > 0
        passed = passed and okay
        if okay:
            objects.append(obj)
        facts.append({"unit": label, "returncode": record["returncode"], "timed_out": record["timed_out"], "object_sha256": sha256(obj) if okay else None})
    return result("10A", "verify_10a_clang_warning_clean_compile", passed, "all Clang translation units compiled cleanly" if passed else "candidate failed strict Clang compilation", {"units": facts}), objects


def verify_10b_clang_link_and_tests(ctx: Context) -> dict[str, Any]:
    executable = ctx.output / "10B_diamond"
    build = run(ctx, "10B", "build", [ctx.compiler, *STRICT, "-DEXERCISM_RUN_ALL_TESTS", "-I", str(ctx.exercise), str(ctx.exercise / "diamond.cpp"), str(ctx.exercise / "diamond_test.cpp"), str(ctx.exercise / "test/tests-main.cpp"), "-o", str(executable)], ctx.compile_timeout)
    if build["returncode"] != 0 or build["timed_out"] or not executable.is_file():
        return result("10B", "verify_10b_clang_link_and_tests", False, "candidate failed Clang build or link", {"build_returncode": build["returncode"], "timed_out": build["timed_out"]})
    execution = run(ctx, "10B", "tests", [str(executable)], ctx.runtime_timeout)
    text = (ctx.output / "10B_tests.stdout").read_text(errors="replace")
    passed = execution["returncode"] == 0 and not execution["timed_out"] and "5 assertions in 5 test cases" in text
    return result("10B", "verify_10b_clang_link_and_tests", passed, "Clang executable passed all five tests" if passed else "candidate failed official tests under Clang", {"build_returncode": build["returncode"], "run_returncode": execution["returncode"], "timed_out": execution["timed_out"], "executable_sha256": sha256(executable)})


def docker_base(ctx: Context, build_root: Path | None = None) -> list[str]:
    args = [ctx.docker, "run", "--rm", "--network", "none", "--read-only", "--tmpfs", "/tmp:rw,nosuid,nodev", "--user", f"{os.getuid()}:{os.getgid()}", "--mount", f"type=bind,src={ctx.exercise},dst=/diamond,readonly"]
    if build_root is not None:
        args.extend(["--mount", f"type=bind,src={build_root},dst=/work"])
    args.append(ctx.image)
    return args


def container_preflight(ctx: Context) -> dict[str, Any]:
    version = run(ctx, "10C", "docker_version", [ctx.docker, "version", "--format", "{{.Server.Version}}"], 30)
    inspect = run(ctx, "10C", "image_inspect", [ctx.docker, "image", "inspect", ctx.image, "--format", "{{json .RepoDigests}} {{.Id}}"], 30)
    inspect_text = (ctx.output / "10C_image_inspect.stdout").read_text(errors="replace")
    if version["returncode"] != 0 or inspect["returncode"] != 0 or IMAGE_DIGEST not in inspect_text:
        raise InvalidEvidence("Docker daemon or pinned immutable Clang image is unavailable")
    clang = run(ctx, "10C", "container_clang", [*docker_base(ctx), "clang++", "--version"], 60)
    cmake = run(ctx, "10C", "container_cmake", [*docker_base(ctx), "cmake", "--version"], 60)
    clang_text = (ctx.output / "10C_container_clang.stdout").read_text(errors="replace")
    cmake_text = (ctx.output / "10C_container_cmake.stdout").read_text(errors="replace")
    if clang["returncode"] != 0 or cmake["returncode"] != 0 or "clang version 18" not in clang_text or "cmake version" not in cmake_text:
        raise InvalidEvidence("pinned container compiler/CMake preflight failed")
    return {"image": ctx.image, "image_inspect": inspect_text.strip(), "clang": clang_text.splitlines()[0], "cmake": cmake_text.splitlines()[0]}


def verify_10c_clean_reproduction(ctx: Context) -> dict[str, Any]:
    identity = container_preflight(ctx)
    build_root = ctx.output / "container_output"
    build_root.mkdir()
    configure = run(ctx, "10C", "configure", [*docker_base(ctx, build_root), "cmake", "-S", "/diamond", "-B", "/work/build", "-DEXERCISM_RUN_ALL_TESTS=ON", "-DCMAKE_CXX_COMPILER=clang++"], ctx.container_timeout)
    if configure["returncode"] != 0 or configure["timed_out"]:
        return result("10C", "verify_10c_clean_reproduction", False, "candidate failed clean container configure", {"identity": identity, "configure_returncode": configure["returncode"]})
    build = run(ctx, "10C", "build", [*docker_base(ctx, build_root), "cmake", "--build", "/work/build", "--target", "diamond", "--clean-first", "--parallel", "1"], ctx.container_timeout)
    if build["returncode"] != 0 or build["timed_out"]:
        return result("10C", "verify_10c_clean_reproduction", False, "candidate failed clean container build", {"identity": identity, "build_returncode": build["returncode"]})
    execution = run(ctx, "10C", "tests", [*docker_base(ctx, build_root), "/work/build/diamond"], ctx.container_timeout)
    text = (ctx.output / "10C_tests.stdout").read_text(errors="replace")
    executable = build_root / "build/diamond"
    passed = execution["returncode"] == 0 and not execution["timed_out"] and "5 assertions in 5 test cases" in text and executable.is_file()
    return result("10C", "verify_10c_clean_reproduction", passed, "immutable Clang reproduction passed all five tests" if passed else "candidate failed container tests", {"identity": identity, "run_returncode": execution["returncode"], "timed_out": execution["timed_out"], "executable_sha256": sha256(executable) if executable.is_file() else None})


def preflight(ctx: Context, expected_source: str | None) -> dict[str, Any]:
    if ctx.exercise.name != TASK_ID or not ctx.exercise.is_dir():
        raise InvalidEvidence("exercise directory must be named diamond")
    for name in ("diamond.cpp", "diamond.h", *PINNED):
        path = ctx.exercise / name
        if path.is_symlink() or not path.is_file():
            raise InvalidEvidence(f"missing or unsafe required file: {name}")
    fixed = {name: sha256(ctx.exercise / name) for name in PINNED}
    if fixed != PINNED:
        raise InvalidEvidence("pinned evaluator asset mismatch")
    ctx.source_before = manifest(ctx.exercise)
    combined = hashlib.sha256(json.dumps(ctx.source_before, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if expected_source and expected_source != combined:
        raise InvalidEvidence("candidate source digest mismatch")
    version = run(ctx, "preflight", "clang_version", [ctx.compiler, "--version"], 10)
    text = (ctx.output / "preflight_clang_version.stdout").read_text(errors="replace")
    if version["returncode"] != 0 or "18.1.3" not in text:
        raise InvalidEvidence("host Clang 18.1.3 unavailable")
    harmless = ctx.output / "harmless.cpp"
    harmless.write_text("int main() { return 0; }\n")
    harmless_bin = ctx.output / "harmless"
    check = run(ctx, "preflight", "harmless_compile", [ctx.compiler, *STRICT, str(harmless), "-o", str(harmless_bin)], ctx.compile_timeout)
    if check["returncode"] != 0 or not harmless_bin.is_file():
        raise InvalidEvidence("harmless Clang preflight failed")
    return {"candidate_files": ctx.source_before, "candidate_combined_sha256": combined, "fixed_assets": fixed, "clang": text.splitlines()[0]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exercise-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--compiler", default="clang++")
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--container-image", default=DEFAULT_IMAGE)
    parser.add_argument("--expected-source-sha256")
    parser.add_argument("--compile-timeout-s", type=int, default=180)
    parser.add_argument("--runtime-timeout-s", type=int, default=60)
    parser.add_argument("--container-timeout-s", type=int, default=300)
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
    docker = shutil.which(args.docker)
    ctx = Context(exercise, output, compiler or args.compiler, docker or args.docker, args.container_image, args.compile_timeout_s, args.runtime_timeout_s, args.container_timeout_s)
    receipt: dict[str, Any] = {"schema_version": 1, "task_id": TASK_ID, "contract_variant": "pristine-original-v1", "policy_id": POLICY_ID, "policy_name": "cross_compiler_toolchain_portability", "verifier_source_sha256": sha256(Path(__file__))}
    started = time.time()
    try:
        if compiler is None or docker is None:
            raise InvalidEvidence("required host Clang or Docker executable is unavailable")
        if args.container_image != DEFAULT_IMAGE:
            raise InvalidEvidence("container image must match the pinned immutable digest")
        receipt["preflight"] = preflight(ctx, args.expected_source_sha256)
        compile_result, _ = verify_10a_clang_warning_clean_compile(ctx)
        kernels = [compile_result, verify_10b_clang_link_and_tests(ctx), verify_10c_clean_reproduction(ctx)]
        if manifest(ctx.exercise) != ctx.source_before:
            raise InvalidEvidence("candidate source changed during verification")
        receipt.update({"kernels": kernels, "commands": ctx.commands, "applicable_kernel_count": 3, "kernel_sum": sum(item["score"] for item in kernels), "overall_status": "pass" if all(item["score"] == 1 for item in kernels) else "fail"})
        exit_code = 0 if receipt["overall_status"] == "pass" else 1
    except InvalidEvidence as exc:
        receipt.update({"overall_status": "INVALID", "reason": str(exc), "commands": ctx.commands})
        exit_code = 2
    receipt["started_at"] = started
    if isinstance(receipt.get("kernels"), list):
        applicable = [item for item in receipt["kernels"] if item.get("applicable", True)]
        receipt["passed_kernel_count"] = sum(item.get("score") == 1 for item in applicable)
        receipt["failed_kernel_count"] = sum(item.get("score") == -1 for item in applicable)
    receipt["duration_seconds"] = round(time.time() - started, 6)
    receipt["source_immutable"] = manifest(ctx.exercise) == ctx.source_before if ctx.source_before else None
    (ctx.output / "verification_receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
