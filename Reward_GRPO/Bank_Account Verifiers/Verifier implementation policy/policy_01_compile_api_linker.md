# Policy 1 — Compile, API Consumer, and Linker Verification

Policy 1 answers one narrow question: can the Bank Account candidate become a clean, runnable test executable? It separates toolchain configuration, implementation compilation, caller compilation, linking, and an independent clean rebuild so the receipt identifies the exact boundary that passed or failed.

Each check returns one equal binary kernel. A verified pass returns `+1`; a candidate-caused failure returns `-1`. An unavailable compiler, missing CMake installation, corrupted task fixture, or other evaluator failure returns `INVALID`, which cancels the category result and requires a rerun rather than assigning a candidate penalty.

## Kernel table

| Kernel | Verifier function | What it asks | Exact implementation | `+1` condition | `-1` condition | Evidence |
|---|---|---|---|---|---|---|
| 1A | `verify_1a_toolchain()` | Is the required build environment ready? | Confirm GNU GCC 13.3, C++17 compile commands, `EXERCISM_RUN_ALL_TESTS`, fresh CMake configuration, and successful `Threads::Threads` resolution | Every toolchain and configuration assertion passes | Not used for infrastructure faults; those produce `INVALID` | Compiler identity, macros, CMake logs, source digest |
| 1B | `verify_1b_implementation_compile()` | Does `bank_account.cpp` compile by itself? | Compile it to `bank_account.o` with C++17, strict warnings, and pthread support | Compiler exits 0 and a nonempty regular object is produced | Candidate implementation does not compile or times out | Compiler log and object digest |
| 1C | `verify_1c_consumers_compile()` | Can the official test and exact API probe include and call the candidate? | Compile `bank_account_test.cpp` and a generated signature-checking probe as separate objects | Both compilers exit 0 and both objects are valid | Either consumer translation unit fails because of candidate declarations | Two compiler logs and two object digests |
| 1D | `verify_1d_link()` | Are all required definitions present and linkable? | Compile Catch's main object, then link it with the implementation and official-test objects using pthread support | Linker exits 0 and creates a nonempty executable | Linker reports missing, duplicate, or incompatible candidate definitions; missing prerequisites also produce `-1` as blocked | Link log, link command, executable digest |
| 1E | `verify_1e_clean_build()` | Does the same candidate build from an empty directory? | Configure a second build tree and build only the `bank-account` executable target with `--clean-first` | Fresh configure and executable-target build exit 0 and create the executable | Candidate compilation or linking fails in the fresh build | Fresh configure/build logs and executable digest |

## Shared result contract

Every function writes command output to log files and returns the same receipt fields: kernel ID, `+1`, `-1`, or `INVALID`, short reason, exact command, return code, facts, artifact paths, and SHA-256 digests. The source digest is captured before any command and checked again afterward so a build cannot silently change the evaluated source.

The category kernel sum is computed only when none of the five checks is `INVALID`. Its range is `-5` to `+5`; `+5` means all five checks passed, while any smaller value means Policy 1 did not fully pass. A blocked linker check is `-1` because the candidate failed to produce the objects needed for linking.

## 1A — Toolchain and configuration

The function first reads the compiler's full version and predefined macros. It accepts only GNU GCC 13.3, rejects Clang pretending to be GCC, checks that CMake is available, and configures a new build directory with the absolute compiler path, `EXERCISM_RUN_ALL_TESTS=ON`, and exported compile commands.

After configuration it reads the generated CMake compiler record and compile commands. It verifies GNU compiler identity, a C++17 command, the all-tests definition, and the pinned `find_package(Threads REQUIRED)` plus `Threads::Threads` target; any missing tool or broken fixture is `INVALID`, while a complete valid environment returns `+1`.

## 1B — Implementation translation unit

The function invokes GCC directly on `bank_account.cpp` with `-std=c++17 -Wall -Wextra -Wpedantic -Werror -pthread`. It compiles only to an object, so syntax, include, namespace, declaration-definition, and warning failures remain separate from caller and linker failures.

It returns `+1` only when the command exits 0 and `bank_account.o` is a nonempty regular file whose digest can be recorded. A compiler diagnostic or candidate-caused timeout returns `-1`; a missing compiler process or unreadable fixed fixture returns `INVALID`.

## 1C — Official caller and API probe

The function compiles the official `bank_account_test.cpp` with all 17 tests enabled, then compiles a generated API probe. The probe uses member-pointer `static_assert` checks for the exact namespace, class, method names, parameters, and return types without examining private fields.

It returns `+1` only when both consumer files compile and produce nonempty objects. If the candidate header prevents either caller from compiling, it returns `-1`; if the official test fixture is missing or altered outside the candidate files, the evaluation is `INVALID`.

## 1D — Linker

The function requires the successful objects from 1B and 1C, compiles the fixed Catch entry point, and links the implementation, official test, and Catch objects with `-pthread`. Link success proves the declarations have compatible definitions and a test executable can be constructed, but it does not claim that the 17 behavioral assertions pass.

It returns `+1` when the linker exits 0 and produces a nonempty executable with an executable bit and recorded digest. Missing candidate definitions, duplicate symbols, or incompatible definitions return `-1`; if 1B or 1C did not produce their objects, 1D is recorded as blocked with kernel `-1`.

## 1E — Independent clean build

The function creates a second empty CMake directory and repeats configuration without reusing the objects or cache from 1A through 1D. It builds the explicit `bank-account` executable target with `--clean-first`, which avoids running behavioral tests that belong to Policy 5.

It returns `+1` when fresh configuration and the clean executable build exit 0, the executable exists, and the source digest remains unchanged. A candidate compile or link failure returns `-1`; missing CMake, missing Threads, disk failure, or task-fixture drift returns `INVALID`.

## Execution

```bash
python3 "Bank_Account Verifiers/verifiers/verifier_01_compile_api_linker.py" \
  --exercise-dir <bank-account-directory> \
  --output-dir <new-empty-receipt-directory> \
  --compiler g++ \
  --cmake cmake
```

The verifier writes `verification_receipt.json` below the output directory. Exit code `0` means all five kernels equal `+1`, exit code `1` means a valid candidate evaluation contains at least one `-1`, and exit code `2` means the evaluation is `INVALID` and must be rerun.
