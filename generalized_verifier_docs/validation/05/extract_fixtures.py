#!/usr/bin/env python3
"""Extract real raw-model-output fixtures for verifier 05 validation.

Sources (all read-only; outputs go to validation/05/fixtures/):

  A. evidence/global_iter14_eval/empty_full.pkl
     Full thinking-channel text of the 126 recorded empty-ANSWER events
     (the ANSWER channel was empty for every one of these; an empty file
     is written alongside each thinking dump to represent that).
  B. /tmp/phone_iter14_gcs_audit/extracted/train_records.jsonl
     Training rollout rows with the full raw response text
     (truncated rows have response_length == 8192 == train cap).
  C. evidence/global_iter14_eval/trial-0*/receipts/.../*/.aider.chat.history.md
     Known-good complete replies: assistant reply blocks (lines not prefixed
     with '>' or '####') that contain a file listing and are immediately
     followed by a '> Applied edit' confirmation from aider.

Every fixture is paired with a small .meta.json describing provenance and
the expected verdict.
"""

import glob
import json
import os
import pickle

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures")
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
EV = os.path.join(REPO, "evidence")
PHONE_RECORDS = "/tmp/phone_iter14_gcs_audit/extracted/train_records.jsonl"

EMPTY_ANSWER = os.path.join(FIX, "_empty_answer.txt")


def write(name, text, meta):
    path = os.path.join(FIX, name)
    with open(path, "w") as f:
        f.write(text)
    meta["fixture"] = name
    with open(path + ".meta.json", "w") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    print(f"  {name:44s} {len(text):7d} chars  expect={meta['expect']}")


def from_pkl():
    print("A. empty_full.pkl events (eval raw generations, ANSWER channel empty):")
    with open(os.path.join(EV, "global_iter14_eval", "empty_full.pkl"), "rb") as f:
        events = pickle.load(f)
    # Hand-picked recorded cases, by (trial, task, index-in-pkl).
    picks = {
        25: ("loop-knapsack-cjk-phrase", "LOOP",
             "trial-01 knapsack cap-hit: 'wait，我将输出文件。' exact-phrase loop, "
             "cut mid-phrase at the 32768 cap"),
        16: ("loop-bank-account-fullwidth-paren", "LOOP",
             "trial-01 bank-account cap-hit: fullwidth-paren run loop"),
        62: ("loop-meetup-fullwidth-paren", "LOOP",
             "trial-02 meetup cap-hit: fullwidth-paren run loop"),
        80: ("empty-crypto-square-solution-in-thinking", "EMPTY",
             "trial-03 crypto-square turn-1: 72.6k chars, complete fenced solution "
             "drafted inside THINKING, clean end, ANSWER empty, no cap"),
        4: ("empty-allergies-solution-in-thinking", "EMPTY",
            "trial-01 allergies: 33.5k chars, clean fenced end, ANSWER empty"),
        61: ("trunc-zebra-puzzle-mid-line-cap", "TRUNCATED",
             "trial-02 zebra-puzzle cap-hit: no tail loop, generation cut "
             "mid-statement ('result[1 + HouseCount] = assignment[')"),
        41: ("trunc-allergies-cjk-drift-cap", "TRUNCATED",
             "trial-02 allergies cap-hit: CJK drift, cut mid-sentence, no hard loop"),
    }
    if not os.path.exists(EMPTY_ANSWER):
        open(EMPTY_ANSWER, "w").close()
    for idx, (name, expect, note) in picks.items():
        e = events[idx]
        src = (f"empty_full.pkl[{idx}] trial={e['trial']} shard={e['shard']} "
               f"task={e['task']} tok_limit={e['tok_limit']} "
               f"think_chars={len(e['think'])}")
        write(name + ".txt", e["think"], {
            "expect": expect, "source": src, "note": note,
            "answer_file": "_empty_answer.txt",
            "gen_tokens": 32768 if e["tok_limit"] else None,
            "max_tokens": 32768 if e["tok_limit"] else None,
        })


def from_phone_records():
    print("B. phone training rows (full raw response text):")
    picked = 0
    with open(PHONE_RECORDS) as f:
        for line in f:
            r = json.loads(line)
            if r.get("sample_status") != "truncated":
                continue
            resp = r["response"]
            fences = resp.count("```")
            if picked == 0 and fences % 2 == 0:
                write("trunc-trainrow-mid-line-8192.txt", resp, {
                    "expect": "TRUNCATED",
                    "source": f"{PHONE_RECORDS} task_id={r['task_id']} "
                              f"iteration={r['iteration']} "
                              f"response_length={r['response_length']}",
                    "note": "truncated train row, cut mid-line "
                            "(tail: '...Usually, yes'), fences balanced",
                    "gen_tokens": r["response_length"], "max_tokens": 8192,
                })
                picked += 1
            elif picked == 1 and fences % 2 == 1:
                write("trunc-trainrow-unclosed-fence-8192.txt", resp, {
                    "expect": "TRUNCATED",
                    "source": f"{PHONE_RECORDS} task_id={r['task_id']} "
                              f"iteration={r['iteration']} "
                              f"response_length={r['response_length']}",
                    "note": "truncated train row, odd fence count "
                            "(unclosed code fence) at the 8192 cap",
                    "gen_tokens": r["response_length"], "max_tokens": 8192,
                })
                picked += 1
            if picked == 2:
                break


PATH_LINE = __import__("re").compile(
    r"^[A-Za-z0-9_./-]+\.[A-Za-z0-9]+$")


def good_replies_from_history(path, limit=2):
    """Assistant reply blocks confirmed by aider's '> Applied edit' line."""
    with open(path) as f:
        lines = f.read().splitlines()
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith(">") or line.startswith("####") or not line.strip():
            i += 1
            continue
        # start of an assistant reply block
        j = i
        while j < len(lines) and not lines[j].startswith(">"):
            j += 1
        block = "\n".join(lines[i:j]) + "\n"
        followed = "\n".join(lines[j:j + 4])
        if ("```" in block and "Applied edit" in followed
                and any(PATH_LINE.match(l) for l in block.splitlines())):
            out.append(block)
            if len(out) >= limit:
                return out
        i = j
    return out


def from_chat_histories():
    print("C. known-good complete replies from chat histories "
          "(aider confirmed 'Applied edit'):")
    # One passed-eval reply per task, three different tasks.
    wants = ["crypto-square", "bank-account", "clock"]
    for task in wants:
        pat = os.path.join(EV, "global_iter14_eval", "trial-0*", "receipts",
                           "shard-*", "*", "cpp", "exercises", "practice",
                           task, ".aider.chat.history.md")
        for hist in sorted(glob.glob(pat)):
            replies = good_replies_from_history(hist, limit=1)
            if replies:
                rel = os.path.relpath(hist, REPO)
                write(f"good-{task}-reply.txt", replies[0], {
                    "expect": "OK",
                    "source": f"{rel} (reply followed by '> Applied edit')",
                    "note": "complete whole-file listing reply from a "
                            "recorded eval turn that aider applied",
                })
                break


def main():
    os.makedirs(FIX, exist_ok=True)
    from_pkl()
    from_phone_records()
    from_chat_histories()


if __name__ == "__main__":
    main()
