# Policy 4 — Include and Dependency Integrity

Policy 4 answers whether the Bank Account candidate declares the headers and fixed dependencies it actually needs. It separates source-level include ownership, standalone header compilation, accidental test-framework leakage, pinned build dependencies, and an empty-directory rebuild so each dependency boundary produces its own receipt.

Every check is an equal binary kernel: a verified pass is `+1`, a candidate-caused failure is `-1`, and an evaluator or unavailable pinned tool is `INVALID`. Policy 4 ranges from `-5` to `+5` and passes only at `+5`; it checks dependency provenance without requiring candidates to copy the reference implementation's private fields.

## Kernel table

| Kernel | Verifier function | What it asks | Exact implementation | `+1` condition | `-1` condition | Evidence |
|---|---|---|---|---|---|---|
| 4A | `verify_4a_direct_include_ownership()` | Does each standard-library symbol have an intentional owning include? | Scan the header and implementation for mapped `std::` symbols, then compare them with direct includes and recorded project-header ownership | Every used mapped symbol has a valid owning header | A mapped symbol depends on an undeclared or unrelated transitive include | Include manifest, missing-owner list, source digest |
| 4B | `verify_4b_header_self_contained()` | Can `bank_account.h` compile by itself? | Compile a generated translation unit containing only the candidate header and an empty `main` | Strict standalone compilation exits 0 | The header needs another file to include something first | Probe source, compiler log, object digest |
| 4C | `verify_4c_dependency_graph()` | Is the implementation independent of tests and unrelated task files? | Compile the header probe and implementation with GCC dependency-file generation, then inspect task-local dependency paths | Both compile and no test, Catch, or forbidden task asset enters the graph | Compilation relies on a missing owner or forbidden task-local dependency | GCC `.d` files, dependency list, compiler logs |
| 4D | `verify_4d_pinned_dependencies()` | Are the fixed compiler, CMake, Catch, test main, and Threads contract intact? | Check pinned file hashes and CMake declarations, then configure with GCC 13.3 and all tests enabled | Every identity, declaration, and configuration check succeeds | A fixed dependency or build declaration differs from the pinned contract | Tool versions, hashes, CMake log, compile commands |
| 4E | `verify_4e_empty_directory_rebuild()` | Can the executable be recreated without stale artifacts? | Configure a second absent build directory and build only the Bank Account executable target with `--clean-first` | Fresh configure and executable build exit 0 and produce a nonempty executable | A source or dependency problem prevents the clean rebuild | Fresh-build logs, executable digest, source digest |

## Shared verification method

The verifier records a digest of the fixed task assets before any check and rejects mid-run mutation. It accepts only GNU GCC 13.3, writes every command and return code to `verification_receipt.json`, and stores generated probes, compiler dependency files, build logs, and artifact hashes under a new empty output directory.

The reference dependency ownership is simple: `bank_account.h` directly owns `<mutex>` because the public class layout uses `std::mutex`, while `bank_account.cpp` directly owns `<stdexcept>` because it throws `std::runtime_error`. A source may use another correct design, but every mapped standard-library symbol it introduces must still have an intentional owning include.

## 4A — Direct include ownership

The function reads only `bank_account.h` and `bank_account.cpp`, removes comments and literals from the symbol scan, and maps standard-library names such as mutexes, locks, runtime exceptions, atomics, threads, and containers to their defining headers. It records the direct include list for both files.

It returns `+1` when each used mapped symbol has a direct owner. The implementation may use a standard header deliberately owned by its own public header, such as the reference's `<mutex>` path, but it may not obtain `<stdexcept>` or another unrelated facility accidentally through that header.

## 4B — Self-contained public header

The function generates a small source file that includes only `bank_account.h` and defines an empty `main`. It compiles this probe with strict C++17 warning-as-error flags and does not pre-include `<mutex>` or any other standard header.

It returns `+1` when the probe produces a nonempty object. A missing direct header, incomplete member type, malformed declaration, compiler failure caused by candidate code, or timeout returns `-1`; an unavailable pinned compiler is `INVALID`.

## 4C — Dependency graph isolation

The function compiles the header probe and `bank_account.cpp` with GCC `-MD -MF`, preserving both dependency files. It resolves task-local paths and rejects dependencies on `bank_account_test.cpp`, Catch headers, `tests-main.cpp`, or other evaluation-only files.

It returns `+1` when both objects and dependency files are valid, the implementation reaches its own public header, no forbidden test asset appears, and the include-ownership scan finds no missing owner. This overlaps with 4A intentionally: 4A explains the source declaration, while 4C proves the compiler's observed graph.

## 4D — Pinned fixed dependencies

The function verifies the known SHA-256 values of `CMakeLists.txt`, `test/catch.hpp`, and `test/tests-main.cpp`. It checks that CMake requires `Threads`, links `Threads::Threads`, enables C++17, and can configure a fresh all-tests build using the pinned GNU compiler.

It returns `+1` only when every fixed identity and generated configuration fact matches. Candidate or fixture drift returns `-1`; if the fixed hashes match but CMake or Threads cannot run because the evaluation machine is broken, the result is `INVALID` and must be rerun.

## 4E — Empty-directory rebuild

The function requires an absent build path, configures it from scratch, and builds the exercise executable target with `--clean-first`. It does not reuse Policy 1 objects, Policy 2 objects, or any previous CMake cache, and it does not execute the functional assertions.

It returns `+1` when configuration and compilation finish successfully and the resulting executable is a regular nonempty executable. A candidate compile or link defect returns `-1`; an unavailable CMake or compiler process is `INVALID`.

## Aggregation

```text
Policy 4 kernel sum = 4A + 4B + 4C + 4D + 4E
Range               = -5 to +5
Full pass           = +5
```

Any `INVALID` kernel cancels the policy sum and exits 2. A valid full pass exits 0, and a valid result containing any `-1` exits 1.

## Execution

```bash
python3 "Bank_Account Verifiers/verifiers/verifier_04_include_dependency_integrity.py" \
  --exercise-dir <bank-account-directory> \
  --output-dir <new-empty-receipt-directory> \
  --compiler g++ \
  --cmake cmake
```

The output directory receives source manifests, generated probes, dependency files, clean build directories, logs, built artifacts, and the complete JSON receipt.
