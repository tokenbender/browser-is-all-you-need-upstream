#!/usr/bin/env bash
# Run verifier 08 against every extracted case and check expectations.
# All runs are real (system g++ 13.3.0, ASan+UBSan); nothing is mocked.
set -u
cd "$(dirname "$0")"
python3 - <<'EOF'
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir() else os.getcwd()
ENGINE = os.path.abspath(os.path.join("../../08_safety_sanitizer_verifier.py"))

with open("cases/expected.json") as f:
    manifest = json.load(f)

results = []
for entry in manifest:
    case = entry["case"]
    header = entry["header"]
    source = entry["source"]
    if not os.path.isabs(header):
        header = os.path.join("cases", case, header)
    if source and not os.path.isabs(source):
        source = os.path.join("cases", case, source)
    cmd = [sys.executable, ENGINE, "--fixture-dir", entry["fixture"],
           "--header", header, "--json"]
    if source:
        cmd += ["--source", source]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        report = {"verdict": "<no json>", "stderr": proc.stderr[:400]}
    ok = (report.get("verdict") in entry["expected_verdict_in"]
          and proc.returncode == entry["expected_exit"])
    if "expected_reason" in entry:
        ok = ok and report.get("reason") == entry["expected_reason"]
    if "expected_functional_outcome" in entry:
        ok = ok and report.get("functional", {}).get("outcome") == \
            entry["expected_functional_outcome"]
    results.append((case, ok))
    loc = report.get("candidate_location")
    loc_s = f" {loc['file']}:{loc['line']}" if loc else ""
    print(f"{'OK  ' if ok else 'BAD '} {case:38s} "
          f"verdict={report.get('verdict')!s:16s} "
          f"kind={report.get('safety_kind')!s:20s} "
          f"exit={proc.returncode}{loc_s}")

bad = [r for r in results if not r[1]]
print(f"\n{len(results) - len(bad)}/{len(results)} cases match expectations")
sys.exit(1 if bad else 0)
EOF
