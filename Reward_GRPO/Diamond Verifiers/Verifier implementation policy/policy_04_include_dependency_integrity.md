# Policy 4 — Include and Dependency Integrity

Policy 4 checks direct standard-library ownership, a self-contained header, task-local dependency isolation, and the pinned evaluator assets.

## Kernel table

| Kernel | Function | Verification | `+1` | `-1` | Evidence |
|---|---|---|---|---|---|
| 4A | `verify_4a_direct_include_ownership()` | Map `std::string`/`std::vector` to `<string>`/`<vector>` | All owners present | Candidate relies on transitive include | Include manifest |
| 4B | `verify_4b_header_self_contained()` | Strict standalone header compile | Compiles | Missing include/declaration | Probe, log, object hash |
| 4C | `verify_4c_dependency_graph()` | GCC `-MMD -MF` graph for header and implementation | No test, Catch, `.meta`, or unrelated task dependency | Forbidden task-local dependency | Dependency files and logs |
| 4D | `verify_4d_pinned_dependencies()` | Recompute all protected hashes and CMake contract facts | All match | Not used; mismatches are `INVALID` | Hash and CMake manifest |

## Method and aggregation

Full pass is `+4`. Candidate dependency faults are `-1`; missing or modified evaluator assets are `INVALID`.

## Exclusions

Correct include reordering is permitted. `.meta/example.*` is validation-only and is never a candidate-time oracle.

## Execution

```bash
python3 "Reward_GRPO/Diamond Verifiers/verifiers/verifier_04_include_dependency_integrity.py" --exercise-dir <diamond> --output-dir <new-output>
```
