#!/usr/bin/env python3
"""Verifier wrapper G03: differential semantic verification.

Runs the differential semantic engine against the manifest's ``fixture_dir``:
the fixture's reference implementation (``.meta/example.h`` / optional
``.meta/example.cpp``) is built and run as a positive control, then the
candidate is built and scored assertion-by-assertion against the same
official test.  Emits one kernel for the reference control and one for the
candidate differential score; when the candidate does not build, the
candidate kernel is ``not_run`` (kernel null) because G02 already scores
that build failure.

If the reference is missing or does not pass 100% of assertions the task
package cannot establish a differential, so the verdict is invalid (never a
candidate-blaming fail).

Runner contract: reads --candidate-dir/--manifest/--expected-manifest-sha256,
writes <output-dir>/verification_receipt.json, exits 0 pass / 1 fail /
2 invalid.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _global_common as common

POLICY_ID = "G03"
ENGINE = "04_differential_semantic_verifier.py"


def run_checks(args, manifest):
    fixture = common.fixture_dir(manifest)
    header, sources = common.split_candidate_files(manifest)
    reference_header = os.path.join(fixture, ".meta", "example.h")
    if not os.path.isfile(reference_header):
        raise common.InvalidInput(
            "fixture has no reference implementation at "
            ".meta/example.h; differential verification cannot run")
    engine_args = [
        "--fixture-dir", fixture,
        "--header", common.candidate_path(args.candidate_dir, header),
    ]
    if sources:
        engine_args += ["--source",
                        common.candidate_path(args.candidate_dir, sources[0])]
    engine_args.append("--json")
    result = common.run_engine(common.find_engine(ENGINE), engine_args)
    report = common.parse_engine_json(result, "differential semantic")

    reference = report.get("reference", {})
    candidate = report.get("candidate", {})
    facts = {
        "engine": ENGINE,
        "engine_exit_code": result["return_code"],
        "reference": reference,
        "candidate": candidate,
        "score": report.get("score"),
        "differential": report.get("differential"),
        "warning": report.get("warning"),
        "stderr_tail": common.tail(result["stderr"]),
    }

    kernels = []
    ref_ok = reference.get("status") == "OK"
    kernels.append(common.kernel(
        f"{POLICY_ID}-1", "pass" if ref_ok else "fail",
        ("reference control: fixture reference implementation passes 100% "
         "of official assertions" if ref_ok else
         f"reference control failed: {reference.get('status')}"),
        facts={"reference": reference}, command=result["command"],
        duration_seconds=result["duration_seconds"]))

    if candidate.get("status") == "BUILD_FAIL":
        build = candidate.get("build", {})
        if build.get("status") not in {"CE-1", "CE-2", "LE"}:
            reason = "candidate differential build encountered an infrastructure failure"
            kernels.append(common.kernel(f"{POLICY_ID}-2", "invalid", reason, facts=facts))
            return kernels, "invalid", reason
        # G02 already scores this exact build failure (this engine reuses
        # G02's build_candidate), so a second -1 here would double-count one
        # root cause.  Emit the candidate kernel as not_run (kernel null,
        # excluded from kernel_sum) and keep the build facts for diagnosis.
        kernels.append(common.kernel(
            f"{POLICY_ID}-2", "not_run",
            "candidate build failed: "
            f"{build.get('status')} -- {build.get('feedback')} "
            "(scored under G02; differential candidate kernel not run)",
            facts=facts))
        if not ref_ok:
            return kernels, "invalid", (
                "reference control failed; candidate build failure is "
                "not differentially attributable")
        return kernels, "pass", (
            "reference control passed; candidate build failure is scored "
            "by G02, so the differential candidate kernel was not run")

    run = candidate.get("run", {})
    score = run.get("score")
    candidate_ok = score == 1.0
    kernels.append(common.kernel(
        f"{POLICY_ID}-2", "pass" if candidate_ok else "fail",
        (f"candidate passes all {run.get('total_assertions')} assertions"
         if candidate_ok else
         report.get("differential", "candidate runtime failure") if run.get("crashed") else
         f"candidate passes {run.get('passed_assertions')}/"
         f"{run.get('total_assertions')} assertions the reference passes"),
        facts=facts))
    if not ref_ok:
        return kernels, "invalid", (
            "reference control did not pass 100%; the candidate score "
            "cannot be trusted as differential")
    status = "pass" if candidate_ok else "fail"
    reason = (f"differential semantic: score {score}"
              + (f" -- {report['differential']}"
                 if report.get("differential") else ""))
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
