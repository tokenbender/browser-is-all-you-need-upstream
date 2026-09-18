# Policy G06 — Warning Hygiene Classification

## Purpose

Translate strict-build compiler output into structured, actionable finding classes so the reward signal and feedback name the exact hygiene defect instead of a generic compile error.

| Kernel | Question | `+1` | `-1` | `INVALID` |
|---|---|---|---|---|
| G06-1 | Does the candidate compile under strict flags? | Compile exit 0 | Candidate compile failure | Compiler/tool infrastructure failure |
| G06-2 | Are classified diagnostics free of errors? | Classifier PASS | Classified error findings | Classifier unavailable or invalid report |

## Shared method

The stage-1 compile is run and its diagnostics parsed into classes: unused-parameter, unused-variable, unused-function, missing-include (with standard-symbol header inference), sign-compare, return-local-addr, shadow, constexpr-not-literal, private-access, tautological-compare, undeclared-identifier, missing-member, other. Each finding carries `{class, file, line, symbol, fix_hint}`; the first finding is the root cause when cascades follow.

## Aggregation

Two diagnostic kernels report compile status and classified hygiene separately; class distribution remains in facts. Tool failures are INVALID, not hygiene penalties. Warning-free-but-failing builds are distinguished from warning-driven failures.

## Execution

`python verifier_06_warning_hygiene.py --candidate-dir TASK --manifest MANIFEST --expected-manifest-sha256 DIGEST --output-dir OUT`

## Evidence boundary

The previous release cited the following historical evidence (not bundled or
revalidated by this focused PR):

> `generalized_verifier_docs/validation/VALIDATION_07.md` (16/16 recorded cases classified correctly across 9 tasks; known-good builds pass with zero false positives).

For current implementation checks, run the repository's hermetic
`generalized_verifier_docs/validation/self_check.py` and
`tests/test_generalized_cpp_reward_reliability.py`. Synthetic local checks do not
establish those historical counts or full benchmark/task coverage.
