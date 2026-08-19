# Policy 2 — Warning-Clean Build Verification

Policy 2 answers whether the Bank Account candidate is clean under the benchmark's warning contract. It separates warnings first enabled by `-Wall`, `-Wextra`, and `-Wpedantic`, then performs one complete warning-as-error compile and link without running the behavioral tests.

Every check is an equal binary kernel: verified pass is `+1`, candidate failure is `-1`, and evaluator or toolchain failure is `INVALID`. Policy 2 ranges from `-4` to `+4` and passes only at `+4`; it contains no weights or partial points.

## Kernel table

| Kernel | Verifier function | What it asks | Exact implementation | `+1` condition | `-1` condition | Evidence |
|---|---|---|---|---|---|---|
| 2A | `verify_2a_wall()` | Does `-Wall` introduce a warning? | Compare GCC JSON diagnostics from a baseline compile with diagnostics from the same units compiled using `-Wall` | No new warning appears | One or more `-Wall`-enabled warnings appear, or candidate compilation fails | Baseline and selected JSON diagnostic logs |
| 2B | `verify_2b_wextra()` | Does `-Wextra` add a warning beyond `-Wall`? | Compare `-Wall` diagnostics with `-Wall -Wextra` diagnostics | No new warning appears | One or more additional warnings appear, or candidate compilation fails | Both diagnostic tiers and warning delta |
| 2C | `verify_2c_wpedantic()` | Does `-Wpedantic` add a standards warning? | Compare `-Wall -Wextra` diagnostics with `-Wall -Wextra -Wpedantic` diagnostics | No new warning appears | A VLA, extension, or other new pedantic warning appears, or candidate compilation fails | Both diagnostic tiers and warning delta |
| 2D | `verify_2d_complete_werror_build()` | Does the complete strict build remain warning-free? | Compile implementation, official tests, and Catch main with all three warning groups plus `-Werror`, then link | All units compile and the executable links | A warning, compile error, timeout, or link failure occurs | Full logs plus object and executable digests |

## Shared verification method

Kernels 2A through 2C compile `bank_account.cpp` and a small generated header consumer with GCC's JSON diagnostic output enabled. Each selected warning tier is compared with the tier immediately below it, so a warning already attributed to `-Wall` is not counted again as a new `-Wextra` or `-Wpedantic` warning.

Every receipt records exact commands, return codes, diagnostic log paths, warning options, source digest, and kernel result. The verifier accepts only GNU GCC 13.3; a missing compiler, altered fixed fixture, or unreadable diagnostic stream is `INVALID`, while a candidate compile error is `-1`.

## 2A — `-Wall` warning delta

The function compiles the two candidate-sensitive units once without a warning group and once with `-Wall`. It requests `-fdiagnostics-format=json` and uses a stable fingerprint made from warning kind, option, message, file, line, and column.

It returns `+1` when the `-Wall` run contains no warning absent from the baseline. It returns `-1` when a new warning appears or the candidate cannot be compiled; environment and fixture failures remain `INVALID`.

## 2B — `-Wextra` warning delta

The function compiles the same units using `-Wall` as its baseline and `-Wall -Wextra` as its selected tier. This matters because warnings such as unused parameters require the combined warning groups and are not reliably enabled by `-Wextra` alone.

It returns `+1` when `-Wextra` adds no warning beyond the `-Wall` result. Any additional warning or candidate compile failure returns `-1`, with the exact added warning stored in the receipt.

## 2C — `-Wpedantic` warning delta

The function uses `-Wall -Wextra` as its baseline and adds `-Wpedantic` for the selected compile. This isolates standards-compliance diagnostics such as variable-length arrays or non-standard language extensions.

It returns `+1` when the pedantic tier introduces no new warning. A new standards warning or candidate compile failure returns `-1`; a compiler that cannot produce valid JSON diagnostics makes the evaluation `INVALID`.

## 2D — Complete warning-as-error build

The function creates new objects for `bank_account.cpp`, `bank_account_test.cpp`, and `test/tests-main.cpp` using `-std=c++17 -Wall -Wextra -Wpedantic -Werror -pthread`. The official test unit is compiled with `EXERCISM_RUN_ALL_TESTS`, and the three objects are then linked into a test executable.

It returns `+1` only when every compile and the final link exit 0 and all generated artifacts are valid. Any candidate warning becomes a compiler error and returns `-1`; this kernel constructs but does not execute the test suite.

## Aggregation

```text
Policy 2 kernel sum = 2A + 2B + 2C + 2D
Range               = -4 to +4
Full pass           = +4
```

If any kernel is `INVALID`, the policy sum is not calculated and the verifier exits 2. A valid full pass exits 0; a valid result containing at least one `-1` exits 1.

## Execution

```bash
python3 "Bank_Account Verifiers/verifiers/verifier_02_warning_clean_build.py" \
  --exercise-dir <bank-account-directory> \
  --output-dir <new-empty-receipt-directory> \
  --compiler g++
```

The output directory receives `verification_receipt.json`, machine-readable GCC diagnostic logs, complete compiler logs, strict-build objects, and the linked executable when 2D passes.
