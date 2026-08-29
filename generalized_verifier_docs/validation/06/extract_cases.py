#!/usr/bin/env python3
"""Extract raw recorded responses for verifier-06 validation cases.

Reads evidence/global_direct_grpo30_audit/rollout_dumps/grpo_<u>.pt with
torch.load(weights_only=True) ONLY (same discipline as
evidence/global_direct_grpo30_audit/extract_audit.py). torch is already
installed on this machine; nothing is installed or fetched.

For each requested (update, task_id, sample_index) row, writes the raw
response text to cases/<family>__u<update>_s<sample>.response.txt and records
the row metadata in cases/manifest.json.
"""
import json
import os
import sys

import torch

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
AUDIT = os.path.join(REPO, "evidence", "global_direct_grpo30_audit")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cases")

# (update, task_id, sample_index, expected_reason) -- coordinates taken from
# evidence/global_direct_grpo30_audit/rows_train.jsonl (reason field).
WANTED = [
    # forbidden_file, four families
    (1, "aider-shadow-cpp/meetup--00-g04-r12", 477, "forbidden_file"),
    (1, "aider-shadow-cpp/linked-list--00-g04-r16", 433, "forbidden_file"),
    (2, "aider-shadow-cpp/kindergarten-garden--00-g04-r10", 666, "forbidden_file"),
    (3, "aider-shadow-cpp/zebra-puzzle--00-g04-r00", 798, "forbidden_file"),
    # duplicate_file, four families
    (0, "aider-shadow-cpp/meetup--00-g04-r05", 130, "duplicate_file"),
    (2, "aider-shadow-cpp/linked-list--00-g04-r08", 530, "duplicate_file"),
    (18, "aider-shadow-cpp/kindergarten-garden--00-g04-r19", 4788, "duplicate_file"),
    (8, "aider-shadow-cpp/zebra-puzzle--00-g04-r15", 2294, "duplicate_file"),
    # invalid_format (truncation), one per family where recorded
    (2, "aider-shadow-cpp/kindergarten-garden--00-g04-r17", 609, "invalid_format"),
    (0, None, None, "invalid_format:meetup"),
]


def family_of(task_id):
    return task_id.split("/")[-1].split("--")[0]


def main():
    os.makedirs(OUT, exist_ok=True)
    rows = {}
    for line in open(os.path.join(AUDIT, "rows_train.jsonl")):
        r = json.loads(line)
        rows[(r["update"], r["task_id"], r["sample_index"])] = r

    # Resolve the two family-level invalid_format picks to concrete rows.
    resolved = []
    for update, task_id, sample, reason in WANTED:
        if task_id is None:
            fam = reason.split(":", 1)[1]
            cand = next(
                (r for (u, _t, _s), r in sorted(rows.items())
                 if u == update and r["family"] == fam
                 and r["reason"] == "invalid_format"
                 and r["status"] == "truncated"),
                None)
            if cand is None:
                print(f"no invalid_format row for {fam} at update {update}",
                      file=sys.stderr)
                continue
            resolved.append((update, cand["task_id"], cand["sample_index"],
                             "invalid_format"))
        else:
            resolved.append((update, task_id, sample, reason))

    manifest = []
    by_update = {}
    for update, task_id, sample, reason in resolved:
        by_update.setdefault(update, []).append((task_id, sample, reason))

    for update, wants in sorted(by_update.items()):
        path = os.path.join(AUDIT, "rollout_dumps", f"grpo_{update}.pt")
        d = torch.load(path, map_location="cpu", weights_only=True)
        for task_id, sample, reason in wants:
            row = rows.get((update, task_id, sample))
            assert row and row["reason"] == reason, (update, task_id, sample)
            hit = None
            for s in d["samples"]:
                r = s.get("reward") or {}
                if (r.get("task_id") == task_id
                        and r.get("sample_index", s.get("index")) == sample):
                    hit = s
                    break
            if hit is None:
                print(f"MISSING sample {update}/{task_id}/{sample}",
                      file=sys.stderr)
                continue
            fam = family_of(task_id)
            base = f"{fam}__u{update}_s{sample}"
            resp_path = os.path.join(OUT, base + ".response.txt")
            with open(resp_path, "w") as f:
                f.write(hit.get("response") or "")
            manifest.append({
                "file": os.path.basename(resp_path),
                "update": update, "task_id": task_id,
                "sample_index": sample, "reason": reason,
                "status": hit.get("status"),
                "response_length": hit.get("response_length"),
                "reward": row["reward"],
            })
            print(f"extracted {base} reason={reason} "
                  f"len={hit.get('response_length')}")

    with open(os.path.join(OUT, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)


if __name__ == "__main__":
    main()
