# Policy 3 — Public API Contract Verification

Policy 3 answers whether the Bank Account candidate exposes the exact public interface required by the task. It separates header independence, public names, parameter and return types, declaration qualifiers, and a linked runtime smoke probe so each API boundary has its own receipt.

Every check is an equal binary kernel: a verified pass is `+1`, a candidate-caused failure is `-1`, and an evaluator or toolchain fault is `INVALID`. Policy 3 ranges from `-5` to `+5` and passes only at `+5`; private field names and private implementation helpers are never prescribed.

## Kernel table

| Kernel | Verifier function | What it asks | Exact implementation | `+1` condition | `-1` condition | Evidence |
|---|---|---|---|---|---|---|
| 3A | `verify_3a_header_self_contained()` | Can the public header stand alone? | Compile a translation unit containing only `bank_account.h` and an empty `main` | Standalone header probe compiles | Header requires an include or declaration supplied elsewhere | Probe source, compiler log, source digest |
| 3B | `verify_3b_public_names()` | Are the required namespace, class, constructor, and method names public? | Compile an external caller using `Bankaccount::Bankaccount`, `open`, `deposit`, `withdraw`, `close`, and `balance` | Every required name is accessible and callable | A required name is missing, renamed, ambiguous, or private | Public-name probe and compiler log |
| 3C | `verify_3c_exact_signatures()` | Do parameters and return types match? | Cast each member address to the required pointer-to-member type | All five casts compile | A parameter, return type, const/ref qualifier, or overload set lacks the exact required form | Signature probe and compiler log |
| 3D | `verify_3d_qualifiers_visibility_exceptions()` | Do constness, visibility, and exception declarations match? | Check external invocability, non-const member behavior, and absence of incompatible `noexcept` declarations | Every declaration-level assertion compiles | A required member is inaccessible, callable on a const object, or incorrectly `noexcept` | Contract probe and compiler log |
| 3E | `verify_3e_api_probe_runtime()` | Are the declared API symbols defined and minimally callable? | Compile and link the implementation with a valid API sequence, then run it under timeout | Build, link, and smoke execution exit 0 | Definition is missing/incompatible or the legal sequence throws, crashes, or times out | Build/run logs and executable digest |

## Shared verification method

The verifier generates four small C++ probes and compiles them outside the candidate source directory. Each probe includes the real candidate header, and every command, return code, generated probe digest, compiler log, and source digest is written into `verification_receipt.json`.

The verifier accepts only GNU GCC 13.3. A missing compiler, altered fixed task fixture, unreadable source, or evaluator I/O failure is `INVALID`; a declaration, compilation, linkage, or candidate-runtime problem is `-1`.

## 3A — Self-contained header

The function generates the smallest possible consumer: it includes `bank_account.h` and defines an empty `main`. It deliberately includes no standard-library header first, so the public header must provide everything needed to parse its own declarations and private member types.

It returns `+1` when this translation unit compiles cleanly. A missing `<mutex>`, incomplete member type, malformed guard, or other header dependency returns `-1`; a missing fixed source asset is `INVALID`.

## 3B — Public namespace and names

The function instantiates `Bankaccount::Bankaccount` from external code and forms valid calls to `open()`, `deposit(int)`, `withdraw(int)`, `balance()`, and `close()`. It compiles only, so operation order does not create a functional judgment here.

It returns `+1` when the namespace, class, constructor, and all five method names are externally accessible. A renamed namespace, replacement class, missing method, private required member, or uncallable name returns `-1`.

## 3C — Exact parameter and return types

The function converts each required member address to its required pointer type: three `void (Account::*)()` forms, two `void (Account::*)(int)` forms, and one `int (Account::*)()` form as applicable. The explicit cast accepts a compatible non-`noexcept` target while rejecting the wrong parameter, return, const, or reference form.

It returns `+1` only when every required member has an exact selectable signature. A `long` amount, reference parameter, const-qualified `balance`, wrong return type, or incompatible overload set returns `-1`.

## 3D — Qualifiers, visibility, and exception declaration

The function uses external member addresses and `std::is_invocable` assertions to confirm that required methods are public and operate on a mutable account, not a const account. It separately evaluates `noexcept(...)` for every operation because each required method may report invalid state with an exception.

It returns `+1` when all external-access, non-const, and potentially-throwing declarations match. A private method, const-callable required operation, ref-qualified mismatch, or incompatible `noexcept` declaration returns `-1`; actual exception behavior belongs to Policy 5.

## 3E — Linked API smoke probe

The function compiles `bank_account.cpp` together with a generated program that constructs an account and performs `open → deposit(1) → withdraw(1) → balance → close`. It links with pthread support and then runs the executable under a short timeout.

It returns `+1` when compilation, linkage, and the legal sequence exit 0. A missing definition, wrong symbol, unexpected exception, native crash, or timeout returns `-1`; the probe does not replace the complete 17-test functional policy.

## Aggregation

```text
Policy 3 kernel sum = 3A + 3B + 3C + 3D + 3E
Range               = -5 to +5
Full pass           = +5
```

Any `INVALID` kernel cancels the policy sum and exits 2. A valid full pass exits 0, and a valid result containing any `-1` exits 1.

## Execution

```bash
python3 "Bank_Account Verifiers/verifiers/verifier_03_public_api_contract.py" \
  --exercise-dir <bank-account-directory> \
  --output-dir <new-empty-receipt-directory> \
  --compiler g++
```

The output directory receives the generated probes, their logs, the API smoke executable when linking succeeds, and the complete JSON receipt.
