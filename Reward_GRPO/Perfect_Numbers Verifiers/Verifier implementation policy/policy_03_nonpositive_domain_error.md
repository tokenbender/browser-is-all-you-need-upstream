# Policy 3 — Nonpositive Domain Error

Policy 3 verifies the exact invalid-input contract exposed by two observed failure forms: returning normally and throwing `std::invalid_argument` instead of `std::domain_error`.

## Kernel table

| Kernel | Verifier function | Question | Exact implementation | `+1` | `-1` | Evidence |
|---|---|---|---|---|---|---|
| E03-A | `verify_e03_a_zero()` | Does `classify(0)` throw `std::domain_error`? | Run the linked exception probe for zero | Exact exception type caught | No exception, wrong exception, crash, or timeout | Probe hash, build/run logs, executable hash |
| E03-B | `verify_e03_b_negative_one()` | Does `classify(-1)` throw `std::domain_error`? | Run the same probe for negative one | Exact exception type caught | No exception, wrong exception, crash, or timeout | Input manifest and run log |
| E03-C | `verify_e03_c_negative_partition()` | Is the exception rule consistent across negative integers? | Check `-2`, `-7`, `-28`, `-33550336`, and `INT_MIN` independently | All five throw the exact type | Any input returns, throws another type, crashes, or times out | Corpus, per-input result, logs |

## Shared method

The verifier compiles one strict C++17 probe with the candidate implementation. The probe returns distinct codes for `std::domain_error`, another exception, and no exception, so a message string or common base class cannot create a false pass.

## E03-A — Zero

Zero is an independent official assertion and receives its own kernel. Only catching `std::domain_error` passes.

## E03-B — Negative one

Negative one is the second independent official assertion. `std::invalid_argument` is a candidate `-1`, even though both types inherit from `std::logic_error`.

## E03-C — Negative partition

The five fixed values extend the same pinned rule without randomness. `INT_MIN` proves the implementation rejects before any unsafe absolute-value or divisor arithmetic.

## Aggregation

All three kernels are equal. The range is `-3` through `+3`, and Policy 3 passes only at `+3`. Exception message text is explicitly excluded.

## Execution

```bash
python3 "Reward_GRPO/Perfect_Numbers Verifiers/verifiers/verifier_03_nonpositive_domain_error.py" \
  --exercise-dir <perfect-numbers-directory> \
  --output-dir <new-empty-directory> \
  --compiler g++ \
  --expected-gcc 13.3
```
