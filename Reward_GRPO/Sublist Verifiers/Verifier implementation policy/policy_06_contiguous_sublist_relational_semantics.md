# Policy 06: Contiguous Sublist relational semantics

## Purpose

Use an independent oracle to detect loose subsequences, reversed direction, false-start errors, reordered values, and input mutation beyond the official examples.

## Kernels

| ID | Function | Claim |
|---|---|---|
| 6a | `verify_6a_exhaustive_independent_oracle` | 116,281 ordered pairs over 341 short lists match an independent contiguous oracle |
| 6b | `verify_6b_contiguity_order_and_identity` | Matching is contiguous, ordered, and integer-exact |
| 6c | `verify_6c_false_start_and_repeated_values` | Overlap and false-start recovery are correct |
| 6d | `verify_6d_swap_relations` | Swapping lists preserves equal/unequal and swaps sublist/superlist |
| 6e | `verify_6e_input_preservation_and_repeatability` | Inputs remain unchanged and results are deterministic |

## Execution

The generated oracle uses bounded window comparison and never imports the reference solution. Any mismatch is `-1`; inability to build or run trustworthy probes is `INVALID` unless caused by candidate compilation.

## Aggregation

All five kernels apply with maximum sum `5`.

## Command

`python3 verifier_06_contiguous_sublist_relational_semantics.py --candidate-dir EXERCISE --output-dir OUTPUT`
