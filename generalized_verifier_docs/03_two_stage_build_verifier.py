#!/usr/bin/env python3
"""
Verifier 03: Two-Stage Build Verifier (generalized, real subprocess builds).

Builds the candidate against the official test fixture in two stages so that
compile errors are separated from linker errors:

  Stage 1: compile <stem>.cpp alone          -> CE-1 on failure
  Stage 2: compile <stem>_test.cpp + tests-main.cpp, then link
           -> CE-2 on compile failure, LE on 'undefined reference' at link
  PASS otherwise.

No task names are hardcoded; everything derives from --fixture-dir and the
candidate paths. build_candidate() is importable and reused by
04_differential_semantic_verifier.py.

    python3 03_two_stage_build_verifier.py --fixture-dir <dir> \
        --header candidate.h [--source candidate.cpp] [--json]
"""

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

CXX = os.environ.get("CXX", "g++")
CXXFLAGS = ["-std=c++17", "-Wall", "-Wextra", "-Wpedantic", "-Werror",
            "-DEXERCISM_RUN_ALL_TESTS"]


class BuildResult:
    def __init__(self, status, stage, feedback, stderr="", workspace=None,
                 binary=None):
        self.status = status        # PASS | CE-1 | CE-2 | LE | ERROR
        self.stage = stage
        self.feedback = feedback
        self.stderr = stderr
        self.workspace = workspace  # kept alive by caller when binary is set
        self.binary = binary

    def as_dict(self):
        return {"status": self.status, "stage": self.stage,
                "feedback": self.feedback,
                "stderr_tail": "\n".join(self.stderr.splitlines()[-15:])}


def _run(cmd, cwd):
    proc = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, timeout=300)
    return proc.returncode, proc.stderr


def _find_stem(fixture_dir):
    tests = glob.glob(os.path.join(fixture_dir, "*_test.cpp"))
    if len(tests) != 1:
        raise FileNotFoundError(
            f"expected exactly one *_test.cpp in {fixture_dir}, "
            f"found {len(tests)}")
    return os.path.basename(tests[0])[:-len("_test.cpp")]


def prepare_workspace(fixture_dir, header, source=None, workspace=None):
    """Copy fixture (test file + test/ harness) into a temp workspace and
    drop the candidate in under the stem name the test file includes."""
    stem = _find_stem(fixture_dir)
    if workspace is None:
        workspace = tempfile.mkdtemp(prefix="twostage-")
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
        # Header-only candidate: provide an empty TU so stage 1 still runs.
        open(os.path.join(workspace, stem + ".cpp"), "w").write(
            f'#include "{stem}.h"\n')
    return workspace, stem


def build_candidate(fixture_dir, header, source=None):
    """Two-stage build. Returns a BuildResult."""
    try:
        workspace = tempfile.mkdtemp(prefix="twostage-")
        workspace, stem = prepare_workspace(fixture_dir, header, source,
                                            workspace)
    except (OSError, FileNotFoundError) as exc:
        return BuildResult("ERROR", 0, f"setup failed: {exc}")

    cpp = stem + ".cpp"
    test_cpp = stem + "_test.cpp"

    # ---- Stage 1: compile the candidate translation unit alone ----------
    rc, err = _run([CXX, *CXXFLAGS, "-I.", "-c", cpp, "-o", stem + ".o"],
                   workspace)
    if rc != 0:
        return BuildResult(
            "CE-1", 1,
            "COMPILE ERROR (stage 1): your implementation file fails to "
            "compile on its own. Fix the syntax/semantic errors in the "
            "candidate source shown below.", err, workspace)

    # ---- Stage 2: compile the official test + harness, then link --------
    rc, err_test = _run([CXX, *CXXFLAGS, "-I.", "-c", test_cpp,
                         "-o", stem + "_test.o"], workspace)
    if rc != 0:
        return BuildResult(
            "CE-2", 2,
            "COMPILE ERROR (stage 2): the official test file does not "
            "compile against your header. The declarations in your header "
            "do not match the API the test uses (missing/wrong names, "
            "private members, wrong template shape).", err_test, workspace)

    rc, err_main = _run([CXX, *CXXFLAGS, "-I.", "-c",
                         os.path.join("test", "tests-main.cpp"),
                         "-o", "tests-main.o"], workspace)
    if rc != 0:
        return BuildResult("ERROR", 2,
                           "test harness (tests-main.cpp) failed to compile; "
                           "the task package itself is broken", err_main,
                           workspace)

    binary = os.path.join(workspace, stem + "_tests")
    rc, err_link = _run([CXX, stem + ".o", stem + "_test.o", "tests-main.o",
                         "-o", binary, "-pthread"], workspace)
    if rc != 0:
        if "undefined reference" in err_link:
            return BuildResult(
                "LE", 2,
                "LINKER ERROR: the test references symbols that have no "
                "definition ('undefined reference'). Typical cause: functions "
                "or template methods declared in the header but defined in "
                "the .cpp file. Move the definitions into the header (or "
                "explicitly instantiate templates).", err_link, workspace)
        return BuildResult("ERROR", 2, "link failed without 'undefined "
                                       "reference' diagnostics", err_link,
                           workspace)

    return BuildResult("PASS", 2, "build clean: candidate compiles and "
                                  "links against the official test",
                       workspace=workspace, binary=binary)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Two-stage build verifier: separates compile errors "
                    "(CE-1/CE-2) from linker errors (LE).")
    ap.add_argument("--fixture-dir", required=True,
                    help="task fixture dir containing <stem>_test.cpp and "
                         "test/tests-main.cpp")
    ap.add_argument("--header", required=True, help="candidate header")
    ap.add_argument("--source", default=None,
                    help="candidate .cpp (omit for header-only candidates)")
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
    result = build_candidate(args.fixture_dir, args.header, args.source)
    if args.json:
        print(json.dumps(result.as_dict(), indent=2))
    else:
        print("--- Two-Stage Build Verifier ---")
        print(f"Stage 1: g++ {' '.join(CXXFLAGS)} -c <candidate>.cpp")
        print("Stage 2: g++ <test>.cpp + tests-main.cpp, then link")
        print(f"STATUS: {result.status}")
        print(f"Feedback: {result.feedback}")
        if result.status not in ("PASS",) and result.stderr:
            tail = "\n".join(result.stderr.splitlines()[:10])
            print(f"--- compiler output (first lines) ---\n{tail}")
    if result.workspace and result.status != "PASS":
        shutil.rmtree(result.workspace, ignore_errors=True)
    return 0 if result.status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
