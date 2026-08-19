# Policy 3 — Exact Public API Contract

Policy 3 checks the pinned free-function API `std::vector<std::string> diamond::rows(char)` from an external caller.

## Kernel table

| Kernel | Function | Verification | `+1` | `-1` | Evidence |
|---|---|---|---|---|---|
| 3A | `verify_3a_header_self_contained()` | Strictly compile header-only translation unit | Compiles | Header needs undeclared ownership | Probe and log |
| 3B | `verify_3b_public_names()` | Call `diamond::rows('A')` externally | Public call compiles | Missing, renamed, inaccessible, or ambiguous name | Probe and log |
| 3C | `verify_3c_exact_signature()` | Cast address to `std::vector<std::string> (*)(char)` | Exact form exists | Wrong parameter or return type | Probe and log |
| 3D | `verify_3d_linked_api_smoke()` | Link candidate and require `rows('A') == {"A"}` | Call succeeds | Missing symbol, crash, timeout, or incompatible result | Build/run logs and binary hash |

## Method and aggregation

Every probe is generated outside the candidate workspace and uses only the public header. Full pass is `+4`.

## Exclusions

No class, constructor, lifecycle, exception, const-member, or concurrency rule applies. Full semantics belong to Policies 5 and 6.

## Execution

```bash
python3 "Reward_GRPO/Diamond Verifiers/verifiers/verifier_03_public_api_contract.py" --exercise-dir <diamond> --output-dir <new-output>
```
