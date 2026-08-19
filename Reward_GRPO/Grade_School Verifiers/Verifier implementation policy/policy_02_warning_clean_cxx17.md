# Policy 2 — Warning-Clean C++17 Build

Policy 2 decides whether candidate-controlled Grade School code is warning-clean under the pinned strict GCC contract. It isolates three warning families and then proves the combined warning-as-error build.

## Kernel table

| Kernel | Verifier function | Exact question | `+1` | `-1` | Evidence |
|---|---|---|---|---|---|
| 2A | `verify_2a_wall()` | Is header and implementation compilation clean under `-Wall`? | Exit 0 with no warning | Candidate warning or compile failure | Diagnostic logs |
| 2B | `verify_2b_wextra()` | Is it clean under `-Wextra`? | Exit 0 with no warning | Candidate warning or compile failure | Diagnostic logs |
| 2C | `verify_2c_wpedantic()` | Is it clean under `-Wpedantic`? | Exit 0 with no warning | Candidate warning, extension, or compile failure | Diagnostic logs |
| 2D | `verify_2d_combined_werror_build()` | Does a fresh build pass with all three families and `-Werror`? | Target builds | Candidate diagnostic stops build | Configure/build logs |

## Shared method

Each isolated kernel compiles a generated header consumer together with the implementation. Policy 2 uses GCC 13.3 and the same protected-asset and immutability preflight as Policy 1.

## Aggregation

The range is `-4` to `+4`; full pass is `+4`. `INVALID` cancels the policy.

## Explicit exclusions

- The protected CMake deprecation warning is evaluator output and is ignored.
- No unpinned families such as `-Wconversion` are introduced.
- Runtime and semantic correctness are not judged.

## Execution

```bash
python3 "Reward_GRPO/Grade_School Verifiers/verifiers/verifier_02_warning_clean_cxx17.py" --exercise-dir <grade-school> --output-dir <new-empty-output> --compiler g++
```
