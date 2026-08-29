# Policy G01 — Structural API Gate

## Purpose

Verify, before any compilation, that the candidate declares every symbol the official test references — existence, namespace placement, template shape, and member visibility.

| Kernel | Question | `+1` | `-1` | `INVALID` |
|---|---|---|---|---|
| G01-A | Does the candidate declare every test-referenced symbol? | All required symbols declared with correct namespace/shape/visibility | One or more required symbols missing, misdeclared, or wrong visibility | Manifest, fixture, or candidate unusable |

## Shared method

Required symbols are derived from the official test file itself (qualified `ns::Ident` usages); nothing is task-specific in the verifier. The candidate is parsed with a comment-stripping structural parser (namespace tracking, access-section tracking, template detection). Feedback names the exact missing/mismatched symbol.

## Aggregation

Single-kernel policy. A symbol defect is a model failure (`-1`); unusable inputs are `INVALID` and never model failure.

## Execution

`python verifier_01_structural_api_gate.py --candidate-dir TASK --manifest MANIFEST --expected-manifest-sha256 DIGEST --output-dir OUT`

## Evidence

The committed self-check matrix covers a passing reference plus missing-namespace fault and tamper controls; `tests/test_generalized_cpp_verifiers.py` executes it from a clean checkout.
