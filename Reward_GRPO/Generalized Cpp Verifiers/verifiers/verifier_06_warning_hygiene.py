#!/usr/bin/env python3
"""Verifier wrapper G06: warning hygiene.

Obtains full compiler diagnostics for the candidate translation unit and
classifies them with the warning-hygiene engine.  The two-stage build
engine is invoked via subprocess for the authoritative stage
classification; the wrapper additionally re-runs the same stage-1 compile
(candidate TU alone, strict flags) in its own temporary workspace to capture
complete stderr, which the classifier engine then grades.

Verdict: pass only when the stage-1 compile is clean and the classifier
finds no error-severity diagnostics.

Runner contract: reads --candidate-dir/--manifest/--expected-manifest-sha256,
writes <output-dir>/verification_receipt.json, exits 0 pass / 1 fail /
2 invalid.
"""

import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _global_common as common

POLICY_ID = "G06"
BUILD_ENGINE = "03_two_stage_build_verifier.py"
CLASSIFIER_ENGINE = "07_warning_hygiene_classifier.py"


def _stage1_compile(args, manifest, fixture, stem):
    """Re-run the stage-1 candidate-TU compile; return (rc, full stderr)."""
    header, sources = common.split_candidate_files(manifest)
    workspace = tempfile.mkdtemp(prefix="warning-hygiene-")
    try:
        shutil.copy2(common.candidate_path(args.candidate_dir, header),
                     os.path.join(workspace, stem + ".h"))
        if sources:
            shutil.copy2(
                common.candidate_path(args.candidate_dir, sources[0]),
                os.path.join(workspace, stem + ".cpp"))
        else:
            with open(os.path.join(workspace, stem + ".cpp"), "w") as handle:
                handle.write(f'#include "{stem}.h"\n')
        command = [common.STAGE1_CXX, *common.STAGE1_CXXFLAGS, "-I.", "-c",
                   stem + ".cpp", "-o", stem + ".o"]
        proc = subprocess.run(command, cwd=workspace, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, timeout=300)
        return proc.returncode, proc.stderr, command
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def run_checks(args, manifest):
    fixture = common.fixture_dir(manifest)
    _test_file, stem = common.fixture_test_file(fixture)
    header, sources = common.split_candidate_files(manifest)

    build_args = [
        "--fixture-dir", fixture,
        "--header", common.candidate_path(args.candidate_dir, header),
    ]
    if sources:
        build_args += ["--source",
                       common.candidate_path(args.candidate_dir, sources[0])]
    build_args.append("--json")
    build = common.run_engine(common.find_engine(BUILD_ENGINE), build_args)
    build_report = common.parse_engine_json(build, "two-stage build")
    build_status = build_report.get("status")
    if build_status == "ERROR":
        raise common.InvalidInput(
            "stage-1 compile could not run: "
            + str(build_report.get("feedback")))

    rc, stderr_text, compile_command = _stage1_compile(
        args, manifest, fixture, stem)
    with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", suffix=".stderr.txt",
            delete=False) as handle:
        handle.write(stderr_text)
        stderr_path = handle.name
    try:
        classified = common.run_engine(
            common.find_engine(CLASSIFIER_ENGINE),
            ["--stderr", stderr_path, "--json"])
        report = common.parse_engine_json(classified, "warning hygiene")
    finally:
        os.unlink(stderr_path)

    facts = {
        "build_engine": BUILD_ENGINE,
        "build_status": build_status,
        "classifier_engine": CLASSIFIER_ENGINE,
        "classifier_exit_code": classified["return_code"],
        "error_count": report.get("error_count"),
        "warning_count": report.get("warning_count"),
        "dominant_class": report.get("dominant_class"),
        "findings": report.get("findings", []),
        "stderr_tail": common.tail(stderr_text),
    }
    compile_ok = rc == 0
    kernels = [common.kernel(
        f"{POLICY_ID}-1", "pass" if compile_ok else "fail",
        ("stage-1 compile: candidate translation unit compiles with zero "
         "diagnostics under strict flags" if compile_ok else
         "stage-1 compile emitted diagnostics under strict flags"),
        facts={"return_code": rc, "stderr_tail": facts["stderr_tail"]},
        command=compile_command)]
    hygiene_ok = report.get("verdict") == "PASS"
    kernels.append(common.kernel(
        f"{POLICY_ID}-2", "pass" if hygiene_ok else "fail",
        (f"warning hygiene: {report.get('error_count')} error(s), "
         f"{report.get('warning_count')} warning(s), dominant class "
         f"{report.get('dominant_class')}"),
        facts=facts, command=classified["command"],
        duration_seconds=classified["duration_seconds"]))
    status = "pass" if compile_ok and hygiene_ok else "fail"
    reason = (f"warning hygiene: build {build_status}, "
              f"{report.get('error_count')} error(s), "
              f"{report.get('warning_count')} warning(s)")
    return kernels, status, reason


def main(argv=None):
    args = common.parse_runner_args(argv)
    try:
        manifest, manifest_sha256 = common.load_manifest(args)
    except common.ManifestError as exc:
        return common.finish_invalid(
            os.path.abspath(__file__), args, POLICY_ID, None, None, None,
            str(exc))
    try:
        before = common.candidate_source_sha256(
            args.candidate_dir, manifest["candidate_files"])
        kernels, status, reason = run_checks(args, manifest)
    except common.InvalidInput as exc:
        return common.finish_invalid(
            os.path.abspath(__file__), args, POLICY_ID, manifest,
            manifest_sha256, None, str(exc))
    return common.finish(
        os.path.abspath(__file__), args, POLICY_ID, manifest,
        manifest_sha256, before, kernels, status, reason)


if __name__ == "__main__":
    sys.exit(main())
