#!/usr/bin/env python3
"""Verifier wrapper G07: safety sanitizer diagnosis (DIAGNOSTIC policy).

Builds the candidate against the manifest's ``fixture_dir`` official test
with AddressSanitizer + UndefinedBehaviorSanitizer (via the safety engine)
and classifies the dynamic safety outcome: CLEAN / SANITIZER_HIT (with UB
kind and first candidate-frame location) / CRASH_NO_REPORT / BUILD_FAIL /
TIMEOUT.

Diagnostic, not additive: every kernel this wrapper emits carries
``kernel: 0``, excluded from the receipt's numeric ``kernel_sum`` (and
``maximum_kernel_sum``), so a G07 finding never changes the semantic score.
The wrapper still reports ``status: fail`` and exits 1 on a safety finding.

Runner contract: reads --candidate-dir/--manifest/--expected-manifest-sha256,
writes <output-dir>/verification_receipt.json, exits 0 no safety finding /
1 safety finding / 2 invalid.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _global_common as common

POLICY_ID = "G07"
ENGINE = "08_safety_sanitizer_verifier.py"

# Verdicts this policy owns (a real safety finding); everything else is a
# fact owned by another policy.
SAFETY_FINDING_VERDICTS = {"SANITIZER_HIT", "CRASH_NO_REPORT"}

DIAGNOSTIC_NOTE = (
    "diagnostic policy: kernel value 0, excluded from the semantic kernel "
    "sum; functional failures are owned by G03, build failures by G02")


def diagnostic_kernel(kernel_id, status, summary, **kwargs):
    """A kernel that reports a verdict but never enters the kernel sum."""
    kern = common.kernel(kernel_id, status, summary, **kwargs)
    kern["kernel"] = 0  # diagnostic: not additive (see module docstring)
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
        # Engine INVALID: usage error or the anti-exploit control fired.
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
