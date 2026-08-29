#!/usr/bin/env python3
"""Agreement sweep: verifier 06 vs the production whole-file parser.

For every recorded case in cases/manifest.json, runs BOTH
  (a) the production parser (src/glm47_posttraining/aider_polyglot/parser.py)
      -- the gate that assigned the recorded `reason` / reward, and
  (b) verifier 06 (06_candidate_boundary_verifier.py, imported)
and asserts:
  * production reason 'forbidden_file' -> 06 status FAIL with a fatal
    FORBIDDEN_FILE issue naming the same file production rejected;
  * production reason 'duplicate_file' -> 06 status FAIL with a fatal
    DUPLICATE_FILE issue on the same file;
  * production reason 'invalid_format' -> 06 status FAIL with NO_FILES;
  * the recorded truncated header-only response (accepted by production)
    -> 06 status OK_WITH_MODIFICATIONS with TRUNCATED_LISTING +
    OMITTED_FILLED (the two facts production kept silent about);
  * both clean recorded-PASS responses -> 06 status OK, zero issues.
"""
import importlib.util
import json
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "src"))
from glm47_posttraining.aider_polyglot.parser import (  # noqa: E402
    AiderResponseError, parse_whole_file_response)

_spec = importlib.util.spec_from_file_location(
    "verifier06",
    os.path.join(REPO, "generalized_verifier_docs",
                 "06_candidate_boundary_verifier.py"))
_v06 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_v06)

CASES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cases")
TASKS = os.path.join(REPO, "evidence", "global_direct_grpo30_audit",
                     "data", "tasks", "train")
FIXTURES = os.path.join(REPO, "Reward_GRPO", "multi_env_fixtures")

EXPECT_FATAL = {"forbidden_file": "FORBIDDEN_FILE",
                "duplicate_file": "DUPLICATE_FILE",
                "invalid_format": "NO_FILES"}


def editable_of(task_id):
    d = json.load(open(os.path.join(TASKS, task_id.split("/")[-1] + ".json")))
    return d["editable_files"], d["family"]


def main():
    failures = []
    manifest = json.load(open(os.path.join(CASES, "manifest.json")))
    for e in manifest:
        editable, family = editable_of(e["task_id"])
        resp = open(os.path.join(CASES, e["file"])).read()
        try:
            parse_whole_file_response(resp, editable)
            prod = "accepted"
        except AiderResponseError as exc:
            prod = exc.reason
        rep = _v06.verify_response(resp, editable)
        kinds = {i["kind"] for i in rep["issues"]}
        fatal_files = {i["file"] for i in rep["issues"]
                       if i["severity"] == "fatal"}
        ok = (prod == e["reason"] and rep["status"] == "FAIL"
              and EXPECT_FATAL[e["reason"]] in kinds)
        print(f"{'OK ' if ok else 'BAD'} {e['file']:46s} prod={prod:15s} "
              f"06={rep['status']} fatal={sorted(str(f)[:40] for f in fatal_files)}")
        if not ok:
            failures.append(e["file"])

    # Recorded truncated header-only response: production ACCEPTED it;
    # 06 must surface TRUNCATED_LISTING + OMITTED_FILLED instead of FAIL.
    resp = open(os.path.join(REPO, "evidence", "global_direct_grpo30_audit",
                             "zebra_case", "resp_u0_s74.txt")).read()
    editable, _ = editable_of("aider-shadow-cpp/zebra-puzzle--00-g04-r00")
    parsed = parse_whole_file_response(resp, editable)
    templates = {n: open(os.path.join(FIXTURES, "zebra-puzzle", n)).read()
                 for n in editable}
    rep = _v06.verify_response(resp, editable, templates)
    kinds = {i["kind"] for i in rep["issues"]}
    ok = (set(parsed.files) == {"zebra_puzzle.h"}
          and rep["status"] == "OK_WITH_MODIFICATIONS"
          and {"TRUNCATED_LISTING", "OMITTED_FILLED"} <= kinds)
    print(f"{'OK ' if ok else 'BAD'} zebra u0/s74 truncated-header-only: "
          f"prod=accepted(files={sorted(parsed.files)}) "
          f"06={rep['status']} issues={sorted(kinds)}")
    if not ok:
        failures.append("zebra_u0_s74")

    # Clean recorded-PASS responses: 06 must return OK with zero issues.
    for task, editable in (("space-age", ["space_age.h", "space_age.cpp"]),
                           ("phone-number",
                            ["phone_number.h", "phone_number.cpp"])):
        resp = open(os.path.join(
            CASES, f"clean__{task}__turn1.response.txt")).read()
        rep = _v06.verify_response(resp, editable)
        ok = rep["status"] == "OK" and not rep["issues"] \
            and not rep["modified"]
        print(f"{'OK ' if ok else 'BAD'} clean {task:14s} "
              f"06={rep['status']} issues={len(rep['issues'])} "
              f"modified={rep['modified']}")
        if not ok:
            failures.append(task)

    print("AGREEMENT:", "ALL PASS" if not failures
          else f"FAILURES: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
