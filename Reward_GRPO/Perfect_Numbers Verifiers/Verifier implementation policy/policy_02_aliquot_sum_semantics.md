# Policy 2 — Aliquot-Sum Semantics

Policy 2 verifies the observed arithmetic boundary and closely related contract cases: classification must use the sum of proper divisors, exclude the number itself, count paired square-root divisors once, and classify `1` as deficient.

## Kernel table

| Kernel | Verifier function | Question | Exact implementation | `+1` | `-1` | Evidence |
|---|---|---|---|---|---|---|
| E02-A | `verify_e02_a_number_one()` | Is `1` deficient? | Link and run a probe requiring `classify(1) == classification::deficient` | Exact result without exception | Wrong category, exception, crash, or timeout | Probe hash, build/run logs, executable hash |
| E02-B | `verify_e02_b_official_positive_cases()` | Do the ten remaining official positive examples match? | Compare three perfect, three abundant, and four deficient official inputs with exact expected categories | All ten match | Any mismatch, exception, crash, or timeout | Case manifest, build/run logs, executable hash |
| E02-C | `verify_e02_c_square_divisors()` | Are square-root divisors counted once? | Compare 14 pinned square inputs with an independent 64-bit proper-divisor oracle | Every square matches | Any square differs, throws, crashes, or times out | Corpus, oracle digest, build/run logs |
| E02-D | `verify_e02_d_generated_oracle()` | Does the candidate agree over a deterministic nonsquare corpus? | Compare all nonsquares from 2 through 4096, excluding E02-B inputs, with the independent oracle | Every generated case matches | Any mismatch, exception, crash, or timeout | Corpus definition, checked count, first mismatch, logs |

## Shared method

Each kernel is compiled with GNU GCC 13.3, C++17, and strict warnings, then run with a fixed locale and timeout. The oracle uses a 64-bit sum and overflow-safe loop condition `divisor <= number / divisor`; it shares no implementation code with the candidate or `.meta/example.cpp`.

## E02-A — Number one

This is the exact historical regression. It remains separate from generated cases so the receipt identifies the unit edge directly.

## E02-B — Official positive cases

The exact corpus is perfect `{6, 28, 33550336}`, abundant `{12, 30, 33550335}`, and deficient `{2, 4, 32, 33550337}`. Invalid inputs and `1` are deliberately assigned to other kernels.

## E02-C — Square divisors

The exact corpus is `{9, 16, 25, 36, 49, 64, 81, 100, 121, 144, 169, 196, 225, 256}`. Expected categories come from the independent oracle at probe runtime.

## E02-D — Generated oracle

The corpus contains deterministic nonsquares in `[2, 4096]` after excluding Policy 2B inputs. It records the total checked count and the first mismatch; it uses no randomness and creates no unstable denominator.

## Aggregation

All four kernels are equal. The range is `-4` through `+4`, and Policy 2 passes only at `+4`. Candidate API or compilation failures are valid `-1` results and may overlap Policy 1.

## Execution

```bash
python3 "Reward_GRPO/Perfect_Numbers Verifiers/verifiers/verifier_02_aliquot_sum_semantics.py" \
  --exercise-dir <perfect-numbers-directory> \
  --output-dir <new-empty-directory> \
  --compiler g++ \
  --expected-gcc 13.3
```
