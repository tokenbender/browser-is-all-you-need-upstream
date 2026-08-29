# Policy 5: Factory, observer, and one-definition discipline

Two eval repairs used instance state from static `at()`, modified state inside the `const` string observer, or defined the same functions in both header and source. This policy targets that object-model damage.

| Kernel | Binary pass condition | Evidence |
|---|---|---|
| 5A | `at`, `plus`, `minus`, equality, and string conversion expose the pinned callable types. | Strict compile/link receipt and hashes |
| 5B | A `const clock` can be formatted repeatedly without mutation, while the static factory creates independent values. | Probe compile/run logs and hashes |
| 5C | Including the header in a separate caller and linking `clock.cpp` produces no duplicate or missing definitions. | Link log and executable hash |

The verifier compiles an external caller together with the candidate implementation. That naturally catches invalid static access, illegal `const` mutation, and non-inline duplicate definitions without inspecting private source text.

All kernels use `+1/-1`; tool or contract failures are `INVALID`.

## Run

    python3 verifiers/verifier_05_factory_observer_odr.py --exercise-dir TASK --output-dir NEW_EMPTY_DIR
