
from __future__ import annotations

import sys
from pathlib import Path

from _grade_school_common import GCC_FLAGS, CandidateContext, KernelReceipt, artifact_entry, failed, invalid, passed, run_candidate_policy, run_command, sha256, write_probe


STATE_SHAPE = """#include \"grade_school.h\"
#include <map>
#include <string>
#include <vector>

int main() {
    grade_school::school value{};
    if (!value.roster().empty()) return 1;
    value.add("Aimee", 2);
    const std::map<int, std::vector<std::string>> one{{2, {"Aimee"}}};
    if (value.roster() != one) return 2;
    value.add("Chelsea", 3);
    value.add("Logan", 7);
    const std::map<int, std::vector<std::string>> many{{2, {"Aimee"}}, {3, {"Chelsea"}}, {7, {"Logan"}}};
    return value.roster() == many ? 0 : 3;
}
"""

ORDERING = """#include \"grade_school.h\"
#include <map>
#include <string>
#include <vector>

int main() {
    grade_school::school value{};
    value.add("Zoe", 10);
    value.add("Franklin", 2);
    value.add("Bradley", 2);
    value.add("Anna", 1);
    value.add("Mira", 11);
    const std::map<int, std::vector<std::string>> expected{{1, {"Anna"}}, {2, {"Bradley", "Franklin"}}, {10, {"Zoe"}}, {11, {"Mira"}}};
    return value.roster() == expected ? 0 : 1;
}
"""

NONMUTATION = """#include \"grade_school.h\"

int main() {
    grade_school::school value{};
    value.add("Aimee", 2);
    const auto before = value.roster();
    const auto missing = value.grade(99);
    const auto after = value.roster();
    if (!missing.empty()) return 1;
    return before == after ? 0 : 2;
}
"""

CONSISTENCY = """#include \"grade_school.h\"

int main() {
    grade_school::school value{};
    value.add("Jennifer", 4);
    value.add("Kareem", 6);
    value.add("Christopher", 4);
    value.add("Kyle", 3);
    const auto baseline = value.roster();
    for (int repeat = 0; repeat < 10; ++repeat) {
        for (const auto& entry : baseline) {
            if (value.grade(entry.first) != entry.second) return 1;
        }
        if (value.roster() != baseline) return 2;
    }
    return 0;
}
"""

GENERATED = """#include \"grade_school.h\"
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
        if (candidate.roster() != oracle) return 10;
        for (const auto& entry : oracle) {
            if (candidate.grade(entry.first) != entry.second) return 11;
        }
        const auto before = candidate.roster();
        if (!candidate.grade(99).empty()) return 12;
        if (candidate.roster() != before) return 13;
    }
    return 0;
}
"""


def _compile_run(ctx: CandidateContext, kernel_id: str, name: str, source: str, facts: dict[str, object] | None = None) -> KernelReceipt:
    probe = write_probe(ctx, kernel_id, name, source)
    executable = ctx.output_dir / "artifacts" / f"{kernel_id.lower()}_{name}"
    executable.parent.mkdir(parents=True, exist_ok=True)
    built = run_command(ctx.output_dir, kernel_id, f"{name}_build", [ctx.compiler, *GCC_FLAGS, f"-I{ctx.exercise_dir}", str(probe), str(ctx.exercise_dir / "grade_school.cpp"), "-o", str(executable)], 30)
    if built.launch_error:
        return invalid(kernel_id, "compiler could not start", [built])
    if built.return_code != 0 or not executable.is_file():
        return failed(kernel_id, f"{name} probe did not compile", [built], facts)
    run = run_command(ctx.output_dir, kernel_id, f"{name}_run", [str(executable)], 10)
    commands = [built, run]
    if run.launch_error:
        return invalid(kernel_id, "semantic probe could not start", commands)
    if run.return_code != 0 or run.timed_out:
        return failed(kernel_id, f"{name} relation failed", commands, {**(facts or {}), "probe_return_code": run.return_code})
    return passed(kernel_id, f"{name} relation passed", commands, facts, {str(probe): sha256(probe), **artifact_entry(executable)})


def verify_6a_exact_state_shape(ctx: CandidateContext) -> KernelReceipt:
    return _compile_run(ctx, "6A", "exact_state_shape", STATE_SHAPE)


def verify_6b_numeric_and_alphabetical_order(ctx: CandidateContext) -> KernelReceipt:
    return _compile_run(ctx, "6B", "numeric_alphabetical_order", ORDERING)


def verify_6c_missing_grade_nonmutation(ctx: CandidateContext) -> KernelReceipt:
    return _compile_run(ctx, "6C", "missing_grade_nonmutation", NONMUTATION)


def verify_6d_grade_roster_consistency(ctx: CandidateContext) -> KernelReceipt:
    return _compile_run(ctx, "6D", "grade_roster_consistency", CONSISTENCY, {"repeated_reads": 10})


def verify_6e_generated_oracle(ctx: CandidateContext) -> KernelReceipt:
    return _compile_run(ctx, "6E", "generated_oracle", GENERATED, {"seed": "0x47524144", "students": 128, "grades": [1, 2, 3, 10, 11]})


if __name__ == "__main__":
    sys.exit(run_candidate_policy("6", "Roster State and Relational Semantics", Path(__file__), [verify_6a_exact_state_shape, verify_6b_numeric_and_alphabetical_order, verify_6c_missing_grade_nonmutation, verify_6d_grade_roster_consistency, verify_6e_generated_oracle], "gcc", "g++"))
