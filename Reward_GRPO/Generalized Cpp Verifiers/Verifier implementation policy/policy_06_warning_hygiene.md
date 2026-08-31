# Policy G06 — Warning Hygiene Classification

## Purpose

Translate strict-build compiler output into structured, actionable finding classes so the reward signal and feedback name the exact hygiene defect instead of a generic compile error.

| Kernel | Question | `+1` | `-1` | `INVALID` |
|---|---|---|---|---|
| G06-A | Is the strict stage-1 compile free of error-severity diagnostics? | Clean compile, zero error diagnostics | One or more diagnostics, each classified with a fix hint | Build engine unavailable |

## Shared method

The stage-1 compile is run and its diagnostics parsed into classes: unused-parameter, unused-variable, unused-function, missing-include (with standard-symbol header inference), sign-compare, return-local-addr, shadow, constexpr-not-literal, private-access, tautological-compare, undeclared-identifier, missing-member, other. Each finding carries `{class, file, line, symbol, fix_hint}`; the first finding is the root cause when cascades follow.

## Aggregation

Single-kernel policy; the class distribution is reported in facts. Warning-free-but-failing builds are distinguished from warning-driven failures.

## Execution

`python verifier_06_warning_hygiene.py --candidate-dir TASK --manifest MANIFEST --expected-manifest-sha256 DIGEST --output-dir OUT`

## Evidence

The committed compact controls cover a clean log, missing `<cstdint>`, and an injected unused-parameter diagnostic.
