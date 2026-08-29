# Policy 4: Canonical time arithmetic

The failed evals emitted `24:00` and `24:01` instead of wrapping to midnight. This policy makes modulo-one-day behavior explicit for construction, comparison, addition, and subtraction.

| Kernel | Binary pass condition | Evidence |
|---|---|---|
| 4A | Equivalent whole-day inputs normalize to `00:00` and compare equal. | Probe compile/run logs and hashes |
| 4B | Negative hours and minutes normalize into the canonical `00:00`–`23:59` range. | Probe compile/run logs and hashes |
| 4C | Large positive and negative arithmetic crosses multiple days without changing the canonical result. | Probe compile/run logs and hashes |

The kernels use public construction, mutation, string conversion, and equality only. They do not require a particular internal minute/hour representation.

Each exact behavior group returns `+1` or `-1`; evaluator faults remain `INVALID`.

## Run

    python3 verifiers/verifier_04_canonical_time_arithmetic.py --exercise-dir TASK --output-dir NEW_EMPTY_DIR
