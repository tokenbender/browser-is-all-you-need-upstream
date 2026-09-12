#!/usr/bin/env python3
"""Verifier wrapper G05: candidate boundary.

Checks the raw model response against the task's editable file set (the
manifest's ``candidate_files`` basenames) and reconstructs the post-response
file set, by invoking the candidate boundary engine.  Template content for
omitted editable files is taken from same-named files in ``fixture_dir``
when present.  The response text comes from the manifest trajectory turns
(``response_file`` / ``response_text``) or the same fields at top level;
without a response the verdict is invalid.

Runner contract: reads --candidate-dir/--manifest/--expected-manifest-sha256,
writes <output-dir>/verification_receipt.json, exits 0 pass / 1 fail /
2 invalid.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _global_common as common

POLICY_ID = "G05"
ENGINE = "06_candidate_boundary_verifier.py"


def run_checks(args, manifest):
    response_path, cleanup = common.find_response(manifest)
    editable = [os.path.basename(item) for item in manifest["candidate_files"]]
    fixture = manifest.get("fixture_dir")
    engine_args = ["--response", response_path]
    for name in editable:
        engine_args += ["--editable", name]
    templates = []
    if isinstance(fixture, str) and os.path.isdir(fixture):
        for name in editable:
            template = os.path.join(fixture, name)
            if os.path.isfile(template):
                templates.append(name)
                engine_args += ["--template", f"{name}={template}"]
    engine_args.append("--json")
    try:
        result = common.run_engine(common.find_engine(ENGINE), engine_args)
        report = common.parse_engine_json(result, "candidate boundary")
    finally:
        if cleanup:
            os.unlink(cleanup)

    boundary_status = report.get("status")
    status = "fail" if boundary_status == "FAIL" else "pass"
    issues = report.get("issues", [])
    summary = (f"candidate boundary: {boundary_status} "
               f"({len(issues)} issue(s))")
    facts = {
        "engine": ENGINE,
        "engine_exit_code": result["return_code"],
        "boundary_status": boundary_status,
        "modified": report.get("modified"),
        "editable": editable,
        "templates_applied": templates,
        "issues": issues,
        "files": report.get("files", {}),
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
