# Policy 1 — Namespace and Class Identity

This policy decides whether an external C++17 consumer can name, construct, link, and minimally execute the required `allergies::allergy_test` type. It is derived from repeated diagnostics in which `allergies` was absent, capitalized as `Allergies`, or lacked `allergy_test`.

## Kernel table

| Kernel | Verifier function | What it asks | Exact implementation | `+1` condition | `-1` condition | Evidence |
|---|---|---|---|---|---|---|
| 1A | `verify_1a_required_qualified_name()` | Is `allergies::allergy_test` a public qualified type? | Compile an isolated probe containing a type alias for the required qualified name | Strict compilation exits 0 and creates a nonempty object | Namespace or class is missing, renamed, wrongly capitalized, ambiguous, or inaccessible | Probe, command, compiler logs, object hash |
| 1B | `verify_1b_unsigned_constructor()` | Is the type constructible from `unsigned int`? | Compile a `std::is_constructible_v` assertion and direct construction expression | Both assertions compile | Constructor is missing, inaccessible, deleted, or incompatible | Probe, compiler logs, object hash |
| 1C | `verify_1c_external_construction_link()` | Is the public constructor defined and linkable? | Compile `allergies.cpp` and an external caller separately, link them, then run the executable | Compile, link, and run exit 0 | Candidate declaration or definition prevents construction, linkage, or execution | Two object hashes, executable hash, build/run logs |

## Shared verification method

Preflight authenticates the fixed Allergies task assets, requires regular non-symlink files, validates GNU GCC 13.3, rejects an output directory inside the task, and records the combined candidate source digest. Generated probes and all build products are written below a new empty output directory. Commands use argument lists, `shell=False`, and the configured timeout.

## 1A — Required qualified name

The probe includes only `allergies.h`, aliases `allergies::allergy_test`, and defines an empty `main`. It does not inspect source text or reject additional declarations.

## 1B — Unsigned constructor

The probe asserts public construction from `unsigned int` and creates a local `allergies::allergy_test{0u}`. It does not score `explicit`, private representation, or member names.

## 1C — External construction and linkage

The implementation and caller are compiled independently with C++17 and strict warnings, linked, and executed. Candidate-caused compile, link, crash, or timeout failures score `-1`; inability to start a required tool is `INVALID`.

## Aggregation

```text
applicable kernels = 3
maximum kernel sum = +3
PASS    = all three kernels are +1
FAIL    = at least one kernel is -1 and none is INVALID
INVALID = at least one kernel is INVALID
```

## Execution

```bash
python3 "Reward_GRPO/Allergies Verifiers/verifiers/verifier_01_namespace_class_identity.py" \
  --exercise-dir /path/to/allergies \
  --output-dir /new/output/policy-01
```
