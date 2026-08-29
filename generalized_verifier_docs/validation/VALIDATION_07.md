# Generalization Proof — Verifier 07: Warning-Hygiene Classifier

Every claim below comes from an actual run on this machine (Linux, system
`g++ 13.3.0`, python3 stdlib only). Reproduce:

```bash
python3 generalized_verifier_docs/validation/07/extract_cases.py   # regenerates cases/
bash    generalized_verifier_docs/validation/07/run_validation.sh  # 16/16 must print OK
```

The verifier runs standalone: `python3 generalized_verifier_docs/07_warning_hygiene_classifier.py --help`.

## 1. Category definition

**Compiler warning/hygiene classification.** Under the strict build
(`-Wall -Wextra -Wpedantic -Werror`, the flags recorded in every eval
receipt and used by `03_two_stage_build_verifier.py`), diagnostics that are
*warnings by nature* become hard errors. The old feedback collapsed all of
them into a generic "Compile Error". This verifier parses raw g++ stderr
into structured findings `{class, file, line, symbol, fix_hint}` with one
of 13 classes — `unused-parameter`, `unused-variable`, `unused-function`,
`missing-include`, `sign-compare`, `return-local-addr`, `shadow`,
`constexpr-not-literal`, `private-access`, `tautological-compare`,
`undeclared-identifier`, `missing-member`, `other` — each mapped to a
one-line actionable fix, plus a `dominant_class` rollup.

## 2. Evidence first (quoted, with paths), before any code was written

All eval-side quotes are verbatim lines from recorded aider chat histories
(the build/lint output block the agent actually saw). `evidence/` was never
modified; extraction copies live in `validation/07/cases/`.

| Class | Recorded failure (verbatim) | Source (path:line) |
|---|---|---|
| unused-parameter | `/aider/crypto-square/crypto_square.cpp:8:35: error: unused parameter ‘text’ [-Werror=unused-parameter]` | `evidence/global_iter14_eval/trial-01/receipts/shard-0/2026-08-26-02-29-51--.../crypto-square/.aider.chat.history.md:279` |
| missing-include (uint32_t→cstdint) | `/aider/spiral-matrix/spiral_matrix.h:8:25: error: ‘uint32_t’ was not declared in this scope` | `.../trial-01/receipts/shard-1/2026-08-26-02-29-42--.../spiral-matrix/.aider.chat.history.md:185` (also trial-02:182) |
| missing-include (unordered_map) | `/aider/allergies/allergies.cpp:11:17: error: ‘unordered_map’ in namespace ‘std’ does not name a template type` | `.../trial-01/receipts/shard-0/.../allergies/.aider.chat.history.md:420` |
| missing-include (string) | `/aider/diamond/diamond.h:7:18: error: ‘string’ is not a member of ‘std’` | `.../trial-01/receipts/shard-0/.../diamond/.aider.chat.history.md:169` |
| return-local-addr | `/aider/robot-name/robot_name.cpp:34:12: error: reference to local variable ‘name’ returned [-Werror=return-local-addr]` | `.../trial-02/receipts/shard-1/2026-08-26-03-40-39--.../robot-name/.aider.chat.history.md:187` |
| undeclared-identifier | `/aider/clock/clock.cpp:15:5: error: ‘normalize’ was not declared in this scope` | `.../trial-01/receipts/shard-0/.../clock/.aider.chat.history.md:507` |
| private-access | `/aider/complex-numbers/complex_numbers.cpp:52:25: error: ‘double complex_numbers::Complex::real_’ is private within this context` | `.../trial-03/receipts/shard-0/2026-08-26-02-39-18--.../complex-numbers/.aider.chat.history.md:305` |
| constexpr-not-literal | `/aider/zebra-puzzle/zebra_puzzle.cpp:13:38: error: the type ‘const std::array<std::__cxx11::basic_string<char>, 5>’ of ‘constexpr’ variable ‘zebra_puzzle::{anonymous}::COLORS’ is not literal` | `.../trial-01/receipts/shard-1/.../zebra-puzzle/.aider.chat.history.md:421` |
| unused-variable | `/aider/parallel-letter-frequency/parallel_letter_frequency.cpp:16:17: error: unused variable ‘total_letters’ [-Werror=unused-variable]` | `.../trial-01/receipts/shard-1/.../parallel-letter-frequency/.aider.chat.history.md:275` |
| unused-function | `/aider/zebra-puzzle/zebra_puzzle.cpp:23:6: error: ‘bool zebra_puzzle::{anonymous}::isValidAssignment(const Assignment&)’ defined but not used [-Werror=unused-function]` | `.../trial-02/receipts/shard-1/.../zebra-puzzle/.aider.chat.history.md:322` |
| tautological-compare | `/aider/circular-buffer/circular_buffer.h:59:19: error: self-comparison always evaluates to true [-Werror=tautological-compare]` | `.../trial-01/receipts/shard-0/.../circular-buffer/.aider.chat.history.md:967` |
| missing-member (training side) | `binary_search_tree_test.cpp:12:63: error: ‘binary_tree’ is not a member of ‘binary_search_tree’` | `evidence/global_direct_grpo30_audit/bst_case/row0.stderr.txt:1` (gcc13: references `/usr/include/c++/13/...`) |

(The full receipt directory names are abbreviated with `--...`; the exact
paths are in `validation/07/cases/expected.json`, emitted by the
extractor.)

## 3. Error shape, task-independently

The shape is a property of the *toolchain*, not of any task:

```
<file>:<line>:<col>: error: <message> [-Werror=<flag>]
```

Classification keys on (a) the `-Werror=<flag>` suffix when present — the
compiler has already named the hygiene rule — and (b) fixed message
templates g++ emits regardless of task (`'X' was not declared in this
scope`, `'X' is not a member of 'NS'`, `'T' is private within this
context`, `the type 'T' of 'constexpr' variable 'X' is not literal`). The
only lookup table maps *standard-library symbol names* to the standard
header that declares them (`uint32_t`→`cstdint`, `unordered_map`→
`unordered_map`, `find`→`algorithm`, ...) — language knowledge, never task
knowledge. Unknown symbols degrade to `undeclared-identifier` /
`missing-member` / `other`; the classifier never invents a header.

## 4. Cross-task check (≥3 tasks — passed easily)

From the evidence survey above, per class:

- `missing-include`: **3 tasks** (spiral-matrix trials 01+02, allergies, diamond)
- `unused-*` family: **4 tasks** (crypto-square, parallel-letter-frequency, diamond trial-02, zebra-puzzle)
- `private-access`: **2 tasks, 3 trials** (complex-numbers trials 01/03/04, bank-account trial-01)
- `constexpr-not-literal` / `unused-function` / GNU-designated-initializer `pedantic`: zebra-puzzle across **3 trials**
- `return-local-addr`: robot-name trial-02; `tautological-compare`: circular-buffer trial-01; `undeclared-identifier`: clock, spiral-matrix, binary-search-tree test cascade
- `missing-member`: 20 recorded training-side submissions in `evidence/global_direct_grpo30_audit/bst_case/row{0..19}.stderr.txt`

Training side: `evidence/global_direct_grpo30_audit/rows_train.jsonl`
contains **2,710 rows with `policy_status.G02 == "fail"`** (strict-build
kernel; families: meetup 1027, zebra-puzzle 603, kindergarten-garden 553,
binary-search-tree 317, linked-list 210). Those rows carry no stderr (no
`logs` field in the schema), so the training-side stderr samples were taken
from the same audit's `bst_case/` directory, which holds the recorded
stderr verbatim. (The mission brief said 2,210 rows and a possible `logs`
field; the actual file has 2,710 G02-fail rows and no logs field —
reported as found.)

## 5. Root cause (mechanism)

The reward/feedback path treated "g++ exited non-zero" as a terminal
opaque event. But g++'s stderr is already a structured stream: each
diagnostic carries severity, source location, a message from a fixed
per-rule template, and — for every warning promoted by `-Werror` — the
rule's own flag name. The information needed to distinguish "you left a
parameter unused" from "you forgot `<cstdint>`" from "you returned a
reference to a stack local" was computed by the compiler and then thrown
away at the feedback boundary. The classifier is a pure text
transformation that recovers it; no rebuild, no task fixture, no AST.

## 6. Validation runs (real, on this machine)

`extract_cases.py` lifts each failing case's verbatim fenced build-output
block from the recorded history (anchor = first `error:` line) and copies
the training-side stderr files; `run_validation.sh` runs the classifier on
each and checks verdict + dominant class. Real output:

```
$ bash generalized_verifier_docs/validation/07/run_validation.sh
OK   eval_unused-parameter                      verdict=FAIL dominant=unused-parameter errors=1 exit=1
OK   eval_missing-include-cstdint               verdict=FAIL dominant=missing-include errors=24 exit=1
OK   eval_missing-include-unordered_map         verdict=FAIL dominant=missing-include errors=4 exit=1
OK   eval_missing-include-string                verdict=FAIL dominant=missing-include errors=14 exit=1
OK   eval_return-local-addr                     verdict=FAIL dominant=return-local-addr errors=1 exit=1
OK   eval_undeclared-identifier                 verdict=FAIL dominant=undeclared-identifier errors=3 exit=1
OK   eval_private-access                        verdict=FAIL dominant=private-access errors=24 exit=1
OK   eval_constexpr-not-literal                 verdict=FAIL dominant=constexpr-not-literal errors=12 exit=1
OK   eval_unused-variable                       verdict=FAIL dominant=unused-variable errors=1 exit=1
OK   eval_unused-function                       verdict=FAIL dominant=unused-function errors=1 exit=1
OK   eval_tautological-compare                  verdict=FAIL dominant=tautological-compare errors=6 exit=1
OK   train_row0                                 verdict=FAIL dominant=undeclared-identifier errors=98 exit=1
OK   train_row1                                 verdict=FAIL dominant=undeclared-identifier errors=98 exit=1
OK   train_row2                                 verdict=FAIL dominant=undeclared-identifier errors=116 exit=1
OK   clean_robot-name_trial-03                  verdict=PASS dominant=None errors=0 exit=0
OK   clean_spiral-matrix_trial-02               verdict=PASS dominant=None errors=0 exit=0

16/16 cases match expectations
```

Coverage: 11 recorded failures across **9 distinct tasks** (all correctly
classified), 3 training-side stderr files, 2 known-good cases (final build
blocks of recorded *passed* eval turns — robot-name trial-03 line 383,
spiral-matrix trial-02 line 438) with **zero false positives**.

Sample real text output (return-local-addr case):

```
--- Warning-Hygiene Classifier ---
  ERROR   [return-local-addr] /aider/robot-name/robot_name.cpp:34: reference to local variable ‘name’ returned [-Werror=return-local-addr]
          fix: do not return a reference/pointer to local 'name'; return by value or give the storage static/member lifetime
dominant class: return-local-addr (1 errors, 0 warnings)
VERDICT: FAIL
```

Real inferred-header hints (from the JSON reports):

```
add #include <cstdint> -- 'uint32_t' is declared there            (spiral-matrix case)
add #include <unordered_map> -- 'unordered_map' is declared there (allergies case)
add #include <string> -- 'string' is declared there               (diamond case)
```

Edge behavior verified live: warnings-only input (no `-Werror`) classifies
but stays `PASS` (exit 0); empty input is `PASS`; stdin and `--stderr`
modes both return exit 1 on error findings.

## 7. Litmus

```
$ grep -icE "bankaccount|crypto|chillout|cipher|binary_tree|kindergarten|zebra|linked_list|Plants|diamond|clock|spiral|allergies|sublist|meetup|gigasecond|robot" \
    generalized_verifier_docs/07_warning_hygiene_classifier.py
0
```

Zero hits — including CLI help text and arg names (no exceptions needed).
Task names appear only in `validation/07/` (extractor manifest, case
filenames, this document) — input data, not verifier logic.

## 8. Honest limitations

- **Cascade vs root cause.** `dominant_class` is a mechanical majority over
  error findings, excluding the residual `other` bucket unless everything
  is `other`. In the training-side rows the true root cause
  (`missing-member`, the *first* finding — g++ prints the root cause before
  its cascade) is outnumbered 23:1 by follow-on `undeclared-identifier`
  errors in the test file, so the rollup says `undeclared-identifier`. The
  root cause is still present as `findings[0]`; consumers that want it
  should take the first error finding, not the dominant class.
- **Compiler-version drift.** The recorded eval histories were produced in
  a container reporting `GNU 11.4.0` (e.g. the crypto-square block), the
  training-audit stderr references `/usr/include/c++/13`, and this machine
  runs 13.3.0. The parser is version-agnostic regex over g++'s stable
  diagnostic format, but message wording is not an API — a future g++ could
  rephrase a template and demote that class to `other` (fail-safe: still
  reported, still FAIL, just with the generic hint).
- **`STD_SYMBOL_HEADERS` is a finite table.** An undeclared standard symbol
  missing from the table degrades to `undeclared-identifier` (correct
  class, less specific hint) — never to a fabricated header.
- **`sign-compare` and `shadow` have no recorded instance in this evidence
  set.** They are implemented from the same `-Werror=flag` mechanism as the
  six evidenced flag classes but are not validated against a real recorded
  failure here.
- **Notes are dropped.** g++ `note:` lines (e.g. "‘std::data’ declared
  here") are treated as annotation of the primary diagnostic, not findings.
- **Heuristic text parser, not clang** — same structural choice as verifier
  01; `parse_stderr()` / `classify_message()` are isolated so a libclang
  backend could replace them without touching verdict logic.
- **The `evidence/gcc_version_check/` directory named in the mission brief
  does not exist** in this checkout. Its 10 documented cases were
  re-derived directly from the underlying recorded chat histories (same
  tasks, same error shapes, quoted in §2) plus the training audit, and the
  extraction script regenerates them deterministically.
