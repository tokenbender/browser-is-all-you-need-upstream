# Policy 9 — Concurrency, Ownership, Memory, and Undefined-Behavior Safety

Policy 9 answers whether Bank Account remains safe under memory sanitizers and concurrent transaction pressure. It uses separate ASan, UBSan, TSAN, and ordinary stress executables so one sanitizer runtime cannot contaminate another result.

All four conditions apply and use equal binary kernels. A clean run is `+1`, a candidate memory, undefined-behavior, race, deadlock, crash, timeout, or wrong-balance result is `-1`, and unavailable or broken sanitizer infrastructure is `INVALID`.

## Kernel table

| Kernel | Verifier function | What it asks | Exact implementation | `+1` condition | `-1` condition | Evidence |
|---|---|---|---|---|---|---|
| 9A | `verify_9a_asan()` | Does the complete Bank Account suite remain memory-safe? | Build all 17 official tests separately with GCC AddressSanitizer and leak detection, then run them | Suite exits 0 with no AddressSanitizer or LeakSanitizer report | Candidate compile failure, memory report, leak, crash, or timeout | ASan build/run logs, binary hash, test hash |
| 9B | `verify_9b_ubsan()` | Does the complete suite avoid undefined behavior? | Build all 17 tests separately with UBSan and recovery disabled, then run them | Suite exits 0 with no UBSan runtime error | Candidate compile failure, UB report, crash, or timeout | UBSan build/run logs, binary hash, test hash |
| 9C | `verify_9c_tsan()` | Are deposits, withdrawals, and balance reads race-free? | Build a focused concurrent probe with ThreadSanitizer and run it with ASLR disabled through `setarch` | Exact final balance, exit 0, and no ThreadSanitizer report | Data race, deadlock, wrong balance, crash, or timeout | TSAN probe, build/run logs, binary hash |
| 9D | `verify_9d_contention_stress()` | Does the account stay correct across repeated high-contention schedules? | Build one optimized probe and run 12 deterministic schedules with 24 threads and 500 transaction loops per thread | Every run prints the exact expected balance and exits 0 | Any wrong result, exception, deadlock, crash, timeout, or inconsistent output | Stress probe, 12 run logs, seeds, operation counts |

## Shared verification method

The verifier first confirms GNU GCC 13.3, the pinned 17-test assets, `setarch`, and harmless ASan, UBSan, and TSAN compiler/runtime probes. A failed harmless probe is evaluator infrastructure failure and makes Policy 9 `INVALID` before candidate code is scored.

Every candidate executable is built from the same source digest using C++17, strict warnings, pthread support, and a new output path. The ASan build downgrades only GCC 13's `maybe-uninitialized` warning because the pinned Catch header triggers a sanitizer-specific standard-library false positive; Policy 2 remains the warning-clean gate. Commands, return codes, timeouts, environment controls, logs, source hashes, probe hashes, and executable hashes are written to `verification_receipt.json`.

## 9A — AddressSanitizer

The function compiles `bank_account.cpp`, the pinned official test file, and Catch main using `-fsanitize=address`, debug information, and frame pointers. It runs the resulting 17-test executable with immediate failure and leak detection enabled.

It returns `+1` only when compilation and execution exit zero and logs contain no AddressSanitizer or LeakSanitizer marker. Candidate memory corruption, invalid access, leak, crash, or timeout returns `-1`; an ASan runtime that cannot execute the harmless preflight is `INVALID`.

## 9B — UndefinedBehaviorSanitizer

The function rebuilds the same official suite in a separate directory using `-fsanitize=undefined` and `-fno-sanitize-recover=all`. It does not reuse ASan objects or binaries.

It returns `+1` only when the complete suite exits zero without a `runtime error` or UndefinedBehaviorSanitizer report. Candidate UB, compiler failure, crash, or timeout returns `-1`; a broken UBSan preflight is `INVALID`.

## 9C — ThreadSanitizer

The focused probe opens one account, then launches 16 threads. Each thread performs 250 positive deposit/withdraw pairs and occasional balance reads; the known final balance is checked after all threads join.

It returns `+1` when the TSAN executable exits zero, prints the expected marker, and reports no race or fatal runtime error. Concurrent `open()` and `close()` are not tested because the parent contract requires parallel transactions but does not clearly require lifecycle calls to race with transactions.

## 9D — Repeated contention stress

The optimized stress probe launches 24 threads, and each performs 500 mixed deposit, withdrawal, balance-read, and scheduler-yield operations. A command-line seed changes yield placement without changing the expected mathematical result.

It returns `+1` only when all 12 seeds finish within the per-run timeout and print the same exact final-balance marker. This catches lost updates, intermittent deadlocks, unhandled transaction errors, and schedule-sensitive corruption even when a sanitizer does not reproduce them.

## Aggregation

```text
Policy 9 kernel sum = 9A + 9B + 9C + 9D
Range               = -4 to +4
Full pass           = +4
```

Any applicable `INVALID` kernel cancels the policy sum and exits 2. A valid full pass exits 0, and a valid result containing any `-1` exits 1.

## Execution

```bash
python3 "Bank_Account Verifiers/verifiers/verifier_09_concurrency_memory_ub_safety.py" \
  --exercise-dir <bank-account-directory> \
  --output-dir <new-empty-receipt-directory> \
  --compiler g++ \
  --setarch setarch
```

The output directory receives the three sanitizer builds, the optimized stress build, all runtime logs, and `verification_receipt.json`.
