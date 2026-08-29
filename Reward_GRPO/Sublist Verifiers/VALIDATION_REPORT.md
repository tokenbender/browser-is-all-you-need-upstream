# Sublist Verifier Validation Report

| Report field | Value |
|---|---|
| Topic | Sublist |
| Workspace base commit | `3e3e1ace6fec6c18a56b48c03e09b3a1fa78ce81` |
| Verifier package state | Uncommitted workspace package |
| Policy/verifier package SHA-256 | `cee98e8b1ee6c6f805b6b7187a38ab009e8bddcb03b34cd973bba61d99da77c6` |
| Policies | 10 |
| Applicable kernels | 46: 36 candidate-source kernels and 10 bundle kernels |
| Validation date | 2026-08-18 |
| Semantic mutation kill ratio | Policy 05: `12/12`; Policy 06: `12/12`; no survivors |
| GRPO readiness | `READY` for the pinned canonical task; live reward-worker wiring remains unverified |

## Step 1: Structure and frozen-contract validation

The structure check read the Sublist setup, all ten policy documents, all ten entry points, and the shared runtime. It authenticated the five protected exercise files, task manifest, pinned Aider parser, 18-test inventory, exact namespace function and enum API, editable-file boundary, strict C++17 commands, receipt schema, source immutability, sanitizer placement, and Clang portability contract. All 11 Python files parse and contain exactly one source comment; policy numbering and entry-point numbering match 1–10.

Re-verification found and fixed four verifier-layer defects without changing the task contract: unsafe nested/symlink output paths, a CMake staging directory whose name broke the derived target, Policy 7 accepting a contradictory 0/18 success receipt, and Policy 4 generating but not inspecting its dependency file. The final runtime rejects 20/20 output-isolation attacks without writing, requires exact 18/18 trajectory success, and rejects extra candidate-local dependencies. The setup's historical reference-source digests were not locally reproduced and are not scoring inputs; protected tests, manifest, parser, and candidate evidence are independently authenticated.

| Check | Expected condition | Result | Evidence |
|---|---|---|---|
| Python structure | Ten entry points plus one shared runtime parse and follow the one-comment rule | PASS | 11/11 AST parses; 11/11 one-comment counts |
| Policy pairing | One policy per numbered verifier | PASS | Ten Markdown/Python pairs, Policies 01–10 |
| Kernel inventory | Every documented condition has an implementation | PASS | `5+4+5+5+6+5+5+5+3+3 = 46` kernels |
| Frozen task evidence | Exact tests, CMake, Catch, manifest, parser, API, and authorized files | PASS | Five fixed hashes, manifest `d45dc8c…`, parser `82558ec…`, 18 `TEST_CASE`s |
| Safe output boundary | No writes inside candidate/bundle or through symlinks | PASS after fix | 20/20 attacks rejected; summary `ec58cab64a7898b630a1f872e646653832ec3b32f88d763df5671564391759eb` |
| Clean CMake identity | Staged directory preserves exercise name `sublist` and target `test_sublist` | PASS after fix | Policy 1 kernel 1E passes with temporary CMake 3.31.6 |
| Dependency ownership | Only `sublist.cpp` and `sublist.h` may appear as candidate-local dependencies | PASS after fix | Extra `extra.h` is reported by 4C and scored `-1` |
| Trajectory success | Passing status must also prove 18 passed, 18 total, 0 failed | PASS after fix | Valid repair passes; contradictory 0/18 receipt fails 7E |
| Toolchains | Primary GCC, sanitizers, independent Clang, and CMake are usable | PASS | GCC 13.3.0, Clang 18.1.3, ASan/UBSan controls, temporary CMake 3.31.6 |
| Change boundary | Infrastructure and training remain read-only | PASS | Changes limited to the Sublist verifier package; validation artifacts stay under `/tmp` |

## Step 2: Known-good and metamorphic validation

Positive validation copied the authenticated exercise fixtures, supplied an independent correct implementation, and ran every policy through its public CLI. Policies 7 and 8 used complete hash-bound repair and response bundles. The harmless source control renamed the internal window helper and reordered independent includes, then reran all 36 candidate-source kernels. Source hashes before and after every candidate run remained identical.

The final known-good campaign passes all 46 applicable kernels. It includes all 18 official tests, 116,281 ordered pairs from the independent short-list oracle, five deterministic official reruns, 500 combined-sanitizer stress repetitions, strict GCC builds, and strict Clang reproduction. The API-correct always-equal adversary passes Policy 3 at `+5`, but Policy 5 rejects all six functional kernels and Policy 6 rejects the exhaustive semantic layer, so API shape cannot produce standalone success.

| Control | Scope | Result | Evidence |
|---|---|---|---|
| Final known-good campaign | Policies 1–10 | PASS: 46/46 | Summary SHA-256 `03703f2d3cb5bc6a64f25b6ec6169e3c82c677f46767c59e76ba935e1c22c0b4` |
| Build, warnings, API, dependencies | Policies 1–4 | PASS: 19/19 | Clean GCC/CMake link, exact API probes, isolated depfile |
| Official and independent semantics | Policies 5–6 | PASS: 11/11 | 18/18 official tests; 341 lists and 116,281 ordered pairs |
| Trajectory and harness bundles | Policies 7–8 | PASS: 10/10 | Exact feedback, 18/18 closure, pinned parser, source/counter/command hashes |
| Sanitizer and portability | Policies 9–10 | PASS: 6/6 | ASan, UBSan, combined stress, and Clang official/clean builds |
| Harmless transformation | All candidate-source policies | PASS: 36/36 | Helper rename and include reorder preserve every decision |
| API-correct semantic adversary | Exact API with always-equal behavior | KILLED | Policy 3 `+5`; Policy 5 `-6`; Policy 6 overall fail |
| Final runtime binding | Every final positive receipt uses the same shared implementation | PASS | Shared runtime SHA-256 `2abd93bfa7f00f47ea506ef92c3ed366cf038d67ad8e56ae72a06d66b813a51c` |

## Step 3: Mutation, `INVALID`, and repeatability validation

Failure validation used policy-specific source and bundle defects: missing definitions, warning-only code, wrong enumerators, missing or extra includes, feedback mismatch, nonzero context counters, out-of-bounds access, and intentional Clang rejection. Twelve compile-clean semantic mutants covered constant returns, direction reversal, loose subsequences, prefix/suffix-only matching, false-start recovery, empty-list rules, equal-size shortcuts, digit-string matching, and sorted equality. Protected-fixture corruption and bundle hash corruption were run separately as evaluator faults.

Every targeted defect produced at least one candidate `-1`, while evaluator corruption produced overall `INVALID` for 10/10 policies and never became candidate failure. Policies 5 and 6 each killed all 12 semantic mutants; these are the same 12 mutants observed by two layers, so the unique denominator is 12 rather than 24. All ten positive policies were repeated with identical normalized status, kernel vector, counts, summaries, and facts; path, duration, and receipt-hash fields were excluded from that deterministic projection.

| Policy | Controlled fault or invalid control | Expected | Observed |
|---:|---|---|---|
| 1 | Missing method definitions; changed protected test | `-1`; `INVALID` | 1D/1E fail; fixture corruption makes 5/5 kernels `INVALID` |
| 2 | Unused local under strict warnings; changed protected test | `-1`; `INVALID` | 2A/2D fail; fixture corruption makes 4/4 `INVALID` |
| 3 | Uppercase enum contract; changed protected test | `-1`; `INVALID` | 3B/3E fail; fixture corruption makes 5/5 `INVALID` |
| 4 | Missing `<vector>` and unauthorized `extra.h`; changed protected test | `-1`; `INVALID` | 4A/4B/4E fail; 4C now rejects `extra.h`; corruption is `INVALID` |
| 5 | Twelve functional mutants; changed official suite | `-1`; `INVALID` | 12/12 killed; protected-test mismatch makes 6/6 `INVALID` |
| 6 | Same twelve mutants against independent oracle; changed official suite | `-1`; `INVALID` | 12/12 killed; protected-test mismatch makes 5/5 `INVALID` |
| 7 | Feedback mismatch and contradictory 0/18 success; artifact hash mismatch | `-1`; `INVALID` | 7B and 7E fail respectively; corrupted response makes overall `INVALID` |
| 8 | Context-exhaustion counter; response hash mismatch | `-1`; `INVALID` | 8C fails; corrupted response makes overall `INVALID` |
| 9 | Deliberate out-of-bounds read; changed protected test | `-1`; `INVALID` | 9A/9C fail; fixture corruption makes 3/3 `INVALID` |
| 10 | Candidate rejected only by Clang; changed protected test | `-1`; `INVALID` | 10A–10C fail; fixture corruption makes 3/3 `INVALID` |
| Mutation adequacy | 12 authoritative-suite-failing semantic mutants | All rejected | Policy 5: 12/12; Policy 6: 12/12; survivors: none; summary `caff719f1ad00f8b7eb458197db488dca12f675592fc61dd46ea281014b5a21c` |
| Repeatability | All ten positive policy decisions | Exact normalized match | 10/10 policies matched across repeated runs |

## Final conclusion

The canonical Sublist package is `READY` as a verifier layer for the pinned task. `strange` defines the contract, `strange-validate-verifiers` exercises positive, metamorphic, mutation, isolation, `INVALID`, and repeatability boundaries, and `strange-build-validation-reports` records the evidence here. Policies 1–4 provide build/API/dependency rewards; Policies 5–6 are the authoritative per-candidate semantic gates; Policies 7–8 require trusted trajectory/evaluation bundles; Policies 9–10 are better placed as periodic audit or promotion gates. The verifier CLIs are ready to be consumed without logic changes, but live GRPO reward-worker wiring and trusted bundle production were not executed; that live integration run is the next check.
