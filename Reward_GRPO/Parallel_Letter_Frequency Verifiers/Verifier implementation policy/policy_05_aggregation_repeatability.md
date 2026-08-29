# Policy 5: Aggregation and repeatability

Parallel implementations can produce correct small answers while losing updates on larger batches. This policy checks partition aggregation and repeated deterministic results without requiring a particular threading library.

| Kernel | Binary pass condition | Evidence |
|---|---|---|
| 5A | Counts from empty and uneven input partitions merge exactly once. | Probe compile/run logs and hashes |
| 5B | A large many-text workload matches an independently constructed oracle. | Probe compile/run logs and hashes |
| 5C | Repeating the same workload 25 times returns the identical complete map. | Probe compile/run logs and hashes |

These are behavior and stress checks, not proof that threads were created. ThreadSanitizer remains a periodic safety boundary rather than a fast per-sample GRPO kernel.

Each kernel returns `+1/-1`; evaluator failures are `INVALID`.

## Run

    python3 verifiers/verifier_05_aggregation_repeatability.py --exercise-dir TASK --output-dir NEW_EMPTY_DIR
