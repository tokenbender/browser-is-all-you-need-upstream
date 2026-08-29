# Policy G07 — Safety Sanitizer Diagnosis (DIAGNOSTIC)

## Purpose

Classify the *dynamic safety* of a candidate that the strict build already accepted: run the candidate against the task's pinned official test under AddressSanitizer + UndefinedBehaviorSanitizer and report the UB/memory-error kind and the first candidate-frame location. This closes a recorded gap: candidates that segfault (or silently invoke UB) under the official test previously surfaced only as an opaque test failure or crash, with no attribution of WHY.

| Kernel | Question | pass (no finding) | fail (safety finding) | `INVALID` |
|---|---|---|---|---|
| G07-1 | Does the candidate run the official test under ASan+UBSan with no sanitizer report and no report-less signal death? | CLEAN, or BUILD_FAIL / TIMEOUT / functional failure (facts only — owned elsewhere) | SANITIZER_HIT (kind + candidate location) or CRASH_NO_REPORT | Candidate carries a sanitizer-suppression attribute (`sanitizer_suppression_attempt`), or engine/fixture unusable |

## Ownership / non-conflict matrix (RULE: diagnostic, never additive)

| Policy | Owns | On a crash/fail |
|---|---|---|
| G01 | structure | missing/misdeclared API |
| G02 | build | CE-1 / CE-2 / LE |
| G03 | functional score | assertion regressions, −1 |
| G04 | response integrity | EMPTY / LOOP / TRUNCATED |
| G05 | boundary | editable-set violations |
| G06 | hygiene | stage-1 diagnostics |
| **G07** | **safety DIAGNOSIS** | classifies WHY (UB kind); **adds no second negative** |

A candidate that crashes or fails functionally already earns its −1 from G03; G07 only classifies the cause. A candidate that *passes functionally yet exhibits UB* is flagged **only** by G07 — that signal is unique to this policy. Mechanically, G07 emits a normal pass/fail kernel inside its own diagnostic receipt and carries `policy_role: "diagnostic"`. The aggregate runner keeps G07 out of `semantic_status`, so it cannot double-count G03; it is reported under `diagnostic_status`. The wrapper exits 1 on a safety finding, 0 for CLEAN and for outcomes owned elsewhere, and 2 only for invalid input.

## Shared method

One sanitized build: `g++ -std=c++17 -Wall -Wextra -Wpedantic -Werror -fsanitize=address,undefined -fno-sanitize-recover=all -DEXERCISM_RUN_ALL_TESTS -g <stem>.cpp <stem>_test.cpp test/tests-main.cpp -pthread`. The instrumented binary runs with `ASAN_OPTIONS=detect_leaks=0` — LeakSanitizer would report the Catch2 harness's own teardown allocations, which the candidate cannot control, so leak noise must not contaminate verdicts; genuine memory errors and UB are unaffected. The verdict comes from dynamic behavior only: the ASan error kind / `SEGV on unknown address` (near-null ⇒ `null-deref`) / UBSan `runtime error` detail / signal death without a report. `candidate_location` is the first stack frame inside a candidate file.

## Anti-exploit control (verifier resistance, not a task requirement)

Before any build, candidate files are scanned (comments stripped, literals blanked) for sanitizer-suppression tokens: `no_sanitize` (all spellings — `__attribute__((no_sanitize...))`, `[[gnu::no_sanitize...]]`, `#pragma GCC … no_sanitize`) and `disable_sanitizer_instrumentation`. A hit is `INVALID` with reason `sanitizer_suppression_attempt`: a candidate must not be able to blind the verifier. This is the only source-text inspection in the policy; it guards verifier integrity and adds no task requirement.

## Aggregation

One normal pass/fail kernel in the diagnostic aggregate. Engine exit-code ownership: nonzero only for safety findings (1) or invalid (2).

## Execution

`python verifier_07_safety.py --candidate-dir TASK --manifest MANIFEST --expected-manifest-sha256 DIGEST --output-dir OUT`

## Evidence

`tests/test_generalized_cpp_verifiers.py` runs G07 with the other six policies and verifies a CLEAN diagnostic receipt under the full profile.
