#!/usr/bin/env python3

















import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _global_common as common

POLICY_ID = "G07"
ENGINE = "08_safety_sanitizer_verifier.py"



SAFETY_FINDING_VERDICTS = {"SANITIZER_HIT", "CRASH_NO_REPORT"}

DIAGNOSTIC_NOTE = (
    "diagnostic policy: excluded from semantic aggregation; functional "
    "failures are owned by G03, build failures by G02")


def diagnostic_kernel(kernel_id, status, summary, **kwargs):
    pass
    kern = common.kernel(kernel_id, status, summary, **kwargs)
    kern["facts"]["policy_role"] = "diagnostic"
    return kern


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
    if result["return_code"] == 2:

        try:
            report = json.loads(result["stdout"])
            reason = report.get("reason") or report.get("detail") or \
                common.tail(result["stderr"], 400)
        except ValueError:
            reason = common.tail(result["stderr"], 400)
        raise common.InvalidInput(f"safety verifier: {reason}")
    report = common.parse_engine_json(result, "safety sanitizer")

    verdict = report.get("verdict")
    functional = report.get("functional") or {}
    facts = {
        "engine": ENGINE,
        "engine_exit_code": result["return_code"],
        "verdict": verdict,
        "safety_kind": report.get("safety_kind"),
        "safety_detail": report.get("safety_detail"),
        "candidate_location": report.get("candidate_location"),
        "functional_outcome": functional.get("outcome"),
        "functional_outcome_ownership": functional.get("ownership"),
        "process_returncode": report.get("process_returncode"),
        "run_output_tail": common.tail(report.get("run_output_tail", "")),
        "diagnostic_note": DIAGNOSTIC_NOTE,
    }
    if verdict in SAFETY_FINDING_VERDICTS:
        kind = report.get("safety_kind")
        loc = report.get("candidate_location") or {}
        where = (f" at {loc.get('file')}:{loc.get('line')}"
                 if loc.get("file") else "")
        kern = diagnostic_kernel(
            f"{POLICY_ID}-1", "fail",
            f"safety finding: {verdict} ({kind}){where} -- "
            f"{report.get('safety_detail')}",
            facts=facts, command=result["command"],
            duration_seconds=result["duration_seconds"])
        status = "fail"
        reason = f"safety finding: {verdict} ({kind}){where}"
    else:
        note = report.get("reason") or "no sanitizer report"
        kern = diagnostic_kernel(
            f"{POLICY_ID}-1", "pass",
            f"no safety finding ({verdict}): {note}",
            facts=facts, command=result["command"],
            duration_seconds=result["duration_seconds"])
        status = "pass"
        reason = f"safety diagnosis: {verdict} -- {note}"
    return [kern], status, reason


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
        manifest_sha256, before, kernels, status, reason,
        extra_fields={
            "policy_role": "diagnostic",
            "diagnostic_note": DIAGNOSTIC_NOTE,
        })


if __name__ == "__main__":
    sys.exit(main())
