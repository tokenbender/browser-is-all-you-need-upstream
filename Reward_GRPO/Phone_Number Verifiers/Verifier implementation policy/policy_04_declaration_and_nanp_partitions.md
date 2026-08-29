# Policy 4: Declaration and NANP partitions

The failed eval repair gave a data member the same name as a member function, so the public header could not compile. This policy combines an exact caller check with the input partitions that define the task.

| Kernel | Binary pass condition | Evidence |
|---|---|---|
| 4A | Constructor, `number`, `area_code`, and explicit string conversion compile and link from an external caller. | Strict compile/link log and hashes |
| 4B | Valid 10/11-digit inputs with allowed punctuation normalize and format exactly. | Probe compile/run logs and hashes |
| 4C | Length, letters, forbidden punctuation, country code, area prefix, and exchange prefix invalid partitions all throw `std::domain_error`. | Probe compile/run logs and hashes |

The verifier does not require private helper or member names. It catches collisions through the public compiler contract and verifies behavior solely through public construction and observers.

Each group returns `+1/-1`; evaluator or fixed-contract failure is `INVALID`.

## Run

    python3 verifiers/verifier_04_declaration_and_nanp_partitions.py --exercise-dir TASK --output-dir NEW_EMPTY_DIR
