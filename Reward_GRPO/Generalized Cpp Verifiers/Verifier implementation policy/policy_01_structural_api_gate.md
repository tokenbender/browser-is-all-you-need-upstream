# Policy G01 — Structural API Gate

## Purpose

Verify, before any compilation, that the candidate declares every symbol the official test references — existence, namespace placement, template shape, and member visibility.

| Kernel | Question | `+1` | `-1` | `INVALID` |
|---|---|---|---|---|
| G01-1 | Does the candidate declare every test-referenced symbol? | All required symbols declared with correct namespace/shape/visibility | One or more required symbols missing, misdeclared, or wrong visibility | Manifest, fixture, or candidate unusable |

## Shared method

Required symbols are derived from the official test file itself (qualified `ns::Ident` usages); nothing is task-specific in the verifier. The candidate is parsed with a comment-stripping structural parser (namespace tracking, access-section tracking, template detection). Feedback names the exact missing/mismatched symbol.

## Aggregation

Single-kernel policy. A symbol defect is a model failure (`-1`); unusable inputs are `INVALID` and never model failure.

## Execution

`python verifier_01_structural_api_gate.py --candidate-dir TASK --manifest MANIFEST --expected-manifest-sha256 DIGEST --output-dir OUT`

## Evidence boundary

The previous release cited the following historical evidence (not bundled or
revalidated by this focused PR):

> `generalized_verifier_docs/validation/VALIDATION.md` (catches recorded failures on 5 tasks; zero false positives on 6 reference solutions).

For current implementation checks, run the repository's hermetic
`generalized_verifier_docs/validation/self_check.py` and
`tests/test_generalized_cpp_reward_reliability.py`. Synthetic local checks do not
establish those historical counts or full benchmark/task coverage.
