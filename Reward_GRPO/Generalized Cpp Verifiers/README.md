# Generalized Cpp Verifiers

A seven-verifier pack for the direct global C++ verifier runner.  Each wrapper
in `verifiers/` adapts the runner's four-argument contract to one task-agnostic
verifier engine in the repository's `generalized_verifier_docs/` directory, and
writes a schema-version-2 `verification_receipt.json` bound by sha256 to the
manifest, the wrapper, this pack's common module and schema, and the candidate
source (before/after).

## Layout

```
Generalized Cpp Verifiers/
  verifiers/
    _global_common.py                  shared receipt/binding/engine helpers
    _manifest_validation.py            validate_manifest() used by the runner
    verifier_01_structural_api_gate.py G01: required API from the official test
    verifier_02_two_stage_build.py     G02: compile-error vs link-error build
    verifier_03_differential_semantic.py G03: reference control + authenticated completion
    verifier_04_response_integrity.py  G04: OK / EMPTY / LOOP / TRUNCATED
    verifier_05_candidate_boundary.py  G05: editable-set boundary + reconstruction
    verifier_06_warning_hygiene.py     G06: stage-1 diagnostics classification
    verifier_07_safety.py              G07: ASan/UBSan safety diagnosis
  global_verifier_manifest.schema.json manifest schema (hashed by the runner)
  generalized_verifier_manifest.example.json
  README.md
```

## Manifest fields

Same shape as the standard global manifest, extended with:

- `fixture_dir` — task fixture directory holding exactly one
  `<stem>_test.cpp`, a `test/` harness (`tests-main.cpp`, `catch.hpp`) and
  `.meta/example.h` (plus optional `.meta/example.cpp`).  Required by G01,
  G02, G03, G06 and G07; G03 turns a missing/broken reference into an `invalid`
  verdict, never a candidate-blaming fail.
- `trajectory.turns[*].response_file` / `response_text` — the raw model
  response for G04/G05.  The last turn carrying either field wins; the same
  fields at manifest top level are the fallback.  Without a response,
  G04/G05 return `invalid` with a precise reason.
- `policies` — keyed by policy id; each policy the runner requests (G02.. for
  the chosen profile) must be present as a key.  Entries are advisory.

## Running with the standard runner

The direct runner resolves the pack as `<reward-root>/Generalized Cpp Verifiers`,
so when assembling a reward root place (or copy) this pack under that
directory name, alongside `global_cpp_verifier_runner.py` and the
`generalized_verifier_docs/` engines:

```
python3 global_cpp_verifier_runner.py \
  --candidate-dir /path/to/candidate \
  --manifest /path/to/manifest.json \
  --expected-manifest-sha256 <64-hex> \
  --output-dir /path/to/empty-output \
  --reward-root /path/to/reward-root \
  --profile live
```

Exit code 0 = pass, 1 = fail, 2 = invalid; the aggregate receipt lands in
`<output-dir>/global_cpp_verification_receipt.json`.

Profiles: `live` executes the semantic policies G01–G05. The `full` profile
also executes the diagnostic policies G06–G07. Every wrapper supports the
same four-argument CLI and can also be invoked directly.

## Verdict behavior

| Wrapper | Pass | Fail | Invalid |
|---|---|---|---|
| G01 structural | all test-derived symbols declared | any missing/misdeclared | manifest/fixture/candidate unusable |
| G02 two-stage build | both stages clean | CE-1 / CE-2 / LE | build engine cannot run |
| G03 differential | healthy reference, witnessed official-main return, successful process and complete passing assertions | failed/incomplete candidate execution | broken reference, launch failure or invalid execution evidence |
| G04 response integrity | verdict OK | EMPTY / LOOP / TRUNCATED | no response in manifest |
| G05 boundary | OK / OK_WITH_MODIFICATIONS | FORBIDDEN/DUPLICATE/NO_FILES | no response in manifest |
| G06 warning hygiene | clean stage-1, no error diagnostics | any error-severity diagnostic | build engine cannot run |

## Policy G07 — safety sanitizer diagnosis (diagnostic, appended 2026-08)

`verifiers/verifier_07_safety.py` (engine
`generalized_verifier_docs/08_safety_sanitizer_verifier.py`, policy doc
`Verifier implementation policy/policy_07_safety.md`) registers a seventh
policy: it builds the candidate against the pinned official test with
ASan+UBSan and classifies the dynamic safety outcome (CLEAN / SANITIZER_HIT
with UB kind and first candidate-frame location / CRASH_NO_REPORT /
BUILD_FAIL / TIMEOUT). G07 is a **diagnostic policy, never additive**: G01
owns structure, G02 build, G03 the functional score, G04 response integrity,
G05 boundary, G06 hygiene, and G07 only classifies *why* a crash happened —
every G07 kernel is confined to the diagnostic aggregate and the receipt is
marked `policy_role: "diagnostic"`, so the semantic kernel sum is untouched
(a crash's −1 stays with G03); its unique signal is flagging a functionally
passing candidate that still exhibits UB. Candidates carrying
sanitizer-suppression attributes are INVALID
(`sanitizer_suppression_attempt`): a candidate must not blind the verifier.
Historical portability and benchmark-validation numbers belong to the prior
release evidence, not to this focused code review; the historical
`validation/VALIDATION_08.md` report is not distributed here. No compiler-portability
or benchmark-coverage result is established merely by shipping this pack.

## Execution evidence and local checks

G03-1 owns the healthy reference control; G03-2 owns candidate execution.
The builder wraps official `main` and observes its return through a separate
completion pipe. Stdout assertion counts are untrusted diagnostics/failure
shaping, never sufficient PASS evidence. This is not an isolation boundary
against arbitrary native code in the same process. The reward adapter rechecks
aggregate PASS against reference/candidate execution facts and engine exits.
Timeouts kill the process group and bound output draining and child reaping;
receipts retain diagnostic tails. Compiler/runtime infrastructure failures
remain INVALID, not candidate penalties.

The manifest example is a placeholder template, not a runnable task or a real
digest. Populate its paths, editable files and hashes from authenticated inputs;
G02-G07 keys cover the full profile, and policy values must be arrays.

From repository root, without staged benchmark fixtures or cloud resources:

```bash
uv run python -B generalized_verifier_docs/validation/self_check.py
uv run --extra dev pytest tests/test_generalized_cpp_reward_reliability.py tests/test_generalized_cpp_verifiers.py
```

These commands test synthetic controls and protocol invariants, not full
production task admission. Production registry/manifests/fixtures and sandbox
image preparation remain explicit external prerequisites described in the root README.
