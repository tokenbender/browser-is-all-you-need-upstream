# Policy 5 — Functional, State, and Boundary Correctness

Policy 5 answers whether the Bank Account candidate behaves correctly after it has compiled. It runs the complete 17-test parent suite and five focused probes for legal lifecycle changes, supported numeric boundaries, arithmetic invariants, forbidden operations, and repeatability.

Every check is an equal binary kernel: a verified pass is `+1`, a candidate-caused failure is `-1`, and an evaluator or unavailable pinned tool is `INVALID`. Policy 5 ranges from `-6` to `+6` and passes only at `+6`; it follows the pinned parent contract in which zero-valued deposits and withdrawals are valid no-op operations.

## Kernel table

| Kernel | Verifier function | What it asks | Exact implementation | `+1` condition | `-1` condition | Evidence |
|---|---|---|---|---|---|---|
| 5A | `verify_5a_official_tests()` | Does the candidate pass the complete parent benchmark? | Build the candidate with the pinned Catch test and main files, list the selected tests, require exactly 17, then execute them | Exactly 17 tests are selected and the suite exits 0 | Candidate build, test, crash, or timeout failure | Build log, test inventory, complete test log, executable digest |
| 5B | `verify_5b_lifecycle_transitions()` | Do legal open, close, and reopen transitions reset state correctly? | Run repeated `open → deposit → close → open` sequences and inspect every observable balance | Every open begins at zero and every reopen discards the previous balance | A legal transition throws, retains balance, crashes, or times out | Lifecycle probe, run log, executable digest |
| 5C | `verify_5c_supported_boundaries()` | Do zero, one, exact depletion, and the largest safe single amount behave correctly? | Check initial zero, `deposit(0)`, `withdraw(0)`, `deposit(1)`, exact withdrawal, and a safe `INT_MAX` deposit/withdraw pair | Every supported boundary produces the exact balance | A supported boundary throws or gives the wrong balance | Boundary probe and result log |
| 5D | `verify_5d_arithmetic_invariants()` | Are valid arithmetic and failed-operation state preservation correct? | Run a fixed mixed sequence, verify exact balances, then check negative and overdraft failures leave the prior balance unchanged | Every safe-range arithmetic assertion and preservation check passes | Arithmetic is wrong or a rejected operation mutates balance | Arithmetic probe and result log |
| 5E | `verify_5e_invalid_operations()` | Do all forbidden state and amount operations throw the required exception without changing state? | Exercise unopened, open, and closed invalid operations, catch `std::runtime_error`, and recheck state after each group | Every forbidden operation throws and subsequent legal observations match | A call succeeds, throws the wrong type, corrupts state, crashes, or times out | Invalid-operation probe and result log |
| 5F | `verify_5f_deterministic_repetition()` | Does the same legal workload always produce the same outcome? | Build one deterministic sequential workload and execute the identical binary ten times | All ten runs exit 0 with byte-identical stdout and stderr | Any run differs, fails, crashes, or times out | Per-run logs and output SHA-256 values |

## Shared verification method

The verifier records the source digest before execution and rejects mid-run mutation. Each focused probe is compiled with GNU GCC 13.3, C++17, strict warnings, and pthread support, then executed under a fixed timeout with its source, binary, commands, outputs, and hashes stored in `verification_receipt.json`.

The generated probes use only the required public namespace, class, and five methods. They never inspect private fields, require a particular mutex type, or use the reference implementation as an oracle at runtime.

## 5A — Complete official test suite

The function compiles `bank_account.cpp`, `bank_account_test.cpp`, and `test/tests-main.cpp` with `EXERCISM_RUN_ALL_TESTS` enabled. Before execution, it asks the resulting Catch binary to list its tests and requires the pinned inventory count of exactly 17.

It returns `+1` only when the candidate builds, all 17 tests are present, and the complete suite exits 0 within the timeout. Candidate compiler, linker, assertion, crash, deadlock, or timeout failures return `-1`; missing or altered fixed test infrastructure is `INVALID`.

## 5B — Lifecycle transitions

The function constructs a new account, opens it, confirms zero, deposits a value, closes it, reopens it, and confirms zero again. It repeats the legal close/reopen cycle with another value so one accidental reset cannot satisfy the probe.

It returns `+1` when every legal lifecycle call succeeds and every open or reopen starts with balance zero. Retaining the previous balance, failing to close, throwing during a legal transition, crashing, or timing out returns `-1`.

## 5C — Supported numeric boundaries

The function verifies the observable zero balance of a new open account, then applies zero-valued deposit and withdrawal operations and requires the balance to remain zero. It also tests the minimum useful amount `1`, exact withdrawal to zero, and one `INT_MAX` deposit followed by the same withdrawal without overflowing.

It returns `+1` when every supported value behaves exactly. Values that would cause signed integer overflow are deliberately excluded because the parent contract does not define overflow behavior and the verifier must not invent a new requirement.

## 5D — Arithmetic invariants

The function performs multiple deposits and withdrawals and checks the exact intermediate and final balances. It then requests a negative deposit, negative withdrawal, and overdraft, requires `std::runtime_error`, and verifies that each rejected operation leaves the previous balance unchanged.

It returns `+1` when valid operations implement exact addition and subtraction and invalid arithmetic cannot partially update the account. A wrong total, accepted invalid amount, wrong exception class, or changed balance returns `-1`.

## 5E — Forbidden operations and state preservation

The function checks invalid calls while unopened, already open, and closed. It covers balance, deposit, withdraw, close, double open, negative amounts, overdraft, and repeated close, and it uses later legal transitions to prove the state machine was not corrupted by an exception.

It returns `+1` when every forbidden call throws `std::runtime_error` and all later state observations remain correct. Error-message wording is not prescribed; no exception, a different exception family, state corruption, crash, or timeout returns `-1`.

## 5F — Deterministic repetition

The function builds one workload that performs the same fixed deposit and withdrawal series, checks the resulting balance, closes, reopens, and prints a single stable result. The Python verifier launches that unchanged executable ten times in the same pinned environment.

It returns `+1` when every execution exits 0 and all stdout and stderr bytes match. This proves repeatability for the fixed sequential workload only; race detection and high-contention scheduling remain Policy 9 responsibilities.

## Aggregation

```text
Policy 5 kernel sum = 5A + 5B + 5C + 5D + 5E + 5F
Range               = -6 to +6
Full pass           = +6
```

Any `INVALID` kernel cancels the policy sum and exits 2. A valid full pass exits 0, and a valid result containing any `-1` exits 1.

## Execution

```bash
python3 "Bank_Account Verifiers/verifiers/verifier_05_functional_state_boundary.py" \
  --exercise-dir <bank-account-directory> \
  --output-dir <new-empty-receipt-directory> \
  --compiler g++
```

The output directory receives generated probe sources, compiled executables, official and focused-test logs, output hashes, and the complete JSON receipt.
