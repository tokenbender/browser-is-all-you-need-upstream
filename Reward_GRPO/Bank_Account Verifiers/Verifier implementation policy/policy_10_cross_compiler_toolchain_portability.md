# Policy 10 — Cross-Compiler and Toolchain Portability

Policy 10 answers whether Bank Account works outside the pinned GCC evaluation path. It checks the candidate directly with Clang, runs the complete official suite under Clang, and repeats the build in an immutable offline Clang container.

All three conditions apply and use equal binary kernels. A verified portability pass is `+1`, a candidate compile, link, test, or reproduction failure is `-1`, and missing or broken evaluator infrastructure is `INVALID`.

## Kernel table

| Kernel | Verifier function | What it asks | Exact implementation | `+1` condition | `-1` condition | Evidence |
|---|---|---|---|---|---|---|
| 10A | `verify_10a_clang_warning_clean_compile()` | Does every Bank Account translation unit compile cleanly with Clang? | Compile the implementation, official test, Catch main, and generated API probe separately with Clang 18, C++17, pthread, and warnings as errors | All four objects are nonempty and every command exits 0 | Any candidate warning, compile error, timeout, or missing object | Clang identity, compile logs, object hashes, source hash |
| 10B | `verify_10b_clang_link_and_tests()` | Does the Clang-built executable link and pass the official contract? | Independently compile and link the complete executable, then run all 17 official tests | Link exits 0, executable is valid, exactly 17 tests run, and all pass | Candidate link error, failed test, crash, timeout, or wrong test count | Build/run logs, binary hash, test hashes, test count |
| 10C | `verify_10c_clean_reproduction()` | Can a second pinned toolchain reproduce the result from an empty build? | Mount the task read-only into the immutable Clang 18.1.8 image, configure a new CMake directory offline, build the target, and run all 17 tests | Image identity matches, clean configure/build exits 0, and all 17 tests pass | Candidate container compile, link, or test failure | Image ID, Clang/CMake versions, clean-build log, binary and fixture hashes |

## Shared verification method

The verifier first confirms the pinned official test hashes and a working host Clang 18.1.3 compiler. It compiles and runs a harmless pthread program before candidate code is scored, so a missing compiler or broken runtime becomes `INVALID` instead of a candidate failure.

Every kernel uses the same immutable source digest and records exact commands, return codes, timeouts, log paths, toolchain identities, and artifact hashes in `verification_receipt.json`. Policy 10 does not replace the GCC checks in Policies 1 and 2; it adds independent Clang evidence.

## 10A — Clang warning-clean compilation

The function compiles `bank_account.cpp`, `bank_account_test.cpp`, `test/tests-main.cpp`, and a generated public API probe into separate objects. It uses `-std=c++17 -Wall -Wextra -Wpedantic -Werror -pthread`, and enables all official tests while compiling the test unit.

It returns `+1` only when all four commands exit zero and every object is a regular nonempty file. Any candidate warning or declaration problem returns `-1`; a failed harmless Clang preflight is `INVALID`.

## 10B — Clang link and official tests

The function performs a second independent build instead of reusing 10A objects. It links the implementation, official test file, and Catch main with pthread support, then runs the resulting executable.

It returns `+1` only when the executable exits zero and its output confirms that all 17 official test cases passed. This proves Clang functional compatibility as well as compilation and linkage.

## 10C — Clean immutable reproduction

The function requires the local immutable image `silkeh/clang@sha256:9388794775d1393c16b6897b4775b6d3e29459319de0bfafec59a20262e1fa68`. The image runs without network access, reads the task through a read-only mount, and writes only to a new output directory.

It configures CMake with Clang 18.1.8, builds the `bank-account` target from an empty directory, and executes all 17 tests. Missing Docker or a missing/mismatched image is `INVALID`; a valid container that rejects the candidate returns `-1`.

## Aggregation

```text
Policy 10 kernel sum = 10A + 10B + 10C
Range                = -3 to +3
Full pass            = +3
```

Any `INVALID` kernel cancels the policy sum and exits 2. A valid full pass exits 0, and a valid result containing any `-1` exits 1.

## Execution

```bash
python3 "Bank_Account Verifiers/verifiers/verifier_10_cross_compiler_toolchain_portability.py" \
  --exercise-dir <bank-account-directory> \
  --output-dir <new-empty-receipt-directory> \
  --compiler clang++ \
  --docker docker
```

The output directory receives host-Clang objects, the independently linked test executable, the clean container build, complete logs, and `verification_receipt.json`.
