# Policy 3: Authenticated official functional behavior

This is the authoritative terminal policy for Clock. A candidate is not accepted unless the exact pinned official test file compiles, links, executes, and reports that all selected tests passed.

| Kernel | Binary pass condition | Evidence |
|---|---|---|
| 3A | Every protected task, Catch2, metadata, and build asset matches pinned SHA-256. | Fixed-asset hash map |
| 3B | The full official executable compiles and links with EXERCISM_RUN_ALL_TESTS. | Build log and executable hash |
| 3C | The executable exits 0 and Catch2 reports All tests passed. | Complete stdout/stderr and exit code |

## Shared method

Third-party Catch2 code is compiled without turning its own pedantic diagnostics into candidate failures. Candidate warning cleanliness remains Policy 1 responsibility, while this policy preserves the exact official behavioral oracle.

## 3A

Authentication prevents test weakening, identity changes, or dependency replacement. Any mismatch is INVALID, not candidate -1.

## 3B

The build enables every selected test and includes only pinned caller assets and candidate implementation. Candidate compile or link failure receives -1.

## 3C

The executable must terminate within timeout, exit 0, and emit Catch2 all-tests-passed marker. This is the mandatory semantic gate for standalone scoring.

## Aggregation

The kernel sum ranges from -3 to +3. Canonical task success requires all three kernels to return +1.

## Run

    python3 verifiers/verifier_03_official_functional_behavior.py --exercise-dir TASK --output-dir NEW_EMPTY_DIR
