# Policy 4: Construction and reset lifecycle

One failed eval declared and defined its name generator inconsistently. This policy checks the externally observable lifecycle without requiring any helper name or implementation strategy.

| Kernel | Binary pass condition | Evidence |
|---|---|---|
| 4A | A separately compiled caller constructs a robot and receives a valid `AA000`-shape name. | Strict compile/run logs and hashes |
| 4B | Repeated `name()` calls are stable and do not lazily consume new names. | Probe compile/run logs and hashes |
| 4C | Repeated `reset()` calls always produce a new valid name. | Probe compile/run logs and hashes |

Linking the external caller catches missing helper declarations and definitions indirectly. Valid implementations may generate names randomly or sequentially.

Each lifecycle group returns `+1/-1`; evaluator faults remain `INVALID`.

## Run

    python3 verifiers/verifier_04_construction_reset_lifecycle.py --exercise-dir TASK --output-dir NEW_EMPTY_DIR
