#!/usr/bin/env python3













import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _global_common as common

POLICY_ID = "G04"
ENGINE = "05_response_integrity_verifier.py"


def run_checks(args, manifest):
    response_path, cleanup = common.find_response(manifest)
    try:
        result = common.run_engine(
            common.find_engine(ENGINE),
            ["--response", response_path, "--json"])
        report = common.parse_engine_json(result, "response integrity")
    finally:
        if cleanup:
            os.unlink(cleanup)

    verdict = report.get("verdict")
    status = "pass" if verdict == "OK" and result["return_code"] == 0 \
        else "fail"
    summary = (f"response integrity: {verdict} -- {report.get('feedback')}")
    facts = {
        "engine": ENGINE,
        "engine_exit_code": result["return_code"],
        "verdict": verdict,
        "feedback": report.get("feedback"),
        "details": report.get("details", {}),
        "warnings": report.get("warnings", []),
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
