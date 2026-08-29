# Generalized Cpp Verifiers

A six-verifier pack for the direct global C++ verifier runner.  Each wrapper
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
    verifier_03_differential_semantic.py G03: reference control + assertion score
    verifier_04_response_integrity.py  G04: OK / EMPTY / LOOP / TRUNCATED
    verifier_05_candidate_boundary.py  G05: editable-set boundary + reconstruction
    verifier_06_warning_hygiene.py     G06: stage-1 diagnostics classification
  global_verifier_manifest.schema.json manifest schema (hashed by the runner)
  generalized_verifier_manifest.example.json
  validation/                          end-to-end run receipts
  README.md
```

## Manifest fields

Same shape as the standard global manifest, extended with:

- `fixture_dir` — task fixture directory holding exactly one
  `<stem>_test.cpp`, a `test/` harness (`tests-main.cpp`, `catch.hpp`) and
  `.meta/example.h` (plus optional `.meta/example.cpp`).  Required by G01,
  G02, G03 and G06; G03 turns a missing/broken reference into an `invalid`
  verdict, never a candidate-blaming fail.
- `trajectory.turns[*].response_file` / `response_text` — the raw model
  response for G04/G05.  The last turn carrying either field wins; the same
  fields at manifest top level are the fallback.  Without a response,
  G04/G05 return `invalid` with a precise reason.
- `policies` — keyed by policy id; each policy the runner requests (G02.. for
  the chosen profile) must be present as a key.  Entries are advisory.

## Running with the standard runner

The direct runner resolves the pack as `<reward-root>/Global Cpp Verifiers`,
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

Profiles: `live` executes G01–G04.  The runner's `full` profile additionally
requests G05 and a G07 wrapper; this pack defines six verifiers (G01–G06), so
it is exercised with `--profile live`, and G05/G06 are invoked directly with
the same four-argument wrapper CLI (see `validation/`).

## Verdict behavior

| Wrapper | Pass | Fail | Invalid |
|---|---|---|---|
| G01 structural | all test-derived symbols declared | any missing/misdeclared | manifest/fixture/candidate unusable |
| G02 two-stage build | both stages clean | CE-1 / CE-2 / LE | build engine cannot run |
| G03 differential | reference OK and candidate 100% | candidate assertion regressions | reference missing or not 100% |
| G04 response integrity | verdict OK | EMPTY / LOOP / TRUNCATED | no response in manifest |
| G05 boundary | OK / OK_WITH_MODIFICATIONS | FORBIDDEN/DUPLICATE/NO_FILES | no response in manifest |
| G06 warning hygiene | clean stage-1, no error diagnostics | any error-severity diagnostic | build engine cannot run |

## Policy G07 — safety sanitizer diagnosis (diagnostic, appended 2026-08)

`verifiers/verifier_07_safety.py` (engine
`generalized_verifier_docs/08_safety_sanitizer_verifier.py`, policy doc
`Verifier implementation policy/policy_07_safety.md`, proof
`generalized_verifier_docs/validation/VALIDATION_08.md`) registers a seventh
policy: it builds the candidate against the pinned official test with
ASan+UBSan and classifies the dynamic safety outcome (CLEAN / SANITIZER_HIT
with UB kind and first candidate-frame location / CRASH_NO_REPORT /
BUILD_FAIL / TIMEOUT). G07 is a **diagnostic policy, never additive**: G01
owns structure, G02 build, G03 the functional score, G04 response integrity,
G05 boundary, G06 hygiene, and G07 only classifies *why* a crash happened —
every G07 kernel carries `kernel: 0` and the receipt is marked
`policy_role: "diagnostic"`, so the semantic kernel sum is untouched (a
crash's −1 stays with G03); its unique signal is flagging a functionally
passing candidate that still exhibits UB. Candidates carrying
sanitizer-suppression attributes are INVALID
(`sanitizer_suppression_attempt`): a candidate must not blind the verifier.
Portability-probe deferral: zero compiler-version-dependent failures exist
in the recorded evidence, eval is gcc-only, and the gcc-11.4-vs-13.3
reproduction found 0/10 dependent cases — a dedicated multi-compiler probe
policy is deferred until multi-compiler eval evidence exists.
