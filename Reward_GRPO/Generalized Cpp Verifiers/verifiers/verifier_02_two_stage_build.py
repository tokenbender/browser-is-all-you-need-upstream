#!/usr/bin/env python3
"""Verifier wrapper G02: two-stage build.

Runs the two-stage build engine (stage 1: candidate translation unit alone;
stage 2: official test + harness compiled against the candidate and linked)
against the manifest's ``fixture_dir`` and the candidate header/sources.
Emits one kernel per executed build stage so compile-error vs link-error
outcomes stay distinguishable in the receipt.

Runner contract: reads --candidate-dir/--manifest/--expected-manifest-sha256,
writes <output-dir>/verification_receipt.json, exits 0 pass / 1 fail /
2 invalid.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _global_common as common

POLICY_ID = "G02"
ENGINE = "03_two_stage_build_verifier.py"


def run_checks(args, manifest):
    fixture = common.fixture_dir(manifest)
    header, sources = common.split_candidate_files(manifest)
    engine_args = [
        "--fixture-dir", fixture,
        "--header", common.candidate_path(args.candidate_dir, header),
    ]
    if sources:
        engine_args += ["--source",
                        common.candidate_path(args.candidate_dir, sources[0])]
    engine_args.append("--json")
    result = common.run_engine(common.find_engine(ENGINE), engine_args)
    report = common.parse_engine_json(result, "two-stage build")

    build_status = report.get("status")
    if build_status == "ERROR":
        raise common.InvalidInput(
            "two-stage build could not run: " + str(report.get("feedback")))

    facts_common = {
        "engine": ENGINE,
        "engine_exit_code": result["return_code"],
        "build_status": build_status,
        "feedback": report.get("feedback"),
        "stderr_tail": common.tail(report.get("stderr_tail", "")),
    }
    kernels = []
    if build_status == "CE-1":
        kernels.append(common.kernel(
            f"{POLICY_ID}-1", "fail",
            "stage 1: candidate translation unit does not compile",
            facts=facts_common, command=result["command"],
            duration_seconds=result["duration_seconds"]))
    else:
        kernels.append(common.kernel(
            f"{POLICY_ID}-1", "pass",
            "stage 1: candidate translation unit compiles cleanly",
            facts=facts_common, command=result["command"],
            duration_seconds=result["duration_seconds"]))
        if build_status == "PASS":
            kernels.append(common.kernel(
                f"{POLICY_ID}-2", "pass",
                "stage 2: official test compiles and links against the "
                "candidate", facts=facts_common))
        else:
            kind = ("linker error (undefined reference)"
                    if build_status == "LE"
                    else "test does not compile against the candidate header")
            kernels.append(common.kernel(
                f"{POLICY_ID}-2", "fail",
                f"stage 2: {kind}", facts=facts_common))

    status = "pass" if build_status == "PASS" else "fail"
    reason = (f"two-stage build: {build_status} -- "
              + str(report.get("feedback")))
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
