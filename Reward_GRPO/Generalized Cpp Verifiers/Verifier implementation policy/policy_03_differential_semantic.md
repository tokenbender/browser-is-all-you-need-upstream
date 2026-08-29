# Policy G03 — Differential Semantic

## Purpose

Score functional behavior as a fraction of official assertions passed, controlled against the task's own reference implementation, instead of an all-or-nothing test verdict.

| Kernel | Question | `+1` | `-1` | `INVALID` |
|---|---|---|---|---|
| G03-A | Does the candidate pass the full official suite under reference control? | 100% assertions, reference control clean | Assertion fraction below 100% (per-case facts reported) | Reference missing/broken or fixture unusable |

## Shared method

The fixture reference (`.meta/example.*`) is built and run first as a positive control; a reference below 100% marks the task package broken and yields `INVALID`, never a candidate penalty. The candidate's Catch2 summary is parsed into `passed/total` assertions; the fraction is reported in facts for partial-credit reward projection.

## Aggregation

Single kernel with a fractional fact channel. Semantic shortfalls are model failures (`-1`) with the exact failing assertions named; control failures are `INVALID`.

## Execution

`python verifier_03_differential_semantic.py --candidate-dir TASK --manifest MANIFEST --expected-manifest-sha256 DIGEST --output-dir OUT` (requires `fixture_dir` in the manifest)

## Evidence

`generalized_verifier_docs/validation/VALIDATION.md` (recorded echo/plaintext candidate scored 0.625 with the exact failing cases; references score 1.0).
