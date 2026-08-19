# Policy 04: Header, include, and dependency ownership

## Purpose

Prove that the authorized source pair owns its public dependencies, avoids test or third-party leakage, and rebuilds from authenticated inputs.

## Kernels

| ID | Function | Claim |
|---|---|---|
| 4a | `verify_4a_direct_vector_include_ownership` | `sublist.h` directly includes `<vector>` |
| 4b | `verify_4b_header_self_contained` | A TU containing only `sublist.h` compiles |
| 4c | `verify_4c_implementation_dependency_graph` | Dependency output contains no Catch, tests, absolute candidate includes, or extra project files |
| 4d | `verify_4d_pinned_fixed_dependencies` | All fixed-file hashes match |
| 4e | `verify_4e_empty_workspace_rebuild` | Only the candidate pair plus authenticated fixtures rebuild in a fresh tree |

## Execution

Missing candidate includes or forbidden dependencies are `-1`. Changed tests, symlinks, missing fixtures, or dependency-tool failure are `INVALID`. Header-only implementation is permitted when all boundaries pass.

## Aggregation

All five kernels apply with maximum sum `5`.

## Command

`python3 verifier_04_header_include_dependency_ownership.py --candidate-dir EXERCISE --output-dir OUTPUT`
