# Policy 05: Official functional classification

## Purpose

Authenticate and execute the complete official suite, then isolate its equality, empty-list, directional, positional, and unequal boundaries.

## Kernels

| ID | Function | Claim |
|---|---|---|
| 5a | `verify_5a_authenticated_official_suite` | Exactly 18 pinned tests pass |
| 5b | `verify_5b_equality_and_empty_boundaries` | Equality and all empty-list directions are correct |
| 5c | `verify_5c_sublist_positions_and_recovery` | Start, middle, end, false-start, and repeated sublists work |
| 5d | `verify_5d_superlist_positions` | Superlist direction and positions work |
| 5e | `verify_5e_unequal_order_and_value_cases` | Gaps, order, and exact integer identity are enforced |
| 5f | `verify_5f_deterministic_official_repetition` | Five fresh official executions agree |

## Execution

Authenticated assertion or candidate-build failures are `-1`. Test hash or inventory failures are `INVALID`. Targeted probes are generated only in the output directory.

## Aggregation

All six kernels apply with maximum sum `6`.

## Command

`python3 verifier_05_official_functional_classification.py --candidate-dir EXERCISE --output-dir OUTPUT`
