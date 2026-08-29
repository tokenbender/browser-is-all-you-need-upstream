# Policy 02: Warning-clean candidate build

## Purpose

Prove that candidate-owned source and header code compile cleanly under the warning contract, independently of fixture-owned CMake messages.

## Kernels

| ID | Function | Flags |
|---|---|---|
| 2a | `verify_2a_wall` | `-Wall -Werror` |
| 2b | `verify_2b_wextra` | `-Wextra -Werror` |
| 2c | `verify_2c_wpedantic` | `-Wpedantic -Werror` |
| 2d | `verify_2d_complete_werror_build` | `-Wall -Wextra -Wpedantic -Werror` with full link |

## Execution

Each family compiles the implementation and a generated header consumer. Candidate diagnostics are `-1`; missing compiler or corrupt evidence is `INVALID`. The fixed CMake compatibility deprecation warning is excluded because it is not emitted by candidate compilation.

## Aggregation

All four kernels are equal and applicable. Maximum sum is `4`.

## Command

`python3 verifier_02_warning_clean_candidate_build.py --candidate-dir EXERCISE --output-dir OUTPUT`
