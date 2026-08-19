# Policy 3 verifier: prove four independent Grade School public type, name, signature, and linked API boundaries.
from __future__ import annotations

import sys
from pathlib import Path

from _grade_school_common import GCC_FLAGS, CandidateContext, KernelReceipt, artifact_entry, command_result, failed, invalid, passed, run_candidate_policy, run_command, sha256, write_probe


TYPE_PROBE = """#include \"grade_school.h\"
#include <type_traits>

static_assert(std::is_default_constructible_v<grade_school::school>);

int main() {
    grade_school::school value{};
    (void)value;
    return 0;
}
"""

NAMES_PROBE = """#include \"grade_school.h\"

int main() {
    grade_school::school value{};
    auto roster_method = &grade_school::school::roster;
    auto add_method = &grade_school::school::add;
    auto grade_method = &grade_school::school::grade;
    (void)value;
    (void)roster_method;
    (void)add_method;
    (void)grade_method;
    return 0;
}
"""

SIGNATURE_PROBE = """#include \"grade_school.h\"
#include <map>
#include <string>
#include <vector>

using School = grade_school::school;
using RosterMethod = const std::map<int, std::vector<std::string>>& (School::*)() const;
using AddMethod = void (School::*)(std::string const&, int);
using GradeMethod = std::vector<std::string> (School::*)(int) const;

constexpr RosterMethod roster_method = static_cast<RosterMethod>(&School::roster);
constexpr AddMethod add_method = static_cast<AddMethod>(&School::add);
constexpr GradeMethod grade_method = static_cast<GradeMethod>(&School::grade);

int main() {
    (void)roster_method;
    (void)add_method;
    (void)grade_method;
    return 0;
}
"""

SMOKE_PROBE = """#include \"grade_school.h\"

int main() {
    grade_school::school value{};
    value.add("Aimee", 2);
    (void)value.grade(2);
    (void)value.roster();
    return 0;
}
"""


def _compile_only(ctx: CandidateContext, kernel_id: str, name: str, source: str) -> KernelReceipt:
    probe = write_probe(ctx, kernel_id, name, source)
    output = ctx.output_dir / "artifacts" / f"{kernel_id.lower()}_{name}.o"
    output.parent.mkdir(parents=True, exist_ok=True)
    receipt = run_command(ctx.output_dir, kernel_id, name, [ctx.compiler, *GCC_FLAGS, f"-I{ctx.exercise_dir}", "-c", str(probe), "-o", str(output)], 30)
    artifacts = {str(probe): sha256(probe)}
    if receipt.return_code == 0 and output.is_file():
        artifacts.update(artifact_entry(output))
    return command_result(kernel_id, receipt, f"{name} probe compiled", f"{name} probe rejected the candidate", artifacts)


def verify_3a_public_type(ctx: CandidateContext) -> KernelReceipt:
    return _compile_only(ctx, "3A", "public_type", TYPE_PROBE)


def verify_3b_public_method_names(ctx: CandidateContext) -> KernelReceipt:
    return _compile_only(ctx, "3B", "public_names", NAMES_PROBE)


def verify_3c_exact_signatures(ctx: CandidateContext) -> KernelReceipt:
    return _compile_only(ctx, "3C", "exact_signatures", SIGNATURE_PROBE)


def verify_3d_linked_api_smoke(ctx: CandidateContext) -> KernelReceipt:
    probe = write_probe(ctx, "3D", "linked_api_smoke", SMOKE_PROBE)
    executable = ctx.output_dir / "artifacts" / "3d_api_smoke"
    executable.parent.mkdir(parents=True, exist_ok=True)
    built = run_command(ctx.output_dir, "3D", "smoke_build", [ctx.compiler, *GCC_FLAGS, f"-I{ctx.exercise_dir}", str(probe), str(ctx.exercise_dir / "grade_school.cpp"), "-o", str(executable)], 30)
    if built.launch_error:
        return invalid("3D", "compiler could not start", [built])
    if built.return_code != 0 or not executable.is_file():
        return failed("3D", "exact API did not link", [built])
    run = run_command(ctx.output_dir, "3D", "smoke_run", [str(executable)], 10)
    commands = [built, run]
    if run.launch_error:
        return invalid("3D", "linked probe could not start", commands)
    if run.return_code != 0 or run.timed_out:
        return failed("3D", "linked API smoke execution failed", commands)
    return passed("3D", "exact API linked and was minimally callable", commands, artifacts={str(probe): sha256(probe), **artifact_entry(executable)})


if __name__ == "__main__":
    sys.exit(run_candidate_policy("3", "Exact Public API Contract", Path(__file__), [verify_3a_public_type, verify_3b_public_method_names, verify_3c_exact_signatures, verify_3d_linked_api_smoke], "gcc", "g++"))
