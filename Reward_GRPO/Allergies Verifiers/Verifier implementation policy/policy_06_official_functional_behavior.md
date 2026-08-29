# Policy 6 — Official Functional Behavior

This policy is the authoritative semantic scorer for the pinned Allergies task. It compiles, links, and runs the protected official suite and accepts a candidate only when all 50 assertions in all 50 test cases pass.

## Kernel table

| Kernel | Verifier function | What it asks | Exact implementation | `+1` condition | `-1` condition | Evidence |
|---|---|---|---|---|---|---|
| 6A | `verify_6a_complete_official_suite()` | Does the candidate satisfy every protected official assertion? | Authenticate the fixed test assets, compile the complete C++17 suite with strict GCC flags and `EXERCISM_RUN_ALL_TESTS`, link it, run it, and parse the exact Catch summary | Build and execution exit 0, the executable exists, and output contains `All tests passed (50 assertions in 50 test cases)` | Candidate compilation, linkage, timeout, crash, assertion failure, incomplete test count, or missing success summary | Commands, exit codes, timeout states, compiler logs, test logs, executable hash, source hashes, fixed-asset hashes, parsed assertion/test counts |

## Shared verification method

Preflight requires regular non-symlink candidate files, exact protected-file SHA-256 values, GNU GCC 13.3, and a new empty output directory outside the exercise. Candidate sources are hashed before and after execution. The verifier writes the executable, logs, and `verification_receipt.json` only below the output directory and invokes subprocesses with argument lists and bounded timeouts.

## 6A — Complete official suite

The verifier directly compiles `allergies_test.cpp`, `allergies.cpp`, and `test/tests-main.cpp` with C++17, `-Wall -Wextra -Wpedantic -Werror`, and `-DEXERCISM_RUN_ALL_TESTS`. A compiler or test process that cannot start, a changed protected test hash, a missing compiler, a changed candidate source during evaluation, or malformed evaluator evidence is `INVALID`. A completed candidate build or test failure is `-1`.

## Aggregation

```text
applicable kernels = 1
maximum kernel sum = +1
PASS    = kernel 6A is +1
FAIL    = kernel 6A is -1
INVALID = kernel 6A is INVALID or preflight/evidence is invalid
```

E06 is the canonical per-sample terminal semantic gate. E01–E04 remain auxiliary shaped rewards, and E05 remains a trajectory-only repair policy.

## Execution

```bash
python3 "Reward_GRPO/Allergies Verifiers/verifiers/verifier_06_official_functional_behavior.py" \
  --exercise-dir /path/to/allergies \
  --output-dir /new/output/policy-06
```
