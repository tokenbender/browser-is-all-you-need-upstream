# Policy 3 — Exact Public API Contract

Policy 3 decides whether the candidate exposes the exact pinned `grade_school::school` interface. This is the primary boundary for the observed wrong-class, renamed-method, reversed-parameter, non-const, and wrong-return failures.

## Kernel table

| Kernel | Verifier function | Exact question | `+1` | `-1` | Evidence |
|---|---|---|---|---|---|
| 3A | `verify_3a_public_type()` | Does `grade_school::school` exist and default-construct? | Probe compiles | Type is absent, renamed, inaccessible, or not constructible | Probe and log |
| 3B | `verify_3b_public_method_names()` | Are `roster`, `add`, and `grade` public names? | External address/call probe compiles | Required name is missing or private | Probe and log |
| 3C | `verify_3c_exact_signatures()` | Do all three pointer-to-member types match exactly? | Exact casts compile | Parameter, return, const, or reference mismatch | Signature probe and log |
| 3D | `verify_3d_linked_api_smoke()` | Are exact API definitions linkable and minimally callable? | Program exits 0 | Missing symbol, crash, throw, or timeout | Build/run logs and executable hash |

## Exact contract

```cpp
const std::map<int, std::vector<std::string>>& roster() const;
void add(std::string const& name, int grade);
std::vector<std::string> grade(int grade) const;
```

## Aggregation

The range is `-4` to `+4`; full pass is `+4`. `INVALID` cancels the policy.

## Explicit exclusions

- Private representation and helper names are unrestricted.
- Extra overloads are allowed when the required overload remains selectable.
- `noexcept` and duplicate-student semantics are not specified.
- The smoke probe does not replace functional testing.

## Execution

```bash
python3 "Reward_GRPO/Grade_School Verifiers/verifiers/verifier_03_public_api_contract.py" --exercise-dir <grade-school> --output-dir <new-empty-output> --compiler g++
```
