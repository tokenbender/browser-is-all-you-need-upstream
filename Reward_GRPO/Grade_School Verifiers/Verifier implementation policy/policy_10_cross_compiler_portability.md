# Policy 10 — Cross-Compiler Portability

Policy 10 decides whether the same candidate compiles, links, and passes the complete suite under Clang without compiler-specific source changes.

## Kernel table

| Kernel | Verifier function | Exact question | `+1` | `-1` | Evidence |
|---|---|---|---|---|---|
| 10A | `verify_10a_clang_strict_compile()` | Does candidate-controlled code compile warning-clean under Clang C++17? | Strict compile succeeds | Clang rejects candidate | Identity and logs |
| 10B | `verify_10b_clang_api_link()` | Does the exact API consumer compile and link? | Executable produced | API or symbol failure | Probe and link log |
| 10C | `verify_10c_clang_official_suite()` | Do all eight official tests pass? | 8/8, exit 0 | Assertion, crash, or candidate timeout | Test log |
| 10D | `verify_10d_clean_reproduction()` | Does a second fresh build reproduce normalized compile/link/test results? | Same successful statuses | Candidate nondeterminism | Independent run logs |

## Aggregation

The range is `-4` to `+4`; full pass is `+4`. Missing or unusable Clang is `INVALID`.

## Explicit exclusions

- Binary hashes and GCC/Clang diagnostic wording need not match.
- AppleClang is useful external evidence but not mandatory.
- Docker and infrastructure changes are not required.
- Private implementation style is unrestricted.

## Execution

```bash
python3 "Reward_GRPO/Grade_School Verifiers/verifiers/verifier_10_cross_compiler_portability.py" --exercise-dir <grade-school> --output-dir <new-empty-output> --compiler clang++
```
