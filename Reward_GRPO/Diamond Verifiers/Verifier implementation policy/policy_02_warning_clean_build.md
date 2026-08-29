# Policy 2 — Warning-Clean Strict Build

Policy 2 isolates warning families and then proves the complete candidate remains clean when warnings are errors.

## Kernel table

| Kernel | Function | Verification | `+1` | `-1` | Evidence |
|---|---|---|---|---|---|
| 2A | `verify_2a_wall()` | Baseline versus `-Wall` GCC JSON diagnostics | No new warning | New warning or candidate compile failure | Diagnostic logs and delta |
| 2B | `verify_2b_wextra()` | `-Wall` versus `-Wall -Wextra` | No new warning | Additional warning or failure | Diagnostic logs and delta |
| 2C | `verify_2c_wpedantic()` | Previous tier versus `-Wpedantic` | No new warning | Extension or pedantic warning | Diagnostic logs and delta |
| 2D | `verify_2d_complete_werror_build()` | Strictly compile implementation, official caller, Catch main, API probe; then link | Complete build succeeds | Candidate warning, error, timeout, or link failure | Logs and artifact hashes |

## Method and aggregation

Protected sources are authenticated before diagnostic comparison. CMake warnings and protected Catch diagnostics are not attributed to the candidate. Full pass is `+4`.

## Exclusions

Ordinary build production belongs to Policy 1. Missing JSON-diagnostic support is `INVALID`.

## Execution

```bash
python3 "Reward_GRPO/Diamond Verifiers/verifiers/verifier_02_warning_clean_build.py" --exercise-dir <diamond> --output-dir <new-output>
```
