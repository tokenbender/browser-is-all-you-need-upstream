# Policy 2 — Specific-Allergy String API

This policy decides whether `allergy_test` exposes the required string-based specific-allergy interface. It is derived from four first-turn failures where the candidate accepted an enum but the official consumer supplied string literals such as `"eggs"`.

## Kernel table

| Kernel | Verifier function | What it asks | Exact implementation | `+1` condition | `-1` condition | Evidence |
|---|---|---|---|---|---|---|
| 2A | `verify_2a_exact_member_signature()` | Does the exact required overload exist? | Cast the member address to `bool (allergy_test::*)(std::string const&) const` | The cast compiles under strict C++17 | Parameter, return, reference, visibility, or const qualification is incompatible | Signature probe, compiler logs, object hash |
| 2B | `verify_2b_string_literal_call()` | Can the official string-literal call shape compile and link? | Invoke `is_allergic_to("eggs")` from an external caller and link with `allergies.cpp` | Compile, link, and run exit 0 | Only an enum API exists, overload resolution fails, or the definition is missing | Caller probe, build/run logs, executable hash |
| 2C | `verify_2c_const_object_call()` | Is the method callable through a const object? | Invoke the method on `allergy_test const` with `std::string` | Compile, link, and run exit 0 | Required const qualification or definition is absent | Const-caller probe, logs, executable hash |

## Shared verification method

The verifier uses the same authenticated fixed assets, immutable candidate-source checks, isolated output directory, GCC identity, safe subprocess execution, timeouts, and receipt schema as Policy 1.

## 2A — Exact overload

The pointer-to-member cast selects the required overload without forbidding extra compatible overloads. A passing historical repair retained an enum overload, so source-text equality or an exact overload count would be an invalid restriction.

## 2B — String-literal call

The external caller reproduces the official expression that triggered `cannot initialize a parameter of type <enum> with an lvalue of type const char[...]`. The returned boolean is consumed without imposing behavioral expectations.

## 2C — Const-object call

This probe proves the declaration and definition remain callable through the pinned const interface. It does not test which allergens should return true.

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
python3 "Reward_GRPO/Allergies Verifiers/verifiers/verifier_02_specific_allergy_string_api.py" \
  --exercise-dir /path/to/allergies \
  --output-dir /new/output/policy-02
```
