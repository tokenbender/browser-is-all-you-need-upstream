#!/usr/bin/env python3
"""
Verifier 04: Differential Semantic Verifier (generalized).

1. Positive control: build the fixture's reference implementation
   (.meta/example.h/.cpp) against the official test and run it; it must
   pass 100% of assertions, else the task package is reported broken
   (TASK_PACKAGE_BROKEN).
2. Build the candidate with the two-stage builder from
   03_two_stage_build_verifier.py (CE/LE classification on failure).
3. Run the candidate test binary and report passed/total assertions as
   partial credit.
4. Differential check: any assertion the reference passes but the candidate
   fails is reported as a semantic regression.

    python3 04_differential_semantic_verifier.py --fixture-dir <dir> \
        --header candidate.h [--source candidate.cpp] \
        [--reference-header h --reference-source cpp] [--json]
"""

import argparse
import importlib.util
import json
import os
import re
import shutil
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


# ---------------------------------------------------------------------------
# Catch2 output parsing
# ---------------------------------------------------------------------------

class TestRun:
    def __init__(self, returncode, passed, total, failed_cases, raw_tail,
                 crashed=False):
        self.returncode = returncode
        self.passed = passed
        self.total = total
        self.failed_cases = failed_cases
        self.raw_tail = raw_tail
        self.crashed = crashed

    @property
    def score(self):
        return (self.passed / self.total) if self.total else 0.0

    def as_dict(self):
        return {"passed_assertions": self.passed,
                "total_assertions": self.total,
                "score": round(self.score, 4),
                "failed_test_cases": self.failed_cases,
                "crashed": self.crashed}


_ALL_PASS_RE = re.compile(
    r'All tests passed\s*\((\d+) assertions? in (\d+) test cases?\)')
# Catch2 prints "assertions: <total> | <n> passed | <n> failed" but omits a
# column entirely when its count is zero ("assertions: 17 | 17 failed").
_SUMMARY_LINE_RE = re.compile(r'^assertions:\s*(.+)$', re.MULTILINE)
_COUNT_RE = re.compile(r'(\d+)\s*(passed|failed)')
_FAILED_CASE_RE = re.compile(r'^-{10,}\n(.+?)\n-{10,}', re.MULTILINE)


def parse_catch2_output(output, returncode):
    all_pass = _ALL_PASS_RE.search(output)
    if all_pass:
        total = int(all_pass.group(1))
        return TestRun(returncode, total, total, [],
                       "\n".join(output.splitlines()[-5:]))
    summary = _SUMMARY_LINE_RE.search(output)
    if summary:
        fields = summary.group(1)
        total_m = re.match(r'\s*(\d+)', fields)
        counts = {label: n for n, label in
                  _COUNT_RE.findall(fields[len(total_m.group(0)):])}
        total = int(total_m.group(1))
        passed = int(counts.get("passed", 0))
        cases = [m.group(1).strip() for m in _FAILED_CASE_RE.finditer(output)]
        return TestRun(returncode, passed, total, cases,
                       "\n".join(output.splitlines()[-10:]))
    # No recognizable summary: binary crashed or aborted mid-run.
    return TestRun(returncode, 0, 0, [],
                   "\n".join(output.splitlines()[-10:]), crashed=True)


def run_test_binary(binary, timeout=120):
    try:
        proc = subprocess.run([binary], stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True,
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        return TestRun(-1, 0, 0, [], "timed out", crashed=True)
    return parse_catch2_output(proc.stdout, proc.returncode)


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

def verify(fixture_dir, header, source=None,
           reference_header=None, reference_source=None):
    report = {}

    if reference_header is None:
        reference_header = os.path.join(fixture_dir, ".meta", "example.h")
    if reference_source is None:
        candidate_cpp = os.path.join(fixture_dir, ".meta", "example.cpp")
        reference_source = (candidate_cpp
                            if os.path.exists(candidate_cpp) else None)

    # ---- 1. Positive control: the reference implementation ----------------
    if not os.path.exists(reference_header):
        report["reference"] = {"status": "MISSING",
                               "detail": f"no reference at {reference_header}"}
    else:
        ref_build = build_candidate(fixture_dir, reference_header,
                                    reference_source)
        if ref_build.status != "PASS":
            report["reference"] = {"status": "BUILD_FAIL",
                                   "detail": ref_build.as_dict()}
        else:
            ref_run = run_test_binary(ref_build.binary)
            report["reference"] = {
                "status": "OK" if ref_run.score == 1.0
                else "TASK_PACKAGE_BROKEN",
                "run": ref_run.as_dict()}
            shutil.rmtree(ref_build.workspace, ignore_errors=True)

    # ---- 2. Candidate build ------------------------------------------------
    cand_build = build_candidate(fixture_dir, header, source)
    if cand_build.status != "PASS":
        report["candidate"] = {"status": "BUILD_FAIL",
                               "build": cand_build.as_dict()}
        report["verdict"] = "FAIL"
        report["score"] = 0.0
        return report

    # ---- 3. Candidate semantic run -----------------------------------------
    cand_run = run_test_binary(cand_build.binary)
    report["candidate"] = {"status": "RAN", "run": cand_run.as_dict()}
    shutil.rmtree(cand_build.workspace, ignore_errors=True)

    # ---- 4. Differential verdict -------------------------------------------
    ref_ok = report.get("reference", {}).get("status") == "OK"
    report["verdict"] = "PASS" if cand_run.score == 1.0 else "FAIL"
    report["score"] = round(cand_run.score, 4)
    if not ref_ok:
        report["warning"] = ("reference did not pass 100%; candidate score "
                             "cannot be trusted as differential")
    elif cand_run.score < 1.0:
        report["differential"] = (
            f"candidate fails {cand_run.total - cand_run.passed}/"
            f"{cand_run.total} assertions that the reference passes -- "
            f"semantic regression, not a build problem")
        if cand_run.failed_cases:
            report["differential_failed_cases"] = cand_run.failed_cases
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
        else:
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
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
