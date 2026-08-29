# Policy 4 — Warning-Clean Integer Operations

This policy decides the observed warning boundary: whether candidate integer comparisons remain clean under the pinned GCC warning set. It is derived from a candidate rejected by `-Werror=sign-compare` for comparing `unsigned int` with `const int`.

## Kernel table

| Kernel | Verifier function | What it asks | Exact implementation | `+1` condition | `-1` condition | Evidence |
|---|---|---|---|---|---|---|
| 4A | `verify_4a_sign_compare_diagnostics()` | Does diagnostic compilation emit `-Wsign-compare`? | Compile `allergies.cpp` with GCC JSON diagnostics, `-Wall -Wextra -Wpedantic`, and `-Wno-error` | Compilation succeeds, JSON is parseable, and no signedness warning is present | Candidate emits `-Wsign-compare` or has another candidate compile error | Raw JSON diagnostics, normalized warnings, object hash |
| 4B | `verify_4b_strict_werror_compile()` | Does the implementation survive the pinned warning-as-error boundary? | Compile `allergies.cpp` with `-Wall -Wextra -Wpedantic -Werror` | Compiler exits 0 and creates a nonempty object | Candidate warning or compile error prevents object production | Command, compiler logs, object hash |

## Shared verification method

Preflight requires GNU GCC 13.3 because JSON diagnostic structure and warning option names are compiler-bound. Missing or incompatible compiler support is `INVALID`. The candidate is never modified; all objects and diagnostic streams are stored under the fresh output directory.

## 4A — Signedness diagnostics

The verifier parses GCC's JSON diagnostics rather than searching human-readable text alone. A diagnostic is a signedness failure when its option is `-Wsign-compare`. Malformed JSON or missing diagnostic support is an evaluator failure.

## 4B — Strict compilation

The second compile reproduces the actual `-Werror` boundary. This policy intentionally does not split every possible GCC warning family into a separate kernel because only signedness was established by the inspected error logs.

## Aggregation

```text
applicable kernels = 2
maximum kernel sum = +2
PASS    = both kernels are +1
FAIL    = at least one kernel is -1 and neither is INVALID
INVALID = at least one kernel is INVALID
```

## Execution

```bash
python3 "Reward_GRPO/Allergies Verifiers/verifiers/verifier_04_warning_clean_integer_operations.py" \
  --exercise-dir /path/to/allergies \
  --output-dir /new/output/policy-04
```
