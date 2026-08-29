
from __future__ import annotations

import sys
from pathlib import Path

from _grade_school_common import GCC_FLAGS, CandidateContext, KernelReceipt, artifact_entry, failed, invalid, passed, run_candidate_policy, run_command, sha256, write_probe


SANITIZER_SMOKE = """int main() {
    return 0;
}
"""

SEMANTIC = """#include \"grade_school.h\"
#include <algorithm>
#include <iomanip>
#include <map>
#include <random>
#include <sstream>
#include <string>
#include <vector>

int main() {
    std::vector<std::string> names;
    for (int index = 0; index < 128; ++index) {
        std::ostringstream stream;
        stream << "student_" << std::setw(3) << std::setfill('0') << index;
        names.push_back(stream.str());
    }
    std::mt19937 generator(0x47524144u);
    std::shuffle(names.begin(), names.end(), generator);
    const std::vector<int> grades{1, 2, 3, 10, 11};
    grade_school::school candidate{};
    std::map<int, std::vector<std::string>> oracle;
    for (std::size_t index = 0; index < names.size(); ++index) {
        const int grade = grades[(index * 7u + 3u) % grades.size()];
        candidate.add(names[index], grade);
        oracle[grade].push_back(names[index]);
        std::sort(oracle[grade].begin(), oracle[grade].end());
        if (candidate.roster() != oracle) return 1;
        if (candidate.grade(grade) != oracle[grade]) return 2;
    }
    return 0;
}
"""

STRESS = """#include \"grade_school.h\"
#include <algorithm>
#include <map>
#include <string>
#include <vector>

int main() {
    const std::vector<int> grades{1, 2, 3, 10, 11};
    for (int school_index = 0; school_index < 100; ++school_index) {
        grade_school::school candidate{};
        std::map<int, std::vector<std::string>> oracle;
        for (int index = 0; index < 128; ++index) {
            const std::string name = "student_" + std::to_string(school_index) + "_" + std::to_string(index);
            const int grade = grades[(index * 7 + school_index) % static_cast<int>(grades.size())];
            candidate.add(name, grade);
            oracle[grade].push_back(name);
            std::sort(oracle[grade].begin(), oracle[grade].end());
            if (candidate.roster() != oracle) return 1;
            if (candidate.grade(grade) != oracle[grade]) return 2;
        }
    }
    return 0;
}
"""


def _environment() -> dict[str, str]:
    return {"ASAN_OPTIONS": "halt_on_error=1:detect_leaks=0", "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"}


def _sanitizer_preflight(ctx: CandidateContext, kernel_id: str, flags: list[str]) -> tuple[KernelReceipt | None, list[object]]:
    probe = write_probe(ctx, kernel_id, "sanitizer_runtime", SANITIZER_SMOKE)
    executable = ctx.output_dir / "artifacts" / f"{kernel_id.lower()}_sanitizer_runtime"
    executable.parent.mkdir(parents=True, exist_ok=True)
    built = run_command(ctx.output_dir, kernel_id, "sanitizer_preflight_build", [ctx.compiler, "-std=c++17", *flags, str(probe), "-o", str(executable)], 30)
    if built.launch_error or built.return_code != 0 or not executable.is_file():
        return invalid(kernel_id, "required sanitizer toolchain is unavailable", [built]), [built]
    run = run_command(ctx.output_dir, kernel_id, "sanitizer_preflight_run", [str(executable)], 10, env_extra=_environment())
    commands = [built, run]
    if run.launch_error or run.return_code != 0 or run.timed_out:
        return invalid(kernel_id, "required sanitizer runtime is unusable", commands), commands
    return None, commands


def _official(ctx: CandidateContext, kernel_id: str, flags: list[str], label: str) -> KernelReceipt:
    early, preflight_commands = _sanitizer_preflight(ctx, kernel_id, flags)
    if early:
        return early
    executable = ctx.output_dir / "artifacts" / f"{kernel_id.lower()}_{label}"
    command = [ctx.compiler, *GCC_FLAGS, *flags, "-DEXERCISM_RUN_ALL_TESTS", f"-I{ctx.exercise_dir}", f"-I{ctx.exercise_dir / 'test'}", str(ctx.exercise_dir / "grade_school_test.cpp"), str(ctx.exercise_dir / "grade_school.cpp"), str(ctx.exercise_dir / "test/tests-main.cpp"), "-o", str(executable)]
    built = run_command(ctx.output_dir, kernel_id, f"{label}_build", command, 60)
    commands = [*preflight_commands, built]
    if built.launch_error:
        return invalid(kernel_id, "sanitizer compiler process could not start", commands)
    if built.return_code != 0 or not executable.is_file():
        return failed(kernel_id, f"candidate did not compile under {label}", commands)
    run = run_command(ctx.output_dir, kernel_id, f"{label}_official", [str(executable)], 60, env_extra=_environment())
    commands.append(run)
    if run.launch_error:
        return invalid(kernel_id, "sanitized candidate executable could not start", commands)
    output = Path(run.stdout_log).read_text(encoding="utf-8") + Path(run.stderr_log).read_text(encoding="utf-8")
    if run.return_code != 0 or run.timed_out or "All tests passed (8 assertions in 8 test cases)" not in output:
        return failed(kernel_id, f"official suite failed under {label}", commands)
    return passed(kernel_id, f"official suite passed under {label}", commands, {"selected": 8, "passed": 8}, artifact_entry(executable))


def _probe(ctx: CandidateContext, kernel_id: str, name: str, source: str, repetitions: int) -> KernelReceipt:
    flags = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-omit-frame-pointer"]
    early, preflight_commands = _sanitizer_preflight(ctx, kernel_id, flags)
    if early:
        return early
    probe = write_probe(ctx, kernel_id, name, source)
    executable = ctx.output_dir / "artifacts" / f"{kernel_id.lower()}_{name}"
    built = run_command(ctx.output_dir, kernel_id, f"{name}_build", [ctx.compiler, *GCC_FLAGS, *flags, f"-I{ctx.exercise_dir}", str(probe), str(ctx.exercise_dir / "grade_school.cpp"), "-o", str(executable)], 60)
    commands = [*preflight_commands, built]
    if built.launch_error:
        return invalid(kernel_id, "combined sanitizer compiler could not start", commands)
    if built.return_code != 0 or not executable.is_file():
        return failed(kernel_id, "candidate did not compile under combined sanitizers", commands)
    outcomes: list[int] = []
    for index in range(1, repetitions + 1):
        run = run_command(ctx.output_dir, kernel_id, f"{name}_run_{index}", [str(executable)], 60, env_extra=_environment())
        commands.append(run)
        if run.launch_error:
            return invalid(kernel_id, "sanitized semantic executable could not start", commands)
        outcomes.append(run.return_code)
        if run.return_code != 0 or run.timed_out:
            return failed(kernel_id, "sanitized semantic or stress execution failed", commands, {"outcomes": outcomes})
    return passed(kernel_id, "sanitized semantic or stress executions passed", commands, {"outcomes": outcomes, "repetitions": repetitions}, {str(probe): sha256(probe), **artifact_entry(executable)})


def verify_9a_asan_official(ctx: CandidateContext) -> KernelReceipt:
    return _official(ctx, "9A", ["-fsanitize=address", "-fno-omit-frame-pointer"], "asan")


def verify_9b_ubsan_official(ctx: CandidateContext) -> KernelReceipt:
    return _official(ctx, "9B", ["-fsanitize=undefined", "-fno-sanitize-recover=all", "-fno-omit-frame-pointer"], "ubsan")


def verify_9c_combined_semantic_oracle(ctx: CandidateContext) -> KernelReceipt:
    return _probe(ctx, "9C", "combined_semantic_oracle", SEMANTIC, 1)


def verify_9d_repeated_sanitized_stress(ctx: CandidateContext) -> KernelReceipt:
    return _probe(ctx, "9D", "repeated_sanitized_stress", STRESS, 3)


if __name__ == "__main__":
    sys.exit(run_candidate_policy("9", "Memory and Undefined-Behavior Safety", Path(__file__), [verify_9a_asan_official, verify_9b_ubsan_official, verify_9c_combined_semantic_oracle, verify_9d_repeated_sanitized_stress], "gcc", "g++"))
