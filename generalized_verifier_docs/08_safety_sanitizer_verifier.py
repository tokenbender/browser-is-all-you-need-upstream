#!/usr/bin/env python3









































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




RUN_ENV = {
    "ASAN_OPTIONS": "detect_leaks=0:halt_on_error=1",
    "UBSAN_OPTIONS": "print_stacktrace=1:halt_on_error=1",
}





SUPPRESSION_RE = re.compile(r"no_sanitize|disable_sanitizer_instrumentation")






def strip_comments_and_literals(code):
    pass





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
    pass




    for name, text in sources:
        clean = strip_comments_and_literals(text)
        m = SUPPRESSION_RE.search(clean)
        if m:
            line = clean.count('\n', 0, m.start()) + 1
            return name, line, m.group(0)
    return None






def _find_stem(fixture_dir):
    tests = glob.glob(os.path.join(fixture_dir, "*_test.cpp"))
    if len(tests) != 1:
        raise FileNotFoundError(
            f"expected exactly one *_test.cpp in {fixture_dir}, "
            f"found {len(tests)}")
    return os.path.basename(tests[0])[:-len("_test.cpp")]


def prepare_workspace(fixture_dir, header, source=None):
    pass

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

        with open(os.path.join(workspace, stem + ".cpp"), "w") as handle:
            handle.write(f'#include "{stem}.h"\n')
    return workspace, stem


def build_sanitized(workspace, stem):
    pass

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


_NULL_PAGE = 0x1000


def first_candidate_frame(text, candidate_files):
    pass





    for m in _FRAME_RE.finditer(text):
        func, path, line = m.group(1), m.group(2), int(m.group(3))
        if os.path.basename(path) in candidate_files:
            return {"function": func, "file": os.path.basename(path),
                    "line": line}
    return None


def parse_sanitizer_output(text, candidate_files):
    pass



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






_ALL_PASS_RE = re.compile(
    r'All tests passed\s*\((\d+) assertions? in (\d+) test cases?\)')
_SUMMARY_LINE_RE = re.compile(r'^assertions:\s*(.+)$', re.MULTILINE)
_COUNT_RE = re.compile(r'(\d+)\s*(passed|failed)')


def functional_outcome(stdout_text):
    pass


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






def tail(text, limit=15):
    return "\n".join(text.splitlines()[-limit:])


def verify(fixture_dir, header, source=None, run_timeout=DEFAULT_RUN_TIMEOUT):
    report = {"verdict": None, "safety_kind": None, "safety_detail": None,
              "candidate_location": None, "sanitizer": "address,undefined",
              "diagnostic_policy": True}


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



EXIT_CODE = {
    "CLEAN": 0,
    "BUILD_FAIL": 0,
    "TIMEOUT": 0,
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
