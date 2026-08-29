
from __future__ import annotations

import sys
from pathlib import Path

from _grade_school_common import GCC_FLAGS, CandidateContext, KernelReceipt, artifact_entry, command_result, failed, invalid, passed, run_candidate_policy, run_command, sha256, write_probe


HEADER_CONSUMER = """#include \"grade_school.h\"

int main() {
    grade_school::school value{};
    return value.roster().empty() ? 0 : 0;
}
"""

API_CONSUMER = """#include \"grade_school.h\"
#include <map>
#include <string>
#include <vector>

using School = grade_school::school;
using RosterMethod = const std::map<int, std::vector<std::string>>& (School::*)() const;
using AddMethod = void (School::*)(std::string const&, int);
using GradeMethod = std::vector<std::string> (School::*)(int) const;

int main() {
    const auto roster_method = static_cast<RosterMethod>(&School::roster);
    const auto add_method = static_cast<AddMethod>(&School::add);
    const auto grade_method = static_cast<GradeMethod>(&School::grade);
    School value{};
    (value.*add_method)("Aimee", 2);
    (void)(value.*grade_method)(2);
    (void)(value.*roster_method)();
    return 0;
}
"""


def _official_build(ctx: CandidateContext, kernel_id: str, label: str) -> tuple[KernelReceipt | None, Path, object]:
    executable = ctx.output_dir / "artifacts" / f"{kernel_id.lower()}_{label}"
    executable.parent.mkdir(parents=True, exist_ok=True)
    command = [ctx.compiler, *GCC_FLAGS, "-DEXERCISM_RUN_ALL_TESTS", f"-I{ctx.exercise_dir}", f"-I{ctx.exercise_dir / 'test'}", str(ctx.exercise_dir / "grade_school_test.cpp"), str(ctx.exercise_dir / "grade_school.cpp"), str(ctx.exercise_dir / "test/tests-main.cpp"), "-o", str(executable)]
    built = run_command(ctx.output_dir, kernel_id, f"{label}_build", command, 60)
    if built.launch_error:
        return invalid(kernel_id, "Clang process could not start", [built]), executable, built
    if built.return_code != 0 or not executable.is_file():
        return failed(kernel_id, "candidate did not build under Clang", [built]), executable, built
    return None, executable, built


def _run_official(ctx: CandidateContext, kernel_id: str, label: str) -> tuple[KernelReceipt | None, list[object], Path]:
    early, executable, built = _official_build(ctx, kernel_id, label)
    if early:
        return early, [built], executable
    run = run_command(ctx.output_dir, kernel_id, f"{label}_run", [str(executable)], 30)
    commands = [built, run]
    if run.launch_error:
        return invalid(kernel_id, "Clang-built executable could not start", commands), commands, executable
    output = Path(run.stdout_log).read_text(encoding="utf-8") + Path(run.stderr_log).read_text(encoding="utf-8")
    if run.return_code != 0 or run.timed_out or "All tests passed (8 assertions in 8 test cases)" not in output:
        return failed(kernel_id, "Clang official suite failed", commands), commands, executable
    return None, commands, executable


def verify_10a_clang_strict_compile(ctx: CandidateContext) -> KernelReceipt:
    probe = write_probe(ctx, "10A", "clang_header_consumer", HEADER_CONSUMER)
    executable = ctx.output_dir / "artifacts" / "10a_clang_compile"
    executable.parent.mkdir(parents=True, exist_ok=True)
    receipt = run_command(ctx.output_dir, "10A", "clang_strict_compile", [ctx.compiler, *GCC_FLAGS, f"-I{ctx.exercise_dir}", str(probe), str(ctx.exercise_dir / "grade_school.cpp"), "-o", str(executable)], 30)
    artifacts = {str(probe): sha256(probe)}
    if receipt.return_code == 0 and executable.is_file():
        artifacts.update(artifact_entry(executable))
    return command_result("10A", receipt, "candidate compiled warning-clean under Clang", "Clang rejected candidate-controlled code", artifacts)


def verify_10b_clang_api_link(ctx: CandidateContext) -> KernelReceipt:
    probe = write_probe(ctx, "10B", "clang_exact_api", API_CONSUMER)
    executable = ctx.output_dir / "artifacts" / "10b_clang_api"
    executable.parent.mkdir(parents=True, exist_ok=True)
    built = run_command(ctx.output_dir, "10B", "clang_api_link", [ctx.compiler, *GCC_FLAGS, f"-I{ctx.exercise_dir}", str(probe), str(ctx.exercise_dir / "grade_school.cpp"), "-o", str(executable)], 30)
    if built.launch_error:
        return invalid("10B", "Clang process could not start", [built])
    if built.return_code != 0 or not executable.is_file():
        return failed("10B", "exact API did not compile and link under Clang", [built])
    run = run_command(ctx.output_dir, "10B", "clang_api_run", [str(executable)], 10)
    commands = [built, run]
    if run.launch_error:
        return invalid("10B", "Clang API executable could not start", commands)
    if run.return_code != 0 or run.timed_out:
        return failed("10B", "Clang API executable failed", commands)
    return passed("10B", "exact API linked and ran under Clang", commands, artifacts={str(probe): sha256(probe), **artifact_entry(executable)})


def verify_10c_clang_official_suite(ctx: CandidateContext) -> KernelReceipt:
    early, commands, executable = _run_official(ctx, "10C", "clang_official")
    if early:
        return early
    return passed("10C", "all eight official tests passed under Clang", commands, {"selected": 8, "passed": 8}, artifact_entry(executable))


def verify_10d_clean_reproduction(ctx: CandidateContext) -> KernelReceipt:
    all_commands: list[object] = []
    results: list[bool] = []
    artifacts: dict[str, str] = {}
    for index in (1, 2):
        early, commands, executable = _run_official(ctx, "10D", f"clean_reproduction_{index}")
        all_commands.extend(commands)
        if early:
            return early
        results.append(True)
        artifacts.update(artifact_entry(executable))
    if results != [True, True]:
        return failed("10D", "clean Clang reproduction was inconsistent", all_commands, {"results": results})
    return passed("10D", "two fresh Clang builds reproduced an 8/8 pass", all_commands, {"results": results}, artifacts)


if __name__ == "__main__":
    sys.exit(run_candidate_policy("10", "Cross-Compiler Portability", Path(__file__), [verify_10a_clang_strict_compile, verify_10b_clang_api_link, verify_10c_clang_official_suite, verify_10d_clean_reproduction], "clang", "clang++"))
