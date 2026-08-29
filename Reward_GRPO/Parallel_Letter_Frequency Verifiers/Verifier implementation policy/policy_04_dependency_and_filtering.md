# Policy 4: Dependency and filtering contract

Failed eval candidates omitted `<execution>` or `<cctype>`, and one used `isalnum`, which would count digits. This policy makes both compilation ownership and letter-only filtering visible.

| Kernel | Binary pass condition | Evidence |
|---|---|---|
| 4A | The implementation compiles from its pinned public header without relying on missing transitive declarations. | Strict compile/link log and hashes |
| 4B | ASCII digits, punctuation, whitespace, and symbols contribute no keys. | Probe compile/run logs and hashes |
| 4C | Uppercase and lowercase letters merge into lowercase counts across multiple texts. | Probe compile/run logs and hashes |

The dependency check does not require `std::execution`; sequential and parallel correct implementations are both accepted. It only requires every symbol actually used by the candidate to be declared by its own includes.

Each kernel returns `+1/-1`; evaluator or contract faults are `INVALID`.

## Run

    python3 verifiers/verifier_04_dependency_and_filtering.py --exercise-dir TASK --output-dir NEW_EMPTY_DIR
