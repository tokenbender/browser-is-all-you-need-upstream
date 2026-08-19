# Policy 09: Memory and undefined-behavior safety

## Purpose

Detect invalid iterator arithmetic, out-of-bounds reads, use-after-lifetime behavior, crashes, and undefined behavior in official and generated workloads.

## Kernels

| ID | Function | Claim |
|---|---|---|
| 9a | `verify_9a_address_sanitizer` | Official and generated workloads are ASan-clean |
| 9b | `verify_9b_undefined_behavior_sanitizer` | Official and generated workloads are UBSan-clean |
| 9c | `verify_9c_repeated_sanitized_stress` | Repeated long-prefix, empty, overlap, and false-start cases remain clean |

## Execution

Sanitizer reports, signals, candidate crashes, or candidate timeouts after a healthy control are `-1`. Unsupported sanitizers or failing controls are `INVALID`.

## Exclusions and aggregation

TSAN, contention, locks, and thread counts are excluded because Sublist has no concurrency contract. The three applicable kernels have maximum sum `3`.

## Command

`python3 verifier_09_memory_undefined_behavior_safety.py --candidate-dir EXERCISE --output-dir OUTPUT`
