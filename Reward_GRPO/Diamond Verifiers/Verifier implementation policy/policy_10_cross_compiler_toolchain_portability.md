# Policy 10 — Cross-Compiler and Toolchain Portability

Policy 10 proves that the same candidate remains warning-clean and correct under host Clang and an immutable offline Clang environment.

## Kernel table

| Kernel | Function | Verification | `+1` | `-1` | Evidence |
|---|---|---|---|---|---|
| 10A | `verify_10a_clang_warning_clean_compile()` | Strictly compile implementation, official caller, Catch main, API probe with Clang 18.1.3 | All objects | Candidate warning/error/timeout | Identity, logs, object hashes |
| 10B | `verify_10b_clang_link_and_tests()` | Independent Clang link and official run | Exactly 5/5 | Candidate link/test/crash/timeout | Build/run logs and binary hash |
| 10C | `verify_10c_clean_reproduction()` | Digest-pinned offline container, read-only source, empty build | Clean configure/build and 5/5 | Candidate rejection in valid environment | Image identity, commands, logs |

## Method and aggregation

The pinned image is `silkeh/clang@sha256:9388794775d1393c16b6897b4775b6d3e29459319de0bfafec59a20262e1fa68`. Container configure, build, and test use separate subprocess argument lists with `--network none`. Full pass is `+3`.

## Exclusions

Missing Docker or image is `INVALID`; the verifier never pulls or uses network access. Policy 10 does not replace the primary GCC policies.

## Execution

```bash
python3 "Reward_GRPO/Diamond Verifiers/verifiers/verifier_10_cross_compiler_toolchain_portability.py" --exercise-dir <diamond> --output-dir <new-output>
```
