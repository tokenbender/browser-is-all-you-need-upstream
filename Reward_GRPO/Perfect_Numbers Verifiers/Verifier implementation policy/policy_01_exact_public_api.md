# Policy 1 — Exact Public API

Policy 1 verifies the first observed failure boundary: whether external C++17 callers see the exact pinned Perfect Numbers API and can link its definition. It does not score classification behavior.

## Kernel table

| Kernel | Verifier function | Question | Exact implementation | `+1` | `-1` | Evidence |
|---|---|---|---|---|---|---|
| E01-A | `verify_e01_a_names_and_scoping()` | Are the namespace, enum type, scoping, and enumerators exact? | Compile a header-only probe using `perfect_numbers::classification`, all three lowercase enumerators, `std::is_enum_v`, and non-convertibility to `int` | Strict compilation succeeds | A required name is missing, incorrectly cased, inaccessible, ambiguous, or unscoped | Probe hash, command, compiler logs, object hash |
| E01-B | `verify_e01_b_function_signature()` | Is `classify` exactly `classification(int)`? | Compile a header-only `decltype(&perfect_numbers::classify)` assertion against `classification (*)(int)` | The exact function-pointer assertion compiles | Parameter, return, namespace, name, overload set, or function type differs | Probe hash, command, compiler logs, object hash |
| E01-C | `verify_e01_c_definition_and_linkage()` | Does one compatible definition link? | Link `perfect_numbers.cpp` with an external caller that takes the function address | A nonempty executable is produced | Candidate compile or link failure, missing definition, duplicate definition, or incompatible definition | Commands, logs, executable hash |
| E01-D | `verify_e01_d_official_caller()` | Can all official callers compile against the header? | Compile pinned `perfect_numbers_test.cpp` with `EXERCISM_RUN_ALL_TESTS` and strict flags | Official test object is produced | Candidate declarations prevent official caller compilation | Fixed test hash, command, logs, object hash |

## Shared method

Preflight requires regular non-symlink task assets, the pinned CMake/test/Catch hashes, GNU GCC 13.3, and a new empty output directory. It records a combined candidate-source hash before commands and rejects source drift afterward. Tool or fixed-evidence failure is `INVALID`; candidate diagnostics are `-1`.

## E01-A — Names and scoping

The probe includes only `perfect_numbers.h`, references the exact lowercase public names, proves `classification` is an enum, and proves it is not implicitly convertible to `int`. It therefore distinguishes the observed uppercase and unscoped alternatives.

## E01-B — Function signature

The probe compares the uncast address of `perfect_numbers::classify` with `perfect_numbers::classification (*)(int)`. An overload set is intentionally rejected because the pinned public surface contains one exact function.

## E01-C — Definition and linkage

The probe takes and observes the function address without calling it. Link success proves declaration-definition compatibility without importing semantic claims from Policies 2 or 3.

## E01-D — Official caller

The official test translation unit is compiled but not linked or run. Its pinned hash and 13 test identities make it an authenticated caller, while runtime assertions remain outside this policy.

## Aggregation

All four kernels are equal. The range is `-4` through `+4`, and Policy 1 passes only at `+4`. One API defect may fail several kernels; the receipt records those as overlapping observations rather than independent defects.

## Execution

```bash
python3 "Reward_GRPO/Perfect_Numbers Verifiers/verifiers/verifier_01_exact_public_api.py" \
  --exercise-dir <perfect-numbers-directory> \
  --output-dir <new-empty-directory> \
  --compiler g++ \
  --expected-gcc 13.3
```
