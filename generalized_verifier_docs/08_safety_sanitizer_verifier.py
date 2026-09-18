#!/usr/bin/env python3
"""
Verifier 08: Safety Sanitizer Verifier (generalized, DIAGNOSTIC policy).

Builds the candidate against the task's official test (via --fixture-dir)
with AddressSanitizer and UndefinedBehaviorSanitizer, runs the test binary,
and classifies the dynamic safety outcome. No task names are hardcoded.

This is a diagnosis layer, not an additive penalty: the exit code is
nonzero ONLY for safety findings this verifier owns.

  0  CLEAN              ran; no sanitizer report (functional failures are
                        owned by policy G03, reported here as a fact)
  0  BUILD_FAIL         compilation failed (owned by G02, reported as fact)
  0  TIMEOUT            test binary exceeded the run timeout (reported as fact)
  1  SANITIZER_HIT      ASan/UBSan fired; safety_kind classifies it
  1  CRASH_NO_REPORT    signal death without any sanitizer report
  2  INVALID            unusable input, or the anti-exploit control fired

Anti-exploit control: any candidate file containing a sanitizer-suppression
attribute (no_sanitize, disable_sanitizer_instrumentation) is rejected as
INVALID (reason sanitizer_suppression_attempt) before any build -- a
candidate must not switch the verifier off. detect_leaks=0 because the
Catch2 harness/stdlib hold allocations until teardown, so leak reports
would come from the harness, not the candidate.

Verdicts:
  CLEAN           -- ran; no sanitizer report
  SANITIZER_HIT   -- sanitizer report parsed; safety_kind is the ASan error
                     kind (heap-buffer-overflow, heap-use-after-free, ...)
                     or undefined-behavior; candidate_location names the
                     first stack frame inside a candidate file
  CRASH_NO_REPORT -- killed by a signal with no sanitizer report
  BUILD_FAIL      -- the sanitized build failed (owned by G02)
  TIMEOUT         -- the test binary did not finish in time
  INVALID         -- usage/IO error or sanitizer_suppression_attempt

    python3 08_safety_sanitizer_verifier.py --fixture-dir <dir> \
        --header candidate.h [--source candidate.cpp] \
        [--timeout-seconds 120] [--json]
"""

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

CXX = os.environ.get("CXX", "g++")
CXXFLAGS = ["-std=c++17", "-Wall", "-Wextra", "-Wpedantic", "-Werror",
            "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
            "-DEXERCISM_RUN_ALL_TESTS", "-g"]
BUILD_TIMEOUT_SECONDS = 300
DEFAULT_RUN_TIMEOUT = 120

# Environment for the instrumented run. detect_leaks=0: leak reports would
# originate in the test harness's own teardown allocations, not in candidate
# code (see module docstring).
RUN_ENV = {
    "ASAN_OPTIONS": "detect_leaks=0:halt_on_error=1",
    "UBSAN_OPTIONS": "print_stacktrace=1:halt_on_error=1",
}

# Anti-exploit control: tokens that blind or selectively disable sanitizers.
# Matched on comment-stripped, literal-blanked source; this is the ONLY
# source-text inspection in this verifier and it guards the verifier, not
# the task contract.
SUPPRESSION_RE = re.compile(r"no_sanitize|disable_sanitizer_instrumentation")


# ---------------------------------------------------------------------------
# Comment/literal stripping (for the suppression scan only)
# ---------------------------------------------------------------------------

def strip_comments_and_literals(code):
    """Remove // and /* */ comments; blank string/char literal contents.

    Same lexical approach as 01_structural_api_gate.py: the suppression
    control must key on actual code, not on a comment that mentions an
    attribute name.
    """
    out = []
    i, n = 0, len(code)
    while i < n:
        c = code[i]
        if c == '/' and i + 1 < n and code[i + 1] == '/':
            while i < n and code[i] != '\n':
                i += 1
        elif c == '/' and i + 1 < n and code[i + 1] == '*':
            i += 2
            while i + 1 < n and not (code[i] == '*' and code[i + 1] == '/'):
                out.append('\n' if code[i] == '\n' else ' ')
                i += 1
            i += 2
        elif c in '"\'':
            quote = c
            out.append(c)
            i += 1
            while i < n and code[i] != quote:
                if code[i] == '\\':
                    i += 1
                if i < n and code[i] != quote:
                    out.append(' ' if code[i] != '\n' else '\n')
                i += 1
            if i < n:
                out.append(quote)
                i += 1
        else:
            out.append(c)
            i += 1
    return ''.join(out)


def find_suppression(sources):
    """Return the first sanitizer-suppression token occurrence, or None.

    ``sources`` is a list of (display_name, text). The result is
    (display_name, line_number, token).
    """
    for name, text in sources:
        clean = strip_comments_and_literals(text)
        m = SUPPRESSION_RE.search(clean)
        if m:
            line = clean.count('\n', 0, m.start()) + 1
            return name, line, m.group(0)
    return None


# ---------------------------------------------------------------------------
# Workspace + build
# ---------------------------------------------------------------------------

def _find_stem(fixture_dir):
    tests = glob.glob(os.path.join(fixture_dir, "*_test.cpp"))
    if len(tests) != 1:
        raise FileNotFoundError(
            f"expected exactly one *_test.cpp in {fixture_dir}, "
            f"found {len(tests)}")
    return os.path.basename(tests[0])[:-len("_test.cpp")]


def prepare_workspace(fixture_dir, header, source=None):
    """Copy fixture (test file + test/ harness) into a temp workspace and
    drop the candidate in under the stem name the test file includes."""
    stem = _find_stem(fixture_dir)
    workspace = tempfile.mkdtemp(prefix="safety-")
    for item in os.listdir(fixture_dir):
        if item.endswith("_test.cpp") or item == "test":
            src = os.path.join(fixture_dir, item)
            dst = os.path.join(workspace, item)
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
    shutil.copy2(header, os.path.join(workspace, stem + ".h"))
    if source is not None:
        shutil.copy2(source, os.path.join(workspace, stem + ".cpp"))
    else:
        # Header-only candidate: provide a minimal TU so the build still runs.
        with open(os.path.join(workspace, stem + ".cpp"), "w") as handle:
            handle.write(f'#include "{stem}.h"\n')
    return workspace, stem


def build_sanitized(workspace, stem):
    """Compile candidate + official test + harness with ASan/UBSan in one
    invocation. Returns (ok, command, stderr)."""
    binary = os.path.join(workspace, stem + "_safety_tests")
    command = [CXX, *CXXFLAGS, "-I.",
               stem + ".cpp", stem + "_test.cpp",
               os.path.join("test", "tests-main.cpp"),
               "-o", binary, "-pthread"]
    try:
        proc = subprocess.run(command, cwd=workspace, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True,
                              timeout=BUILD_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, command, f"build could not run: {exc}"
    return proc.returncode == 0, command, proc.stderr


# ---------------------------------------------------------------------------
# Sanitizer output parsing
# ---------------------------------------------------------------------------

_ASAN_ERROR_RE = re.compile(
    r'==\d+==ERROR: AddressSanitizer: ([A-Za-z-]+(?:-[A-Za-z]+)*)')
_ASAN_SEGV_RE = re.compile(
    r'==\d+==ERROR: AddressSanitizer: SEGV on unknown address '
    r'(0x[0-9a-fA-F]+)')
_UBSAN_ERROR_RE = re.compile(r'runtime error: (.+)')
_UBSAN_SUMMARY_RE = re.compile(
    r'SUMMARY: UndefinedBehaviorSanitizer: undefined-behavior (\S+)')
_FRAME_RE = re.compile(
    r'#\d+\s+0x[0-9a-fA-F]+\s+in\s+(.+?)\s+(\S+):(\d+)\s*$',
    re.MULTILINE)

# ASan SEGV on a near-null address is a null(-ish) dereference.
_NULL_PAGE = 0x1000


def first_candidate_frame(text, candidate_files):
    """First stack frame located inside a candidate file, else None.

    ``candidate_files`` are workspace basenames (<stem>.h / <stem>.cpp).
    Frame file paths are matched by basename so the verdict does not depend
    on the temp workspace location.
    """
    for m in _FRAME_RE.finditer(text):
        func, path, line = m.group(1), m.group(2), int(m.group(3))
        if os.path.basename(path) in candidate_files:
            return {"function": func, "file": os.path.basename(path),
                    "line": line}
    return None


def parse_sanitizer_output(text, candidate_files):
    """Classify sanitizer output. Returns (safety_kind, detail, location).

    safety_kind is None when no sanitizer report is present.
    """
    segv = _ASAN_SEGV_RE.search(text)
    if segv:
        address = int(segv.group(1), 16)
        kind = "null-deref" if address < _NULL_PAGE else "SEGV"
        return kind, f"SEGV on unknown address {segv.group(1)}", \
            first_candidate_frame(text, candidate_files)

    m = _ASAN_ERROR_RE.search(text)
    if m:
        return m.group(1), _summary_line(text, "AddressSanitizer"), \
            first_candidate_frame(text, candidate_files)

    if _UBSAN_ERROR_RE.search(text) or _UBSAN_SUMMARY_RE.search(text):
        detail = None
        err = _UBSAN_ERROR_RE.search(text)
        if err:
            detail = err.group(1).strip()
        summary = _UBSAN_SUMMARY_RE.search(text)
        location = first_candidate_frame(text, candidate_files)
        if location is None and summary:
            site = summary.group(1)
            file_part, _, line_part = site.rpartition(":")
            if os.path.basename(file_part) in candidate_files \
                    and line_part.isdigit():
                location = {"function": None,
                            "file": os.path.basename(file_part),
                            "line": int(line_part)}
        return "undefined-behavior", detail, location

    return None, None, None


def _summary_line(text, sanitizer):
    for line in text.splitlines():
        if line.startswith(f"SUMMARY: {sanitizer}:"):
            return line.strip()
    return None


# ---------------------------------------------------------------------------
# Catch2 functional outcome (reported as a FACT; owned by policy G03)
# ---------------------------------------------------------------------------

_ALL_PASS_RE = re.compile(
    r'All tests passed\s*\((\d+) assertions? in (\d+) test cases?\)')
_SUMMARY_LINE_RE = re.compile(r'^assertions:\s*(.+)$', re.MULTILINE)
_COUNT_RE = re.compile(r'(\d+)\s*(passed|failed)')


def functional_outcome(stdout_text):
    """Parse the Catch2 summary into {outcome, passed, total} -- never used
    for the safety verdict, only recorded so consumers can see that any
    functional failure here belongs to policy G03."""
    all_pass = _ALL_PASS_RE.search(stdout_text)
    if all_pass:
        total = int(all_pass.group(1))
        return {"outcome": "PASSED", "passed_assertions": total,
                "total_assertions": total,
                "ownership": "functional score owned by G03"}
    summary = _SUMMARY_LINE_RE.search(stdout_text)
    if summary:
        fields = summary.group(1)
        total_m = re.match(r'\s*(\d+)', fields)
        counts = {label: n for n, label in
                  _COUNT_RE.findall(fields[len(total_m.group(0)):])}
        total = int(total_m.group(1))
        passed = int(counts.get("passed", 0))
        return {"outcome": "FAILED" if passed < total else "PASSED",
                "passed_assertions": passed,
                "total_assertions": total,
                "ownership": "functional score owned by G03"}
    return {"outcome": "NO_SUMMARY", "passed_assertions": None,
            "total_assertions": None,
            "ownership": "functional score owned by G03"}


# ---------------------------------------------------------------------------
# Run + verdict
# ---------------------------------------------------------------------------

def tail(text, limit=15):
    return "\n".join(text.splitlines()[-limit:])


def verify(fixture_dir, header, source=None, run_timeout=DEFAULT_RUN_TIMEOUT):
    report = {"verdict": None, "safety_kind": None, "safety_detail": None,
              "candidate_location": None, "sanitizer": "address,undefined",
              "diagnostic_policy": True}

    # ---- 0. Anti-exploit control (before any build) ------------------------
    try:
        sources = [(os.path.basename(header), open(header).read())]
        if source is not None:
            sources.append((os.path.basename(source), open(source).read()))
    except OSError as exc:
        report["verdict"] = "INVALID"
        report["reason"] = f"candidate file unreadable: {exc}"
        return report
    hit = find_suppression(sources)
    if hit:
        name, line, token = hit
        report["verdict"] = "INVALID"
        report["reason"] = "sanitizer_suppression_attempt"
        report["detail"] = (
            f"candidate file {name}:{line} contains sanitizer-suppression "
            f"token '{token}'; a candidate must not blind this verifier")
        return report

    # ---- 1. Sanitized build against the official test ----------------------
    try:
        workspace, stem = prepare_workspace(fixture_dir, header, source)
    except (OSError, FileNotFoundError) as exc:
        report["verdict"] = "INVALID"
        report["reason"] = f"fixture setup failed: {exc}"
        return report
    candidate_files = {stem + ".h", stem + ".cpp"}
    try:
        ok, command, build_stderr = build_sanitized(workspace, stem)
        report["build_command"] = command
        if not ok:
            report["verdict"] = "BUILD_FAIL"
            report["reason"] = (
                "sanitized build failed; compile/link failures are owned by "
                "policy G02 -- reported here as a fact, no penalty added")
            report["build_stderr_tail"] = tail(build_stderr)
            return report

        # ---- 2. Instrumented run -------------------------------------------
        binary = os.path.join(workspace, stem + "_safety_tests")
        env = dict(os.environ)
        env.update(RUN_ENV)
        try:
            proc = subprocess.run([binary], cwd=workspace,
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True,
                                  timeout=run_timeout, env=env)
        except subprocess.TimeoutExpired:
            report["verdict"] = "TIMEOUT"
            report["reason"] = (
                f"test binary did not finish within {run_timeout}s; "
                "timeout handling is owned by the functional policies "
                "(G03/G04) -- reported here as a fact, no penalty added")
            return report

        combined = proc.stdout + "\n" + proc.stderr
        report["process_returncode"] = proc.returncode
        report["functional"] = functional_outcome(proc.stdout)
        report["run_output_tail"] = tail(combined)

        # ---- 3. Safety classification --------------------------------------
        kind, detail, location = parse_sanitizer_output(
            combined, candidate_files)
        if kind is not None:
            report["verdict"] = "SANITIZER_HIT"
            report["safety_kind"] = kind
            report["safety_detail"] = detail
            report["candidate_location"] = location
            return report

        if proc.returncode < 0:
            signum = -proc.returncode
            report["verdict"] = "CRASH_NO_REPORT"
            report["safety_kind"] = "signal"
            report["safety_detail"] = (
                f"process killed by signal {signum} with no sanitizer report")
            return report

        report["verdict"] = "CLEAN"
        report["reason"] = (
            "no sanitizer report; any functional failure visible in "
            "'functional' is owned by policy G03 and adds no penalty here")
        return report
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


# Exit-code ownership: nonzero ONLY for safety findings (1) or invalid (2).
EXIT_CODE = {
    "CLEAN": 0,
    "BUILD_FAIL": 0,      # owned by G02
    "TIMEOUT": 0,         # owned by G03/G04
    "SANITIZER_HIT": 1,
    "CRASH_NO_REPORT": 1,
    "INVALID": 2,
}


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Safety sanitizer verifier (DIAGNOSTIC): builds the "
                    "candidate against the official test with "
                    "ASan+UBSan, runs it, and classifies the dynamic safety "
                    "outcome. Exit code is nonzero only for safety findings "
                    "(1) or invalid input (2).")
    ap.add_argument("--fixture-dir", required=True,
                    help="task fixture dir containing <stem>_test.cpp and "
                         "test/tests-main.cpp")
    ap.add_argument("--header", required=True, help="candidate header")
    ap.add_argument("--source", default=None,
                    help="candidate .cpp (omit for header-only candidates)")
    ap.add_argument("--timeout-seconds", type=int,
                    default=DEFAULT_RUN_TIMEOUT,
                    help="test-binary run timeout (default: %(default)s)")
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
                    run_timeout=args.timeout_seconds)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("--- Safety Sanitizer Verifier (diagnostic) ---")
        print(f"VERDICT: {report['verdict']}")
        if report.get("safety_kind"):
            print(f"kind: {report['safety_kind']}")
        if report.get("safety_detail"):
            print(f"detail: {report['safety_detail']}")
        loc = report.get("candidate_location")
        if loc:
            print(f"candidate location: {loc['file']}:{loc['line']}"
                  + (f" in {loc['function']}" if loc.get("function") else ""))
        if report.get("reason"):
            print(f"note: {report['reason']}")
        func = report.get("functional")
        if func:
            print(f"functional (owned by G03, fact only): {func['outcome']} "
                  f"({func['passed_assertions']}/{func['total_assertions']} "
                  f"assertions)")
        if report["verdict"] == "BUILD_FAIL" and report.get(
                "build_stderr_tail"):
            print("--- compiler output (tail) ---")
            print(report["build_stderr_tail"])
    return EXIT_CODE.get(report["verdict"], 2)


if __name__ == "__main__":
    sys.exit(main())
