# Policy 4 verifier: prove a self-contained Grade School header and compiler-resolved ownership of every local dependency.
from __future__ import annotations

import shlex
import sys
from pathlib import Path

from _grade_school_common import GCC_FLAGS, CandidateContext, KernelReceipt, artifact_entry, command_result, failed, invalid, passed, run_candidate_policy, run_command, sha256, write_probe


HEADER_PROBE = """#include \"grade_school.h\"

int main() {
    return 0;
}
"""


def verify_4a_header_self_contained(ctx: CandidateContext) -> KernelReceipt:
    probe = write_probe(ctx, "4A", "header_self_contained", HEADER_PROBE)
    output = ctx.output_dir / "artifacts" / "4a_header.o"
    output.parent.mkdir(parents=True, exist_ok=True)
    receipt = run_command(ctx.output_dir, "4A", "header_compile", [ctx.compiler, *GCC_FLAGS, f"-I{ctx.exercise_dir}", "-c", str(probe), "-o", str(output)], 30)
    artifacts = {str(probe): sha256(probe)}
    if receipt.return_code == 0 and output.is_file():
        artifacts.update(artifact_entry(output))
    return command_result("4A", receipt, "header is self-contained", "header requires an incidental include", artifacts)


def _dependency_compile(ctx: CandidateContext, kernel_id: str) -> tuple[KernelReceipt | None, list[str], Path, object]:
    dependency = ctx.output_dir / "artifacts" / f"{kernel_id.lower()}_dependencies.d"
    output = ctx.output_dir / "artifacts" / f"{kernel_id.lower()}_implementation.o"
    dependency.parent.mkdir(parents=True, exist_ok=True)
    command = [ctx.compiler, *GCC_FLAGS, "-MMD", "-MF", str(dependency), f"-I{ctx.exercise_dir}", "-c", str(ctx.exercise_dir / "grade_school.cpp"), "-o", str(output)]
    receipt = run_command(ctx.output_dir, kernel_id, "dependency_compile", command, 30)
    if receipt.launch_error:
        return invalid(kernel_id, "compiler could not start", [receipt]), [], dependency, receipt
    if receipt.return_code != 0 or not dependency.is_file():
        return failed(kernel_id, "candidate dependency compilation failed", [receipt]), [], dependency, receipt
    text = dependency.read_text(encoding="utf-8").replace("\\\n", " ")
    payload = text.split(":", 1)[1] if ":" in text else ""
    dependencies = shlex.split(payload)
    return None, dependencies, dependency, receipt


def verify_4b_implementation_owns_header(ctx: CandidateContext) -> KernelReceipt:
    early, dependencies, dependency, receipt_value = _dependency_compile(ctx, "4B")
    if early:
        return early
    resolved = {Path(item).resolve() for item in dependencies}
    header = (ctx.exercise_dir / "grade_school.h").resolve()
    if header not in resolved:
        return failed("4B", "implementation dependency graph omits grade_school.h", [receipt_value], {"dependencies": sorted(str(item) for item in resolved)})
    return passed("4B", "implementation owns its public header", [receipt_value], {"dependencies": sorted(str(item) for item in resolved)}, artifact_entry(dependency))


def verify_4c_no_unowned_local_dependencies(ctx: CandidateContext) -> KernelReceipt:
    early, dependencies, dependency, receipt_value = _dependency_compile(ctx, "4C")
    if early:
        return early
    allowed = {(ctx.exercise_dir / "grade_school.cpp").resolve(), (ctx.exercise_dir / "grade_school.h").resolve()}
    resolved = {Path(item).resolve() for item in dependencies}
    unowned = sorted(str(item) for item in resolved - allowed)
    if unowned:
        return failed("4C", "candidate uses unowned non-system dependencies", [receipt_value], {"unowned": unowned})
    return passed("4C", "all non-system dependencies are authorized", [receipt_value], {"dependencies": sorted(str(item) for item in resolved)}, artifact_entry(dependency))


if __name__ == "__main__":
    sys.exit(run_candidate_policy("4", "Header and Dependency Ownership", Path(__file__), [verify_4a_header_self_contained, verify_4b_implementation_owns_header, verify_4c_no_unowned_local_dependencies], "gcc", "g++"))
