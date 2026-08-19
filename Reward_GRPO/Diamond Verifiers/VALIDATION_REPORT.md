# Diamond Verifier Validation Report

| Report field | Value |
|---|---|
| Topic | `diamond` |
| Workspace base commit | `3e3e1ace6fec6c18a56b48c03e09b3a1fa78ce81` |
| Verifier package state | Uncommitted workspace package |
| Policy/verifier package SHA-256 | `08baac993bd70d70c21de87155e77894affa2d764661a4f003542901b861ff5f` |
| Policies | 10 |
| Applicable kernels | 44 for a complete two-turn campaign: 34 candidate-source kernels and 10 bundle kernels |
| Validation date | 2026-08-18 |
| Semantic mutation adequacy | Official-suite-failing mutants `10/10`; full canonical-contract union `13/13`; no survivors |
| GRPO readiness | `READY` for the pinned canonical task; live reward-worker wiring remains unverified |

## Step 1: Structure and frozen-contract validation

The structure audit read the Diamond setup, all ten policy documents, all ten Python verifiers, the pinned Aider parser, and the protected task assets. It matched policy numbers one-to-one, parsed every verifier with Python's AST, counted comments with the tokenizer, checked subprocess argument lists and receipt logic, and traced the namespace, `rows(char)` API, five official cases, exact fixed-width A–Z geometry, authorized files, toolchains, and exclusions to kernels.

All ten pairs pass structure review and contain exactly one Python source comment each. Validation fixed four verifier-layer defects: unsafe nested or symlinked outputs, Policy 8's filename-only response binding, Policy 4 reading hidden `.meta/example.*` reference files, and Policy 9 missing logical container-bound checks. The final package rejects 12/12 sampled isolation attacks without writes, never loads hidden examples at candidate time, and leaves invalid characters explicitly outside the pinned A–Z contract; no infrastructure or training file was changed.

| Component or category | Role or failure pattern | Evidence or current status | How to verify | Files, controls, or next action |
|---|---|---|---|---|
| Python structure | Syntax and one-comment convention | PASS: 10/10 AST parses; comment vector is ten `1`s | Parse with `ast`; count `tokenize.COMMENT` | `verifiers/verifier_01_*.py` through `verifier_10_*.py` |
| Policy pairing | One documented contract per executable verifier | PASS: ten numbered Markdown/Python pairs | Compare numbered basenames and kernel functions | `Verifier implementation policy/`; `verifiers/` |
| Kernel inventory | Stable `+1`/`-1` decisions | PASS: `5+4+4+4+4+6+5+5+4+3 = 44` | Compare tables with `verify_*` functions | 34 source kernels; 10 full two-turn bundle kernels |
| Frozen contract | Exact API, five official assertions, and A–Z byte geometry | PASS: no uncovered canonical requirement | Review setup traceability against Policies 3, 5, and 6 | `strange/strange/diamond-setup.md` |
| Protected assets | Prevent test/CMake/parser substitution | PASS: pinned CMake/test/Catch/parser hashes validated | Modify one protected file or parser digest | Tampered test and response controls return `INVALID` |
| Hidden-reference isolation | Candidate verifier must not use `.meta/example.*` | PASS after fix: no verifier source references it; Policy 4 passes when examples are absent | Search verifier sources; run Policy 4 on stripped candidate tree | Verifier 04 SHA-256 `f700cecf…fa692` |
| Output isolation | Keep evidence outside candidate and bundle trees | PASS after fix: 10/10 nested outputs plus symlink input/output rejected; no target created | Invoke each CLI with nested output; test symlink traversal | All failures exit `2` before receipt creation |
| Toolchains | Primary, sanitizer, and portable builds | PASS | Run clean controls | GCC 13.3.0; Clang 18.1.3; CMake 3.31.6; pinned Clang container |
| Change boundary | Keep VM and training systems immutable | PASS | Review touched paths | Changes limited to Diamond policy/verifier/report files |

## Step 2: Known-good and metamorphic validation

Positive validation staged the exact pinned task, copied the hidden reference only into an isolated validation candidate, and ran all ten public CLIs. Policies 1–6, 9, and 10 consumed source; Policy 7 consumed a complete hash-bound two-turn repair bundle; Policy 8 consumed a parser-, response-, tree-, log-, and task-bound integrity bundle. The official suite ran five assertions, while Policy 6 independently checked exact outputs and invariants for every letter A through Z.

The known-good campaign passes 44/44 applicable kernels. Three behavior-preserving implementations—parameter renaming, a row-index formula, and a brace-clean reserve/reflect algorithm—pass 102/102 candidate-source kernels. An API-correct always-A adversary passes all 17 build/warning/API/dependency kernels but Policy 5 records only 1/5 official assertions and returns `-1` for execution and repetition, proving auxiliary rewards cannot create standalone semantic success.

| Component or category | Role or failure pattern | Evidence or current status | How to verify | Files, controls, or next action |
|---|---|---|---|---|
| Canonical known-good | Full policy campaign | PASS: 44/44 | Run Policies 1–10 with complete two-turn evidence | Validation summary SHA-256 `991c189e…32fc` |
| Build, warnings, API, dependencies | Auxiliary per-sample structure signals | PASS: 17/17 | Run Policies 1–4 with GCC 13.3 | Clean compile/link, exact API, isolated dependency graph |
| Official behavior | Pinned public examples and determinism | PASS: 5/5 assertions; ten identical reruns | Run Policy 5 | Kernels 5A–5D all `+1` |
| Independent semantics | Exact A–Z dimensions, bytes, glyph order, spacing, and symmetry | PASS: all 26 letters in six modes | Run Policy 6 | Kernels 6A–6F all `+1` |
| Bundle controls | Repair and Aider/harness integrity | PASS: Policy 7 `+5`; Policy 8 `+5` | Run authenticated two-turn and integrity bundles | First-turn-pass Policy 7 path also passes applicable `+2` |
| Sanitizer and portability | Bounds, ASan/UBSan, host/container Clang | PASS: Policy 9 `+4`; Policy 10 `+3` | Run official plus full-domain workloads | libstdc++ assertions, sanitizers, immutable container |
| Harmless transformations | Avoid reference-shape overfitting | PASS: three variants × 34 kernels = 102/102 | Rerun all source policies on each implementation | Parameter rename, row formula, reserve/reflect |
| Warning-sensitive control | One-line loop looked equivalent but violated strict build | Correctly rejected, then replaced with brace-clean version | Inspect `-Wmisleading-indentation`; rerun corrected source | Uncompilable control excluded from semantic mutation counts |
| API-correct semantic adversary | Always returns `{"A"}` | KILLED: Policies 1–4 `+17/17`; Policy 5 official result 1/5 | Compare auxiliary and official receipts | Standalone success requires Policies 5 and 6 |
| Candidate immutability | Prevent verifier edits to submitted source | PASS | Compare source manifests before and after runs | Reference SHA-256 values remain `a18f55e3…1ce6f` and `360626dd…4c33b` |

## Step 3: Mutation, `INVALID`, and repeatability validation

Failure validation used one targeted defect per policy role: missing definitions, warning-only code, wrong API names, absent or hidden-reference includes, incorrect output, mismatched feedback, parsed-body/tree disagreement, two forms of out-of-bounds access, and Clang-only rejection. Thirteen warning-clean semantic mutants were compiled and run through Policy 5 first; the three mutants that deliberately evaded A/B/C/D/Z examples were then run through the independent A–Z oracle.

Policy 5 kills all 10 mutants that fail the official suite, and Policy 6 kills all three official-suite survivors, so the combined canonical semantic layer kills 13/13 with no survivor. One evaluator dependency per policy returns `INVALID` for 10/10 controls, never candidate `-1`; 5 representative positive and 6 representative negative rerun pairs reproduce identical status and kernel vectors. Overlapping failures are not double-counted, and live reward-worker invocation plus trusted production of Policies 7–8 bundles remain unverified.

| Component or category | Role or failure pattern | Evidence or current status | How to verify | Files, controls, or next action |
|---|---|---|---|---|
| Policy 1 | Missing `rows` definition | KILLED: 1D and 1E `-1` | Run compile/link policy | Compile units succeed; link and clean build fail |
| Policy 2 | Unused local under strict warnings | KILLED: 2A and 2D `-1` | Run warning tiers | GCC reports controlled unused variable |
| Policy 3 | `rows` renamed to `make` | KILLED: 3B–3D `-1` | Run exact API probes | Header remains syntactically self-contained |
| Policy 4 | Missing `<vector>` and hidden `.meta/example.cpp` include | KILLED: ownership/self-containment and dependency kernels `-1` | Inspect depfile and header probe | 4C reports forbidden `.meta/example.cpp` |
| Policies 5–6 | Thirteen compile-clean semantic mutants | KILLED: official `10/10`; three official survivors killed by A–Z oracle | Run Policy 5 first, then Policy 6 on survivors | Union `13/13`; survivors: none |
| Policy 7 | Delivered feedback differs from generated feedback | KILLED: 7B `-1` | Run hash-consistent mismatch bundle | Correct two-turn control remains `+5` |
| Policy 8 | Parsed body differs from authenticated after tree; malformed response | KILLED: 8B `-1`; malformed 8A/8B `-1` | Rebind all hashes, preserve contradiction | Hash corruption separately returns `INVALID` |
| Policy 9 | Heap OOB and small-string logical OOB | KILLED: ASan catches heap; libstdc++ assertions catch logical bounds | Run official and A–Z sanitizer workloads | Reference remains `+4` after hardening |
| Policy 10 | Candidate rejects only Clang | KILLED: 10A–10C `-1` | Run host and pinned-container Clang | GCC auxiliary controls remain separate |
| Evaluator faults | Missing tools, changed tests, wrong source digest, corrupted bundles | PASS: 10/10 policy controls are overall `INVALID` | Break one dependency per policy | No evaluator fault becomes candidate `-1` |
| Repeatability | Positive and negative representative controls | PASS: 11/11 normalized pairs match | Compare status, applicability, kernel IDs, and scores | 5 positive and 6 negative pairs; paths/times excluded |
| Mutation adequacy | All sampled non-equivalent contract faults | PASS: 13/13 union; no survivor | Recompute from official-first receipts | Official denominator 10; full-domain extension 3 |

## Final conclusion

The pinned canonical Diamond package is `READY` as a GRPO verifier layer: `strange` freezes the contract and builds the policy pairs, `strange-validate-verifiers` exercises positive, metamorphic, mutation, isolation, `INVALID`, and repeatability boundaries, and `strange-build-validation-reports` records the evidence here. Policies 1–6 are suitable for per-sample signals with Policies 5–6 mandatory for semantic success; Policies 7–8 require trusted conversation/evaluation bundles; Policies 9–10 should normally run as periodic audit or promotion gates. The verifier CLIs need no further logic change before consumption, but the next concrete check is one real reward-worker invocation that proves bundle production and score ingestion end to end.
