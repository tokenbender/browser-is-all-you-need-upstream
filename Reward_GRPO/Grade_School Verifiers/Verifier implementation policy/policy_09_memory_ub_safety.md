# Policy 9 — Memory and Undefined-Behavior Safety

Policy 9 decides whether official and generated Grade School operations remain free of ASan and UBSan findings. Each sanitizer is proven usable with a known-good runtime probe before candidate scoring.

## Kernel table

| Kernel | Verifier function | Exact question | `+1` | `-1` | Evidence |
|---|---|---|---|---|---|
| 9A | `verify_9a_asan_official()` | Does the 8-test suite pass under ASan? | 8/8, no report | Candidate compile/run/report failure | Sanitizer logs |
| 9B | `verify_9b_ubsan_official()` | Does it pass under UBSan? | 8/8, no report | Candidate compile/run/report failure | Sanitizer logs |
| 9C | `verify_9c_combined_semantic_oracle()` | Does the generated oracle pass under combined ASan+UBSan? | All checkpoints, no report | Mismatch or report | Probe and logs |
| 9D | `verify_9d_repeated_sanitized_stress()` | Are 100 fresh schools with 128 additions stable across three executions? | Three clean passes | Finding, inconsistency, crash, or timeout | Three run receipts |

## Aggregation

The range is `-4` to `+4`; full pass is `+4`. Unavailable or broken sanitizer support is `INVALID`.

## Explicit exclusions

- TSAN, contention, and thread-safety checks are inapplicable.
- Leak detection is disabled for cross-host stability.
- Duplicate and invalid-grade semantics are excluded.
- No performance score is produced.

## Execution

```bash
python3 "Reward_GRPO/Grade_School Verifiers/verifiers/verifier_09_memory_ub_safety.py" --exercise-dir <grade-school> --output-dir <new-empty-output> --compiler g++
```
