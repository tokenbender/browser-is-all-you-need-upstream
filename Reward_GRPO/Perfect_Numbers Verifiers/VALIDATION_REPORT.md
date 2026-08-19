# Perfect Numbers Verifier Validation Report

| Report field | Value |
|---|---|
| Topic | `perfect-numbers` |
| Verifier commit | Workspace base `3e3e1ace6fec6c18a56b48c03e09b3a1fa78ce81`; verifier package is uncommitted |
| Policies | 4 |
| Kernels | 15 total: 11 per-candidate and 4 trajectory |
| Validation date | 2026-08-18 |
| GRPO readiness | `READY` for the pinned canonical contract |

## Step 1: Structure and frozen-contract validation

I parsed all four verifier programs, matched them one-to-one with four policy documents, counted exactly one Python source comment per verifier, and authenticated the nine protected task assets. The traceability review maps the exact namespace, scoped enum, three enumerators, function signature, all 13 official assertions, deterministic divisor cases, and two-turn repair requirements to 15 kernels.

All structural checks passed. Validation tightened only verifier-layer integrity: unsafe output paths are rejected before any receipt write, trajectory source directories permit only the two authorized files, evaluation receipts bind each turn's combined source digest, and a terminal success now requires the `complete` stage plus 13 explicit passing outcomes; infrastructure and training files were not changed.

| Check | Expected condition | Result | Evidence |
|---|---|---|---|
| Policy/verifier pairing | One numbered policy per verifier | PASS | 4 policies and 4 verifiers |
| Python structure | AST parses; exactly one source comment each | PASS | 4/4 AST parses; comment vector `[1, 1, 1, 1]` |
| Policy simplicity | No `Evidence Boundary` or `Conclusion` sections | PASS | 4/4 policy documents clean |
| Frozen assets | Every protected digest matches the setup | PASS | 9/9 hashes matched; official test SHA-256 `fa206f8f…50be3` |
| Contract coverage | Every public clause and official assertion family is mapped | PASS | API E01; positive semantics E02; invalid inputs E03; trajectory E04; uncovered official requirements: none |
| Output/source isolation | No candidate/bundle writes and exact source authorization | PASS | 8/8 nested/symlink attacks rejected; candidate and bundle trees unchanged |
| Final verifier digests | Record post-fix verifier identity | PASS | E01 `6d402b5b…c9781`; E02 `4877ace2…b8c37`; E03 `091a7e3d…f51d`; E04 `c98b7eaf…d0ae` |

## Step 2: Known-good and metamorphic validation

I staged the exact pinned task in a temporary directory, installed an independent warning-clean correct implementation, and ran Policies 1–3 plus the pinned 13-test executable. I then repeated the check with three behavior-preserving implementations that rename locals, reorder classification branches, or use an equivalent lambda-based divisor calculation; Policy 4 received a source-bound two-turn bundle that repaired the historical `classify(1)` error.

The known-good candidate passed all 11 per-candidate kernels and all 13 official assertions, while the repair bundle passed all four trajectory kernels. The three harmless variants passed 33/33 kernels and 39/39 official assertions. An API-correct always-deficient adversary still passed E01 and E03, but E02 rejected it and the official suite recorded 7 passes and 6 failures, proving that compile/API rewards cannot create a standalone semantic success.

| Control | Scope | Result | Evidence |
|---|---|---|---|
| Canonical known-good | E01–E03 and official suite | PASS | 11/11 kernels; 13/13 assertions |
| Valid repair trajectory | E04-A through E04-D | PASS | Vector `[+1, +1, +1, +1]` |
| Harmless metamorphic controls | Three independently written equivalent candidates | PASS | 33/33 kernels; 39/39 official assertions |
| API-correct semantic adversary | Always returns `deficient` for positive input | KILLED | E01 `[+1,+1,+1,+1]`; E02 `[+1,-1,-1,-1]`; E03 `[+1,+1,+1]`; official 7/13 |
| Candidate immutability | Source before and after verifier execution | PASS | Combined source digests unchanged |
| Candidate campaign receipt | Machine-readable positive/adversary evidence | PASS | Summary SHA-256 `38ea1b67…7a80` |

## Step 3: Mutation, `INVALID`, and repeatability validation

I exercised one controlled candidate failure for every E01–E03 kernel and one bundle failure for every E04 kernel, then ran 12 warning-clean semantic mutants through the pinned official test executable before scoring them. The mutants cover the unit edge, category-return swaps, self inclusion, square-root double counting, paired-divisor omission, wrong exception type, nonpositive handling, and hard-coded behavior.

Every intended kernel boundary produced `-1`; E04-C also caused the documented dependent E04-D failure because a regressed test prevents 13/13 completion. All 12 authoritative-suite-failing mutants were killed with no survivors. Five evaluator-corruption controls returned `INVALID`, eight isolation attacks made no writes, and eight positive/negative rerun pairs reproduced identical status, kernel vector, counts, and summaries.

| Policy or control | Controlled fault | Expected | Observed |
|---:|---|---|---|
| E01-A–E01-D | Unscoped enum, wrong signature, missing definition, broken official caller | Intended kernel `-1` | 4/4 isolated vectors matched |
| E02-A–E02-D | Wrong `1`, official case, square case, generated case | Intended kernel `-1` | 4/4 isolated vectors matched |
| E03-A–E03-C | Zero, negative one, negative partition violate exact exception rule | Intended kernel `-1` | 3/3 isolated vectors matched |
| E04-A–E04-D | Untargeted edit, retained diagnostic, regression, incomplete repair | Intended kernel `-1` | 4/4 matched; E04-C also failed dependent E04-D |
| Mutation adequacy | 12 compile-clean official-suite-failing mutants | All rejected | 12/12 killed, 100%; survivors: none |
| Evaluator integrity | Three missing compilers, source-binding corruption, unauthorized snapshot file | `INVALID`, never `-1` | 5/5 `INVALID` |
| Output isolation | Nested and symlinked outputs across four CLIs | Reject without writes | 8/8 rejected; no output target created |
| Repeatability | Positive and negative pair for each policy | Identical normalized decisions | 8/8 pairs matched |
| Evidence summaries | Candidate, trajectory, integrity, repeatability JSON | SHA-256 bound | `38ea1b67…7a80`, `073dc700…5d3`, `13686fc1…7b36`, `0f435a25…1fbd` |

## Final conclusion

The canonical Perfect Numbers package is `READY` as a GRPO verifier layer for the pinned task. `strange` fixes the contract and builds the policy pairs, `strange-validate-verifiers` supplies positive, metamorphic, semantic-adversary, mutation, isolation, `INVALID`, and repeatability evidence, and `strange-build-validation-reports` records the decision here. Policies 1–3 can provide per-sample signals, but a terminal success must require both the API layer and semantic Policies 2–3; Policy 4 consumes trusted two-turn evaluation bundles. Live reward-worker wiring and trusted bundle production were not executed, so the next integration check is one real reward-worker invocation that preserves these receipt bindings. No infrastructure or training file was changed.
