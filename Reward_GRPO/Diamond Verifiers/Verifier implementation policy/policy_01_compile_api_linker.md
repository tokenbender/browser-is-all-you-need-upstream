# Policy 1 — Compile, Caller, and Link Production

Policy 1 decides whether the pinned GCC/CMake environment can turn the Diamond candidate into a runnable C++17 executable. Missing or broken tools and altered fixed assets are `INVALID`; authenticated candidate compile, caller, link, or clean-build failures are `-1`.

## Kernel table

| Kernel | Function | Verification | `+1` | `-1` | Evidence |
|---|---|---|---|---|---|
| 1A | `verify_1a_toolchain()` | GCC 13.3, C++17, strict flags, CMake ≥3.5.1, clean configure | All preflights and configure pass | Not used for infrastructure faults | Tool identities and configure log |
| 1B | `verify_1b_implementation_compile()` | Compile `diamond.cpp` separately | Nonempty object | Candidate error or timeout | Command, log, object hash |
| 1C | `verify_1c_consumers_compile()` | Compile official caller and exact API consumer | Both objects | Candidate declaration prevents either compile | Commands, logs, hashes |
| 1D | `verify_1d_link()` | Compile Catch main and link all objects | Nonempty executable | Missing, duplicate, or incompatible symbol | Link log and executable hash |
| 1E | `verify_1e_clean_build()` | Second empty CMake build of target `diamond --clean-first` | Executable produced | Candidate clean-build failure | Configure/build logs and binary hash |

## Method and aggregation

Commands use argument lists, `-std=c++17 -Wall -Wextra -Wpedantic -Werror`, isolated output paths, timeouts, and before/after source hashes. Full pass is `+5`. Any `INVALID` cancels the sum; any valid `-1` fails the policy.

## Exclusions

Warning attribution belongs to Policy 2, exact API diagnosis to Policy 3, and output correctness to Policies 5 and 6.

## Execution

```bash
python3 "Reward_GRPO/Diamond Verifiers/verifiers/verifier_01_compile_api_linker.py" --exercise-dir <diamond> --output-dir <new-output>
```
