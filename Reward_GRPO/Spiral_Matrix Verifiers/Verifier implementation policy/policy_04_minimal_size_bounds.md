# Policy 4: Minimal-size bounds

Two failed eval trials segfaulted specifically at size 2 after passing sizes 0 and 1. This policy isolates the smallest matrices so the dangerous boundary receives a direct reward signal.

| Kernel | Binary pass condition | Evidence |
|---|---|---|
| 4A | Sizes 0 and 1 return the exact empty and singleton matrices. | Probe compile/run logs and hashes |
| 4B | Size 2 returns `{{1,2},{4,3}}` without a signal or bounds failure. | Probe compile/run logs and hashes |
| 4C | Sizes 3–5 match exact canonical matrices and preserve square shape. | Probe compile/run logs and hashes |

Each kernel uses the pinned `spiral_matrix(uint32_t)` public API. A crash or nonzero process exit is a candidate `-1`, while inability to start the evaluator is `INVALID`.

Policy 3 still authenticates and runs the complete official suite; these checks make the size-2 failure independently visible to GRPO.

## Run

    python3 verifiers/verifier_04_minimal_size_bounds.py --exercise-dir TASK --output-dir NEW_EMPTY_DIR
