# Policy 01: Build-stage and link completion

## Purpose

Prove that the pinned Sublist sources can move through primary-toolchain preflight, candidate compilation, caller compilation, linking, and a clean CMake build.

## Kernels

| ID | Function | Claim |
|---|---|---|
| 1a | `verify_1a_primary_toolchain_and_fixture` | GCC and authenticated fixed inputs are usable |
| 1b | `verify_1b_candidate_translation_unit` | `sublist.cpp` compiles as C++17 |
| 1c | `verify_1c_official_and_external_callers` | Official and generated callers compile against `sublist.h` |
| 1d | `verify_1d_link_completion` | Required objects link into an executable |
| 1e | `verify_1e_clean_cmake_build` | Clean CMake target `test_sublist` configures, builds, and runs |

## Execution

Candidate compile or link diagnostics are `-1`. Missing tools, changed fixtures, process-start failures, or unsafe paths are `INVALID`. Candidate-blocked downstream stages record `blocked_candidate` without fabricated commands; infrastructure-blocked stages are `INVALID`. All commands use argument arrays and write under the new output directory.

## Aggregation

All five kernels are equal and applicable. Maximum sum is `5`; every kernel must be `+1` to pass.

## Command

`python3 verifier_01_build_stage_link_completion.py --candidate-dir EXERCISE --output-dir OUTPUT`
