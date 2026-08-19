# Policy 6 — Output, Mapping, Validation, and Relational Logic

Policy 6 answers whether all observable Bank Account results agree with one consistent state model. It separates exact outputs, operation ordering, input/state partitions, balance relations, and longer whole-state traces instead of treating every functional mismatch as the same failure.

Five conditions apply to Bank Account. Each is an equal binary kernel: a verified pass is `+1`, a candidate-caused failure is `-1`, and an evaluator fault is `INVALID`; 6E uniqueness/exhaustion is explicitly excluded because the task has no finite name or identifier space to exhaust.

## Kernel table

| Kernel | Verifier function | What it asks | Exact implementation | `+1` condition | `-1` condition | Evidence |
|---|---|---|---|---|---|---|
| 6A | `verify_6a_exact_observables()` | Are balances and exception outcomes exact? | Run one golden trace and compare its stdout byte-for-byte with the pinned expected trace | Every integer, exception label, newline, and order matches | Any observed value, exception class, formatting byte, crash, or timeout differs | Golden probe, expected and actual SHA-256, run log |
| 6B | `verify_6b_order_and_state_mapping()` | Does operation order map to the correct state? | Run several sequences where moving a withdrawal before or after a deposit changes validity or final balance | Every ordered sequence reaches its expected state and balance | An operation is ignored, reordered, applied twice, or mapped to the wrong state | Ordered-sequence probe and result log |
| 6C | `verify_6c_input_partitions()` | Are state and amount classes separated correctly? | Exercise unopened, open, and closed states with negative, zero, valid positive, exact-balance, and overdraft values | Every state/value cell is accepted or rejected correctly and preserves the expected balance | Any partition receives the wrong result or changes state on failure | Partition probe and matrix receipt |
| 6D | `verify_6d_balance_relations()` | Do deposits and withdrawals obey their mathematical relations? | Check deposit/withdraw inverses, overdraft preservation, exact depletion, and deposit-order equivalence across multiple safe balances | Every applicable relation holds | Addition/subtraction, acceptance, inverse, or preservation relation fails | Relational probe, case count, result log |
| 6F | `verify_6f_whole_state_consistency()` | Does one model explain a longer mixture of valid and invalid operations? | Compare the candidate after every step with an independent state-machine oracle over a fixed prelude and 256 deterministic generated operations | Every outcome, exception, balance, and transition matches the oracle | Any step diverges, throws the wrong type, corrupts later state, crashes, or times out | Oracle probe, seed, step count, result log |

## Excluded 6E condition

The original general rubric contains a uniqueness/exhaustion condition for tasks such as Robot Name. Bank Account creates no unique identifier and owns no finite namespace, so there is no honest operation that can prove or fail that property.

The receipt records `6E` under `excluded_conditions` with reason `not_applicable_to_bank_account`. It is not assigned `+1`, `-1`, or `INVALID`, and it is not included in the kernel range or full-pass denominator.

## Shared verification method

The verifier compiles five generated C++17 probes against the candidate using pinned GNU GCC 13.3, strict warnings, and pthread support. Each command, return code, timeout, source hash, executable hash, stdout hash, stderr hash, and source-tree digest is preserved in `verification_receipt.json`.

Every probe calls only the required public API. The whole-state probe contains its own small boolean-open/integer-balance oracle; it does not read candidate private fields or compile the reference solution into the candidate process.

## 6A — Exact observable trace

The function performs an unopened balance check, opens the account, deposits and withdraws known amounts, attempts an overdraft, closes, checks the closed exception, reopens, and prints each result. Runtime errors are printed as a fixed label while other exception types receive a different label.

It returns `+1` only when stdout exactly matches the pinned golden bytes and stderr is empty. A numerically close balance, wrong exception class, missing line, additional output, crash, or timeout returns `-1`.

## 6B — Ordered operation mapping

The function runs fresh accounts through order-sensitive sequences. It checks a valid `deposit(100) → withdraw(37) → deposit(3)` trace, an exact-depletion trace, an invalid withdrawal before funding, and a close/reopen boundary.

It returns `+1` when each operation is applied once, in order, and reaches the expected balance and state. A stale balance, premature withdrawal, duplicated update, retained reopen balance, or legal-sequence exception returns `-1`.

## 6C — State and input partitions

The function forms a small matrix over unopened, open, and closed states. Within the open state it separately checks negative, zero, positive, exact-balance, and overdraft deposit/withdraw behavior and observes balance after rejected operations.

It returns `+1` when every matrix cell matches the pinned state oracle. This check treats zero as valid for the parent Bank Account contract; a strengthened equivalent benchmark that rejects zero is not substituted here.

## 6D — Balance relations

The function creates fresh accounts for several base balances and withdrawal amounts. Successful withdrawals must produce `base - amount`, depositing the same amount must restore `base`, and rejected overdrafts must leave `base` unchanged; paired deposit orders must also reach the same total.

It returns `+1` when every safe-range relation holds. Signed-overflow inputs are excluded because the parent contract does not specify overflow semantics and this verifier must not create undefined behavior.

## 6F — Whole-state oracle

The function first executes a distinctive mixed prelude, then generates 256 deterministic operations from a fixed 32-bit seed. Before each candidate call, its independent oracle decides whether the operation should return, throw, or change balance; after each successful step it checks the candidate's observable balance when open.

It returns `+1` when all prelude and generated steps agree with the oracle. A wrong exception family, delayed corruption, invalid transition, inconsistent balance, crash, or timeout returns `-1`; the fixed seed and operation count are written to the receipt.

## Aggregation

```text
Policy 6 kernel sum = 6A + 6B + 6C + 6D + 6F
Applicable range    = -5 to +5
Full pass           = +5
6E                   = excluded, not scored
```

Any applicable `INVALID` kernel cancels the policy sum and exits 2. A valid full pass exits 0, and a valid result containing any `-1` exits 1.

## Execution

```bash
python3 "Bank_Account Verifiers/verifiers/verifier_06_output_mapping_relational_logic.py" \
  --exercise-dir <bank-account-directory> \
  --output-dir <new-empty-receipt-directory> \
  --compiler g++
```

The output directory receives generated probes, executables, expected and actual output hashes, logs, and the complete JSON receipt.
