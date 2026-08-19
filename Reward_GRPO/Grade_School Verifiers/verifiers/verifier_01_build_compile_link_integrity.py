# Policy 1 verifier: prove five independent Grade School build, consumer, and linker boundaries.
from __future__ import annotations

import sys
from pathlib import Path

from _grade_school_common import GCC_FLAGS, CandidateContext, KernelReceipt, artifact_entry, command_result, failed, invalid, passed, run_candidate_policy, run_command, sha256, write_probe


API_CONSUMER = """#include \"grade_school.h\"

int main() {
    grade_school::school value{};
    value.add("Aimee", 2);
    (void)value.grade(2);
    (void)value.roster();
    return 0;
}
"""


def verify_1a_implementation_compile(ctx: CandidateContext) -> KernelReceipt:
    output = ctx.output_dir / "artifacts" / "grade_school.o"
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [ctx.compiler, *GCC_FLAGS, f"-I{ctx.exercise_dir}", "-c", str(ctx.exercise_dir / "grade_school.cpp"), "-o", str(output)]
    receipt = run_command(ctx.output_dir, "1A", "implementation_compile", command, 30)
    artifacts = artifact_entry(output) if receipt.return_code == 0 and output.is_file() else {}
    return command_result("1A", receipt, "implementation compiled", "implementation compilation failed", artifacts)


def verify_1b_official_consumer_compile(ctx: CandidateContext) -> KernelReceipt:
    output = ctx.output_dir / "artifacts" / "grade_school_test.o"
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [ctx.compiler, *GCC_FLAGS, "-DEXERCISM_RUN_ALL_TESTS", f"-I{ctx.exercise_dir}", f"-I{ctx.exercise_dir / 'test'}", "-c", str(ctx.exercise_dir / "grade_school_test.cpp"), "-o", str(output)]
    receipt = run_command(ctx.output_dir, "1B", "official_consumer_compile", command, 30)
    artifacts = artifact_entry(output) if receipt.return_code == 0 and output.is_file() else {}
    return command_result("1B", receipt, "official consumer compiled", "official consumer rejected the candidate API", artifacts)


def verify_1c_external_consumer_compile(ctx: CandidateContext) -> KernelReceipt:
    probe = write_probe(ctx, "1C", "external_consumer", API_CONSUMER)
    output = ctx.output_dir / "artifacts" / "external_consumer.o"
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [ctx.compiler, *GCC_FLAGS, f"-I{ctx.exercise_dir}", "-c", str(probe), "-o", str(output)]
    receipt = run_command(ctx.output_dir, "1C", "external_consumer_compile", command, 30)
    artifacts = {str(probe): sha256(probe)}
    if receipt.return_code == 0 and output.is_file():
        artifacts.update(artifact_entry(output))
    return command_result("1C", receipt, "external consumer compiled", "external consumer compilation failed", artifacts)


def verify_1d_external_consumer_link(ctx: CandidateContext) -> KernelReceipt:
    probe = write_probe(ctx, "1D", "external_link", API_CONSUMER)
    output = ctx.output_dir / "artifacts" / "external_link"
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [ctx.compiler, *GCC_FLAGS, f"-I{ctx.exercise_dir}", str(probe), str(ctx.exercise_dir / "grade_school.cpp"), "-o", str(output)]
    receipt = run_command(ctx.output_dir, "1D", "external_consumer_link", command, 30)
    artifacts = {str(probe): sha256(probe)}
    if receipt.return_code == 0 and output.is_file():
        artifacts.update(artifact_entry(output))
    return command_result("1D", receipt, "external consumer linked", "candidate definitions did not link", artifacts)


def verify_1e_clean_cmake_build(ctx: CandidateContext) -> KernelReceipt:
    build = ctx.output_dir / "cmake-build"
    configure = run_command(ctx.output_dir, "1E", "cmake_configure", ["cmake", "-S", str(ctx.exercise_dir), "-B", str(build), "-DEXERCISM_RUN_ALL_TESTS=ON", f"-DCMAKE_CXX_COMPILER={ctx.compiler}"], 30)
    if configure.launch_error:
        return invalid("1E", "CMake could not start", [configure])
    if configure.return_code != 0:
        return invalid("1E", "protected task configuration failed", [configure])
    build_receipt = run_command(ctx.output_dir, "1E", "cmake_build", ["cmake", "--build", str(build), "--target", "grade-school", "--parallel", "2"], 60)
    commands = [configure, build_receipt]
    executable = build / "grade-school"
    if build_receipt.launch_error:
        return invalid("1E", "CMake build process could not start", commands)
    if build_receipt.return_code != 0 or not executable.is_file():
        return failed("1E", "clean CMake build failed", commands, {"executable_exists": executable.is_file()})
    return passed("1E", "clean CMake target built", commands, artifacts=artifact_entry(executable))


if __name__ == "__main__":
    sys.exit(run_candidate_policy("1", "Build, Compilation, and Linking Integrity", Path(__file__), [verify_1a_implementation_compile, verify_1b_official_consumer_compile, verify_1c_external_consumer_compile, verify_1d_external_consumer_link, verify_1e_clean_cmake_build], "gcc", "g++"))
