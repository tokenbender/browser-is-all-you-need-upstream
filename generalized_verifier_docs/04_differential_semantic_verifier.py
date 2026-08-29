#!/usr/bin/env python3
"""
Verifier 04: Differential Semantic Verifier (generalized).

MOTIVATION
----------
A candidate can compile cleanly and still be wrong. Worse, a binary pass/fail
reward gives the RL loop no gradient: a candidate failing 1 of 12 assertions
is treated exactly like one failing 12 of 12. And a subtle but observed
failure class -- implementations that pass *some* tests while silently
violating the transformation contract (e.g. returning an echo of the input
where a transformed output was expected) -- needs a *semantic* gate, not
another compile flag.

MECHANISM (task-agnostic)
-------------------------
1. POSITIVE CONTROL: build the fixture's reference implementation
   (``.meta/example.h`` / ``.meta/example.cpp``) against the official test
   and run it. It must pass 100% of assertions; if it does not, the task
   package itself is broken and that is reported separately
   (``TASK_PACKAGE_BROKEN``) instead of blaming the candidate.
2. Build the candidate the same way (reusing the two-stage builder from
   03_two_stage_build_verifier.py). Build failures are reported with their
   CE/LE classification -- semantic scoring only applies to clean builds.
3. Run the candidate test binary, parse the Catch2 summary, and report
   PASSED_ASSERTIONS / TOTAL_ASSERTIONS as partial credit (a gradient),
   plus the per-test-case failures.
4. DIFFERENTIAL CHECK: every assertion the reference passes is one the
   candidate must pass too. A candidate assertion failure on inputs where
   the reference succeeds is a semantic regression, reported as such.

ON "ECHO" DETECTION (honest limitation)
---------------------------------------
A fully generic echo/identity probe is NOT implemented here, by design:
detecting "the output is just the input, untransformed" requires knowing
which test inputs should *not* be fixed points of the function under test --
that is task knowledge. There is no task-agnostic way to know whether
``f(x) == x`` is a bug (it is correct for a normalizer, wrong for a
rearranging transform).
What IS task-agnostic is the differential above: the reference defines the
correct input/output relation, and any deviation from it -- including echo
behavior -- shows up as assertion failures on cases the reference passes.
The observed "returns essentially the input" failure is caught exactly this
way (see validation/VALIDATION.md); a dedicated echo heuristic would only
make the report prettier, not the verdict stronger.

USAGE
-----
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
    args = ap.parse_args(argv)

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
