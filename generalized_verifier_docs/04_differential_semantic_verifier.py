#!/usr/bin/env python3
"""
Verifier 04: Differential Semantic Verifier (generalized).

1. Positive control: build the fixture's reference implementation
   (.meta/example.h/.cpp) against the official test and run it; it must
   pass 100% of assertions, else the task package is reported broken
   (TASK_PACKAGE_BROKEN).
2. Build the candidate with the two-stage builder from
   03_two_stage_build_verifier.py (CE/LE classification on failure).
3. Require return from the official test entry point, witnessed on a separate
   completion pipe, and a healthy process exit before awarding PASS.
4. Keep printed assertion counts as diagnostic failure shaping only. Neither
   stdout nor floating-point scores establish successful execution.

    python3 04_differential_semantic_verifier.py --fixture-dir <dir> \
        --header candidate.h [--source candidate.cpp] \
        [--reference-header h --reference-source cpp] [--json]
"""

import argparse
import importlib.util
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys

# Import the two-stage builder from the sibling module (filename starts with
# a digit, so importlib is needed).
_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "twostage", os.path.join(_HERE, "03_two_stage_build_verifier.py"))
_twostage = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_twostage)
build_candidate = _twostage.build_candidate

# Separate, bounded cleanup budgets; neither extends candidate execution time.
POST_KILL_DRAIN_SECONDS = 0.25
POST_KILL_REAP_SECONDS = 0.25


# ---------------------------------------------------------------------------
# Catch2 output parsing
# ---------------------------------------------------------------------------

class TestRun:
    def __init__(self, returncode, passed, total, failed_cases, raw_tail,
                 crashed=False, timed_out=False, timeout_seconds=None,
                 infrastructure_error=None):
        self.returncode, self.passed, self.total = returncode, passed, total
        self.failed_cases, self.raw_tail = failed_cases, raw_tail
        self.crashed, self.timed_out = crashed, timed_out
        self.timeout_seconds = timeout_seconds
        self.infrastructure_error = infrastructure_error
        self.execution_completed = False
        self.harness_returncode = None
        self.runtime_diagnostic = None
        self.output_drain_timed_out = False
        self.cleanup_timed_out = False

    @property
    def verified_pass(self):
        return (self.execution_completed and self.harness_returncode == 0
                and self.returncode == 0 and not self.crashed
                and not self.timed_out and not self.infrastructure_error
                and self.total > 0 and self.passed == self.total)

    @property
    def score(self):
        if self.verified_pass:
            return 1.0
        if (not self.execution_completed or self.crashed or self.infrastructure_error
                or self.timed_out or self.returncode is None or self.returncode < 0
                or not self.total or self.passed == self.total):
            return 0.0
        # Counts are untrusted diagnostics. Even float conversion of very large
        # counts must not promote a failed execution to a full score.
        return min(self.passed / self.total, math.nextafter(1.0, 0.0))

    def as_dict(self):
        signaled = self.returncode is not None and self.returncode < 0
        return {"passed_assertions": self.passed,
                "total_assertions": self.total,
                "score": self.score,
                "verified_pass": self.verified_pass,
                "execution_completed": self.execution_completed,
                "harness_returncode": self.harness_returncode,
                "infrastructure_error": bool(self.infrastructure_error),
                "runtime_diagnostic": self.runtime_diagnostic,
                "output_drain_timed_out": self.output_drain_timed_out,
                "cleanup_timed_out": self.cleanup_timed_out,
                "failed_test_cases": self.failed_cases,
                "crashed": self.crashed,
                "returncode": self.returncode,
                "timed_out": self.timed_out,
                "timeout_seconds": self.timeout_seconds,
                "failure_kind": (self.infrastructure_error or
                                 ("runtime_timeout" if self.timed_out else
                                  "signal" if signaled else
                                  "incomplete_test_execution" if not self.execution_completed else
                                  "incomplete_test_output" if self.crashed else
                                  "assertion_failure" if not self.verified_pass else None)),
                "signal": -self.returncode if signaled and not self.timed_out
                          and not self.infrastructure_error else None,
                "raw_tail": self.raw_tail[-4000:]}


_ALL_PASS_RE = re.compile(
    r'All tests passed\s*\((\d+) assertions? in (\d+) test cases?\)')
# Catch2 prints "assertions: <total> | <n> passed | <n> failed" but omits a
# column entirely when its count is zero ("assertions: 17 | 17 failed").
_SUMMARY_LINE_RE = re.compile(r'^assertions:\s*(.+)$', re.MULTILINE)
_COUNT_RE = re.compile(r'(\d+)\s*(passed|failed)')
_FAILED_CASE_RE = re.compile(r'^-{10,}\n(.+?)\n-{10,}', re.MULTILINE)


def parse_catch2_output(output, returncode):
    try:
        return _parse_catch2_output(output, returncode)
    except ValueError:
        # Includes Python's limit on integer conversion of hostile count text.
        return TestRun(returncode, 0, 0, [], output[-4000:], crashed=True)


def _parse_catch2_output(output, returncode):
    all_pass_matches = list(_ALL_PASS_RE.finditer(output))
    summary_matches = list(_SUMMARY_LINE_RE.finditer(output))
    all_pass = all_pass_matches[0] if len(all_pass_matches) == 1 else None
    if all_pass and not summary_matches and returncode == 0:
        total = int(all_pass.group(1))
        return TestRun(returncode, total, total, [],
                       "\n".join(output.splitlines()[-5:]))
    summary = summary_matches[0] if len(summary_matches) == 1 else None
    if summary and not all_pass_matches and returncode >= 0:
        fields = summary.group(1)
        columns = [column.strip() for column in fields.split("|")]
        total_m = re.fullmatch(r'\d+', columns[0])
        matches = [re.fullmatch(r'(\d+)\s+(passed|failed)', column)
                   for column in columns[1:]]
        if total_m and matches and all(matches):
            counts = {match.group(2): int(match.group(1)) for match in matches}
            total = int(total_m.group())
            if len(counts) == len(matches) and total > 0 and sum(counts.values()) == total:
                passed = counts.get("passed", 0)
                cases = [m.group(1).strip() for m in _FAILED_CASE_RE.finditer(output)]
                return TestRun(returncode, passed, total, cases,
                               "\n".join(output.splitlines()[-10:]))
        # Malformed, duplicated or inconsistent counts are candidate output
        # failures, never parser exceptions or invented partial correctness.
    # No recognizable summary: binary crashed or aborted mid-run.
    return TestRun(returncode, 0, 0, [],
                   "\n".join(output.splitlines()[-10:]), crashed=True)


def _kill_process_group(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _timeout_output(error):
    # TimeoutExpired.output is bytes even when Popen is in text mode. A second
    # communicate timeout includes all output collected so far, not a new chunk.
    output = error.output or ""
    return output.decode("utf-8", errors="replace") if isinstance(output, bytes) else output


def run_test_binary(binary, timeout=120, *, completion_token=None):
    read_fd = write_fd = None
    proc = run = None
    try:
        read_fd, write_fd = os.pipe2(os.O_CLOEXEC | os.O_NONBLOCK)
        environment = dict(os.environ, G03_COMPLETION_FD=str(write_fd))
        proc = subprocess.Popen([binary], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace", env=environment,
                                pass_fds=(write_fd,), start_new_session=True)
        try:
            output, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            _kill_process_group(proc)
            output = _timeout_output(error)
            drain_timed_out = False
            try:
                output, _ = proc.communicate(timeout=POST_KILL_DRAIN_SECONDS)
            except subprocess.TimeoutExpired as drain_error:
                drain_timed_out = True
                if drain_error.output is not None:
                    output = _timeout_output(drain_error)
                # An escaped descendant may hold the pipe open. Stop waiting
                # for EOF; the finally block closes our read end and boundedly
                # reaps the direct child without changing timeout attribution.
            run = TestRun(proc.poll(), 0, 0, [], output[-4000:], crashed=True,
                          timed_out=True, timeout_seconds=timeout)
            run.output_drain_timed_out = drain_timed_out
        else:
            run = parse_catch2_output(output, proc.returncode)
            try:
                completion = os.read(read_fd, 4096).decode("ascii")
            except (BlockingIOError, UnicodeError):
                completion = ""
            if completion_token:
                match = re.fullmatch(re.escape(completion_token) + r":(-?\d+)\n", completion)
                if match:
                    run.harness_returncode = int(match.group(1))
                    run.execution_completed = (proc.returncode >= 0 and
                                               run.harness_returncode % 256 == proc.returncode)
            # Completion/process status precedes candidate-generated text.
            # No launch failure was reported by Popen; text alone cannot turn
            # even an incomplete/early-exit candidate into INVALID.
            run.infrastructure_error = _twostage.runtime_infrastructure_failure(
                output, execution_completed=run.execution_completed)
        run.runtime_diagnostic = _twostage.runtime_failure_diagnostic(output)
    except OSError as error:
        run = TestRun(-1, 0, 0, [], str(error), crashed=True,
                      infrastructure_error=_twostage.runtime_infrastructure_failure(
                          str(error), launch_error=error))
        run.runtime_diagnostic = _twostage.runtime_failure_diagnostic(str(error))
    finally:
        if proc is not None:
            _kill_process_group(proc)
            if proc.stdout is not None:
                proc.stdout.close()
            try:
                proc.wait(timeout=POST_KILL_REAP_SECONDS)
            except subprocess.TimeoutExpired:
                if run is not None:
                    run.cleanup_timed_out = True
            if run is not None and run.returncode is None:
                run.returncode = proc.returncode
        for fd in (read_fd, write_fd):
            if fd is not None:
                os.close(fd)
    return run


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

def verify(fixture_dir, header, source=None,
           reference_header=None, reference_source=None):
    report = {"verdict": "INVALID", "score": 0.0,
              "candidate": {"status": "NOT_RUN"}}
    if reference_header is None:
        reference_header = os.path.join(fixture_dir, ".meta", "example.h")
    if reference_source is None:
        cpp = os.path.join(fixture_dir, ".meta", "example.cpp")
        reference_source = cpp if os.path.exists(cpp) else None

    if not os.path.exists(reference_header):
        report["reference"] = {"status": "MISSING", "detail": f"no reference at {reference_header}"}
        return report
    ref_build = build_candidate(fixture_dir, reference_header, reference_source,
                                authenticate_main=True)
    try:
        if ref_build.status != "PASS":
            report["reference"] = {"status": "BUILD_FAIL", "detail": ref_build.as_dict()}
            return report
        ref_run = run_test_binary(ref_build.binary, completion_token=ref_build.completion_token)
        report["reference"] = {"status": "OK" if ref_run.verified_pass else "TASK_PACKAGE_BROKEN",
                               "run": ref_run.as_dict()}
    finally:
        if ref_build.workspace:
            shutil.rmtree(ref_build.workspace, ignore_errors=True)
    if report["reference"]["status"] != "OK":
        return report

    cand_build = build_candidate(fixture_dir, header, source, authenticate_main=True)
    try:
        if cand_build.status != "PASS":
            report["candidate"] = {"status": "BUILD_FAIL", "build": cand_build.as_dict()}
            report["verdict"] = "INVALID" if cand_build.status == "ERROR" else "FAIL"
            return report
        run = run_test_binary(cand_build.binary, completion_token=cand_build.completion_token)
        report["candidate"] = {"status": "RAN", "run": run.as_dict()}
    finally:
        if cand_build.workspace:
            shutil.rmtree(cand_build.workspace, ignore_errors=True)

    report["verdict"] = "INVALID" if run.infrastructure_error else "PASS" if run.verified_pass else "FAIL"
    report["score"] = run.score
    if not run.verified_pass:
        report["differential"] = (
            f"candidate {run.as_dict()['failure_kind']}; process exit {run.returncode}, "
            f"official main completed={run.execution_completed}; "
            f"reported assertions {run.passed}/{run.total} (diagnostic counts, not proof of execution)")
        if run.failed_cases:
            report["differential_failed_cases"] = run.failed_cases
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Differential semantic verifier: reference positive "
                    "control + partial-credit assertion scoring.")
    ap.add_argument("--fixture-dir", required=True)
    ap.add_argument("--header", required=True, help="candidate header")
    ap.add_argument("--source", default=None, help="candidate .cpp")
    ap.add_argument("--reference-header", default=None,
                    help="override reference header (default: "
                         "<fixture>/.meta/example.h)")
    ap.add_argument("--reference-source", default=None,
                    help="override reference .cpp (default: "
                         "<fixture>/.meta/example.cpp if present)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--receipt", default=None, metavar="DIR",
                    help="also write a sandbox-compatible kernel receipt "
                         "(<verifier>_kernel_receipt.json) into DIR")
    args = ap.parse_args(argv)
    if args.receipt:
        import receipt_compat
        return receipt_compat.run_with_receipt(args.receipt, run, args, argv)
    return run(args)


def run(args):
    report = verify(args.fixture_dir, args.header, args.source,
                    args.reference_header, args.reference_source)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("--- Differential Semantic Verifier ---")
        ref = report.get("reference", {})
        print(f"Positive control (reference): {ref.get('status')}"
              + (f" run={ref['run']}" if "run" in ref else ""))
        cand = report.get("candidate", {})
        if cand.get("status") == "BUILD_FAIL":
            print(f"Candidate: BUILD_FAIL "
                  f"({cand['build']['status']}: {cand['build']['feedback']})")
        elif cand.get("status") == "RAN":
            run = cand["run"]
            print(f"Candidate: {run['passed_assertions']}/"
                  f"{run['total_assertions']} assertions passed "
                  f"(score {run['score']})")
            for case in run.get("failed_test_cases", []):
                print(f"  failing case: {case}")
        if "differential" in report:
            print(f"Differential: {report['differential']}")
        if "warning" in report:
            print(f"WARNING: {report['warning']}")
        print(f"VERDICT: {report['verdict']} (score {report['score']})")
    return {"PASS": 0, "FAIL": 1}.get(report["verdict"], 2)


if __name__ == "__main__":
    sys.exit(main())
