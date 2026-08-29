# Policy 6 — Roster State and Relational Semantics

Policy 6 compares candidate observations with an independent ordered-school model. It covers the observed flattened roster, lookup mutation, and insertion-order defects beyond the eight fixed examples.

## Kernel table

| Kernel | Verifier function | Exact question | `+1` | `-1` | Evidence |
|---|---|---|---|---|---|
| 6A | `verify_6a_exact_state_shape()` | Do empty, single-add, and multi-grade states have exact map shape? | Expected maps match | Wrong partition or observation | Probe/run logs |
| 6B | `verify_6b_numeric_and_alphabetical_order()` | Are numeric grades and names ordered regardless of insertion? | Exact ordered result | Wrong order | Probe/run logs |
| 6C | `verify_6c_missing_grade_nonmutation()` | Is a missing grade empty and state-preserving? | Empty result and unchanged roster | Lookup inserts or mutates | Before/after probe |
| 6D | `verify_6d_grade_roster_consistency()` | Do repeated `grade()` views equal roster entries? | All repeated comparisons match | Inconsistent or unstable view | Probe/run logs |
| 6E | `verify_6e_generated_oracle()` | Do 128 deterministic unique additions match the oracle after every checkpoint? | All checkpoints match | First mismatch, crash, or timeout | Seed, probe, logs |

## Generated oracle

The fixed seed is `0x47524144`, grades are `1, 2, 3, 10, 11`, and names are `student_000` through `student_127` in a deterministic shuffle.

## Aggregation

The range is `-5` to `+5`; full pass is `+5`. `INVALID` cancels the policy.

## Explicit exclusions

- Duplicate names, cross-grade duplicate identity, zero grades, and negative grades are not generated.
- Private containers and algorithms are unrestricted.
- No performance score is produced.

## Execution

```bash
python3 "Reward_GRPO/Grade_School Verifiers/verifiers/verifier_06_roster_state_relational_semantics.py" --exercise-dir <grade-school> --output-dir <new-empty-output> --compiler g++
```
