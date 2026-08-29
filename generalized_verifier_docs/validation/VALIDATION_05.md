# Generalization Proof — Verifier 05: Response Integrity Verifier

Every claim below comes from an actual run on this machine
(Linux, `g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0`, python3 stdlib only —
no pip packages, no network). Reproduce the fixture-level transcript:

```bash
bash generalized_verifier_docs/validation/05/run_validation_05.sh
```

(`transcript_05.txt` is regenerated; all pasted outputs below were copied
from it verbatim. Corpus-scale numbers: `python3
generalized_verifier_docs/validation/05/corpus_check.py`, output saved in
`validation/05/corpus_check.out`.)

The verifier runs standalone: `python3
generalized_verifier_docs/05_response_integrity_verifier.py --help`.

## 1. Category definition

**Response integrity / degeneration**: the generation fails in the channel
itself, before any question of semantic correctness. Four shapes, all
recorded in the evidence:

- **EMPTY** — the answer channel carries no file listing and no code block,
  either because generation ended (EOS) with the complete solution still
  inside the reasoning channel, or because the reply is prose with no
  parseable listing.
- **LOOP** — an exact phrase/line unit repeats and the run reaches the end
  of the generation (canonical recorded units: a CJK sentence interleaved
  with blank lines; runs of one fullwidth punctuation character).
- **TRUNCATED** — the output-token cap destroyed the stream: unclosed code
  fence, or a cut mid-line exactly at the cap.
- **OK** — a complete payload ending at a clean boundary.

The *shape* is task-independent: it is defined over lines, fence delimiters
and repeated substrings of the raw output text, plus two harness-supplied
numbers (generated tokens, token cap). No task name, file name, or
task-specific content appears anywhere in the verifier (§6 litmus).

## 2. Evidence first — recorded failures, quoted

### 2a. Eval side: 126 empty-ANSWER events (`evidence/global_iter14_eval/`)

`EMPTY_ANSWER_ANALYSIS.md` §1a: 126 empty-ANSWER asks (28.0% of 450),
touching **90 of 104 task-trials and all 26 tasks**; 43 burned the
32,768-token cap, 83 self-terminated with the solution sitting inside
THINKING. Full thinking text per event is in `empty_full.pkl` (real
recorded generations, used as fixtures below).

Loop tail, `empty_full.pkl[25]` (trial-01, knapsack, cap-hit, 80,610 chars,
CJK 38%) — quoted from the fixture:

```
'wait，我将输出文件。\n\nwait，我将输出文件。\n\nwait，我将输出文件。\n\n ... wait，我将\n\n'
```

Fullwidth-paren run, `empty_full.pkl[16]` (trial-01, bank-account, cap-hit,
43,484 chars):

```
'）））））））））））））））））\n））））））））…）\n … ））））））））））））））））\n\n'
```

Clean-end "solution in the wrong channel", `empty_full.pkl[80]` (trial-03,
crypto-square, **no cap**, 72,580 chars):

```
"size());\n        result += normalized_.substr(start, end - start));\n ...\n\n}  // namespace crypto_square\n```\n\n"
```

Cap cut mid-statement with no loop, `empty_full.pkl[61]` (trial-02,
zebra-puzzle, 85,501 chars):

```
' Norwegian lives next to the blue house.\n    for (int house = 0; house < HOUSE_COUNT - 1; ++house)\n\n'
```

Chat-history corroboration that the crypto-square trial-03 turn-1 answer
channel was empty (the model's 28k-token reply produced zero edits; the
build then failed against the untouched starting files):
`evidence/global_iter14_eval/trial-03/receipts/shard-0/2026-08-26-02-39-18--...-trial-03-shard-0/cpp/exercises/practice/crypto-square/.aider.chat.history.md:120`
(`> Tokens: 1.5k sent, 28k received.` with no reply body), followed by the
`'cipher' is not a member of 'crypto_square'` compile cascade at lines
134-227.

### 2b. Training side: `evidence/global_direct_grpo30_audit/rows_train.jsonl`

Measured on the file itself (`corpus_check.py`-style tally): 7,680 rows,
**1,517 `status=truncated` (19.8%), every one with `response_length` exactly
8,192** (the train cap). Per family: kindergarten-garden 570/1,536 = **37%**,
zebra-puzzle 781/1,472 = 53%, meetup 159/1,600 = 10%. The audit's own
`loop_analysis.json` records the degenerate-loop share of truncated rows
rising 12% (updates 0-5) → ~40% (updates 24-29) while completed rows stay at
1-2% loops / 0% CJK.

### 2c. Phone run: `/tmp/phone_iter14_gcs_audit/extracted/train_records.jsonl`

5,120 rows with full raw `response` text: **63 `sample_status=truncated`**
(all `response_length == 8192`), 173 `format_valid=false`. Two real tails
(both used as fixtures):

- cut mid-line, fences balanced: `'... Is this "good enough"?\n    Usually, yes'`
- cut inside a code block (odd fence count 17): `'gits_.substr(0, 3); }\n\nstd::string phone'`

## 3. Cross-task check

The shapes are not task-specific:

| Shape | # tasks in evidence | Examples (real texts in `validation/05/fixtures/`) |
|---|---|---|
| Empty answer, solution in reasoning | all 26 tasks have empty-ANSWER events (`EMPTY_ANSWER_ANALYSIS.md` §1c) | crypto-square (idx 80), allergies (idx 4) fixtures |
| End-of-generation loop | loops recorded in 25/26 tasks (84/126 events carry a detected loop unit) | knapsack CJK-phrase, bank-account + meetup fullwidth-paren fixtures |
| Truncation at cap | eval: 43 cap-hits across 15+ tasks; train: 19.8% of rows in 4/4 families (37-53% in two of them) | zebra-puzzle + allergies eval fixtures, two phone train-row fixtures |

Distribution of the 84 loop-bearing events across tasks (from
`empty_full.pkl`): binary-search-tree 6, bank-account 6, meetup 6,
zebra-puzzle 6, crypto-square 5, circular-buffer 5, … down to single events
in knapsack, yacht, queen-attack. Loop units recur cross-task: the
fullwidth-paren run appears in 9+ tasks' traces.

## 4. Root cause (mechanism level)

The policy never learned to *close* a long reasoning trace. Training
truncates at 8,192 generated tokens and gives every truncated row the same
negative reward (score_mean −0.87 → −0.83), so trajectories that think past
the cap are uniformly destroyed and the "wrap up and emit the answer"
behavior is only reinforced for short traces; GRPO then amplified the
degenerate-loop subpopulation (hard loops 12% → ~40% of truncated rows)
because the flat negative mass contains no gradient distinguishing "long but
working" from "stuck in a loop". At eval the same checkpoint gets 4× the
rope (32,768) with no stop strings, no repetition penalty and no thinking
budget, so non-convergence either meanders into an exact-phrase loop until
the cap (LOOP/TRUNCATED), or — after re-planning churn drafts the full
solution inside the reasoning channel — terminates at EOS without ever
crossing the thinking→answer boundary (EMPTY). The failure is in the
generation channel, not in task competence: 77/83 uncapped empty events
contain a complete, well-formed solution draft.

## 5. Validation runs

### 5a. Fixture-level (12 real recorded texts, all pass)

Fixtures extracted by `validation/05/extract_fixtures.py` (provenance in each
`*.meta.json`). Full output: `validation/05/transcript_05.txt`.

| Fixture (real text) | Source | Expected | Got |
|---|---|---|---|
| loop-knapsack-cjk-phrase | `empty_full.pkl[25]` trial-01 knapsack, cap-hit | LOOP | **LOOP** — `identical-line unit 'wait，我将输出文件。' repeats 1142x … CJK/fullwidth drift in the tail: 58%` |
| loop-bank-account-fullwidth-paren | `empty_full.pkl[16]` trial-01 bank-account, cap-hit | LOOP | **LOOP** — `mono-char-lines unit "'）'" repeats 391x … drift 100%` |
| loop-meetup-fullwidth-paren | `empty_full.pkl[62]` trial-02 meetup, cap-hit | LOOP | **LOOP** — `mono-char-lines unit "'）'" repeats 191x … drift 100%` |
| empty-crypto-square-solution-in-thinking | `empty_full.pkl[80]` trial-03 crypto-square, no cap | EMPTY | **EMPTY** — `the answer channel is empty -- 72580 chars of reasoning produced no file edits. The reasoning channel contains 15 complete fenced block(s) that were never emitted …` (+ warning: mid-generation `'），' x227` loop recovered 6,732 chars before the end) |
| empty-allergies-solution-in-thinking | `empty_full.pkl[4]` trial-01 allergies, no cap | EMPTY | **EMPTY** — same shape, 5 unshipped fenced blocks |
| trunc-zebra-puzzle-mid-line-cap | `empty_full.pkl[61]` trial-02 zebra-puzzle, cap-hit | TRUNCATED | **TRUNCATED** — `stopped at the output cap (32768 >= 32768) without reaching a closing fence` |
| trunc-allergies-cjk-drift-cap | `empty_full.pkl[41]` trial-02 allergies, cap-hit | TRUNCATED | **TRUNCATED** — `cut mid-output; CJK/fullwidth drift in the tail: 65%` |
| trunc-trainrow-mid-line-8192 | phone `train_records.jsonl` (length-partition-repair, iter 0) | TRUNCATED | **TRUNCATED** — `stopped at the output cap (8192 >= 8192) …` |
| trunc-trainrow-unclosed-fence-8192 | phone `train_records.jsonl` (country-code-repair, iter 13) | TRUNCATED | **TRUNCATED** — `the deliverable's last code fence is never closed (17 fence lines)` |
| good-crypto-square-reply | trial-01 crypto-square chat history, reply aider applied | OK | **OK** — `2 file listing(s), 2 complete fenced block(s); ends at a clean boundary` |
| good-bank-account-reply | trial-01 bank-account chat history | OK | **OK** |
| good-clock-reply | trial-01 clock chat history | OK | **OK** |

That is recorded failures caught from **7 distinct tasks** (knapsack,
bank-account, meetup, crypto-square, allergies, zebra-puzzle, phone-number)
and known-good passes from **3 distinct tasks** — above the required ≥3/≥2.

### 5b. Corpus-scale (whole evidence sets, `corpus_check.out`)

```
1. eval empty-ANSWER events (n=126):
   cap       -> LOOP      29
   cap       -> TRUNCATED 14
   uncapped  -> EMPTY     83
   verdict OK (must be 0): 0 []
2. phone train rows (n=5120, truncated=63):
   truncated-row verdicts: {'TRUNCATED': 61, 'LOOP': 2}  (OK among them: 0)
   format-valid completed-row verdicts: {'OK': 4946}
3. aider-confirmed good replies: 324, non-OK (must be 0): 0
```

Reading: every recorded empty-ANSWER event is classified as degeneration
(none as OK); the verdict split matches the recorded mechanism (uncapped
self-terminations → EMPTY; cap-hits → LOOP when a loop runs to the end, else
TRUNCATED). All 63 truncated train rows are caught; all 4,946 format-valid
completed rows and all 324 aider-confirmed eval replies are OK — zero false
positives.

## 6. Litmus

```
$ grep -iE "bankaccount|crypto|chillout|cipher|binary_tree|kindergarten|zebra|linked_list|Plants|diamond|clock|spiral|allergies|sublist|meetup|gigasecond|robot" \
    generalized_verifier_docs/05_response_integrity_verifier.py
LITMUS: ZERO task-name hits (grep exit 1)
```

No exceptions needed: CLI arg names and help text contain no task names
either. (Task names do appear under `validation/05/` — that is input data
and provenance, not verifier logic.)

## 7. Honest limitations

- **Channel split must be supplied.** The verifier cannot tell "solution
  drafted in the reasoning channel" from "solution in the answer" unless the
  harness passes `--answer` (eval-side GLM channel markers are stripped by
  `skip_special_tokens` before logs are written, so the split is harness
  knowledge). Without `--answer`, a thinking-only trace with complete fences
  looks like a payload — that is input misuse, documented in `--help`.
- **Token-cap fact is a parameter.** The "cut mid-line *at the cap*" verdict
  requires `--gen-tokens`/`--max-tokens`; without them only the unclosed-
  fence signature fires. A model that stops mid-prose short of the cap by
  its own EOS is indistinguishable from a finished short prose reply —
  flagged only if the deliverable is also empty/unparseable (then EMPTY).
- **Fence quoting noise.** Models quote prompt material containing fences;
  raw fence parity drifts odd in ~0.7% of clean completed generations. The
  implemented rule (toggle open at end AND stream does not end on a bare
  closing fence) eliminated all 36 such false TRUNCATEDs in the phone
  corpus, but an adversarial tail (e.g. an unclosed block whose last line is
  a bare ``` opener) can still slip either way.
- **Loop detectors are exact-match.** Character-level drift loops with no
  line structure shorter than the 6-repeat tail-period case, or fuzzy
  near-repeats, are not detected. Mid-generation loops that recover are
  reported as warnings, never verdicts — by design, since 42/77 uncapped
  recorded events looped and then drafted a complete solution.
- **Thresholds are calibrated, not derived** (TAIL_SLACK=100: recorded
  end-loops terminate 1-50 chars from the end, recovered loops are followed
  by ≥176 chars; run-length minimums 8/5/3: zero false positives on 324
  known-good replies + 4,946 completed train rows). A different model family
  may need them re-checked, not re-thought.
- **Truncated-row verdicts on the 14 non-loop cap-hits** say TRUNCATED even
  when the thinking contained a full solution draft — arguably also an EMPTY
  commit failure. Precedence LOOP > TRUNCATED > EMPTY is a deliberate choice
  (stream-level destruction outranks channel-level commit failure), stated
  in the module docstring.
