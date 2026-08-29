# Allergies Verifier Validation Report

| Report field | Value |
|---|---|
| Topic | Allergies |
| Workspace base commit | `3e3e1ace6fec6c18a56b48c03e09b3a1fa78ce81` |
| Verifier package state | Uncommitted workspace package |
| Policy/verifier package SHA-256 | `eb078c6186abec494ed1fc06e70f412a553dcc3d9fe5948ff2ea1466bd1ef705` |
| Policies | 6 |
| Applicable kernels | 11 for a candidate directory, 5 for an authenticated two-turn trajectory, 16 when both inputs exist |
| Validation date | 2026-08-18 |
| Semantic mutation kill ratio | `12/12 (100%)`; no surviving non-equivalent mutant |
| GRPO readiness | `READY` for canonical per-sample success and terminal reward when E06 is required; live reward-worker wiring remains unverified |

## Step 1: Structure and frozen-contract validation

The structure check matched all six policy Markdown files to six Python implementations, parsed every verifier with Python's AST parser, counted actual Python comments with the tokenizer, and inspected subprocess, timeout, output-isolation, source-immutability, SHA-256, aggregation, and receipt behavior. This re-verification found and fixed one evidence-safety defect: an empty output nested inside the candidate or an output path traversing a symlink could receive evaluator artifacts. The frozen contract remains `allergies::allergy_test`, an `unsigned int` constructor, the const string-query API, the const `unordered_set<string>` collection API, 50 protected assertions, C++17, strict GCC warnings, and two authorized source files.

All six pairs pass structure review and contain exactly one Python source comment each. After the correction, all 12 output-isolation attacks—nested output and symlink traversal against each of E01–E06—return exit code 2, create no receipt or executable through the unsafe path, and leave the candidate or trajectory bundle and external target unchanged. The setup maps every canonical public-contract clause and official assertion family to E01–E06; unknown allergen names, sanitizer safety, include ownership, and portability remain explicit non-claims. E06 is canonical-task-specific because it binds the exact Allergies test assets and must not be reused for renamed equivalents.

| Component or category | Role or failure pattern | Evidence or current status | How to verify | Files, controls, or next action |
|---|---|---|---|---|
| Python structure | Verifier syntax and comment convention | PASS: 6/6 AST parses; 6/6 have one comment | Parse with `ast`; count `tokenize.COMMENT` | `verifiers/verifier_01_*.py` through `verifier_06_*.py` |
| Policy pairing | One contract per implementation | PASS: six matched E01–E06 pairs | Compare numbered Markdown/Python basenames | `Verifier implementation policy/`; `verifiers/` |
| Kernel inventory | Stable binary decisions | PASS: E01 `3`, E02 `3`, E03 `2`, E04 `2`, E05 `5`, E06 `1` | Compare policy tables with `verify_*` functions | 16 total across candidate and two-turn inputs |
| Contract traceability | Prevent API-only success claims | PASS for pinned canonical contract | Review setup matrix against all 50 official assertions | `strange/strange/allergies-setup.md` |
| Authoritative semantic gate | Authenticate and execute full behavior contract | PASS: E06 binds four fixed assets and exact 50/50 summary | Run E06 on reference and semantic adversary | E06 verifier SHA-256 `06e35b4d1c839aa39c3e837d3202de821d0025084f2adf23f2fcd27848b5ddcb` |
| Evidence safety | Separate candidate failures from evaluator failures | PASS after fix: 12/12 isolation attacks rejected without writes; fixed hashes and immutable inputs preserved | Try nested-empty and symlink-traversing outputs, changed tests, and missing compiler | Isolation summary SHA-256 `1ada2fd17c0de0195321856aa014b5d596c812226f20d05cd41a2970e28d1a77` |
| Explicit non-claims | Avoid overstating standalone coverage | VERIFIED: unknown-name behavior and periodic sanitizer/include/portability audits are not scored | Compare setup non-scoring section with policy set | Add separate policies only if those claims become required |
| Change boundary | Keep infrastructure and training untouched | PASS | Review workspace status and touched paths | Changes limited to Allergies package and Allergies setup |

## Step 2: Known-good and metamorphic validation

The positive validation ran E01–E04 against the pinned reference, E05 against an authenticated successful repair bundle, and E06 against the complete protected test program. It also renamed the reference's private `result` field to `stored_score` without changing behavior, then reran the candidate policies and official suite. The previously validated ten renamed equivalents remain transfer evidence for the general Allergies behavior, not inputs to the canonical hash-bound E06.

All 16 applicable kernels return `+1` when both candidate and two-turn evidence are present: policy sums are `+3`, `+3`, `+2`, `+2`, `+5`, and `+1`. E06 records 50 passed assertions in 50 passed test cases for both the reference and harmless rename. The known-good official output digest remains `9ca98f7046d1ef027be17feb2627e3bd45eda7aa92f2713f19a82be2a3ecb2f1`.

| Component or category | Role or failure pattern | Evidence or current status | How to verify | Files, controls, or next action |
|---|---|---|---|---|
| Canonical fast candidate | API and warning-shaped rewards | PASS: E01 `+3`, E02 `+3`, E03 `+2`, E04 `+2` | Run E01–E04 on pinned `.meta/example.*` | 10/10 fast kernels passed |
| Successful repair bundle | Authenticated two-turn closure | PASS: E05 `+5` | Run E05 on Luna successful repair bundle | 5A–5E all returned `+1` |
| Canonical official behavior | Terminal semantic success | PASS: E06 `+1`; 50/50 | Run E06 on pinned reference | Fresh receipt SHA-256 `58e9a0e8159372548580b2783ccbcd1b649fd821d2e8daea79d2b5a44a629a6a` |
| Harmless private-field rename | Reject reference-shape matching | PASS: E01–E04 remain `+10/10`; E06 remains 50/50 | Rename only `result` to `stored_score` in a temporary copy | No public or behavioral change |
| Equivalent-suite transfer | Ten renamed Allergies-like tasks | PASS: 500/500 assertions, ten strict builds, ten self-contained headers | Run each equivalent's own authoritative suite | Receipt SHA-256 `ec174cad45904efe1146eaceb782a0dca29bba0f964113b61a2846b04833a20a` |
| Canonical specificity | Prevent hash/API leakage into equivalents | VERIFIED boundary | Compare each equivalent manifest before reuse | E06 is not claimed as a manifest adapter |

## Step 3: Mutation, `INVALID`, and repeatability validation

Failure validation reran the API-correct false/empty adversary, four constant mutants, four operator mutants, two return mutants, and two branch mutants. Every counted mutant compiled warning-cleanly before the protected suite ran. Missing-compiler and changed-test controls exercised evaluator failure, while positive and negative E06 controls were each repeated twice and compared by status, score, assertion totals, and summaries.

The old blind spot is closed: E01–E04 still give the false/empty adversary `+10/10`, but E06 reports 17 passed and 33 failed assertions and returns `-1`. E06 killed all 12 authoritative-suite-failing, compile-clean mutants, for `12/12 (100%)`, with no survivors. One initial forced-return mutation that introduced an unused-variable compile error was excluded from the semantic denominator and replaced with a warning-clean forced-return mutant.

| Component or category | Role or failure pattern | Evidence or current status | How to verify | Files, controls, or next action |
|---|---|---|---|---|
| API-correct semantic adversary | Both methods return false/empty | KILLED: fast `+10/10`; E06 `-1`; 17 passed, 33 failed | Run E01–E04 and E06 on the same source snapshot | Original standalone false-positive path is closed only when E06 is required |
| Constant mutations | Eggs `1→2`, peanuts `2→1`, cats `128→64`, add unknown bit `256` | KILLED `4/4`; all compile return codes 0 | Run E06 and inspect assertion totals | Failure splits: `43/7`, `43/7`, `48/2`, `48/2` passed/failed |
| Operator mutations | Query/list `&→|` and `==→!=` | KILLED `4/4`; all compile return codes 0 | Run E06 | Failure splits: `26/24`, `10/40`, `43/7`, `40/10` |
| Return mutations | Query always false; list always empty | KILLED `2/2`; both compile return codes 0 | Run E06 | Failure splits: `26/24` and `41/9` |
| Branch mutations | Force eggs false; skip cats in returned set | KILLED `2/2`; both compile return codes 0 | Run E06 | Both split `47/3` |
| Mutation adequacy | All compile-clean, official-suite-failing semantic mutants | PASS: `12/12 (100%)`; survivors: none | Recompute projection from fresh receipts | Campaign summary SHA-256 `5df6554cb9259f756316f5a762d2af7a1652fbd19ae629255401076b0ee42952` |
| Excluded mutation | First forced-false edit left an unused local under `-Werror` | CLASSIFIED: uncompilable, excluded from semantic denominator | Inspect compile receipt; compare replacement mutant | Not counted as a semantic kill or survivor |
| E06 evaluator faults | Missing GCC and modified protected test | PASS: both `INVALID`, never `-1` | Run with missing compiler; alter `allergies_test.cpp` hash | Preflight identifies exact failure owner |
| E05 evidence fault | Delivered feedback differs from generated feedback | PASS: E05 `INVALID` | Rehash altered feedback bundle and run E05 | Trajectory integrity remains separate from candidate semantics |
| Repeatability | E01–E06 positives plus E06 adversary | PASS: normalized decisions match; E06 positive and negative each repeated twice | Compare status, kernel vector, counts, facts, and summaries | Absolute output paths, durations, and timestamps excluded from the projection |

## Final conclusion

The canonical Allergies package remains `READY` for direct per-sample success and terminal reward when E06 is mandatory: the `strange` workflow builds the six policies, `strange-validate-verifiers` validates their controls and 100% sampled mutation kill ratio, and `strange-build-validation-reports` records the evidence here. E01–E04 remain auxiliary shaped rewards, E05 remains trajectory-only, and E06 is the authoritative canonical semantic gate. The re-verification also corrected and retested unsafe output-path handling across E01–E06. Live reward-worker integration, sanitizers, include ownership, portability, and renamed-task adaptation were not tested or claimed; the next integration check is an actual reward-worker run that requires a passing E06 receipt.
