#!/usr/bin/env python3
"""
Verifier 03: Two-Stage Build Verifier (generalized, real subprocess builds).

Builds the candidate against the official test fixture in two stages so that
compile errors are separated from linker errors:

  Stage 1: compile <stem>.cpp alone          -> CE-1 on failure
  Stage 2: compile <stem>_test.cpp + tests-main.cpp, then link
           -> CE-2 on compile failure, LE on attributable candidate link errors
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
import re
import shutil
import subprocess
import sys
import tempfile

CXX = os.environ.get("CXX", "g++")
CXXFLAGS = ["-std=c++17", "-Wall", "-Wextra", "-Wpedantic", "-Werror",
            "-DEXERCISM_RUN_ALL_TESTS"]


class BuildResult:
    def __init__(self, status, stage, feedback, stderr="", workspace=None,
                 binary=None, failure_kind=None, returncode=None):
        self.status = status        # PASS | CE-1 | CE-2 | LE | ERROR
        self.stage = stage
        self.feedback = feedback
        self.stderr = stderr
        self.workspace = workspace  # kept alive by caller when binary is set
        self.binary = binary
        self.failure_kind = failure_kind
        self.returncode = returncode

    def as_dict(self):
        return {"status": self.status, "stage": self.stage,
                "feedback": self.feedback,
                "failure_kind": self.failure_kind, "returncode": self.returncode,
                "stderr_tail": "\n".join(self.stderr.splitlines()[-15:])}


class BuildInfrastructureError(RuntimeError):
    def __init__(self, result):
        self.result = result
        super().__init__(result.feedback)


_TOOL_FAILURE = re.compile(
    r"^(?:[^:\n]*/)?(?:g\+\+|c\+\+|clang\+\+|cc1plus|collect2|ld(?:\.lld)?|as):"
    r"[^\n]*(?:killed signal|internal compiler error|cannot execute|"
    r"no space left on device|cannot find -l|permission denied|"
    r"cannot open output file|file format not recognized)", re.I | re.M)


def _run(cmd, cwd, stage):
    try:
        proc = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True,
                              encoding="utf-8", errors="replace", timeout=300)
    except (OSError, subprocess.TimeoutExpired) as error:
        stderr = getattr(error, "stderr", "") or ""
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        raise BuildInfrastructureError(BuildResult(
            "ERROR", stage, f"compiler invocation failed: {error}", stderr,
            cwd, failure_kind="compiler_timeout" if isinstance(error, subprocess.TimeoutExpired)
            else "compiler_unavailable")) from error
    if proc.returncode < 0 or _TOOL_FAILURE.search(proc.stderr):
        raise BuildInfrastructureError(BuildResult(
            "ERROR", stage, "compiler/toolchain failed; candidate attribution is unavailable",
            proc.stderr, cwd, failure_kind="toolchain_failure", returncode=proc.returncode))
    return proc.returncode, proc.stderr


def classify_link_failure(stderr):
    """Keep unknown/tool failures invalid; recognize ordinary candidate errors."""
    kinds, feedback = [], []
    if re.search(r"multiple definition of|duplicate symbol", stderr, re.I):
        kinds.append("duplicate_definition")
        feedback.append("Duplicate definitions: keep each non-inline definition in one .cpp "
                        "file, or make header-defined functions inline (or templates). "
                        "An include guard does not prevent definitions in separate translation units.")
    if re.search(r"undefined reference|undefined symbol|unresolved external symbol", stderr, re.I):
        kinds.append("undefined_reference")
        feedback.append("Missing definitions: define the declared symbol with its exact "
                        "namespace and signature. Put template definitions in the header "
                        "or explicitly instantiate the required types.")
    if not kinds:
        return "ERROR", "unclassified_link_failure", (
            "Linker failed without a recognized candidate diagnostic; inspect the linker "
            "output and toolchain before assigning a model reward.")
    return "LE", kinds[0] if len(kinds) == 1 else "multiple_link_errors", (
        "LINKER ERROR: " + " ".join(feedback))


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
        return _build_candidate(fixture_dir, header, source)
    except BuildInfrastructureError as error:
        return error.result


def _build_candidate(fixture_dir, header, source=None):
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
                   workspace, 1)
    if rc != 0:
        return BuildResult(
            "CE-1", 1,
            "COMPILE ERROR (stage 1): your implementation file fails to "
            "compile on its own. Fix the syntax/semantic errors in the "
            "candidate source shown below.", err, workspace,
            failure_kind="candidate_compile", returncode=rc)

    # ---- Stage 2: compile the official test + harness, then link --------
    rc, err_test = _run([CXX, *CXXFLAGS, "-I.", "-c", test_cpp,
                         "-o", stem + "_test.o"], workspace, 2)
    if rc != 0:
        return BuildResult(
            "CE-2", 2,
            "COMPILE ERROR (stage 2): the official test file does not "
            "compile against your header. The declarations in your header "
            "do not match the API the test uses (missing/wrong names, "
            "private members, wrong template shape).", err_test, workspace,
            failure_kind="candidate_test_compile", returncode=rc)

    rc, err_main = _run([CXX, *CXXFLAGS, "-I.", "-c",
                         os.path.join("test", "tests-main.cpp"),
                         "-o", "tests-main.o"], workspace, 2)
    if rc != 0:
        return BuildResult("ERROR", 2,
                           "test harness (tests-main.cpp) failed to compile; "
                           "the task package itself is broken", err_main,
                           workspace, failure_kind="harness_compile", returncode=rc)

    binary = os.path.join(workspace, stem + "_tests")
    rc, err_link = _run([CXX, stem + ".o", stem + "_test.o", "tests-main.o",
                         "-o", binary, "-pthread"], workspace, 2)
    if rc != 0:
        status, kind, feedback = classify_link_failure(err_link)
        return BuildResult(status, 2, feedback, err_link, workspace,
                           failure_kind=kind, returncode=rc)

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
