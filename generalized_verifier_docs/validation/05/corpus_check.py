#!/usr/bin/env python3
"""Corpus-scale validation of verifier 05 (real recorded data, not fixtures):

  1. All 126 recorded empty-ANSWER eval events (empty_full.pkl): none may
     verdict OK; verdicts should track the recorded cap-hit flag
     (cap-hit -> LOOP or TRUNCATED; uncapped -> EMPTY unless it ends in a
     loop).
  2. All 5,120 phone training rows: truncated rows (cap == 8192) should be
     LOOP/TRUNCATED/EMPTY, never OK; format_valid rows that passed should be
     overwhelmingly OK.
  3. Every aider-confirmed reply in all 104 chat histories: all OK
     (false-positive sweep).
"""
import glob
import importlib.util
import json
import os
import pickle
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
spec = importlib.util.spec_from_file_location(
    "v05", os.path.join(REPO, "generalized_verifier_docs",
                        "05_response_integrity_verifier.py"))
v05 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v05)

# ---- 1. eval empty-ANSWER events -----------------------------------------
with open(os.path.join(REPO, "evidence", "global_iter14_eval",
                       "empty_full.pkl"), "rb") as f:
    events = pickle.load(f)
tally = Counter()
ok_bad = []
for i, e in enumerate(events):
    r = v05.analyze_response(e["think"], answer="",
                             gen_tokens=32768 if e["tok_limit"] else None,
                             max_tokens=32768 if e["tok_limit"] else None)
    key = ("cap" if e["tok_limit"] else "uncapped", r.verdict.value)
    tally[key] += 1
    if r.verdict is v05.Verdict.OK:
        ok_bad.append(i)
print("1. eval empty-ANSWER events (n=126):")
for k, v in sorted(tally.items()):
    print(f"   {k[0]:9s} -> {k[1]:9s} {v}")
print(f"   verdict OK (must be 0): {len(ok_bad)} {ok_bad}")

# ---- 2. phone training rows ----------------------------------------------
tr_tally = Counter()
ok_trunc = 0
n_rows = n_trunc = 0
good_completed = Counter()
with open("/tmp/phone_iter14_gcs_audit/extracted/train_records.jsonl") as f:
    for line in f:
        r = json.loads(line)
        n_rows += 1
        trunc = r.get("sample_status") == "truncated"
        if trunc:
            n_trunc += 1
        rep = v05.analyze_response(
            r["response"],
            gen_tokens=r.get("response_length") if trunc else None,
            max_tokens=8192 if trunc else None)
        if trunc:
            tr_tally[rep.verdict.value] += 1
            if rep.verdict is v05.Verdict.OK:
                ok_trunc += 1
        elif r.get("format_valid"):
            good_completed[rep.verdict.value] += 1
print(f"2. phone train rows (n={n_rows}, truncated={n_trunc}):")
print(f"   truncated-row verdicts: {dict(tr_tally)}  (OK among them: {ok_trunc})")
print(f"   format-valid completed-row verdicts: {dict(good_completed)}")

# ---- 3. known-good reply sweep -------------------------------------------
import sys
sys.path.insert(0, HERE)
from extract_fixtures import good_replies_from_history  # noqa: E402

n = fp = 0
for hist in glob.glob(os.path.join(
        REPO, "evidence", "global_iter14_eval", "trial-0*", "receipts",
        "shard-*", "*", "cpp", "exercises", "practice", "*",
        ".aider.chat.history.md")):
    for reply in good_replies_from_history(hist, limit=99):
        n += 1
        rep = v05.analyze_response(reply)
        if rep.verdict is not v05.Verdict.OK:
            fp += 1
            print("   FP:", hist.split("practice/")[1], rep.verdict.value,
                  rep.feedback[:100])
print(f"3. aider-confirmed good replies: {n}, non-OK (must be 0): {fp}")
