# Global Verifiers Set 2 vs. Topic-Specific Verifiers

## Execution model

A topic-specific verifier embeds a task's API names, source filenames, build
commands, expected behavior, and edge cases directly in its Python verifier
package. Adding another topic normally means copying or writing new Python
policies and then validating that new code.

Global Verifiers Set 2 separates reusable execution from task knowledge. The
same ten Python modules reconstruct, authenticate, compile, link, test, sandbox,
and report every candidate. A task bundle supplies the task-specific facts as
immutable, hash-authenticated data. Adding a task therefore creates a new bundle;
it must not require edits to the global Python modules.

| Stage or policy | Topic-specific execution | Global Verifiers Set 2 execution | Task-specific input used by Set 2 |
|---|---|---|---|
| Candidate reconstruction | Python code usually names the expected `.h`/`.cpp` files and overlays them according to that task | `candidate_reconstruction.py` applies the same safe overlay algorithm for every task | `manifest.json` supplies `editable_files`; `starter/` supplies omitted unchanged files |
| G01 — integrity | A task package hard-codes protected filenames and expected hashes | `g01_integrity.py` checks arbitrary safe relative paths and SHA-256 values | `manifest.json` supplies `protected_files`; the bundle contains the authenticated assets |
| Dependency preflight | Task verifier code checks its expected compiler, CMake packages, Boost libraries, or other tools | `runner.py` executes authenticated argument arrays before candidate scoring and maps evaluator faults to `INVALID` | `manifest.json` supplies `preflight_commands`, compiler identity, libraries, and limits |
| G02 — strict build | Python verifier embeds task filenames, flags, include paths, and compile commands | `g02_build.py` compiles manifest-listed translation units once and classifies warning, compilation, timeout, and tool failures | `manifest.json` supplies C++ standard, flags, source files, include directories, and libraries |
| G03 — API structure | Task verifier contains explicit namespace, class, constructor, and method checks | `g03_api_link.py` reads declaration requirements, obtains a Clang AST, and compares it without knowing the task name | `public_api.json` or an immutable contract header describes required declarations; `manifest.json` selects it |
| G03 — linkage | Task verifier generates or embeds a caller written specifically for that task | The global linker compiles the authenticated caller and links it with objects preserved from G02 | `api_caller.cpp` contains the task-specific calls and template instantiations |
| G04 — functional correctness | Python verifier embeds task assertions, expected values, or invokes a task-owned test script | `g04_functional.py` authenticates and runs a supplied semantic oracle under common limits and returns a test fraction | `official_tests.cpp`, a reference oracle, or machine-readable properties provide semantic truth |
| G05 — safety | Each task package writes its own sanitizer compilation and workload logic | `g05_safety.py` applies common ASan/UBSan handling to the manifest-defined sources and official workload | Build sources and `official_tests.cpp` supply code paths that must be exercised |
| G07 — portability | Task code separately implements GCC/Clang checks | `g07_portability.py` repeats the authenticated build and functional workload with manifest-selected compilers | `manifest.json` supplies supported compilers, flags, dependencies, and tests |
| Failure classification | Individual task packages may use different error schemas | `receipt.py` consistently emits `PASS`, `FAIL`, `INVALID`, or `NOT_RUN` | The task identity and manifest digest bind every receipt to the correct bundle |
| Isolation | Every task package may reproduce sandbox commands independently | `sandbox.py` provides one networkless, capability-dropped, resource-limited execution boundary | The bundle supplies limits and the pinned runtime image; it does not change sandbox logic |
| Policy ordering | Task verifier code decides which policies run and may repeat compilation | `runner.py` enforces reconstruction → G01 → preflight → G02 → G03 → G04, followed optionally by G05/G07 | The manifest enables task capabilities but cannot bypass mandatory prerequisites |

## Why the task bundle is necessary

The task bundle is the data adapter between a specific exercise and the portable
global engine. The global Python modules deliberately contain no task names,
function names, expected answers, or hidden semantic rules. Consequently, the
bundle must provide everything that changes between tasks.

| Bundle asset | Information it supplies | Why the global engine cannot infer it safely |
|---|---|---|
| `manifest.json` | Task ID, contract version, editable files, protected hashes, build settings, dependencies, policy inputs, limits, and runtime identity | Source discovery and compiler defaults are ambiguous and environment-dependent |
| `instructions.md` | Model-visible problem statement and public API contract | The verifier must authenticate that training and evaluation describe the same task |
| `public_api.json` or immutable contract header | Required namespaces, types, visibility, signatures, templates, and qualifiers | Compilable code does not prove that callers can use the required interface |
| `starter/` | Pristine editable-file baseline | A valid Aider response may omit a file that was not changed |
| `api_caller.cpp` | Concrete use of every required public symbol and required template instantiation | AST shape alone does not prove that the complete caller links successfully |
| `official_tests.cpp` | Expected behavior and edge cases | API signatures describe how to call code, not which results are correct |
| Optional reference implementation | Differential oracle for generated or exhaustive inputs | Some semantic spaces cannot be covered adequately by a fixed test list |
| Protected-asset SHA-256 values | Exact identity of tests, contracts, callers, and instructions | Without hashes, a modified test or stale contract could grant an invalid reward |

These files **fetch and bind the important information for a specific task**,
but they are not hidden Python verifiers. The global policies interpret the same
bundle schema for every task. Task-specific semantics remain unavoidable in
`official_tests.cpp` or another oracle because no general program can determine
arbitrary intended behavior from a function signature alone.

## Portability rule

A new compatible C++ task is onboarded by creating and validating a new task
bundle. If onboarding requires adding a task name, API signature, expected value,
or special-case branch to one of the ten Python modules, the design boundary has
been violated and the change should remain in the bundle instead.
