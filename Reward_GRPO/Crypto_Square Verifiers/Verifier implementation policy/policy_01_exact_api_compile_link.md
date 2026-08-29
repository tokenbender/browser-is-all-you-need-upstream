# Policy 1: Exact public API, compile, and link

This policy asks one narrow question: can the candidate be consumed through the pinned Crypto Square interface and become a runnable C++17 program?

| Kernel | Binary pass condition | Evidence |
|---|---|---|
| 1A | Required namespace, class/function names, and basic calls compile with GCC 13.3 and strict warnings. | Compiler log and object hash |
| 1B | Exact public parameter, return, const, and reference types compile through static assertions. | Signature-probe source and compiler log |
| 1C | Candidate definitions link with a real caller and the caller exits 0 with exact output. | Link/run logs and executable hash |

## Shared method

The verifier authenticates pinned non-candidate task assets, hashes candidate source before execution, writes probes outside the exercise tree, and invokes the compiler without a shell. A changed contract asset or unavailable compiler is INVALID; candidate compile or link errors are -1.

## 1A

The names probe includes the public header and makes normal calls. It catches wrong namespaces, missing symbols, inaccessible public members, and headers that cannot stand on their own.

## 1B

The signature probe uses compile-time type checks. It rejects candidates that change argument types, return types, constness, references, or required container shapes.

## 1C

The link probe combines the caller with candidate implementation and runs one minimal check. Unresolved symbols and namespace-definition mistakes receive -1; exact success receives +1.

## Aggregation

The kernel sum ranges from -3 to +3. Full policy success requires all three kernels to return +1.

## Run

    python3 verifiers/verifier_01_exact_api_compile_link.py --exercise-dir TASK --output-dir NEW_EMPTY_DIR
