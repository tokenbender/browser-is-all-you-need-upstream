#!/usr/bin/env bash
# Run verifier 07 against every extracted real case and check expectations.
set -u
cd "$(dirname "$0")"
V=../../07_warning_hygiene_classifier.py
python3 - <<'EOF'
import json, subprocess, sys

with open("cases/expected.json") as f:
    manifest = json.load(f)

results = []
for entry in manifest:
    case = entry["case"]
    path = None
    for ext in (".stderr.txt", ".build-log.txt"):
        p = f"cases/{case}{ext}"
        try:
            open(p); path = p; break
        except OSError:
            pass
    proc = subprocess.run(
        [sys.executable, "../../07_warning_hygiene_classifier.py",
         "--stderr", path, "--json"],
        capture_output=True, text=True)
    report = json.loads(proc.stdout)
    ok = (report["verdict"] == entry["expected_verdict"]
          and report["dominant_class"] == entry["expected_dominant"])
    results.append((case, ok, report["verdict"], report["dominant_class"],
                    report["error_count"], proc.returncode))
    print(f"{'OK  ' if ok else 'BAD '} {case:42s} "
          f"verdict={report['verdict']:4s} dominant={report['dominant_class']} "
          f"errors={report['error_count']} exit={proc.returncode}")

bad = [r for r in results if not r[1]]
print(f"\n{len(results) - len(bad)}/{len(results)} cases match expectations")
sys.exit(1 if bad else 0)
EOF
