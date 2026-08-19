# Policy 3 — Allergy-List Return Contract

This policy decides whether `get_allergies()` returns the exact string-set type consumed by the pinned tests. It is derived from one historical `vector<string>` mismatch and two repair attempts that returned an `unordered_set` of enum values.

## Kernel table

| Kernel | Verifier function | What it asks | Exact implementation | `+1` condition | `-1` condition | Evidence |
|---|---|---|---|---|---|---|
| 3A | `verify_3a_exact_return_signature()` | Does the exact list method exist? | Cast the member address to `std::unordered_set<std::string> (allergy_test::*)() const` | The cast compiles under strict C++17 | Container, element type, visibility, parameters, or const qualification is incompatible | Signature probe, compiler logs, object hash |
| 3B | `verify_3b_string_set_consumer()` | Can the result participate in the official string-set comparison? | Compile and link a caller comparing an empty `unordered_set<string>` with `get_allergies()` | Compile, link, and run exit 0 | Candidate returns a vector, enum set, or other incompatible type, or lacks a definition | Consumer probe, build/run logs, executable hash |

## Shared verification method

The verifier authenticates the task and toolchain before scoring, writes only to a new external output directory, uses strict argument-list subprocesses, binds every generated artifact by SHA-256, and proves the editable sources did not change.

## 3A — Exact return signature

The pointer-to-member cast checks the public contract without depending on private representation or requiring the example implementation's `ALLERGENS` map.

## 3B — String-set consumer

The probe recreates the comparison shape responsible for the logged compiler failures. Its return code does not depend on the contents of the set; semantic correctness belongs to a separate contract-derived policy.

## Aggregation

```text
applicable kernels = 2
maximum kernel sum = +2
PASS    = both kernels are +1
FAIL    = at least one kernel is -1 and neither is INVALID
INVALID = at least one kernel is INVALID
```

## Execution

```bash
python3 "Reward_GRPO/Allergies Verifiers/verifiers/verifier_03_allergy_list_return_contract.py" \
  --exercise-dir /path/to/allergies \
  --output-dir /new/output/policy-03
```
