#!/usr/bin/env python3
"""Extract clean (recorded PASS) assistant responses from eval chat histories.

Aider whole-format chat histories prefix every user-side line with '#### '
or '> '; the assistant's reply is the trailing UNPREFIXED block before the
turn-closing '> Tokens:' line. This script extracts the turn-1 assistant
reply from two recorded turn-1 PASS runs (.aider.results.json
tests_outcomes == [true]) and asserts the production whole-file parser
accepts the extraction as format-valid over both editable files.

Stdlib only. Writes cases/clean__<task>__turn1.response.txt.
"""
import json
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "src"))
from glm47_posttraining.aider_polyglot.parser import (  # noqa: E402
    parse_whole_file_response)

EVAL = os.path.join(
    REPO, "evidence", "global_iter14_eval", "trial-01", "receipts", "shard-1",
    "2026-08-26-02-29-42--global-direct-iter14-fixed26-20260826-020704"
    "-trial-01-shard-1", "cpp", "exercises", "practice")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cases")

TASKS = {
    "space-age": ["space_age.h", "space_age.cpp"],
    "phone-number": ["phone_number.h", "phone_number.cpp"],
}


def extract_turn1_assistant(history_path):
    lines = open(history_path).read().splitlines(keepends=True)
    # Turn 1 ends at the first '> Tokens:' line.
    end = next(i for i, l in enumerate(lines) if l.startswith("> Tokens:"))
    turn = lines[:end]
    # The assistant reply is the trailing block after the last user-side
    # ('#### ' or '> '-prefixed) line.
    last_user = max(i for i, l in enumerate(turn)
                    if l.startswith("#### ") or l.startswith("> "))
    return "".join(turn[last_user + 1:]).strip("\n") + "\n"


def main():
    for task, editable in TASKS.items():
        exdir = os.path.join(EVAL, task)
        results = json.load(open(os.path.join(exdir, ".aider.results.json")))
        assert results["tests_outcomes"] == [true_]
        resp = extract_turn1_assistant(
            os.path.join(exdir, ".aider.chat.history.md"))
        parsed = parse_whole_file_response(resp, editable)
        assert set(parsed.files) == set(editable), (task, parsed.files)
        assert parsed.format_valid, task
        out = os.path.join(OUT, f"clean__{task}__turn1.response.txt")
        with open(out, "w") as f:
            f.write(resp)
        print(f"{task}: turn-1 PASS response extracted ({len(resp)} chars), "
              f"production parser: files={sorted(parsed.files)} "
              f"format_valid={parsed.format_valid} -> {out}")


true_ = True  # results json literal

if __name__ == "__main__":
    main()
