#!/usr/bin/env python3
"""self_check -- three-control self-validation for the six check-layer
verifiers (01, 03, 04, 05, 06, 07).

For EACH verifier this runs three controls, orchestrating the verifier
purely through its CLI (zero task names in this file -- every concrete
input path and expectation lives in ``self_check_cases.json`` as data):

  (a) positive control -- a known-good input must yield PASS/OK;
  (b) fault control    -- the verifier's recorded failure inputs (from
                          validation/0N/ and validation/candidates/) must
                          yield the recorded FAIL class;
  (c) tamper control   -- a deliberately corrupted or cross-task-mismatched
                          input must NOT silently PASS (verifier-specific
                          sensible behavior, documented per case in the
                          config's ``rationale`` field).

Every run also exercises the ``--receipt`` emitter: each case's kernel
receipt lands in ``<receipt-dir>/<case-id>/``.

Outputs:
  --report PATH        human report with the full 6x3 matrix and real
                       pasted outputs (default validation/SELF_CHECK.md)
  --json-out PATH      machine-readable results
  --sandbox-receipt P  additionally write a sandbox-run receipt binding the
                       whole run (image id + controls from the SANDBOX_*
                       environment, per-case verdicts, sha256 of every
                       input/output). Used by run_sandboxed.sh.

Exit code 0 = every control behaved as expected, 1 otherwise.
stdlib only.
"""

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_GV = os.path.dirname(_HERE)
_REPO = os.path.dirname(_GV)

CONTROL_ORDER = ("positive", "fault", "tamper")


def sha256_path(path):
    value = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            value.update(chunk)
    return value.hexdigest()


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Tamper-input generation (generic transforms, no task knowledge)
# ---------------------------------------------------------------------------

def _gen_drop_last_fence(source, dest):
    """Remove the final fence line: a clean stream becomes an unclosed
    (truncated-mid-block) deliverable."""
    with open(source, encoding="utf-8") as handle:
        lines = handle.read().splitlines(keepends=True)
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].lstrip().startswith("```"):
            del lines[i]
            break
    else:
        raise ValueError(f"no fence line found in {source}")
    with open(dest, "w", encoding="utf-8") as handle:
        handle.writelines(lines)


def _gen_concat(sources, dest):
    """Concatenate inputs: a clean log with a foreign error block appended."""
    with open(dest, "w", encoding="utf-8") as out:
        for source in sources:
            with open(source, encoding="utf-8") as handle:
                text = handle.read()
            out.write(text)
            if not text.endswith("\n"):
                out.write("\n")


def generate_input(spec, gen_dir, resolve):
    os.makedirs(gen_dir, exist_ok=True)
    dest = os.path.join(gen_dir, spec["name"])
    kind = spec["kind"]
    if kind == "drop_last_fence":
        _gen_drop_last_fence(resolve(spec["source"]), dest)
    elif kind == "concat":
        _gen_concat([resolve(s) for s in spec["sources"]], dest)
    else:
        raise ValueError(f"unknown generate kind: {kind}")
    return dest


# ---------------------------------------------------------------------------
# Case execution
# ---------------------------------------------------------------------------

def run_case(case, receipts_root, resolve):
    receipt_dir = os.path.join(receipts_root, case["id"])
    os.makedirs(receipt_dir, exist_ok=True)
    argv = [resolve(item) for item in case["argv"]]
    command = [sys.executable, os.path.join(_GV, case["verifier"]),
               *argv, "--receipt", receipt_dir]
    started = time.monotonic()
    proc = subprocess.run(command, cwd=_REPO, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, timeout=600)
    duration = round(time.monotonic() - started, 6)

    expect = case["expect"]
    failures = []
    if proc.returncode != expect["exit"]:
        failures.append(
            f"exit {proc.returncode} != expected {expect['exit']}")
    for needle in expect.get("stdout_contains", []):
        if needle not in proc.stdout:
            failures.append(f"stdout missing {needle!r}")
    for needle in expect.get("stdout_not_contains", []):
        if needle in proc.stdout:
            failures.append(f"stdout unexpectedly contains {needle!r}")

    verifier_stem = os.path.splitext(case["verifier"])[0]
    receipt_path = os.path.join(
        receipt_dir, f"{verifier_stem}_kernel_receipt.json")
    receipt = None
    if os.path.isfile(receipt_path):
        with open(receipt_path, encoding="utf-8") as handle:
            receipt = json.load(handle)

    return {
        "id": case["id"],
        "verifier": case["verifier"],
        "control": case["control"],
        "description": case["description"],
        "rationale": case.get("rationale"),
        "command": command,
        "exit_code": proc.returncode,
        "expected_exit": expect["exit"],
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "duration_seconds": duration,
        "ok": not failures,
        "failures": failures,
        "receipt_path": receipt_path if receipt else None,
        "receipt": receipt,
    }


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------

def _clip(text, max_lines=40):
    lines = text.rstrip("\n").splitlines()
    if len(lines) > max_lines:
        lines = lines[:max_lines] + [f"... ({len(lines) - max_lines} more lines)"]
    return "\n".join(lines)


def render_report(results, all_ok, started_at):
    out = []
    add = out.append
    add("# SELF-CHECK -- 6 verifiers x 3 controls (positive / fault / tamper)")
    add("")
    add(f"Generated: {started_at} by `validation/self_check.py` on "
        f"`{platform.node()}` ({platform.system()} {platform.release()}, "
        f"python {platform.python_version()}, stdlib only).")
    add("")
    add("Every verdict below is from a **real execution** on this machine; "
        "stdout blocks are pasted verbatim. Each run also wrote a "
        "sandbox-compatible kernel receipt via `--receipt` (paths shown per "
        "case). Overall result: "
        f"**{'ALL CONTROLS BEHAVED AS EXPECTED' if all_ok else 'MISMATCHES FOUND -- see FAILURES'}**.")
    add("")
    add("## Matrix")
    add("")
    add("| Verifier | (a) positive -> PASS/OK | (b) fault -> FAIL class | (c) tamper -> no silent PASS |")
    add("|---|---|---|---|")
    verifiers = []
    for r in results:
        if r["verifier"] not in verifiers:
            verifiers.append(r["verifier"])
    for verifier in verifiers:
        cells = []
        for control in CONTROL_ORDER:
            r = next((x for x in results
                      if x["verifier"] == verifier and x["control"] == control),
                     None)
            if r is None:
                cells.append("n/a")
                continue
            mark = "OK" if r["ok"] else "MISMATCH"
            cells.append(f"{mark} (exit {r['exit_code']})")
        add(f"| `{verifier}` | {cells[0]} | {cells[1]} | {cells[2]} |")
    add("")
    add("Legend: `OK` = the verifier produced the expected verdict class for "
        "the control; `MISMATCH` = expectation failed (details below).")
    add("")
    add("## Per-case detail")
    for r in results:
        add("")
        add(f"### {r['id']} -- `{r['verifier']}` ({r['control']} control)")
        add("")
        add(r["description"])
        if r["rationale"]:
            add(f"\nTamper rationale: {r['rationale']}")
        add("")
        add("```")
        add("$ " + " ".join(r["command"]))
        add("```")
        add("")
        add(f"exit code: {r['exit_code']} (expected {r['expected_exit']}) "
            f"-- expectation {'MET' if r['ok'] else 'FAILED: ' + '; '.join(r['failures'])}")
        if r["receipt_path"]:
            add(f"kernel receipt: `{os.path.relpath(r['receipt_path'], _REPO)}`")
        add("")
        add("```")
        add(_clip(r["stdout"]))
        if r["stderr"].strip():
            add("--- stderr ---")
            add(_clip(r["stderr"], 10))
        add("```")
    add("")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Sandbox receipt
# ---------------------------------------------------------------------------

def write_sandbox_receipt(path, results, report_path, json_path):
    """Bind the whole run: image identity + controls from the environment
    (injected by run_sandboxed.sh), per-case verdicts, sha256 of every
    input and output."""
    image = os.environ.get("SANDBOX_IMAGE")
    image_id = os.environ.get("SANDBOX_IMAGE_ID")
    try:
        controls = json.loads(os.environ.get("SANDBOX_CONTROLS", "{}"))
    except json.JSONDecodeError:
        controls = {"raw": os.environ.get("SANDBOX_CONTROLS")}

    inputs = {}
    cases = []
    for r in results:
        receipt = r["receipt"] or {}
        for name, digest in (receipt.get("input_sha256") or {}).items():
            inputs[name] = digest
        entry = {
            "case_id": r["id"],
            "verifier": r["verifier"],
            "control": r["control"],
            "exit_code": r["exit_code"],
            "expected_exit": r["expected_exit"],
            "expectation_met": r["ok"],
            "kernel_status": receipt.get("status"),
            "kernel": (receipt.get("kernel_results") or [{}])[0].get("kernel"),
            "summary": (receipt.get("kernel_results") or [{}])[0].get("summary"),
        }
        if r["receipt_path"] and os.path.isfile(r["receipt_path"]):
            entry["kernel_receipt_sha256"] = sha256_path(r["receipt_path"])
        cases.append(entry)

    outputs = {}
    for label, candidate in (("self_check_report", report_path),
                             ("self_check_results", json_path)):
        if candidate and os.path.isfile(candidate):
            outputs[label] = {"path": candidate,
                              "sha256": sha256_path(candidate)}

    receipt = {
        "receipt_format": "check-layer-sandbox-run/1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "image": image,
        "image_id": image_id,
        "controls": controls,
        "inside_container": os.environ.get("SANDBOX_INSIDE") == "1",
        "status": "pass" if all(r["ok"] for r in results) else "fail",
        "case_count": len(cases),
        "cases": cases,
        "inputs_sha256": inputs,
        "outputs": outputs,
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(receipt, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Three-control self-validation matrix for the six "
                    "check-layer verifiers (positive / fault / tamper).")
    ap.add_argument("--cases", default=os.path.join(_HERE, "self_check_cases.json"),
                    help="case matrix JSON (all concrete inputs live here)")
    ap.add_argument("--receipt-dir",
                    default=os.path.join(_HERE, "self_check_receipts"),
                    help="root dir for per-case kernel receipts")
    ap.add_argument("--gen-dir",
                    default=os.path.join(_HERE, "self_check_generated"),
                    help="dir for runtime-generated tamper inputs")
    ap.add_argument("--report", default=os.path.join(_HERE, "SELF_CHECK.md"))
    ap.add_argument("--json-out", default=None,
                    help="write machine-readable results JSON here")
    ap.add_argument("--sandbox-receipt", default=None, metavar="PATH",
                    help="also write a sandbox-run receipt (image identity "
                         "and controls are read from SANDBOX_* env vars)")
    args = ap.parse_args(argv)

    with open(args.cases, encoding="utf-8") as handle:
        config = json.load(handle)

    placeholders = {
        "{REPO}": _REPO,
        "{GV}": _GV,
        "{VAL}": _HERE,
        "{FIXTURES}": os.path.join(_HERE, "fixtures"),
        "{GEN}": args.gen_dir,
    }

    def resolve(value):
        for token, target in placeholders.items():
            value = value.replace(token, target)
        return value

    started_at = datetime.now(timezone.utc).isoformat()
    results = []
    for case in config["cases"]:
        if "generate" in case:
            spec = dict(case["generate"])
            for key in ("source",):
                if key in spec:
                    spec[key] = resolve(spec[key])
            if "sources" in spec:
                spec["sources"] = [resolve(s) for s in spec["sources"]]
            generate_input(spec, args.gen_dir, lambda v: v)
        print(f"[self-check] {case['id']} ({case['verifier']}, "
              f"{case['control']}) ...", flush=True)
        results.append(run_case(case, args.receipt_dir, resolve))
        print(f"[self-check]   -> exit {results[-1]['exit_code']} "
              f"({'ok' if results[-1]['ok'] else 'MISMATCH: ' + '; '.join(results[-1]['failures'])})",
              flush=True)

    all_ok = all(r["ok"] for r in results)
    report = render_report(results, all_ok, started_at)
    os.makedirs(os.path.dirname(os.path.abspath(args.report)), exist_ok=True)
    with open(args.report, "w", encoding="utf-8") as handle:
        handle.write(report)
    print(f"[self-check] report: {args.report}", flush=True)

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump({"generated_at": started_at,
                       "all_ok": all_ok,
                       "cases": [{k: v for k, v in r.items()
                                  if k not in ("stdout", "stderr", "receipt")}
                                 for r in results]},
                      handle, indent=2, ensure_ascii=False)
            handle.write("\n")

    if args.sandbox_receipt:
        write_sandbox_receipt(args.sandbox_receipt, results,
                              args.report, args.json_out)
        print(f"[self-check] sandbox receipt: {args.sandbox_receipt}",
              flush=True)

    print(f"[self-check] overall: "
          f"{'PASS' if all_ok else 'FAIL'} "
          f"({sum(r['ok'] for r in results)}/{len(results)} controls ok)")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
