# Policy 4: Staged square layout

The failed evals mixed constructor state, normalization helpers, square dimensions, and final formatting. This policy verifies each public stage separately so one error does not hide every useful behavior.

| Kernel | Binary pass condition | Evidence |
|---|---|---|
| 4A | Empty, punctuation-only, mixed-case, digit, and spaced input normalize exactly. | Probe compile/run logs and hashes |
| 4B | Square size and plaintext segments are correct on perfect and incomplete squares. | Probe compile/run logs and hashes |
| 4C | Compact and normalized ciphertext match byte-for-byte, including required trailing padding. | Probe compile/run logs and hashes |

The checks call only the pinned `crypto_square::cipher` API and keep expected strings literal. They catch declaration mismatches, missing dependencies, accidental mutation in `const` observers, and spacing errors through normal compile/run evidence.

Each stage returns `+1/-1`; an evaluator or fixed-contract failure is `INVALID`.

## Run

    python3 verifiers/verifier_04_staged_square_layout.py --exercise-dir TASK --output-dir NEW_EMPTY_DIR
