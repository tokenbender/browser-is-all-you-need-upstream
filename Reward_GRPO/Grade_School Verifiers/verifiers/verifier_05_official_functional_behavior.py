
from __future__ import annotations

import sys
from pathlib import Path

from _grade_school_common import EXPECTED_TESTS, GCC_FLAGS, CandidateContext, KernelReceipt, artifact_entry, failed, invalid, passed, run_candidate_policy, run_command


def _build_official(ctx: CandidateContext, kernel_id: str, name: str) -> tuple[KernelReceipt | None, Path, object]:
    executable = ctx.output_dir / "artifacts" / f"{kernel_id.lower()}_{name}"
    executable.parent.mkdir(parents=True, exist_ok=True)
    command = [ctx.compiler, *GCC_FLAGS, "-DEXERCISM_RUN_ALL_TESTS", f"-I{ctx.exercise_dir}", f"-I{ctx.exercise_dir / 'test'}", str(ctx.exercise_dir / "grade_school_test.cpp"), str(ctx.exercise_dir / "grade_school.cpp"), str(ctx.exercise_dir / "test/tests-main.cpp"), "-o", str(executable)]
    built = run_command(ctx.output_dir, kernel_id, f"{name}_build", command, 60)
    if built.launch_error:
        return invalid(kernel_id, "compiler could not start", [built]), executable, built
    if built.return_code != 0 or not executable.is_file():
        return failed(kernel_id, "official executable build failed", [built]), executable, built
    return None, executable, built


def verify_5a_complete_test_selection(ctx: CandidateContext) -> KernelReceipt:
    early, executable, built = _build_official(ctx, "5A", "selection")
    if early:
        return early
    listed = run_command(ctx.output_dir, "5A", "list_tests", [str(executable), "--list-test-names-only"], 10)
    commands = [built, listed]
    if listed.launch_error:
        return invalid("5A", "official executable could not start", commands)
    observed = tuple(line.strip() for line in Path(listed.stdout_log).read_text(encoding="utf-8").splitlines() if line.strip())
    if listed.return_code not in {0, 8} or set(observed) != set(EXPECTED_TESTS) or len(observed) != 8:
        return failed("5A", "complete official test selection was not proven", commands, {"observed_tests": observed, "expected_tests": EXPECTED_TESTS})
    return passed("5A", "exactly eight pinned official tests are selected", commands, {"observed_tests": observed}, artifact_entry(executable))


def verify_5b_official_suite(ctx: CandidateContext) -> KernelReceipt:
    early, executable, built = _build_official(ctx, "5B", "official")
    if early:
        return early
    run = run_command(ctx.output_dir, "5B", "official_suite", [str(executable)], 30)
    commands = [built, run]
    if run.launch_error:
        return invalid("5B", "official executable could not start", commands)
    output = Path(run.stdout_log).read_text(encoding="utf-8") + Path(run.stderr_log).read_text(encoding="utf-8")
    complete = "All tests passed (8 assertions in 8 test cases)" in output
    if run.return_code != 0 or run.timed_out or not complete:
        return failed("5B", "complete official suite did not pass", commands, {"complete_summary": complete})
    return passed("5B", "all eight official tests passed", commands, {"selected": 8, "passed": 8}, artifact_entry(executable))


def verify_5c_deterministic_repetition(ctx: CandidateContext) -> KernelReceipt:
    early, executable, built = _build_official(ctx, "5C", "repeat")
    if early:
        return early
    commands = [built]
    summaries: list[bool] = []
    for index in range(1, 4):
        run = run_command(ctx.output_dir, "5C", f"official_repeat_{index}", [str(executable)], 30)
        commands.append(run)
        if run.launch_error:
            return invalid("5C", "official repeat could not start", commands)
        output = Path(run.stdout_log).read_text(encoding="utf-8") + Path(run.stderr_log).read_text(encoding="utf-8")
        summaries.append(run.return_code == 0 and not run.timed_out and "All tests passed (8 assertions in 8 test cases)" in output)
    if summaries != [True, True, True]:
        return failed("5C", "official outcomes were not three stable 8/8 passes", commands, {"successful_runs": summaries})
    return passed("5C", "official 8/8 result repeated three times", commands, {"successful_runs": summaries}, artifact_entry(executable))


if __name__ == "__main__":
    sys.exit(run_candidate_policy("5", "Complete Official Functional Behavior", Path(__file__), [verify_5a_complete_test_selection, verify_5b_official_suite, verify_5c_deterministic_repetition], "gcc", "g++"))
