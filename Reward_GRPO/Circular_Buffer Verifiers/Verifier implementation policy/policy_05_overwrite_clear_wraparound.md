# Policy 5: Overwrite, clear, and wraparound

The eval histories showed that overwrite could corrupt fullness and that an initial `clear()` could break later wraparound. This policy tests those specific transitions independently.

| Kernel | Binary pass condition | Evidence |
|---|---|---|
| 5A | Overwriting a full buffer discards only the oldest item and preserves the remaining FIFO order. | Probe compile/run logs and hashes |
| 5B | A buffer remains full after overwrite, so ordinary `write` still throws until an item is read. | Probe compile/run logs and hashes |
| 5C | Clearing before first use and clearing after use both reset state without damaging later wraparound. | Probe compile/run logs and hashes |

The probes never inspect private indices; they verify only public behavior. This allows different valid ring-buffer implementations while rejecting the size/head/tail errors observed in `midbreak-RL-v2`.

All three kernels use `+1/-1`, and any broken evaluator or altered pinned contract is `INVALID`.

## Run

    python3 verifiers/verifier_05_overwrite_clear_wraparound.py --exercise-dir TASK --output-dir NEW_EMPTY_DIR
