#!/usr/bin/env python3
"""Verifier wrapper G01: structural API gate.

Derives the required public API from the task's official test file (in the
manifest's ``fixture_dir``) and checks that the candidate header/sources
declare every required symbol with the required shape, by invoking the
structural API gate engine in ``generalized_verifier_docs``.

Runner contract: reads --candidate-dir/--manifest/--expected-manifest-sha256,
writes <output-dir>/verification_receipt.json, exits 0 pass / 1 fail /
2 invalid.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _global_common as common

POLICY_ID = "G01"
ENGINE = "01_structural_api_gate.py"


def run_checks(args, manifest):
    fixture = common.fixture_dir(manifest)
    test_file, _stem = common.fixture_test_file(fixture)
    header, sources = common.split_candidate_files(manifest)
    engine_args = [
        "--test", test_file,
        "--header", common.candidate_path(args.candidate_dir, header),
    ]
    for source in sources:
        engine_args += ["--source",
                        common.candidate_path(args.candidate_dir, source)]
    engine_args.append("--json")
    result = common.run_engine(common.find_engine(ENGINE), engine_args)
    report = common.parse_engine_json(result, "structural API gate")

    verdicts = report.get("verdicts", [])
    failed = [v for v in verdicts if not v.get("ok")]
    passed = bool(report.get("passed")) and result["return_code"] == 0
    status = "pass" if passed else "fail"
    if failed:
        summary = (f"structural API gate: {len(failed)}/{len(verdicts)} "
                   "required symbols missing or misdeclared")
    else:
        summary = (f"structural API gate: all {len(verdicts)} required "
                   "symbols declared correctly")
    facts = {
        "engine": ENGINE,
        "engine_exit_code": result["return_code"],
        "required_symbols": report.get("required_symbols", []),
        "failed_symbols": [v.get("symbol") for v in failed],
        "messages": [msg for v in failed for msg in v.get("messages", [])],
        "stderr_tail": common.tail(result["stderr"]),
    }
    kernels = [common.kernel(
        f"{POLICY_ID}-1", status, summary, facts=facts,
        command=result["command"],
        duration_seconds=result["duration_seconds"])]
    return kernels, status, summary


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
