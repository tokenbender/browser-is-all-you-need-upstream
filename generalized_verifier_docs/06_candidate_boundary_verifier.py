#!/usr/bin/env python3
"""
Verifier 06: Candidate Boundary + Reconstruction Verifier (generalized).

Checks a raw whole-file response against the task's editable file set and
reconstructs the post-response file set. Issue classes:

  FORBIDDEN_FILE     -- listing label is file-like but not in the editable set
  DUPLICATE_FILE     -- the same editable file listed twice (last listing kept)
  OMITTED_FILLED     -- editable file absent from the response keeps its
                        template content (legal, but reported: a kept stub
                        can cause link-time 'undefined reference')
  TRUNCATED_LISTING  -- final fence never closed (generation cap mid-file);
                        partial content is not applied

All fences (closed and unclosed) are scanned and every issue is reported
with the reconstructed file set (listed files + template-filled omissions,
each tagged with its origin). Boundary semantics mirror the production
whole-file response parser so verdicts agree with recorded rewards.

Status ladder:
  OK                    -- no issues; reconstructed set == listed set
  OK_WITH_MODIFICATIONS -- only non-fatal issues; set complete
  FAIL                  -- at least one fatal issue (FORBIDDEN_FILE,
                           DUPLICATE_FILE, NO_FILES)

No task names are hardcoded; all task knowledge enters via --editable /
--template. stdlib only.

    python3 06_candidate_boundary_verifier.py --response resp.txt \
        --editable solution.h --editable solution.cpp \
        [--template solution.cpp=fixture/solution.cpp ...] \
        [--out-dir DIR] [--json]

Exit code 0 = OK or OK_WITH_MODIFICATIONS, 1 = FAIL, 2 = usage/IO error.
"""

import argparse
import json
import os
import re
import sys
from pathlib import PurePath

# ---------------------------------------------------------------------------
# Boundary constants -- deliberately identical to the production whole-file
# response parser's semantics (see validation/VALIDATION_06.md, section 2).
# ---------------------------------------------------------------------------

FENCE_LINE_RE = re.compile(r"^```(?P<language>[^\n]*)$", re.MULTILINE)
TERMINAL_STOP_RE = re.compile(
    r"(?:[ \t\r\n]*(?:<\|endoftext\|>|<\|user\|>|<\|observation\|>))+$"
)
RECOVERABLE_LABEL_RE = re.compile(
    r"^(?:#{1,6}\s+|[-*]\s+)?`{0,2}(?P<label>[^`]+?)`{0,2}:?$"
)
PROTECTED_NAMES = {"CMakeLists.txt"}
PROTECTED_SUFFIXES = ("_test.cpp", "_test.cc", "_test.h", ".cmake")
ALLOWED_LANGUAGES = {"", "cpp", "c++", "cc", "hpp", "h"}
THINKING_END = "</think>"

FATAL = {"FORBIDDEN_FILE", "DUPLICATE_FILE", "NO_FILES"}


# ---------------------------------------------------------------------------
# Response normalization (protocol noise, not task knowledge)
# ---------------------------------------------------------------------------

def normalize_response(response):
    """Strip decoding-protocol artifacts that are not part of the answer:
    everything up to the last </think> (the assistant continuation keeps the
    closing token, sometimes glued to the first filename) and terminal EOS
    markers (which may be glued to the final closing fence)."""
    if THINKING_END in response:
        response = response.rsplit(THINKING_END, 1)[1].lstrip()
    return TERMINAL_STOP_RE.sub("", response)


# ---------------------------------------------------------------------------
# Fence scanning: closed listings + unclosed (truncated) tail
# ---------------------------------------------------------------------------

class Listing:
    def __init__(self, label_line, language, content, closed):
        self.label_line = label_line
        self.language = language.strip().lower()
        self.content = content
        self.closed = closed


def _preceding_line(text, offset):
    prefix = text[:offset].rstrip("\r\n")
    if not prefix:
        return ""
    return prefix.splitlines()[-1].strip()


def scan_listings(response):
    """Pair fence markers sequentially: marker 2k opens, marker 2k+1 closes.
    An odd trailing marker is an unclosed (truncated) listing whose content
    is unrecoverable; it is returned with closed=False."""
    markers = list(FENCE_LINE_RE.finditer(response))
    listings = []
    i = 0
    while i < len(markers):
        op = markers[i]
        if i + 1 < len(markers):
            cl = markers[i + 1]
            content = response[op.end() + 1:cl.start()]
            listings.append(Listing(_preceding_line(response, op.start()),
                                    op.group("language"), content, True))
            i += 2
        else:
            listings.append(Listing(_preceding_line(response, op.start()),
                                    op.group("language"),
                                    response[op.end() + 1:], False))
            i += 1
    return listings


# ---------------------------------------------------------------------------
# Label classification (the editable-set boundary)
# ---------------------------------------------------------------------------

def _normalize_label(label_line):
    exact = label_line.strip()
    m = RECOVERABLE_LABEL_RE.fullmatch(exact)
    normalized = m.group("label").strip() if m else exact
    return normalized, normalized == exact


def _looks_like_file_target(label):
    if not label or " " in label:
        return False
    path = PurePath(label)
    if path.is_absolute() or ".." in path.parts or len(path.parts) > 1:
        return True
    return (label in PROTECTED_NAMES
            or label.endswith(PROTECTED_SUFFIXES) or "." in label)


def _suggest_editable(label, editable):
    """If the label is a decorated/case-shifted spelling of an editable file,
    return that name (for actionable feedback); else None."""
    stripped = label.strip("*_\"'`# ")
    for name in editable:
        if stripped == name or stripped.lower() == name.lower():
            return name
        if PurePath(stripped).name.lower() == name.lower():
            return name
    return None


# ---------------------------------------------------------------------------
# Verdict logic
# ---------------------------------------------------------------------------

def verify_response(response, editable_files, templates=None):
    """Boundary-check one raw model response.

    editable_files: iterable of editable basenames (the task contract).
    templates: {filename: original content} used to fill omitted files.
    Returns a report dict (see module docstring for the status ladder).
    """
    templates = templates or {}
    editable = list(editable_files)
    allowed = set(editable)
    issues = []
    files = {}        # target -> {"content", "origin", "listings"}

    def issue(kind, feedback, file=None, severity=None):
        issues.append({
            "kind": kind,
            "severity": severity or ("fatal" if kind in FATAL else "warning"),
            "file": file,
            "feedback": feedback,
        })

    listings = scan_listings(normalize_response(response))

    for lst in listings:
        label = lst.label_line
        normalized, exact = _normalize_label(label)

        if not lst.closed:
            intended = None
            if normalized in allowed:
                intended = normalized
            elif normalized and PurePath(normalized).name in allowed:
                intended = PurePath(normalized).name
            else:
                intended = _suggest_editable(normalized, editable)
            issue("TRUNCATED_LISTING",
                  f"listing for '{intended or label or '(unlabeled)'}' was "
                  f"cut off: the fence is never closed (generation limit hit "
                  f"mid-file). The partial content is unrecoverable and was "
                  f"NOT applied; emit the file listings earlier in the "
                  f"response or shorten the prose before them.",
                  file=intended)
            continue

        if normalized in allowed:
            target = normalized
        elif normalized and PurePath(normalized).name in allowed:
            target = PurePath(normalized).name
            exact = False
        elif _looks_like_file_target(normalized):
            hint = _suggest_editable(normalized, editable)
            feedback = (f"response targets non-editable file '{normalized}': "
                        f"this name is outside the editable set "
                        f"{sorted(allowed)}, so the whole response is "
                        f"rejected.")
            if hint:
                feedback += (f" Did you mean '{hint}'? Emit the bare "
                             f"filename '{hint}' on the line directly above "
                             f"the fence -- no markdown emphasis, quotes, "
                             f"or case changes.")
            else:
                feedback += (" Remove this listing (it looks like an "
                             "illustrative or out-of-scope file); only list "
                             "files you were told to modify.")
            issue("FORBIDDEN_FILE", feedback, file=normalized)
            continue
        else:
            issue("SKIPPED_LISTING",
                  f"fence has no usable filename label (found "
                  f"'{label[:60] or '(none)'}'); the listing was ignored. "
                  f"Put the bare editable filename on the line directly "
                  f"above each ``` fence.")
            continue

        if lst.language not in ALLOWED_LANGUAGES:
            issue("BAD_LANGUAGE_TAG",
                  f"fence language tag '{lst.language}' is not a C/C++ tag; "
                  f"use a bare fence or cpp/h.", file=target)
        if not exact:
            issue("LABEL_NOT_EXACT",
                  f"label '{label[:60]}' was normalized to '{target}'; write "
                  f"the bare filename exactly to avoid the format penalty.",
                  file=target)

        content = lst.content.rstrip() + "\n"
        if content.strip() == "...":
            issue("PLACEHOLDER_CONTENT",
                  f"listing for '{target}' contains only the ellipsis "
                  f"placeholder '...' -- the whole-file format requires the "
                  f"COMPLETE new file content, not an abbreviation.",
                  file=target)
        if target in files:
            previous = files[target]["content"]
            if previous == content:
                detail = "identical content both times"
            else:
                first_diff = next(
                    (k for k, (a, b) in enumerate(
                        zip(previous.splitlines(), content.splitlines()))
                     if a != b), None)
                detail = (f"CONFLICTING content (first differs at line "
                          f"{first_diff + 1 if first_diff is not None else '?'}"
                          f"; {len(previous.splitlines())} vs "
                          f"{len(content.splitlines())} lines)")
            issue("DUPLICATE_FILE",
                  f"file '{target}' is listed more than once ({detail}). "
                  f"List each editable file exactly once; if you corrected "
                  f"yourself, keep only the final version. The LAST listing "
                  f"is kept in the reconstructed set.",
                  file=target)
        files[target] = {"content": content, "origin": "listed"}

    # ---- Omission reconstruction ------------------------------------------
    for name in editable:
        if name in files:
            continue
        if name in templates:
            files[name] = {"content": templates[name], "origin": "template"}
            issue("OMITTED_FILLED",
                  f"editable file '{name}' was not listed in the response; "
                  f"its ORIGINAL content was kept unchanged in the "
                  f"reconstructed set. This is legal, but if you declared "
                  f"new API in a sibling file, this file still provides no "
                  f"definition -- expect 'undefined reference' at link time.",
                  file=name, severity="modification")
        else:
            issue("OMITTED_NO_TEMPLATE",
                  f"editable file '{name}' was not listed and no template "
                  f"content was supplied, so the reconstructed set is "
                  f"incomplete.", file=name, severity="modification")

    if not listings:
        issue("NO_FILES",
              "response contains no fenced file listings at all; emit each "
              "editable file as: its filename on one line, then a ``` fence "
              "with the COMPLETE new content.")
    elif not any(f["origin"] == "listed" for f in files.values()):
        issue("NO_FILES",
              "no fence yielded a complete editable file; every listing was "
              "either unlabeled, mislabeled, or cut off before its closing "
              "fence.")

    fatal = [i for i in issues if i["severity"] == "fatal"]
    status = ("FAIL" if fatal
              else "OK" if not issues
              else "OK_WITH_MODIFICATIONS")

    return {
        "status": status,
        "modified": any(f["origin"] == "template" for f in files.values()),
        "issues": issues,
        "files": {name: {"origin": f["origin"],
                         "bytes": len(f["content"].encode("utf-8"))}
                  for name, f in sorted(files.items())},
        "_contents": files,  # internal; stripped before printing
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_template(spec):
    if "=" not in spec:
        raise ValueError(f"--template expects NAME=PATH, got {spec!r}")
    name, path = spec.split("=", 1)
    with open(path) as f:
        return name, f.read()


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Candidate boundary + reconstruction verifier: check a "
                    "raw whole-file response against the task's editable "
                    "file set and reconstruct the resulting file set.")
    ap.add_argument("--response", required=True,
                    help="path to the raw model response text")
    ap.add_argument("--editable", action="append", required=True,
                    help="editable filename (repeatable); the task contract")
    ap.add_argument("--template", action="append", default=[], metavar="NAME=PATH",
                    help="original/template content for an editable file "
                         "(repeatable); used to fill omitted files")
    ap.add_argument("--out-dir", default=None,
                    help="write the reconstructed file set into DIR")
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
    try:
        with open(args.response) as f:
            response = f.read()
        templates = dict(_parse_template(spec) for spec in args.template)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    report = verify_response(response, args.editable, templates)

    if args.out_dir:
        os.makedirs(args.out_dir, exist_ok=True)
        for name, f in report["_contents"].items():
            with open(os.path.join(args.out_dir, name), "w") as fh:
                fh.write(f["content"])

    contents = report.pop("_contents")
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("--- Candidate Boundary Verifier ---")
        print(f"Editable set: {', '.join(args.editable)}")
        for name, meta in report["files"].items():
            tag = "LISTED" if meta["origin"] == "listed" \
                else "TEMPLATE-FILLED (unchanged original)"
            print(f"  file {name}: {tag}, {meta['bytes']} bytes")
        for i in report["issues"]:
            loc = f" [{i['file']}]" if i["file"] else ""
            print(f"  {i['severity'].upper():12s} {i['kind']}{loc}: "
                  f"{i['feedback']}")
        if not report["issues"]:
            print("  no issues; reconstructed set == listed set")
        print(f"VERDICT: {report['status']}"
              + (" (reconstructed set modified: template-filled omissions)"
                 if report["modified"] else ""))
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
