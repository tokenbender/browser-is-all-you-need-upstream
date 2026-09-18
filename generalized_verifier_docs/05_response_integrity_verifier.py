#!/usr/bin/env python3
"""
Verifier 05: Response Integrity Verifier (generalized, pure-text).

Classifies a raw model generation before any correctness question:

  * EMPTY     -- no file listing and no complete code block in the
                 deliverable (solution may sit in the reasoning channel).
  * LOOP      -- degenerate repetition running to the end of the stream.
  * TRUNCATED -- generation cut by the output-token cap (unclosed code
                 fence, or cap hit without a clean fence ending).
  * OK        -- complete payload ending at a clean boundary.

Inputs: the generation text (optionally pre-split into reasoning/answer
channels) plus harness-reported --gen-tokens/--max-tokens when known.
All thresholds are task-independent. Precedence is LOOP > TRUNCATED >
EMPTY > OK: stream-level degeneration outranks channel-level commit
failure.

    python3 05_response_integrity_verifier.py --response raw_output.txt \
        [--answer answer_channel.txt] [--gen-tokens N --max-tokens M] [--json]

Exit code 0 = OK, 1 = degeneration verdict (EMPTY/LOOP/TRUNCATED),
2 = usage/IO error.
"""

import argparse
import enum
import json
import re
import sys

# ---------------------------------------------------------------------------
# Tunables are task-independent and exercised by the hermetic control matrix.
# ---------------------------------------------------------------------------

TAIL_WINDOW = 16000      # loop scan covers the last N chars of the stream
TAIL_SLACK = 100         # loop run must end within N chars of the end
IDENT_LINE_RUN = 8       # identical non-blank lines in a row
MONOCHAR_LINE_RUN = 5    # consecutive single-character-run lines
TILED_LINE_RUN = 3       # consecutive intra-line-periodic lines, same unit
TILED_UNIT_MAX = 10      # max period of the tiling unit
TILED_LINE_MIN = 200     # one tiled line this long is a loop on its own
CJK_TAIL_CHARS = 2000    # window for the CJK-drift diagnostic
CJK_DRIFT_FRAC = 0.15    # tail CJK fraction reported as drift

_FENCE_RE = re.compile(r"^\s*```")
_PATH_RE = re.compile(r"^[A-Za-z0-9_./-]+\.[A-Za-z0-9]+$")
_LABEL_PREFIX_RE = re.compile(r"^(?:#{1,6}\s+|[-+*]\s+)")
_MARKDOWN_WRAPPERS = ("**", "__", "``", "`", "*", "_")
_CJK_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿＀-￯]")


class Verdict(enum.Enum):
    OK = "OK"
    EMPTY = "EMPTY"
    LOOP = "LOOP"
    TRUNCATED = "TRUNCATED"


class Report:
    def __init__(self, verdict, feedback, details=None, warnings=None):
        self.verdict = verdict
        self.feedback = feedback
        self.details = details or {}
        self.warnings = warnings or []

    def as_dict(self):
        return {"verdict": self.verdict.value, "feedback": self.feedback,
                "details": self.details, "warnings": self.warnings}


# ---------------------------------------------------------------------------
# Loop detection
# ---------------------------------------------------------------------------

class LoopHit:
    def __init__(self, kind, unit, run, end_pos):
        self.kind = kind        # identical-line | mono-char-lines | tiled-*
        self.unit = unit        # the repeated unit (display-truncated)
        self.run = run          # consecutive repeats observed
        self.end_pos = end_pos  # char offset where the run ends

    def as_dict(self):
        return {"kind": self.kind, "unit": self.unit, "run": self.run,
                "end_pos": self.end_pos}


def _tiles(s, unit, frac=0.8):
    """True if >= frac of s is covered by consecutive copies of unit."""
    if not unit or len(s) < 12:
        return False
    i, n = 0, 0
    while s.startswith(unit, i):
        i += len(unit)
        n += 1
    return n >= 3 and i / len(s) >= frac


def _line_unit(s):
    """Shortest period (<= TILED_UNIT_MAX) that tiles s, else None."""
    for p in range(1, TILED_UNIT_MAX + 1):
        if _tiles(s, s[:p]):
            return s[:p]
    return None


def find_loop(text):
    """Find the degenerate repetition run reaching furthest toward the end
    of the text's tail window. Returns a LoopHit or None.

    Three exact-match detectors: consecutive identical non-blank lines
    (blank lines skipped, recorded phrase loops interleave them);
    consecutive lines that are each a run of one repeated character;
    consecutive lines tiled by the same short unit, or one very long
    tiled line.
    """
    base = max(0, len(text) - TAIL_WINDOW)
    tail = text[base:]
    lines = tail.splitlines(keepends=True)
    offs = []
    pos = base
    for line in lines:
        offs.append(pos)
        pos += len(line)
    nb = [(k, line.rstrip("\n")) for k, line in enumerate(lines)
          if line.strip()]
    best = None  # LoopHit with the largest end_pos

    def consider(line_idx, kind, unit, run):
        nonlocal best
        end_pos = offs[line_idx] + len(lines[line_idx])
        if best is None or end_pos > best.end_pos:
            best = LoopHit(kind, unit, run, end_pos)

    # 1. identical-line run
    run = 1
    for (ka, a), (kb, b) in zip(nb, nb[1:]):
        run = run + 1 if a == b else 1
        if run >= IDENT_LINE_RUN:
            consider(kb, "identical-line", b.strip()[:60], run)
    # 2. mono-char line run
    run, prev = 0, None
    for k, line in nb:
        s = line.strip()
        ch = s[0] if s and len(s) >= 2 and len(set(s)) == 1 else None
        run = run + 1 if (ch is not None and ch == prev) else (1 if ch else 0)
        prev = ch
        if run >= MONOCHAR_LINE_RUN:
            consider(k, "mono-char-lines", repr(ch), run)
    # 3. tiled lines (same unit, consecutive) / single huge tiled line
    run, prev_u = 0, None
    for k, line in nb:
        s = line.strip()
        u = _line_unit(s)
        if u is not None and len(s) >= TILED_LINE_MIN and _tiles(s, u, 0.9):
            consider(k, "tiled-line", repr(u[:20]), 1)
        run = run + 1 if (u is not None and u == prev_u) else (1 if u else 0)
        prev_u = u
        if run >= TILED_LINE_RUN:
            consider(k, "tiled-lines", repr(u[:20]), run)
    return best


def cjk_fraction(text):
    """CJK/fullwidth share of non-space chars in the tail window."""
    tail = text[-CJK_TAIL_CHARS:]
    chars = [c for c in tail if not c.isspace()]
    if not chars:
        return 0.0
    return sum(1 for c in chars if _CJK_RE.match(c)) / len(chars)


# ---------------------------------------------------------------------------
# Payload / truncation analysis of the deliverable
# ---------------------------------------------------------------------------

def parse_deliverable(text):
    """Fence-aware scan. Returns dict with fence-line count, number of
    complete fenced blocks with content, whether a fence is left open at the
    end, and the number of whole-file listings (path line immediately before
    an opening fence).

    Unclosed-fence rule: the fence toggle state at end-of-text is open AND
    the last non-blank line is not itself a bare closing fence. The second
    clause matters because models quote prompt material containing fences,
    so raw fence parity alone can drift odd on otherwise clean generations.
    """
    fences = 0
    complete = 0
    listings = 0
    in_fence = False
    has_content = False
    prev_line = ""
    last_nonblank = ""
    for line in text.splitlines():
        if _FENCE_RE.match(line):
            fences += 1
            if in_fence:
                in_fence = False
                if has_content:
                    complete += 1
                has_content = False
            else:
                in_fence = True
                if _is_file_listing_label(prev_line):
                    listings += 1
        elif in_fence and line.strip():
            has_content = True
        if line.strip():
            last_nonblank = line.strip()
            prev_line = line
    ends_on_bare_fence = bool(re.match(r"^```\s*$", last_nonblank))
    return {"fence_lines": fences, "complete_blocks": complete,
            "unclosed_fence": in_fence and not ends_on_bare_fence,
            "listings": listings}


def _is_file_listing_label(line):
    label = _LABEL_PREFIX_RE.sub("", line.strip(), count=1).strip()
    if label.endswith(":"):
        label = label[:-1].rstrip()
    for wrapper in _MARKDOWN_WRAPPERS:
        if (label.startswith(wrapper) and label.endswith(wrapper)
                and len(label) > 2 * len(wrapper)):
            label = label[len(wrapper):-len(wrapper)].strip()
            if label.endswith(":"):
                label = label[:-1].rstrip()
            break
    return _PATH_RE.fullmatch(label) is not None


def ends_clean(text):
    """The stream ends at a clean boundary: last non-blank line is a fence."""
    for line in reversed(text.splitlines()):
        if line.strip():
            return bool(_FENCE_RE.match(line))
    return False


# ---------------------------------------------------------------------------
# Verdict logic
# ---------------------------------------------------------------------------

def analyze_response(response, answer=None, gen_tokens=None, max_tokens=None):
    """Classify one raw model generation.

    response   -- full raw generation text (used for loop/truncation analysis)
    answer     -- the deliverable channel only, if the harness splits
                  channels; defaults to `response` itself
    gen_tokens / max_tokens -- harness-reported counts; equality means the
                  output cap was hit (harness knowledge, arrives as input)
    """
    deliverable = response if answer is None else answer
    warnings = []

    loop = find_loop(response)
    loop_at_end = loop is not None and len(response) - loop.end_pos <= TAIL_SLACK
    cjk = cjk_fraction(response)
    cjk_note = (f"; CJK/fullwidth drift in the tail: {cjk:.0%}"
                if cjk >= CJK_DRIFT_FRAC else "")

    cap_hit = (gen_tokens is not None and max_tokens is not None
               and gen_tokens >= max_tokens)
    info = parse_deliverable(deliverable)
    details = {
        "response_chars": len(response),
        "deliverable_chars": len(deliverable),
        "cap_hit": cap_hit,
        "cjk_tail_fraction": round(cjk, 4),
        **info,
    }

    # ---- 1. LOOP: degeneration runs to the end of the generation --------
    if loop_at_end:
        details["loop"] = loop.as_dict()
        return Report(
            Verdict.LOOP,
            f"LOOP: degenerate repetition -- {loop.kind} unit "
            f"{loop.unit!r} repeats {loop.run}x and the run reaches the end "
            f"of the generation{cjk_note}. This is non-convergence, not a "
            f"wrong answer: apply anti-loop filtering / overlong masking "
            f"rather than a plain negative reward, and do not retry "
            f"identically.",
            details, warnings)
    if loop is not None:
        warnings.append(
            f"mid-generation {loop.kind} loop ({loop.unit!r} x{loop.run}) "
            f"recovered {len(response) - loop.end_pos} chars before the end")

    # ---- 2. TRUNCATED: destroyed by the output-token cap ----------------
    if info["unclosed_fence"]:
        return Report(
            Verdict.TRUNCATED,
            f"TRUNCATED: the deliverable's last code fence is never closed "
            f"({info['fence_lines']} fence lines) -- generation was cut "
            f"mid-block"
            + (f" at the token cap ({gen_tokens} >= {max_tokens})"
               if cap_hit else "")
            + f"{cjk_note}. Consider a reasoning budget or overlong "
            f"shaping; a plain negative reward cannot distinguish this from "
            f"a wrong answer.",
            details, warnings)
    if cap_hit and not ends_clean(response):
        return Report(
            Verdict.TRUNCATED,
            f"TRUNCATED: generation stopped at the output cap "
            f"({gen_tokens} >= {max_tokens}) without reaching a closing "
            f"fence -- cut mid-output{cjk_note}. The stream never had the "
            f"chance to commit an answer; treat as overlong, not as a "
            f"semantic failure.",
            details, warnings)
    if cap_hit:
        warnings.append(
            f"token cap reached ({gen_tokens} >= {max_tokens}) but the "
            f"stream ends at a fence boundary")

    # ---- 3. EMPTY: no parseable payload in the deliverable --------------
    if not deliverable.strip():
        reasoning = ("" if answer is None else
                     parse_deliverable(response))
        drafted = (answer is not None and reasoning["complete_blocks"] > 0)
        fb = (f"EMPTY: the answer channel is empty -- {len(response)} chars "
              f"of reasoning produced no file edits")
        if drafted:
            fb += (f". The reasoning channel contains "
                   f"{reasoning['complete_blocks']} complete fenced block(s) "
                   f"that were never emitted (solution drafted in the wrong "
                   f"channel): retry with a commit-nudge ('emit the complete "
                   f"edited files now'), not an identical retry.")
        else:
            fb += ". Retry with a commit-nudge, not an identical retry."
        return Report(Verdict.EMPTY, fb, details, warnings)
    if info["complete_blocks"] == 0 and info["listings"] == 0:
        return Report(
            Verdict.EMPTY,
            f"EMPTY: the response contains {len(deliverable.strip())} "
            f"non-space chars of prose but no parseable file listing (a "
            f"path line followed by a fenced code block) -- unparseable "
            f"payload. Ask for the complete edited files as fenced "
            f"whole-file listings.",
            details, warnings)

    # ---- 4. OK -----------------------------------------------------------
    return Report(
        Verdict.OK,
        f"OK: {info['listings']} file listing(s), {info['complete_blocks']} "
        f"complete fenced block(s); the stream ends at a clean boundary.",
        details, warnings)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Response integrity verifier: classify a raw model "
                    "generation as OK / EMPTY / LOOP / TRUNCATED.")
    ap.add_argument("--response", required=True,
                    help="file with the full raw generation text")
    ap.add_argument("--answer", default=None,
                    help="file with the answer/deliverable channel only, if "
                         "the harness splits channels (default: the whole "
                         "--response text is the deliverable)")
    ap.add_argument("--gen-tokens", type=int, default=None,
                    help="tokens actually generated (harness-reported)")
    ap.add_argument("--max-tokens", type=int, default=None,
                    help="output token cap in effect for this generation")
    ap.add_argument("--json", action="store_true",
                    help="emit machine-readable report")
    ap.add_argument("--receipt", default=None, metavar="DIR",
                    help="also write a sandbox-compatible kernel receipt "
                         "(<verifier>_kernel_receipt.json) into DIR")
    args = ap.parse_args(argv)
    if args.receipt:
        import receipt_compat
        return receipt_compat.run_with_receipt(args.receipt, run, args, argv)
    return run(args)


def run(args):
    if (args.gen_tokens is None) != (args.max_tokens is None):
        print("error: --gen-tokens and --max-tokens must be given together",
              file=sys.stderr)
        return 2
    try:
        with open(args.response) as f:
            response = f.read()
        answer = None
        if args.answer is not None:
            with open(args.answer) as f:
                answer = f.read()
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    report = analyze_response(response, answer,
                              args.gen_tokens, args.max_tokens)
    if args.json:
        print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
    else:
        print("--- Response Integrity Verifier ---")
        print(f"VERDICT: {report.verdict.value}")
        print(f"Feedback: {report.feedback}")
        for w in report.warnings:
            print(f"  warning: {w}")
    return 0 if report.verdict is Verdict.OK else 1


if __name__ == "__main__":
    sys.exit(main())
