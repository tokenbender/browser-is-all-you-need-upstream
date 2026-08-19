# Grade School Verifier Validation Report

| Report field | Value |
|---|---|
| Topic | Grade School |
| Workspace base commit | `3e3e1ace6fec6c18a56b48c03e09b3a1fa78ce81` |
| Verifier package state | Uncommitted workspace package |
| Policy/verifier package SHA-256 | `b54e471556ae6c6d15442924919663c2ae99dd2a273799240be693fe835a81b9` |
| Policies | 10 |
| Applicable kernels | 32 candidate-source kernels, 5 trajectory kernels, 6 integrity kernels; 43 total when all evidence types exist |
| Validation date | 2026-08-18 |
| Semantic mutation kill ratio | `6/6 (100%)`; no surviving API-correct semantic mutant |
| GRPO readiness | `READY` for the pinned canonical verifier layer when Policies 5 and 6 are mandatory semantic gates; live reward-worker wiring remains unverified |

## Step 1: Structure and frozen-contract validation

The structure pass matched ten policy Markdown files to ten Python implementations, parsed all eleven Python files including the shared helper, counted real tokenizer comments, compared policy kernel IDs with implementation functions, and inspected command execution, timeouts, immutable inputs, protected hashes, output isolation, binary aggregation, and receipt provenance. The frozen contract remains revision `7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f`, the two authorized Grade School source files, the exact `grade_school::school` API, eight official tests, GCC 13.3, C++17, and strict warning-as-error compilation.

All ten pairs pass structure review, expose 43 unique matched kernels, contain exactly one source comment per policy verifier, and never use `shell=True`. The setup now maps every pinned API and official behavior clause to authoritative kernels and makes Policies 5 and 6 jointly mandatory for semantic success. Verifier outputs are rejected when placed inside candidate or evidence trees, parent-component symlinks are rejected, and every receipt binds both the policy script and shared helper digest; duplicate enrollment, cross-grade duplication, non-positive grades, and concurrency remain explicit non-claims.

| Component or category | Role or failure pattern | Evidence or current status | How to verify | Files, controls, or next action |
|---|---|---|---|---|
| Python structure | Syntax and one-comment convention | PASS: 11/11 AST parses; 10/10 policy verifiers have one comment | Parse with `ast`; count `tokenize.COMMENT` | `verifiers/_grade_school_common.py`; `verifiers/verifier_01_*.py` through `verifier_10_*.py` |
| Policy pairing | One policy document per implementation | PASS: 10/10 pairs | Compare numbered Markdown and Python basenames | `Verifier implementation policy/`; `verifiers/` |
| Kernel inventory | Stable `+1/-1/INVALID` decisions | PASS: 43/43 IDs match; no duplicates | Compare policy tables with `verify_*` functions | P1 `5`, P2 `4`, P3 `4`, P4 `3`, P5 `3`, P6 `5`, P7 `5`, P8 `6`, P9 `4`, P10 `4` |
| Contract traceability | Prevent build/API-only semantic success | PASS for all pinned API and eight official behavior families | Review the contract-to-kernel matrix | `strange/strange/grade-school-setup.md` |
| Output isolation | Prevent receipts from changing evaluated inputs | PASS: candidate, trajectory, and integrity nested outputs each exit 2, create no directory, and leave trees unchanged | Run each verifier with `--output-dir` beneath its input | Three copied-tree controls returned `unchanged=True` |
| Evidence path safety | Reject hash corruption and symlink evidence | PASS: both classes become `INVALID` | Alter a bound artifact or replace it with a symlink | P7 corrupt-hash and symlink controls; P8 corrupt-hash control |
| Receipt provenance | Bind shared logic as well as policy entry point | PASS: all 10 canonical receipts bind helper `42215c0f…` | Compare `shared_helper_sha256` across receipts | Canonical evidence-set SHA-256 `6e597f43…` |
| Change boundary | Keep infrastructure and training untouched | PASS | Review touched paths | Changes are limited to the Grade School verifier package and Grade School setup |

## Step 2: Known-good and metamorphic validation

The positive pass ran all ten policies against a pinned canonical candidate, a complete successful two-turn trajectory, and a complete response/harness bundle. It then changed only the private roster field name and reran all 32 source-based kernels, preserving the public API and behavior while changing source shape. As independent transfer evidence, all ten renamed Grade-School-like variants were configured, strict-built, and executed on current Linux/GCC.

The canonical package returns `+1` on all 43/43 applicable kernels, and every canonical receipt carries the same shared-helper digest. The harmless private rename returns `+1` on 32/32 source-based kernels. The current equivalent run passes 10/10 variants and 120/120 assertions; the suite's stored authenticated receipt also passes strict and sanitizer modes, while its top-level rerun currently reports a generator dependency hash mismatch, so the current claim is based on direct immutable variant builds rather than silently ignoring that evaluator drift.

| Control | Scope | Result | Evidence |
|---|---|---|---|
| Canonical candidate | Policies 1–6, 9, and 10 | PASS: 32/32 source kernels | Canonical evidence-set SHA-256 `6e597f43e3ad3437a4ac304d1bd806ade23dafb87409c14ce9fbf7fd85372eb0` |
| Successful repair bundle | Policy 7 | PASS: 5/5 trajectory kernels | 7A–7E all returned `+1` |
| Complete response/harness bundle | Policy 8 | PASS: 6/6 integrity kernels | 8A–8F all returned `+1` |
| Harmless private-field rename | All 32 source-based kernels | PASS: 32/32 | Metamorphic evidence-set SHA-256 `ee11fcb0d1fb3a1461699766bc74baa7b6c4324eaf3d05e944b4cf24c6fa98a6` |
| Equivalent-suite transfer | Ten renamed roster tasks | PASS: 10/10 strict Linux/GCC builds and 120/120 assertions | Current log-set SHA-256 `0740c9a9…`; stored suite receipt SHA-256 `b42fa391…` |
| Equivalent-suite generator gate | Whole generated-suite provenance rerun | INVALID because the local generator common-module hash changed after suite generation | The direct variant results remain valid supplemental evidence; do not claim a new whole-suite provenance receipt |
| API-correct semantic adversaries | Six wrong implementations with unchanged exact API | PASS as a validation control: Policy 3 gives 24/24 `+1`, then Policies 5/6 reject all six | Mutations cover ordering, grade mapping, empty queries, query mutation, roster reporting, and no-op insertion |

## Step 3: Mutation, `INVALID`, and repeatability validation

Failure validation used mechanically generated candidate faults for compilation, warnings, API shape, include ownership, functional behavior, relational semantics, sanitizer safety, and Clang portability. Separate evidence controls changed protected tests, removed the compiler, altered feedback, preserved an unsuccessful repair honestly, corrupted bound bytes, used a symlink artifact, and supplied a malformed response with internally consistent harness metadata. This separates a candidate-owned `-1` from an evaluator-owned `INVALID`.

All six API-correct semantic mutants were killed, giving `6/6 (100%)` with no survivor. Each representative source fault reached its intended policy boundary, every protected/evaluator fault became `INVALID`, and honest bad trajectory or response evidence became `-1`. Repeated Policy 6 runs produced identical normalized decisions for both the canonical candidate (`pass`, `+5`) and the unsorted mutant (`fail`, `+1`); timestamps, durations, commands, and temporary paths were excluded from the comparison.

| Policy or control | Controlled fault or invalid condition | Expected | Observed |
|---:|---|---|---|
| 1 | Header syntax error | Candidate `-1` | FAIL: 1A–1E all `-1` |
| 2 | Unused local under strict warnings | Candidate `-1` | FAIL: 2A and 2D `-1`; 2B and 2C correctly remain `+1` |
| 3 | `roster()` returns by value | Candidate `-1` | FAIL: exact-signature kernel 3C `-1` |
| 4 | Missing direct `<vector>` include | Candidate `-1` | FAIL: 4A–4C `-1` |
| 5–6 | Six API-correct semantic mutants | Every non-equivalent mutant rejected | KILLED `6/6 (100%)`; semantic receipt-set SHA-256 `c94b4d9f…` |
| 7 | Delivered feedback changed | Candidate/evidence `-1` | FAIL: 7B `-1` |
| 7 | Valid evidence reports no repair | Candidate/evidence `-1` | FAIL: 7D and 7E `-1` |
| 7 | Bound hash corruption or symlink artifact | `INVALID` | INVALID: affected evidence kernels never become candidate `-1` |
| 8 | Honest malformed Aider response | Candidate/evidence `-1` | FAIL: 8A–8D `-1`; internally consistent 8E–8F remain `+1` |
| 8 | Response bytes changed without hash update | `INVALID` | INVALID during integrity preflight |
| 9 | Heap out-of-bounds write | Candidate `-1` | FAIL: ASan/safety kernels 9A, 9C, and 9D `-1`; UBSan-only 9B remains `+1` |
| 10 | Controlled Clang rejection | Candidate `-1` | FAIL: 10A–10D `-1` |
| Evaluator ownership | Missing compiler or changed protected official test | `INVALID` | Both controls are INVALID with exact preflight reasons |
| Output ownership | Output path inside any immutable input tree | Exit 2 with no write | PASS: all three input trees remained byte-identical |
| Repeatability | Canonical and unsorted Policy 6 reruns | Stable normalized decisions | PASS: both projections are identical |

## Final conclusion

The canonical Grade School package is `READY` as a direct verifier layer for the pinned task. Candidate terminal success must require the authoritative build/API/behavior path, with Policies 5 and 6 mandatory for semantics; Policies 1–4 provide precise shaped failure signals, Policies 7–8 apply only when their authenticated bundles exist, and Policies 9–10 are suitable periodic safety and portability gates. The validation combines frozen hashes, 43/43 positive kernels, a source-shape-preserving metamorphic control, 120 equivalent assertions, a 100% sampled semantic mutation kill ratio, evaluator-fault separation, no-write input isolation, and deterministic reruns.

This does not prove rejection of every imaginable faulty program, and it does not claim excluded duplicate or non-positive-grade behavior. Live reward-worker invocation is also still a separate integration check. The mandatory Strange workflow is: `strange` freezes the task and builds policies, `strange-validate-verifiers` runs positive, mutation, metamorphic, `INVALID`, and repeatability controls, and `strange-build-validation-reports` records the evidence and readiness decision here.
