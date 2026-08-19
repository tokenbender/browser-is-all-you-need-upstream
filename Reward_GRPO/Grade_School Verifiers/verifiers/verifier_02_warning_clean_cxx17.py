# Policy 2 verifier: isolate three GCC warning families and the combined Grade School warning-as-error build.
from __future__ import annotations

import sys
from pathlib import Path

from _grade_school_common import CandidateContext, KernelReceipt, artifact_entry, command_result, failed, invalid, passed, run_candidate_policy, run_command, sha256, write_probe


CONSUMER = """#include \"grade_school.h\"

int main() {
    grade_school::school value{};
    return value.roster().empty() ? 0 : 0;
}
"""


def _warning_kernel(ctx: CandidateContext, kernel_id: str, flag: str) -> KernelReceipt:
    probe = write_probe(ctx, kernel_id, flag.lstrip("-"), CONSUMER)
    output = ctx.output_dir / "artifacts" / f"{kernel_id.lower()}_warning_probe"
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [ctx.compiler, "-std=c++17", flag, "-Werror", "-fno-diagnostics-color", f"-I{ctx.exercise_dir}", str(probe), str(ctx.exercise_dir / "grade_school.cpp"), "-o", str(output)]
    receipt = run_command(ctx.output_dir, kernel_id, flag, command, 30)
    artifacts = {str(probe): sha256(probe)}
    if receipt.return_code == 0 and output.is_file():
        artifacts.update(artifact_entry(output))
    return command_result(kernel_id, receipt, f"candidate is clean under {flag}", f"candidate is not clean under {flag}", artifacts, {"warning_family": flag})


def verify_2a_wall(ctx: CandidateContext) -> KernelReceipt:
    return _warning_kernel(ctx, "2A", "-Wall")


def verify_2b_wextra(ctx: CandidateContext) -> KernelReceipt:
    return _warning_kernel(ctx, "2B", "-Wextra")


def verify_2c_wpedantic(ctx: CandidateContext) -> KernelReceipt:
    return _warning_kernel(ctx, "2C", "-Wpedantic")


def verify_2d_combined_werror_build(ctx: CandidateContext) -> KernelReceipt:
    build = ctx.output_dir / "combined-build"
    flags = "-Wall -Wextra -Wpedantic -Werror -fno-diagnostics-color"
    configure = run_command(ctx.output_dir, "2D", "cmake_configure", ["cmake", "-S", str(ctx.exercise_dir), "-B", str(build), "-DEXERCISM_RUN_ALL_TESTS=ON", f"-DCMAKE_CXX_COMPILER={ctx.compiler}", f"-DCMAKE_CXX_FLAGS={flags}"], 30)
    if configure.launch_error or configure.return_code != 0:
        return invalid("2D", "protected warning build could not be configured", [configure])
    built = run_command(ctx.output_dir, "2D", "combined_werror_build", ["cmake", "--build", str(build), "--target", "grade-school", "--parallel", "2"], 60)
    commands = [configure, built]
    executable = build / "grade-school"
    if built.launch_error:
        return invalid("2D", "build process could not start", commands)
    if built.return_code != 0 or not executable.is_file():
        return failed("2D", "combined warning-as-error build failed", commands)
    return passed("2D", "combined warning-as-error build passed", commands, artifacts=artifact_entry(executable))


if __name__ == "__main__":
    sys.exit(run_candidate_policy("2", "Warning-Clean C++17 Build", Path(__file__), [verify_2a_wall, verify_2b_wextra, verify_2c_wpedantic, verify_2d_combined_werror_build], "gcc", "g++"))
