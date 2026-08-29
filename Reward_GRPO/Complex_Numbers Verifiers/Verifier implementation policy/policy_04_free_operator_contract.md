# Policy 4: Free-operator contract

Three failed trials implemented free operators by reading private or stale member names. This policy compiles and runs the externally visible equality, stream, and scalar-operator surface so valid implementations must use a legal access path.

| Kernel | Binary pass condition | Evidence |
|---|---|---|
| 4A | Equality and stream insertion compile and link; equality distinguishes components and insertion leaves the stream valid. No textual format is imposed because the pinned task does not specify one. | Probe compile/run logs and hashes; Midband Trial 4 official-positive control |
| 4B | Addition and subtraction work with the scalar on either side. | Probe compile/run logs and hashes |
| 4C | Multiplication and division work with the scalar on either side. | Probe compile/run logs and hashes |

No private field name, friendship layout, or stream text format is required. A candidate may use public observers, friends, or another valid design, but every declared free operator must compile and satisfy the behavior stated by the pinned task.

Each group returns `+1/-1`; evaluator failures remain `INVALID`.

## Run

    python3 verifiers/verifier_04_free_operator_contract.py --exercise-dir TASK --output-dir NEW_EMPTY_DIR
