# Policy 5 — Complete Official Functional Behavior

Policy 5 decides whether the candidate passes the complete pinned Grade School suite, not the single default test. The official executable must contain exactly eight expected test names and produce stable 8/8 results.

## Kernel table

| Kernel | Verifier function | Exact question | `+1` | `-1` | Evidence |
|---|---|---|---|---|---|
| 5A | `verify_5a_complete_test_selection()` | Are exactly the eight pinned tests selected? | Expected name set and count | Candidate prevents valid selection after build | List output and hash |
| 5B | `verify_5b_official_suite()` | Do all eight official tests pass? | 8/8 and exit 0 | Assertion, candidate crash, or timeout | Test log and exit code |
| 5C | `verify_5c_deterministic_repetition()` | Does the full result repeat three times? | Three 8/8 passes | Any differing or failed candidate outcome | Three run receipts |

## Shared method

Every kernel builds its own executable with `EXERCISM_RUN_ALL_TESTS` defined. The protected test hash and expected test-name set prevent a partial suite from becoming a pass.

## Aggregation

The range is `-3` to `+3`; full pass is `+3`. `INVALID` cancels the policy.

## Explicit exclusions

- No ninth duplicate-student test is invented.
- Sanitizer findings belong to Policy 9.
- Runtime duration differences do not count as nondeterminism when outcomes agree.

## Execution

```bash
python3 "Reward_GRPO/Grade_School Verifiers/verifiers/verifier_05_official_functional_behavior.py" --exercise-dir <grade-school> --output-dir <new-empty-output> --compiler g++
```
