#!/usr/bin/env python3
"""Scratch v2: position-aware loop detectors; verdict only when the loop
reaches the end of the generation."""
import glob
import os
import pickle
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
EV = os.path.join(REPO, "evidence")

TAIL_WINDOW = 16000
IDENT_LINE_RUN = 8
MONOCHAR_LINE_RUN = 5
TILED_LINE_RUN = 3
TILED_LINE_MIN = 200       # a single very long tiled line is a loop by itself
TAIL_SLACK = 200           # loop must end within this many chars of the end


def _tiles(s, unit, frac=0.8):
    if not unit or len(s) < 12:
        return False
    i = 0
    n = 0
    while s.startswith(unit, i):
        i += len(unit)
        n += 1
    return n >= 3 and i / len(s) >= frac


def _line_unit(s):
    for p in range(1, 11):
        if _tiles(s, s[:p]):
            return s[:p]
    return None


def find_loop(text):
    """Return (kind, unit, run, end_pos) of the loop run reaching furthest
    toward the end of the tail window, or None."""
    base = max(0, len(text) - TAIL_WINDOW)
    tail = text[base:]
    lines = tail.splitlines(keepends=True)
    offs = []
    pos = base
    for l in lines:
        offs.append(pos)
        pos += len(l)
    nb = [(k, l.rstrip("\n")) for k, l in enumerate(lines) if l.strip()]
    best = None  # (end_pos, kind, unit, run)

    def consider(end_line_idx, kind, unit, run):
        end_pos = offs[end_line_idx] + len(lines[end_line_idx])
        if best is None or end_pos > best[0]:
            return (end_pos, kind, unit, run)
        return best

    # identical-line run
    run = 1
    for (ka, a), (kb, b) in zip(nb, nb[1:]):
        run = run + 1 if a == b else 1
        if run >= IDENT_LINE_RUN:
            best = consider(kb, "identical-line", b.strip()[:60], run) or best
    # mono-char line run
    run = 0
    prev = None
    for k, l in nb:
        s = l.strip()
        ch = s[0] if s and len(set(s)) == 1 and len(s) >= 2 else None
        run = run + 1 if (ch is not None and ch == prev) else (1 if ch else 0)
        prev = ch
        if run >= MONOCHAR_LINE_RUN:
            best = consider(k, "mono-char-lines", repr(ch), run) or best
    # tiled-line run / single huge tiled line
    run = 0
    prev_u = None
    for k, l in nb:
        s = l.strip()
        u = _line_unit(s)
        if u is not None and len(s) >= TILED_LINE_MIN and _tiles(s, u, 0.9):
            best = consider(k, "tiled-line", repr(u[:20]), 1) or best
        run = run + 1 if (u is not None and u == prev_u) else (1 if u else 0)
        prev_u = u
        if run >= TILED_LINE_RUN:
            best = consider(k, "tiled-lines", repr(u[:20]), run) or best
    if best is None:
        return None
    end_pos, kind, unit, run = best
    return (kind, unit, run, end_pos)


d = pickle.load(open(os.path.join(EV, "global_iter14_eval", "empty_full.pkl"), "rb"))
verdict_loop = warn_loop = 0
clean_flagged = []
for i, e in enumerate(d):
    r = find_loop(e["think"])
    if not r:
        continue
    kind, unit, run, end = r
    at_end = len(e["think"]) - end <= TAIL_SLACK
    if at_end:
        verdict_loop += 1
        if not e["tok_limit"] and e["ends_fence"]:
            clean_flagged.append((i, e["task"], e["trial"], kind, unit))
    else:
        warn_loop += 1
print(f"verdict-LOOP (loop at end): {verdict_loop}, mid-trace loop (warning): {warn_loop}")
print("clean-end events wrongly verdict-LOOP:", clean_flagged)
cap = [e for e in d if e["tok_limit"]]
cap_loop = sum(1 for e in cap
               if (lambda r: r and len(e["think"]) - r[3] <= TAIL_SLACK)(find_loop(e["think"])))
print(f"cap-hit events verdict-LOOP: {cap_loop}/{len(cap)}")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract_fixtures import good_replies_from_history  # noqa: E402

n_ok = n_fp = 0
for hist in glob.glob(os.path.join(
        EV, "global_iter14_eval", "trial-0*", "receipts", "shard-*", "*",
        "cpp", "exercises", "practice", "*", ".aider.chat.history.md")):
    for reply in good_replies_from_history(hist, limit=99):
        n_ok += 1
        r = find_loop(reply)
        if r and len(reply) - r[3] <= TAIL_SLACK:
            n_fp += 1
            print("  FP:", hist.split("practice/")[1], r)
print(f"known-good replies: {n_ok}, FP: {n_fp}")

# check the TRUNCATED fixtures: no end loop expected
for name in ("trunc-zebra-puzzle-mid-line-cap", "trunc-allergies-cjk-drift-cap",
             "trunc-trainrow-mid-line-8192", "trunc-trainrow-unclosed-fence-8192"):
    t = open(f"fixtures/{name}.txt").read()
    r = find_loop(t)
    at_end = r and len(t) - r[3] <= TAIL_SLACK
    print(name, "loop:", r, "at_end:", bool(at_end),
          "fences:", t.count("```"), "tail:", repr(t[-40:]))
