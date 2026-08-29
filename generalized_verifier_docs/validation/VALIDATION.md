# Generalization Proof — Generalized Verifiers 01 / 03 / 04

Every claim below comes from an actual run on this machine
(Linux, `g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0`, python3 stdlib only —
no pip packages, no clang dependency).

Reproduce everything (this regenerates `transcript.txt`, from which all
outputs below were copied verbatim):

```bash
bash generalized_verifier_docs/validation/run_validation.sh
```

The three verifiers are runnable standalone, e.g.
`python3 generalized_verifier_docs/01_structural_api_gate.py --help`.

## 0. Candidate provenance (extracted, not invented)

`extract_candidates.py` parses aider whole-file chat histories and takes the
last complete listing of each editable file **before** the recorded error
line. Manifests printed during extraction:

| Candidate | Source | Extraction result |
|---|---|---|
| `candidates/binary-search-tree/row{0..4}.{h,cpp}` | `/tmp/global_direct_grpo30_audit/bst_case/row{0..4}.*` (20 recorded submissions failing `'binary_tree' is not a member`; first 5 copied) | direct copy |
| `candidates/bank-account/` | trial-01 shard-0 `bank-account/.aider.chat.history.md`, error line 349 (`'Bankaccount::Bankaccount::Bankaccount()' is private within this context`) | `bank_account.h` from listing @ line 207, `bank_account.cpp` @ line 238 |
| `candidates/kindergarten-garden/` | trial-01 shard-0 KG history, error line 141 (`'Plants' is not a member`) | **no listing before the error line** — the model hit a token limit before its first edit, so the failure was recorded against the untouched starting files; extractor fell back to the fixture starting files (reported honestly by the script) |
| `candidates/zebra-puzzle/` | trial-03 shard-1 zebra history, error line 127 (`'solve' is not a member of 'zebra_puzzle'`) | same situation: token-limit, **starting-file fallback** |
| `candidates/crypto-square/` | trial-02 shard-0 crypto history, error line 411 (Catch2 `FAILED`, `"clu hlt io " == "chillout "`) | `crypto_square.h` @ line 327, `crypto_square.cpp` @ line 148 |
| `candidates/linked-list/` | trial-01 shard-1 linked-list history, error line 405 (`undefined reference to 'linked_list::List<int>::List()'`) | `linked_list.h` @ line 295, `linked_list.cpp` @ line 143 |
| `candidates/kindergarten-garden-semantic/` | trial-01 shard-0 KG history, error line 1402 (Catch2 `FAILED` after the model's first successful edit) | `.h` @ line 1300, `.cpp` @ line 1318 |

The bank-account **fixture** (official test file + `.meta/example.*`) is not in
`Reward_GRPO/multi_env_fixtures/`; it is taken from the recorded receipt dir
`/tmp/global_iter14_eval/trial-01/receipts/shard-0/2026-08-26-.../cpp/exercises/practice/bank-account/`
(referenced by path in `run_validation.sh`).

## 1. Verifier 01 — Structural API Gate

Mechanism: required symbols are derived **from the official test file**
(`ns::Ident` chains), then checked against the candidate's declarations
(namespace placement, class/enum/function kind, template shape, constructor
access section). No task names in code.

### 1a. Catches all recorded structural failures

| # | Recorded failure (real compiler error) | 01 verdict | 01 feedback (real output) |
|---|---|---|---|
| 1 | binary-search-tree row0: `'binary_tree' is not a member of 'binary_search_tree'` | FAIL | `required symbol 'binary_tree' not declared in namespace 'binary_search_tree'` |
| 2 | binary-search-tree row1 | FAIL | same |
| 3 | binary-search-tree row2 | FAIL | same |
| 4 | binary-search-tree row3 | FAIL | same |
| 5 | binary-search-tree row4 | FAIL | same |
| 6 | bank-account: `'Bankaccount::Bankaccount::Bankaccount()' is private within this context` | FAIL | `'Bankaccount' constructor is private -- the test constructs 'Bankaccount::Bankaccount' and needs a public constructor` |
| 7 | kindergarten-garden: `'Plants' is not a member of 'kindergarten_garden'` (+ `'plants' is not a member`) | FAIL | `required symbol 'Plants' not declared in namespace 'kindergarten_garden'` + `required symbol 'plants' not declared in namespace 'kindergarten_garden'` |
| 8 | zebra-puzzle: `'solve' is not a member of 'zebra_puzzle'` | FAIL | `required symbol 'solve' not declared in namespace 'zebra_puzzle'` (while `zebra_puzzle::Solution` correctly reports OK) |
| 9 | linked-list candidate | PASS (correct) | this candidate's failure was a **linker** error, not structural — 01 must not flag it, and does not; it is caught by 03 instead (§2) |

### 1b. Zero false positives on reference implementations

`.meta/example.*` of the same tasks, run through 01 — all PASS:

| Reference | 01 verdict |
|---|---|
| binary-search-tree `.meta/example.h` (header-only, `template<typename T> class binary_tree`) | PASS (1 symbol) |
| bank-account `.meta/example.{h,cpp}` (no user ctor → implicit public default) | PASS (1 symbol) |
| kindergarten-garden `.meta/example.{h,cpp}` | PASS (2 symbols) |
| zebra-puzzle `.meta/example.{h,cpp}` | PASS (2 symbols) |
| linked-list `.meta/example.{h,cpp}` (`template <typename T> class List`) | PASS (1 symbol) |
| crypto-square `.meta/example.{h,cpp}` | PASS (1 symbol) |

The crypto-square failed candidate also passes 01 (correct: its API is right,
its semantics are wrong — caught by 04, §3).

Sample real output (bank-account candidate):

```
--- Structural API Gate ---
Required symbols derived from test: Bankaccount::Bankaccount
  FAIL  'Bankaccount' constructor is private -- the test constructs 'Bankaccount::Bankaccount' and needs a public constructor
VERDICT: FAIL (1/1 symbols)
```

## 2. Verifier 03 — Two-Stage Build (CE vs LE)

Real subprocess builds: stage 1 `g++ -std=c++17 -Wall -Wextra -Wpedantic
-Werror -c <candidate>.cpp`; stage 2 compiles `<stem>_test.cpp` +
`test/tests-main.cpp` and links.

| Case | Expected | Got | Evidence |
|---|---|---|---|
| binary-search-tree row0 | compile error | **CE-2** | `binary_search_tree_test.cpp:12:63: error: 'binary_tree' is not a member of 'binary_search_tree'` — the candidate TU itself compiles (stage 1 clean); the *test* fails against the candidate header |
| linked-list candidate (recorded `undefined reference to 'linked_list::List<int>::List()'` — template defs in `.cpp`) | linker error | **LE** | `undefined reference to 'linked_list::List<int>::List()'` / `push(int)` / `pop()` …; feedback: "Typical cause: functions or template methods declared in the header but defined in the .cpp file. Move the definitions into the header." |
| binary-search-tree `.meta/example.h` (header-only reference) | clean | **PASS** | `build clean: candidate compiles and links against the official test` |

Note: the LE demonstration is not synthetic — it is the exact candidate
extracted from the recorded trial-01 linked-list run (see §0).

## 3. Verifier 04 — Differential Semantic Gate

Positive control (reference `.meta/example.*` must pass 100% or the task
package is reported broken), then the candidate's Catch2 assertion summary as
partial credit, plus a differential statement (candidate fails assertions the
reference passes).

| Case | Reference control | Candidate | Verdict |
|---|---|---|---|
| crypto-square failed candidate (recorded `"clu hlt io " == "chillout "` — returns essentially-normalized input) | OK 8/8 | 5/8, failing cases: `9 character plaintext results in 3 chunks of 3 characters`, `8 character plaintext results in 3 chunks, the last one with a trailing space`, `54 character plaintext results in 7 chunks, the last two with trailing spaces` | **FAIL, score 0.625** |
| crypto-square `.meta/example.*` (as candidate) | OK 8/8 | 8/8 | **PASS, score 1.0** |
| kindergarten-garden semantic candidate (recorded 17 Catch2 `FAILED` lines) | OK 17/17 | 0/17 | **FAIL, score 0.0** |
| kindergarten-garden `.meta/example.*` (as candidate) | OK 17/17 | 17/17 | **PASS, score 1.0** |

Real output (crypto-square candidate):

```
Positive control (reference): OK run={'passed_assertions': 8, 'total_assertions': 8, 'score': 1.0, ...}
Candidate: 5/8 assertions passed (score 0.625)
  failing case: 8 character plaintext results in 3 chunks, the last one with a trailing space
  ...
Differential: candidate fails 3/8 assertions that the reference passes -- semantic regression, not a build problem
VERDICT: FAIL (score 0.625)
```

The observed "returns the input essentially unchanged" failure is caught
**without any echo-specific heuristic**: the 8-character case above is exactly
the recorded `REQUIRE( "clu hlt io " == ... )` failure, and it falls out of
the differential against the reference.

## 4. Litmus

```
$ grep -riE "bankaccount|crypto|chillout|cipher|binary_tree|kindergarten|zebra|linked_list|Plants" \
    01_structural_api_gate.py 03_two_stage_build_verifier.py 04_differential_semantic_verifier.py
LITMUS: ZERO task-name hits
```

Scope note: the litmus covers the three rewritten verifiers. `00_*`, `02_*`
and `example_*` are pre-existing demo files outside the rewrite scope; `02`
still contains its original hardcoded snippet by design. Task names do appear
in `validation/` (extraction manifests, this document, CLI arguments in
`run_validation.sh`) — that is input data, not verifier logic.

## 5. Honest limitations

- **01's parser is a heuristic tokenizer**, not a full C++ parser (structured
  behind `parse_candidate()` / `required_symbols_from_test()` so a clang-AST
  backend can replace it). Known edges: nested namespaces (`a::b::X` in the
  test is read as symbol `b` in namespace `a`); a function *called* (not
  declared) inside a candidate `.cpp` namespace block can be mis-registered
  as a declared function; call syntax `ns::Foo(...)` is treated as
  construction only when the candidate declares `Foo` as a class/struct.
- **KG and zebra "candidates" are the starting fixture files.** In both
  recorded runs the model produced no edit before the first build (token
  limit), so the recorded structural failure is against the untouched
  starting files. The extractor reports this (`starting_file_fallback`)
  rather than fabricating a submission.
- **04 does not implement a generic echo/identity probe.** Deciding that
  `f(x) == x` is a bug requires knowing which inputs should not be fixed
  points — task knowledge. The differential-vs-reference comparison catches
  the same failure class generically (demonstrated above); an echo probe
  would only prettify the report. See the module docstring of
  `04_differential_semantic_verifier.py`.
- **04's partial credit assumes Catch2 v2 output format** (the `assertions:`
  summary line, including its zero-suppressed columns, and the
  `All tests passed` banner).
- Builds use `-DEXERCISM_RUN_ALL_TESTS` so the full test body runs; the
  recorded aider runs used the fixture CMake (same flags per its
  `CMakeLists.txt`: `-Wall -Wextra -Wpedantic -Werror`, C++17).
