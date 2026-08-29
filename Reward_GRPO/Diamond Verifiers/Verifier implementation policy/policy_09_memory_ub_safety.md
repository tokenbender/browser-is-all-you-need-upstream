# Policy 9 — Memory and Undefined-Behavior Safety

Policy 9 runs independent AddressSanitizer and UndefinedBehaviorSanitizer checks over the official and full A-Z workloads, with libstdc++ bounds assertions enabled.

## Kernel table

| Kernel | Function | Verification | `+1` | `-1` | Evidence |
|---|---|---|---|---|---|
| 9A | `verify_9a_asan_official()` | ASan/LSan official suite | 5/5 and no report | Candidate failure, report, crash, timeout | Build/run logs and binary hash |
| 9B | `verify_9b_asan_full_domain()` | ASan A-Z oracle | 26/26 and no report | Wrong result or sanitizer failure | Probe and logs |
| 9C | `verify_9c_ubsan_official()` | UBSan official suite, no recovery | 5/5 and no report | Candidate failure or UB | Build/run logs and binary hash |
| 9D | `verify_9d_ubsan_full_domain()` | UBSan A-Z oracle | 26/26 and no report | Wrong result or UB | Probe and logs |

## Method and aggregation

Harmless sanitizer runtime preflights run before candidate scoring. Full pass is `+4`; unsupported sanitizer infrastructure is `INVALID`.

## Exclusions

TSAN and contention stress are excluded because Diamond has no concurrency contract. Invalid-character inputs are excluded.

## Execution

```bash
python3 "Reward_GRPO/Diamond Verifiers/verifiers/verifier_09_memory_ub_safety.py" --exercise-dir <diamond> --output-dir <new-output>
```
