#!/usr/bin/env python3
"""
Extract the exact candidate file versions that produced a recorded failure
from an aider (whole-edit-format) chat history.

Mechanism (task-agnostic): the history contains repeated whole-file listings

    <filename>
    ```
    <content>
    ```

followed by an error block (compiler output or Catch2 failures). The failed
candidate is the LAST complete listing of each editable file strictly BEFORE
the recorded error line. If an editable file has no listing before the error
line, the failure was produced by the untouched starting files (e.g. the
model hit a token limit before its first edit) -- with ``--fallback-dir``
those starting files are copied instead and the fact is reported.

USAGE
-----
    python3 extract_candidates.py --history <path/.aider.chat.history.md> \
        --error-line <N> --files foo.h,foo.cpp --outdir <dir> \
        [--fallback-dir <fixture dir with starting files>]

Prints a JSON manifest of what was written and from which history line.
Exit 0 on success, 1 if a file could not be resolved.
"""

import argparse
import json
import os
import re
import sys


def find_listings(history_text):
    """Yield (line_number, filename, content) for every whole-file listing.

    A listing is a line containing only a file name (relative path ending in
    a source extension), immediately followed by a ``` fence.
    """
    lines = history_text.splitlines()
    listings = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if (re.fullmatch(r'[\w./-]+\.(?:h|hpp|cpp|cc|cxx)', line)
                and i + 1 < len(lines) and lines[i + 1].strip() == '```'):
            fname = line
            j = i + 2
            body = []
            while j < len(lines) and lines[j].strip() != '```':
                body.append(lines[j])
                j += 1
            if j < len(lines):  # closing fence found -> complete listing
                listings.append((i + 1, fname, '\n'.join(body) + '\n'))
                i = j
        i += 1
    return listings


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--history", required=True, help="aider chat history .md")
    ap.add_argument("--error-line", required=True, type=int,
                    help="1-based line number of the recorded error in the "
                         "history; the failed candidate is the last listing "
                         "before this line")
    ap.add_argument("--files", required=True,
                    help="comma-separated editable file names to extract")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--fallback-dir", default=None,
                    help="directory with starting files, used when a file has "
                         "no listing before --error-line")
    args = ap.parse_args(argv)

    with open(args.history) as f:
        history = f.read()
    listings = find_listings(history)

    os.makedirs(args.outdir, exist_ok=True)
    manifest = {}
    missing = []
    for fname in [x.strip() for x in args.files.split(',') if x.strip()]:
        base = os.path.basename(fname)
        before = [(ln, fn, content) for ln, fn, content in listings
                  if os.path.basename(fn) == base and ln < args.error_line]
        if before:
            ln, _, content = before[-1]
            origin = {"kind": "history_listing", "line": ln}
        elif args.fallback_dir and os.path.exists(
                os.path.join(args.fallback_dir, base)):
            with open(os.path.join(args.fallback_dir, base)) as f:
                content = f.read()
            origin = {"kind": "starting_file_fallback",
                      "note": "no submission before the error line; failure "
                              "was recorded against the untouched starting "
                              "file", "line": None}
        else:
            missing.append(base)
            continue
        out_path = os.path.join(args.outdir, base)
        with open(out_path, 'w') as f:
            f.write(content)
        manifest[base] = {"path": out_path, **origin}

    print(json.dumps({"history": args.history, "error_line": args.error_line,
                      "extracted": manifest, "missing": missing}, indent=2))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
