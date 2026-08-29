# Policy 4: Signed modifier and generation contract

The failed trial used integer truncation for negative modifiers, then introduced a multiple-definition linker error while repairing `ability()`. This policy targets both faults directly.

| Kernel | Binary pass condition | Evidence |
|---|---|---|
| 4A | Odd negative modifier cases use mathematical floor: scores 3, 5, 7, and 9 return -4, -3, -2, and -1. | Probe compile/run logs and hashes |
| 4B | A separate caller links with the implementation and 4,000 generated abilities remain in 3–18. | Compile/run logs and executable hash |
| 4C | Repeated characters keep all six abilities in range and derive hit points from constitution. | Probe compile/run logs and hashes |

Compiling a separate caller together with `dnd_character.cpp` catches non-inline function bodies accidentally placed in the header. Runtime checks do not demand a specific random sequence.

Each kernel returns `+1/-1`; evaluator faults remain `INVALID`.

## Run

    python3 verifiers/verifier_04_signed_modifier_and_generation.py --exercise-dir TASK --output-dir NEW_EMPTY_DIR
