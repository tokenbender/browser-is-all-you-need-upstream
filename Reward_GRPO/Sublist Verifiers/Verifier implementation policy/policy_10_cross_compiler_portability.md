# Policy 10: Cross-compiler portability

## Purpose

Prove that the candidate honors C++17 and the strict contract under an independent Clang frontend, linker, and clean staging tree.

## Kernels

| ID | Function | Claim |
|---|---|---|
| 10a | `verify_10a_clang_warning_clean_compile` | Candidate and API probes compile warning-clean with Clang |
| 10b | `verify_10b_clang_link_and_official_tests` | Clang links and passes all 18 official tests |
| 10c | `verify_10c_clean_secondary_reproduction` | A fresh staged Clang build reproduces the result and artifacts |

## Execution

Candidate-specific Clang diagnostics or assertions are `-1`. Missing Clang, corrupt fixtures, or unusable runtime support are `INVALID`.

## Exclusions and aggregation

MSVC and AppleClang are corroborating but not mandatory local tools. All three kernels apply with maximum sum `3`.

## Command

`python3 verifier_10_cross_compiler_portability.py --candidate-dir EXERCISE --output-dir OUTPUT`
