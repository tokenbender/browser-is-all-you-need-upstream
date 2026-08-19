# Policy 03: Exact public API and caller contract

## Purpose

Reject the historically observed invented types, functions, uppercase enumerators, templates, and parameter changes while accepting the pinned namespace API.

## Kernels

| ID | Function | Claim |
|---|---|---|
| 3a | `verify_3a_namespace_enum_type` | `sublist::List_comparison` is a scoped enum |
| 3b | `verify_3b_lowercase_enumerators` | Required lowercase enumerators exist and known wrong aliases do not |
| 3c | `verify_3c_exact_non_template_signature` | `decltype(&sublist::sublist)` is the exact two-const-reference function pointer |
| 3d | `verify_3d_braced_call_compatibility` | Official braced calls compile and link |
| 3e | `verify_3e_enum_distinctness_and_smoke` | Four results are distinct and the API executes |

## Execution

Positive probes must compile; each known-wrong alias is compiled separately and must fail. A candidate-caused mismatch is `-1`; a missing compiler is `INVALID`. Header self-containment belongs to Policy 04.

## Aggregation

All five kernels apply with maximum sum `5`.

## Command

`python3 verifier_03_exact_public_api_caller_contract.py --candidate-dir EXERCISE --output-dir OUTPUT`
