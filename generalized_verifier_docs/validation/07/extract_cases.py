#!/usr/bin/env python3
"""Extract REAL recorded compiler-output blocks into validation/07/cases/.

Every failing case is a verbatim fenced build-output block lifted from a
recorded aider chat history under evidence/ (anchor = 1-based line of the
first 'error:' line inside that block). The training-side cases are direct
copies of recorded stderr files from the GRPO training audit. Nothing here
invents compiler output; expected classes were assigned by reading the
recorded diagnostics.

The evidence/ tree is never modified; all outputs land in cases/.
"""

import glob
import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
EVAL = os.path.join(REPO, "evidence", "global_iter14_eval")
AUDIT = os.path.join(REPO, "evidence", "global_direct_grpo30_audit")
OUT = os.path.join(HERE, "cases")


def history(trial, shard, task):
    pat = os.path.join(EVAL, trial, "receipts", shard, "*",
                       "cpp", "exercises", "practice", task,
                       ".aider.chat.history.md")
    hits = glob.glob(pat)
    if len(hits) != 1:
        raise SystemExit(f"history glob failed for {trial}/{shard}/{task}: {hits}")
    return hits[0]


def fence_block(path, anchor_lineno):
    """Return the verbatim content of the ``` fence enclosing anchor_lineno
    (1-based)."""
    with open(path) as f:
        lines = f.read().splitlines()
    idx = anchor_lineno - 1
    if "```" not in lines[idx]:
        pass  # anchor itself is a content line; fences surround it
    start = None
    for i in range(idx, -1, -1):
        if lines[i].strip() == "```":
            start = i
            break
    end = None
    for i in range(idx + 1, len(lines)):
        if lines[i].strip() == "```":
            end = i
            break
    if start is None or end is None or start >= end:
        raise SystemExit(f"no enclosing fence around {path}:{anchor_lineno}")
    return "\n".join(lines[start + 1:end]) + "\n"


# (case_name, trial, shard, task, anchor_line, expected_dominant, note)
FAIL_CASES = [
    ("eval_unused-parameter", "trial-01", "shard-0", "crypto-square", 279,
     "unused-parameter",
     "error: unused parameter 'text' [-Werror=unused-parameter]"),
    ("eval_missing-include-cstdint", "trial-01", "shard-1", "spiral-matrix", 185,
     "missing-include",
     "error: 'uint32_t' was not declared in this scope -> #include <cstdint>"),
    ("eval_missing-include-unordered_map", "trial-01", "shard-0", "allergies", 420,
     "missing-include",
     "error: 'unordered_map' in namespace 'std' does not name a template type"),
    ("eval_missing-include-string", "trial-01", "shard-0", "diamond", 169,
     "missing-include",
     "error: 'string' is not a member of 'std'"),
    ("eval_return-local-addr", "trial-02", "shard-1", "robot-name", 187,
     "return-local-addr",
     "error: reference to local variable 'name' returned"),
    ("eval_undeclared-identifier", "trial-01", "shard-0", "clock", 507,
     "undeclared-identifier",
     "error: 'normalize' was not declared in this scope"),
    ("eval_private-access", "trial-03", "shard-0", "complex-numbers", 305,
     "private-access",
     "error: 'double ...::Complex::real_' is private within this context"),
    ("eval_constexpr-not-literal", "trial-01", "shard-1", "zebra-puzzle", 421,
     "constexpr-not-literal",
     "error: the type '...' of 'constexpr' variable '...' is not literal"),
    ("eval_unused-variable", "trial-01", "shard-1", "parallel-letter-frequency",
     275, "unused-variable",
     "error: unused variable 'total_letters' [-Werror=unused-variable]"),
    ("eval_unused-function", "trial-02", "shard-1", "zebra-puzzle", 322,
     "unused-function",
     "error: 'bool ...' defined but not used [-Werror=unused-function]"),
    ("eval_tautological-compare", "trial-01", "shard-0", "circular-buffer", 967,
     "tautological-compare",
     "error: self-comparison always evaluates to true"),
]

# Training-side: recorded stderr from the GRPO training audit (direct copies).
# Note: in these files the ROOT CAUSE is the first finding (missing-member:
# the test references a symbol the candidate namespace never declares) but
# the cascade of follow-on "'x' was not declared in this scope" errors in
# the test file outnumbers it, so dominant_class is undeclared-identifier.
TRAIN_CASES = [
    ("train_row0", "bst_case/row0.stderr.txt", "undeclared-identifier"),
    ("train_row1", "bst_case/row1.stderr.txt", "undeclared-identifier"),
    ("train_row2", "bst_case/row2.stderr.txt", "undeclared-identifier"),
]

# Known-good: final build blocks of recorded PASSED eval turns.
CLEAN_CASES = [
    ("clean_robot-name_trial-03", "trial-03", "shard-1", "robot-name"),
    ("clean_spiral-matrix_trial-02", "trial-02", "shard-1", "spiral-matrix"),
]


def main():
    os.makedirs(OUT, exist_ok=True)
    manifest = []

    for name, trial, shard, task, anchor, expected, note in FAIL_CASES:
        path = history(trial, shard, task)
        block = fence_block(path, anchor)
        assert "error:" in block, f"{name}: block has no error line"
        out = os.path.join(OUT, name + ".stderr.txt")
        with open(out, "w") as f:
            f.write(block)
        rel = os.path.relpath(path, REPO)
        manifest.append({"case": name, "source": f"{rel}:{anchor}",
                         "expected_verdict": "FAIL",
                         "expected_dominant": expected, "note": note})
        print(f"{name}: {rel}:{anchor} -> {len(block.splitlines())} lines")

    for name, rel, expected in TRAIN_CASES:
        src = os.path.join(AUDIT, rel)
        out = os.path.join(OUT, name + ".stderr.txt")
        shutil.copyfile(src, out)
        manifest.append({"case": name,
                         "source": f"evidence/global_direct_grpo30_audit/{rel}",
                         "expected_verdict": "FAIL",
                         "expected_dominant": expected,
                         "note": "recorded training-audit stderr (direct copy)"})
        print(f"{name}: copied {rel}")

    for name, trial, shard, task in CLEAN_CASES:
        path = history(trial, shard, task)
        with open(path) as f:
            lines = f.read().splitlines()
        # final passing build = fence enclosing the LAST 'All tests passed'
        anchors = [i + 1 for i, l in enumerate(lines) if "All tests passed" in l]
        if not anchors:
            raise SystemExit(f"{name}: no 'All tests passed' in {path}")
        block = fence_block(path, anchors[-1])
        if "error:" in block:
            raise SystemExit(f"{name}: 'clean' block unexpectedly has errors")
        out = os.path.join(OUT, name + ".build-log.txt")
        with open(out, "w") as f:
            f.write(block)
        rel = os.path.relpath(path, REPO)
        manifest.append({"case": name, "source": f"{rel}:{anchors[-1]}",
                         "expected_verdict": "PASS",
                         "expected_dominant": None,
                         "note": "final build block of a recorded passed turn"})
        print(f"{name}: {rel}:{anchors[-1]} -> {len(block.splitlines())} lines")

    with open(os.path.join(OUT, "expected.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"\nwrote {len(manifest)} cases + expected.json to {OUT}")


if __name__ == "__main__":
    main()
