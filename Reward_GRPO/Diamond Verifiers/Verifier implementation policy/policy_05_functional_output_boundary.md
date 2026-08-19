# Policy 5 — Complete Official Functional Behavior

Policy 5 proves agreement with the complete pinned five-test parent benchmark and checks deterministic repetition.

## Kernel table

| Kernel | Function | Verification | `+1` | `-1` | Evidence |
|---|---|---|---|---|---|
| 5A | `verify_5a_official_build()` | Independently build the official executable | Executable produced | Candidate compile/link failure | Build log and binary hash |
| 5B | `verify_5b_official_test_inventory()` | Run `--list-tests` | Exactly five expected cases | Not used; wrong fixed inventory is `INVALID` | Inventory log and parsed names |
| 5C | `verify_5c_official_tests()` | Run complete official suite | 5 cases and 5 assertions pass | Assertion failure, crash, or candidate timeout | Complete test log |
| 5D | `verify_5d_deterministic_repetition()` | Run identical binary ten times | Byte-identical successful output | Difference, failure, crash, or timeout | Per-run output hashes |

## Method and aggregation

The suite is built with authenticated tests, Catch main, C++17, and strict warnings. Full pass is `+4`.

## Exclusions

This policy reports parent-suite agreement; property-level diagnosis belongs to Policy 6. A changed test inventory is `INVALID`.

## Execution

```bash
python3 "Reward_GRPO/Diamond Verifiers/verifiers/verifier_05_functional_output_boundary.py" --exercise-dir <diamond> --output-dir <new-output>
```
