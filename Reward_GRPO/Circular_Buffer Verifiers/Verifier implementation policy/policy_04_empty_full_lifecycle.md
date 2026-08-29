# Policy 4: Empty/full lifecycle

The eval model treated `head == tail` as both empty and full, so a newly constructed buffer rejected its first write. This policy isolates the state transitions that disambiguate those conditions.

| Kernel | Binary pass condition | Evidence |
|---|---|---|
| 4A | A new buffer rejects `read`, accepts its first `write`, returns that item once, and is empty again. | Probe compile/run logs and hashes |
| 4B | A full buffer rejects another `write`; one `read` frees exactly one slot and FIFO order remains intact. | Probe compile/run logs and hashes |
| 4C | The same lifecycle works with `std::string`, proving the template is not accidentally integer-specific. | Probe compile/run logs and hashes |

Each kernel compiles a separate deterministic state-machine probe against the candidate. A candidate-caused compile or behavior failure is `-1`; authenticated success is `+1`; evaluator failure is `INVALID`.

These checks are deliberately narrower than the official suite. They provide useful GRPO credit for each correct state boundary while Policy 3 still decides terminal task correctness.

## Run

    python3 verifiers/verifier_04_empty_full_lifecycle.py --exercise-dir TASK --output-dir NEW_EMPTY_DIR
