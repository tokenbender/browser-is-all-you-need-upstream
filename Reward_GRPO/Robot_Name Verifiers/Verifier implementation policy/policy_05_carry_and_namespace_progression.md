# Policy 5: Carry and namespace progression

Two failed evals exhausted the namespace too early or produced an invalid name when the numeric suffix crossed its three-digit boundary. This policy stresses exactly that transition.

| Kernel | Binary pass condition | Evidence |
|---|---|---|
| 5A | At least 1,100 constructed robots have valid, unique names, crossing the first 1,000-name carry. | Probe compile/run logs and hashes |
| 5B | At least 1,100 resets on one robot remain valid and unique. | Probe compile/run logs and hashes |
| 5C | A mixed 5,000 construction/reset workload contains no collision, invalid format, or premature exhaustion. | Probe compile/run logs and hashes |

The verifier does not require a particular order such as `AA999` followed by `AB000`; it checks the contract properties the eval violated. Full exhaustion of all 676,000 names is intentionally excluded from the fast reward path.

Each stress group returns `+1/-1`; evaluator failures are `INVALID`.

## Run

    python3 verifiers/verifier_05_carry_and_namespace_progression.py --exercise-dir TASK --output-dir NEW_EMPTY_DIR
