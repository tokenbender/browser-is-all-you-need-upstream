# Policy 1 — Build, Compilation, and Linking Integrity

Policy 1 decides whether the pinned Grade School candidate can be compiled by GCC 13.3, consumed by the official and external callers, linked, and reproduced through the protected CMake target. Every kernel is equal: `+1` is a proven pass, `-1` is a candidate-owned failure, and evaluator failure is `INVALID`.

## Kernel table

| Kernel | Verifier function | Exact question | `+1` | `-1` | Evidence |
|---|---|---|---|---|---|
| 1A | `verify_1a_implementation_compile()` | Does `grade_school.cpp` compile as strict C++17? | Object produced | Candidate compile error or timeout | Command, logs, object hash |
| 1B | `verify_1b_official_consumer_compile()` | Does the complete official caller compile? | Test object produced | Candidate declarations reject the caller | Test hash, macro, logs |
| 1C | `verify_1c_external_consumer_compile()` | Does an independent API consumer compile? | Consumer object produced | Public API cannot be consumed | Probe and logs |
| 1D | `verify_1d_external_consumer_link()` | Do candidate definitions link with that consumer? | Executable produced | Missing or incompatible symbol | Link log and executable hash |
| 1E | `verify_1e_clean_cmake_build()` | Does a fresh protected CMake build produce `grade-school`? | Target builds | Candidate configure/build failure | Configure/build logs |

## Shared method

Preflight validates the candidate files, GCC 13.3, protected hashes, new output directory, and source immutability. Commands use argument arrays and write only to the output directory. CMake is configured with `-DEXERCISM_RUN_ALL_TESTS=ON`.

## Aggregation

The range is `-5` to `+5`; full pass is `+5`. `INVALID` cancels the policy. A compile failure may also be observed by Policy 3 without becoming a second root cause.

## Explicit exclusions

- No functional assertion is judged here.
- Exact signature identity belongs to Policy 3.
- Missing compiler or changed protected build files are `INVALID`.

## Execution

```bash
python3 "Reward_GRPO/Grade_School Verifiers/verifiers/verifier_01_build_compile_link_integrity.py" --exercise-dir <grade-school> --output-dir <new-empty-output> --compiler g++
```
