# Policy 4 — Header and Dependency Ownership

Policy 4 decides whether `grade_school.h` is a self-contained public boundary and whether candidate compilation uses only authorized local inputs plus system headers.

## Kernel table

| Kernel | Verifier function | Exact question | `+1` | `-1` | Evidence |
|---|---|---|---|---|---|
| 4A | `verify_4a_header_self_contained()` | Can the header compile as the first and only include? | Probe compiles | Incidental include is required | Probe and log |
| 4B | `verify_4b_implementation_owns_header()` | Does the implementation dependency graph contain `grade_school.h`? | Header is a direct compile dependency | Implementation bypasses its public header | Dependency manifest |
| 4C | `verify_4c_no_unowned_local_dependencies()` | Are all non-system dependencies authorized? | Only candidate source/header occur | Candidate imports another local/project file | Normalized dependency manifest |

## Shared method

The compiler generates `.d` dependency files with `-MMD`; source-text regexes are not used as the oracle. Protected files and their hashes are evaluator preflight rather than scored candidate kernels.

## Aggregation

The range is `-3` to `+3`; full pass is `+3`. `INVALID` cancels the policy.

## Explicit exclusions

- Any standard-library header may be used internally.
- Textual include order and private implementation style are unrestricted.
- A changed test, CMake, metadata, or Catch file produces `INVALID`.

## Execution

```bash
python3 "Reward_GRPO/Grade_School Verifiers/verifiers/verifier_04_header_dependency_ownership.py" --exercise-dir <grade-school> --output-dir <new-empty-output> --compiler g++
```
