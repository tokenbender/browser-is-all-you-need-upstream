# Generalization Proof — Verifier 06: Candidate Boundary + Reconstruction

Every claim below comes from an actual run on this machine
(Linux, `g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0`, python3; the verifier
itself is stdlib-only — torch 2.10.0, already installed, is used once to
*extract* recorded responses from the rollout dumps, with
`weights_only=True`, mirroring `evidence/global_direct_grpo30_audit/extract_audit.py`).

Reproduce everything:

```bash
bash generalized_verifier_docs/validation/06/run_validation_06.sh
```

(full transcript: `validation/06/transcript.txt`; outputs below were copied
from it verbatim).

## 1. Category definition (shape, not instance)

**Candidate file boundary + reconstruction.** The response-to-files contract
in aider whole-file format: each fenced listing is preceded by a filename
label; only files in the task's `editable_files` set may be listed; each at
most once; any editable file not listed keeps its template content. Four
task-independent failure shapes:

| Shape | Definition (no task terms) |
|---|---|
| FORBIDDEN_FILE | A listing whose label is file-like but outside the editable set: markdown-glued (`**x.h**`, `*X.h*`), quoted (`"x.h"`), wrong-case, illustrative example paths (`path/to/filename.js`), or space-free prose containing `/` or `.` |
| DUPLICATE_FILE | The same editable file listed twice — the model self-corrects mid-response and re-emits; contents may be identical or conflicting |
| OMITTED_FILLED | An editable file absent from the response silently keeps its template (stub) content; legal per the prompt but must be REPORTED, because a stub kept next to a newly-declared API is a deferred link error |
| TRUNCATED_LISTING | The final fence is never closed (generation cap hit mid-file); the partial file is unrecoverable. Must be separated from other format errors (no fences at all / unusable labels) because the corrective feedback differs |

## 2. Old gate and root cause

The production boundary gate is
`src/glm47_posttraining/aider_polyglot/parser.py`:
`parse_whole_file_response()` **raises** on the first forbidden filename
(`:79-82`, reason `forbidden_file`) or repeated editable file (`:87-90`,
reason `duplicate_file`), and raises `invalid_format` (`:97-98`) when no
complete editable listing survives. Its fence regex (`FENCE_RE`, `:11-13`)
only matches *closed* fences, so a truncated trailing listing vanishes
without a trace; labels it cannot map to the editable set are skipped with
only a `format_valid=False` flag (`:83-85`).

**Root cause (mechanism-level).** The 8,192-token generation cap interacts
with the model's prose-first style: responses that burn thousands of tokens
reasoning before emitting code are cut mid-listing, leaving an unclosed
fence that closed-fence-only parsing silently drops; the editable file that
listing was meant to replace keeps its stub content, so the failure
reappears one stage later as a link error against the hidden test — with
the reward attributing it to the wrong layer. Independently, the model's
markdown habits (bold/italic/quoted filename labels, self-correction
re-listings, illustrative format examples) collide with a label grammar
that accepts only the bare filename, and fail-fast raising throws away all
per-file detail the RL loop could learn from: a single opaque reason string
per row, no reconstructed file set, no distinction between "hit the token
cap" and "never emitted a listing".

## 3. Cross-task evidence (recorded, with paths + lines)

Reason × family counts over all 7,680 training rows of run
`multi-env-global-direct-phone14-grpo30-spot-20260825-202821`
(`evidence/global_direct_grpo30_audit/rows_train.jsonl`, `reason` field;
distribution recomputed for this document):

| reason | families (counts) | total |
|---|---|---|
| forbidden_file | meetup 36, zebra-puzzle 29, kindergarten-garden 22, linked-list 5 | **92** |
| duplicate_file | meetup 28, linked-list 3, zebra-puzzle 3, kindergarten-garden 3 | **37** |
| invalid_format | kindergarten-garden 543, zebra-puzzle 531, meetup 82, linked-list 5, binary-search-tree 3 | **1,164** |

The shapes appear in ≥4 task families each — not a one-task quirk.

Concrete recorded rows (raw responses extracted to
`validation/06/cases/` by `extract_cases.py`; coordinates verified against
`rows_train.jsonl`):

| Case file | Recorded row | Recorded reason/status | What the response actually did |
|---|---|---|---|
| `meetup__u1_s477.response.txt` | rows_train.jsonl:478 | forbidden_file, completed | labels `*Meetup.h*` / `*Meetup.cpp*` (italic + wrong case) |
| `linked-list__u1_s433.response.txt` | rows_train.jsonl:434 | forbidden_file, completed | labels `**linked_list.h**` / `**linked_list.cpp**` (bold markdown) |
| `kindergarten-garden__u2_s666.response.txt` | rows_train.jsonl:667 | forbidden_file, truncated@8192 | illustrative `"path/to/filename.js"` fence + quoted `"kindergarten_garden.h"` + `...` placeholder listings + unclosed final fence |
| `zebra-puzzle__u3_s798.response.txt` | rows_train.jsonl:799 | forbidden_file, truncated@8192 | Chinese prose label containing `/` parses as a multi-part path |
| `meetup__u0_s130.response.txt` | rows_train.jsonl:131 | duplicate_file, completed | meetup.h listed 2× (identical), meetup.cpp 2× (conflicting) |
| `linked-list__u2_s530.response.txt` | rows_train.jsonl:531 | duplicate_file, completed | both files listed twice |
| `kindergarten-garden__u18_s4788.response.txt` | rows_train.jsonl:4789 | duplicate_file, completed | both files listed twice |
| `zebra-puzzle__u8_s2294.response.txt` | rows_train.jsonl:2295 | duplicate_file, truncated@8192 | both files listed twice (.cpp conflicting), then a third header fence labeled `Header:` |
| `meetup__u0_s240.response.txt` | rows_train.jsonl:241 | invalid_format, truncated@8192 | 3 closed fences, labels `I'll add:` / `Header:` / `Implementation:` — none usable |
| `kindergarten-garden__u2_s609.response.txt` | rows_train.jsonl:610 | invalid_format, truncated@8192 | zero fences in the entire response; cut mid-sentence |

The truncated-header-only case (OMITTED_FILLED shape):
`evidence/global_direct_grpo30_audit/zebra_case/resp_u0_s74.txt` — update 0,
sample 74, truncated at 8,192 tokens; 19 fence markers, the last labeled
`zebra_puzzle.cpp` and never closed. Only the header listing survived; the
stub `.cpp` (`Reward_GRPO/multi_env_fixtures/zebra-puzzle/zebra_puzzle.cpp`,
an empty namespace) stayed. Recorded downstream result:
`zebra_case/g03_batch.json:9` —
`G03rc=1:zebra_puzzle_test.cpp:(.text+0x2a): undefined reference to 'zebra_puzzle::solve()'`
(7 of 14 sampled G03-fail rows are exactly this pattern;
`flow_zebra-puzzle.md:61-63`).

Clean known-good cases (must not false-positive): turn-1 assistant responses
from two recorded PASS eval runs
(`tests_outcomes: [true]` in each `.aider.results.json`):

- `evidence/global_iter14_eval/trial-01/receipts/shard-1/2026-08-26-02-29-42--global-direct-iter14-fixed26-20260826-020704-trial-01-shard-1/cpp/exercises/practice/space-age/.aider.chat.history.md` (assistant reply = lines after the last `####`-prefixed prompt line through the `> Tokens:` line at :196)
- same receipt dir, `practice/phone-number/.aider.chat.history.md` (`> Tokens:` at :160)

Extracted by `extract_clean_cases.py`, which also asserts the production
parser accepts each extraction as format-valid over both editable files.

**Missing evidence source (honest note):** the assigned
`evidence/phone_iter14_gcs_audit/extracted/train_records.jsonl` does not
exist in this checkout (`evidence/` contains only `global_direct_grpo30_audit/`
and `global_iter14_eval/`). The phone-run evidence used instead is the
grpo30 audit above, whose receipts name the run
`...-phone14-grpo30-spot-20260825-202821`; the 140 format-invalid phone rows
could not be consulted.

## 4. Validation runs (real output)

### 4a. Recorded failures are caught — ≥3 tasks per shape

forbidden_file (meetup; same shape caught in all four families):

```
--- Candidate Boundary Verifier ---
Editable set: meetup.h, meetup.cpp
  FATAL        FORBIDDEN_FILE [*Meetup.h*]: response targets non-editable file '*Meetup.h*': this name is outside the editable set ['meetup.cpp', 'meetup.h'], so the whole response is rejected. Did you mean 'meetup.h'? Emit the bare filename 'meetup.h' on the line directly above the fence -- no markdown emphasis, quotes, or case changes.
  ...
  FATAL        NO_FILES: no fence yielded a complete editable file; every listing was either unlabeled, mislabeled, or cut off before its closing fence.
VERDICT: FAIL
exit=1
```

linked-list u1 s433: `FATAL FORBIDDEN_FILE [**linked_list.h**] ... Did you
mean 'linked_list.h'?` — FAIL. kindergarten-garden u2 s666:
`FATAL FORBIDDEN_FILE ["path/to/filename.js"] ... Remove this listing (it
looks like an illustrative or out-of-scope file)` plus
`WARNING PLACEHOLDER_CONTENT [kindergarten_garden.h]: listing ... contains
only the ellipsis placeholder '...'` plus `WARNING TRUNCATED_LISTING
[kindergarten_garden.cpp]: listing ... was cut off: the fence is never
closed` — FAIL. zebra-puzzle u3 s798: FORBIDDEN_FILE on the Chinese prose
label — FAIL.

duplicate_file (identical vs conflicting distinguished):

```
  FATAL        DUPLICATE_FILE [meetup.h]: file 'meetup.h' is listed more than once (identical content both times). ...
  FATAL        DUPLICATE_FILE [meetup.cpp]: file 'meetup.cpp' is listed more than once (CONFLICTING content (first differs at line 4; 76 vs 76 lines)). ...
VERDICT: FAIL
```

Caught identically in linked-list u2 s530, kindergarten-garden u18 s4788,
zebra-puzzle u8 s2294 — FAIL each.

invalid_format, split by mechanism (the truncated-vs-format separation):

```
# meetup u0 s240 -- fences exist but no usable labels:
  WARNING      SKIPPED_LISTING: fence has no usable filename label (found 'Header:'); ...
  FATAL        NO_FILES: no fence yielded a complete editable file; ...
VERDICT: FAIL

# kindergarten-garden u2 s609 -- no fences at all:
  FATAL        NO_FILES: response contains no fenced file listings at all; emit each editable file as: its filename on one line, then a ``` fence with the COMPLETE new content.
VERDICT: FAIL
```

### 4b. Omission reconstruction + end-to-end link-error reproduction

```
### truncated header-only / zebra u0 s74 (OMITTED_FILLED + reconstruction)
  file zebra_puzzle.cpp: TEMPLATE-FILLED (unchanged original), 79 bytes
  file zebra_puzzle.h: LISTED, 251 bytes
  WARNING      TRUNCATED_LISTING [zebra_puzzle.cpp]: listing for 'zebra_puzzle.cpp' was cut off: the fence is never closed (generation limit hit mid-file). The partial content is unrecoverable and was NOT applied; ...
  MODIFICATION OMITTED_FILLED [zebra_puzzle.cpp]: editable file 'zebra_puzzle.cpp' was not listed in the response; its ORIGINAL content was kept unchanged in the reconstructed set. This is legal, but if you declared new API in a sibling file, this file still provides no definition -- expect 'undefined reference' at link time.
VERDICT: OK_WITH_MODIFICATIONS (reconstructed set modified: template-filled omissions)
exit=0
```

The reconstructed set written to `--out-dir` was then built with verifier 03
against the task fixture:

```
### end-to-end: build the reconstructed set with verifier 03
STATUS: LE
Feedback: LINKER ERROR: the test references symbols that have no definition ('undefined reference'). ...
/usr/bin/ld: zebra_puzzle_test.cpp:(.text+0x2a): undefined reference to `zebra_puzzle::solve()'
```

— byte-identical signature to the recorded `g03_batch.json:9` line. The
verifier's OMITTED_FILLED feedback predicted the link error before the build.

### 4c. Zero false positives on recorded clean responses

```
### clean / space-age trial-01 turn-1 (recorded PASS)
  file space_age.cpp: LISTED, 933 bytes
  file space_age.h: LISTED, 1001 bytes
  no issues; reconstructed set == listed set
VERDICT: OK
exit=0
### clean / phone-number trial-01 turn-1 (recorded PASS)
  file phone_number.cpp: LISTED, 1034 bytes
  file phone_number.h: LISTED, 374 bytes
  no issues; reconstructed set == listed set
VERDICT: OK
exit=0
```

### 4d. Agreement sweep vs the production gate

`check_agreement.py` runs both parsers over every case. Final lines:

```
OK  zebra u0/s74 truncated-header-only: prod=accepted(files=['zebra_puzzle.h']) 06=OK_WITH_MODIFICATIONS issues=['OMITTED_FILLED', 'TRUNCATED_LISTING']
OK  clean space-age      06=OK issues=0 modified=False
OK  clean phone-number   06=OK issues=0 modified=False
AGREEMENT: ALL PASS
```

All 10 recorded failure rows: production reason reproduced AND 06 = FAIL
with the matching fatal issue kind (full table in `transcript.txt`). On the
one recorded response production *accepted* (the truncated header-only row),
06 reports — instead of hiding — the two facts that explain the downstream
link error. Deliberate difference: 06 is stricter than the old gate by
*reporting*, never by rejecting something the old gate accepted.

## 5. Litmus

```
$ grep -inE "bankaccount|crypto|chillout|cipher|binary_tree|kindergarten|zebra|linked_list|Plants|diamond|clock|spiral|allergies|sublist|meetup|gigasecond|robot" \
    generalized_verifier_docs/06_candidate_boundary_verifier.py
litmus exit=1 (1 = zero hits)
```

No exceptions needed: CLI help/args use only generic names
(`--editable solution.h`, `--template NAME=PATH`).

## 6. Honest limitations

- **Label grammar mirrors the production parser by design** (preceding-line
  label, `RECOVERABLE_LABEL_RE` normalization, file-like heuristic). A
  response that a *different* listing dialect produces (e.g. diff format)
  will be reported as NO_FILES/SKIPPED_LISTING, not parsed — 06 is a
  boundary verifier for the whole-file format only.
- **Fence pairing is positional** (marker 2k opens, 2k+1 closes). A ` ``` `
  line inside file *content* would desync the pairing; C++ sources
  effectively never contain one at column 0, and the recorded corpus shows
  no instance, but the heuristic is documented, not sound.
- **DUPLICATE_FILE keeps the LAST listing** in the reconstructed set
  (sequential-apply semantics). Whether the model's later listing is the
  intended one is not decidable task-agnostically; the verdict is FAIL
  either way, and the feedback states the convention.
- **TRUNCATED_LISTING detects only an unclosed trailing fence.** A response
  cut off *between* two listings (even fence count) is invisible as
  truncation; it surfaces only as OMITTED_* for the never-started files.
- **The `...` PLACEHOLDER_CONTENT check** is a one-pattern heuristic lifted
  from observed rows; other abbreviation styles are not detected.
- **The missing phone-audit evidence** (`evidence/phone_iter14_gcs_audit/…`,
  140 format-invalid rows) could not be used — the directory is absent from
  this checkout. Cross-task proof rests on the grpo30 audit (5 families) and
  the iter14 eval receipts instead.
- Verifier 06 judges the *boundary*, not the code: a response can be
  boundary-clean and still fail to compile or pass tests — that is what
  verifiers 03/04 are for (chaining demonstrated in §4b).
