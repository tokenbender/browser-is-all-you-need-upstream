# Policy 5: Numerical identities

Compile success does not prove complex division or transcendental behavior. This policy checks independent numerical identities across signs and nontrivial real/imaginary components.

| Kernel | Binary pass condition | Evidence |
|---|---|---|
| 5A | Multiplication followed by division reconstructs the original nonzero complex value. | Probe compile/run logs and hashes |
| 5B | Magnitude and conjugation satisfy `abs(z)^2 = real(z * conj(z))`. | Probe compile/run logs and hashes |
| 5C | Exponential checks pass for zero, a real input, Euler's identity, and a mixed input. | Probe compile/run logs and hashes |

Comparisons use a documented floating-point tolerance and avoid division by zero. The checks extend, rather than replace, the pinned official suite.

Each identity group returns `+1/-1`; evaluator faults are `INVALID`.

## Run

    python3 verifiers/verifier_05_numerical_identities.py --exercise-dir TASK --output-dir NEW_EMPTY_DIR
