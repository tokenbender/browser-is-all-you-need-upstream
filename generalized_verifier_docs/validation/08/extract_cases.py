#!/usr/bin/env python3
"""Extract REAL recorded crashing candidates into validation/08/cases/.

Fault controls are lifted verbatim from recorded evidence (chat-history
whole-file listings before the recorded crash line, or the already-extracted
training-audit candidate directory). The exploit control is synthetic (a
known-good reference plus one sanitizer-suppression attribute) and is labeled
as such. The functional-fail control is the recorded wrong-logic
crypto-square candidate already extracted by validation/extract_candidates.py
(copied, not modified).

The evidence/ tree is never modified; all outputs land in cases/.
"""

import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
EVAL = os.path.join(REPO, "evidence", "global_iter14_eval")
AUDIT = os.path.join(REPO, "evidence", "global_direct_grpo30_audit")
FIXTURES = os.path.join(REPO, "Reward_GRPO", "multi_env_fixtures")
OUT = os.path.join(HERE, "cases")

SPIRAL_HISTORY = os.path.join(
    EVAL, "trial-01", "receipts", "shard-1",
    "2026-08-26-02-29-42--global-direct-iter14-fixed26-20260826-020704-"
    "trial-01-shard-1", "cpp", "exercises", "practice", "spiral-matrix",
    ".aider.chat.history.md")
PLF_HISTORY = os.path.join(
    EVAL, "trial-03", "receipts", "shard-1",
    "2026-08-26-02-39-18--global-direct-iter14-fixed26-20260826-020704-"
    "trial-03-shard-1", "cpp", "exercises", "practice",
    "parallel-letter-frequency", ".aider.chat.history.md")
ZEBRA_CAND = os.path.join(AUDIT, "zebra_case", "cand_u22_s5825")
CRYPTO_CAND = os.path.join(REPO, "generalized_verifier_docs", "validation",
                           "candidates", "crypto-square")


def listing_after_label(path, lineno):
    """Return the content of the ``` fence immediately following the bare
    filename label at 1-based line ``lineno`` (aider whole-file format)."""
    with open(path) as f:
        lines = f.read().splitlines()
    assert lines[lineno - 1].strip() == lines[lineno - 1] and \
        lines[lineno - 1].endswith((".h", ".cpp")), \
        f"{path}:{lineno} is not a filename label: {lines[lineno - 1]!r}"
    i = lineno  # 0-based index just past the label
    assert lines[i].strip() == "```", f"{path}:{lineno + 1} fence expected"
    body = []
    for j in range(i + 1, len(lines)):
        if lines[j].strip() == "```":
            return "\n".join(body) + "\n"
        body.append(lines[j])
    raise SystemExit(f"unterminated fence after {path}:{lineno}")


def write_case(name, files):
    case_dir = os.path.join(OUT, name)
    os.makedirs(case_dir, exist_ok=True)
    for filename, content in files.items():
        with open(os.path.join(case_dir, filename), "w") as handle:
            handle.write(content)


def copy_case(name, src_dir, filenames):
    case_dir = os.path.join(OUT, name)
    os.makedirs(case_dir, exist_ok=True)
    for filename in filenames:
        shutil.copy2(os.path.join(src_dir, filename),
                     os.path.join(case_dir, filename))


def main():
    os.makedirs(OUT, exist_ok=True)
    manifest = []

    # ---- Fault controls (recorded crashes) --------------------------------
    write_case("fault_spiral_trial-01", {
        "spiral_matrix.h": listing_after_label(SPIRAL_HISTORY, 468),
        "spiral_matrix.cpp": listing_after_label(SPIRAL_HISTORY, 79),
    })
    manifest.append({
        "case": "fault_spiral_trial-01",
        "fixture": os.path.join(FIXTURES, "spiral-matrix"),
        "header": "spiral_matrix.h", "source": "spiral_matrix.cpp",
        "expected_verdict_in": ["SANITIZER_HIT", "CRASH_NO_REPORT"],
        "expected_exit": 1,
        "provenance": ("eval trial-01 shard-1 spiral-matrix chat history: "
                       "spiral_matrix.cpp listing @ line 79, spiral_matrix.h "
                       "listing @ line 468 (last complete listings before "
                       "the recorded SIGSEGV at line 535)"),
    })

    write_case("fault_plf_trial-03", {
        "parallel_letter_frequency.h": listing_after_label(PLF_HISTORY, 1268),
        "parallel_letter_frequency.cpp":
            listing_after_label(PLF_HISTORY, 1289),
    })
    manifest.append({
        "case": "fault_plf_trial-03",
        "fixture": os.path.join(FIXTURES, "parallel-letter-frequency"),
        "header": "parallel_letter_frequency.h",
        "source": "parallel_letter_frequency.cpp",
        "expected_verdict_in": ["SANITIZER_HIT", "CRASH_NO_REPORT"],
        "expected_exit": 1,
        "provenance": ("eval trial-03 shard-1 parallel-letter-frequency chat "
                       "history: .h listing @ line 1268, .cpp listing @ line "
                       "1289 (last complete listings before the recorded "
                       "SIGSEGV at lines 1402-1408)"),
    })

    copy_case("fault_zebra_u22_s5825", ZEBRA_CAND,
              ["zebra_puzzle.h", "zebra_puzzle.cpp"])
    manifest.append({
        "case": "fault_zebra_u22_s5825",
        "fixture": os.path.join(FIXTURES, "zebra-puzzle"),
        "header": "zebra_puzzle.h", "source": "zebra_puzzle.cpp",
        "expected_verdict_in": ["SANITIZER_HIT", "CRASH_NO_REPORT"],
        "expected_exit": 1,
        "provenance": ("training audit rollout row u22/s5825, recorded "
                       "SIGSEGV (flow_zebra-puzzle.md:87,131); candidate "
                       "already extracted in zebra_case/cand_u22_s5825, "
                       "copied verbatim"),
    })

    # ---- Positive controls (reference implementations) --------------------
    for task, stem in [("spiral-matrix", "spiral_matrix"),
                       ("parallel-letter-frequency",
                        "parallel_letter_frequency"),
                       ("zebra-puzzle", "zebra_puzzle"),
                       ("clock", "clock"),
                       ("allergies", "allergies")]:
        meta = os.path.join(FIXTURES, task, ".meta")
        entry = {
            "case": f"reference_{task}",
            "fixture": os.path.join(FIXTURES, task),
            "header": os.path.join(meta, "example.h"),
            "source": (os.path.join(meta, "example.cpp")
                       if os.path.exists(os.path.join(meta, "example.cpp"))
                       else None),
            "expected_verdict_in": ["CLEAN"],
            "expected_exit": 0,
            "provenance": f"{task}/.meta/example.* (pinned reference)",
        }
        manifest.append(entry)

    # ---- Exploit control (synthetic, labeled) ------------------------------
    with open(os.path.join(FIXTURES, "clock", ".meta", "example.h")) as f:
        exploit_h = f.read()
    with open(os.path.join(FIXTURES, "clock", ".meta", "example.cpp")) as f:
        exploit_cpp = f.read()
    # Add a sanitizer-suppression attribute to the otherwise-clean reference.
    exploit_cpp = exploit_cpp.replace(
        "namespace date_independent",
        "__attribute__((no_sanitize(\"address\")))\n"
        "static void exploit_probe() {}\n\n"
        "namespace date_independent", 1)
    if "no_sanitize" not in exploit_cpp:
        raise SystemExit("exploit splice failed: anchor not found")
    write_case("exploit_no_sanitize", {
        "clock.h": exploit_h, "clock.cpp": exploit_cpp})
    manifest.append({
        "case": "exploit_no_sanitize",
        "fixture": os.path.join(FIXTURES, "clock"),
        "header": "clock.h", "source": "clock.cpp",
        "expected_verdict_in": ["INVALID"],
        "expected_reason": "sanitizer_suppression_attempt",
        "expected_exit": 2,
        "provenance": ("SYNTHETIC (labeled): clock .meta/example.* plus one "
                       "__attribute__((no_sanitize(\"address\"))) function; "
                       "passes trivially if the control were absent"),
    })

    # ---- Functional-fail-without-UB control (recorded wrong logic) --------
    copy_case("functional_fail_crypto-square", CRYPTO_CAND,
              ["crypto_square.h", "crypto_square.cpp"])
    manifest.append({
        "case": "functional_fail_crypto-square",
        "fixture": os.path.join(FIXTURES, "crypto-square"),
        "header": "crypto_square.h", "source": "crypto_square.cpp",
        "expected_verdict_in": ["CLEAN"],
        "expected_functional_outcome": "FAILED",
        "expected_exit": 0,
        "provenance": ("recorded wrong-logic candidate from eval trial-02 "
                       "crypto-square (Catch2 FAILED '\"clu hlt io \" == "
                       "\"chillout \"'), previously extracted by "
                       "validation/extract_candidates.py; fails assertions "
                       "with no UB"),
    })

    with open(os.path.join(OUT, "expected.json"), "w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    for entry in manifest:
        print(f"extracted {entry['case']}: {entry['provenance']}")


if __name__ == "__main__":
    main()
