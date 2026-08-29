# Policy G02 — Two-Stage Build

## Purpose

Separate compilation failures from linkage failures so the reward signal and feedback distinguish syntax/declaration defects (CE) from missing definitions and template-placement defects (LE).

| Kernel | Question | `+1` | `-1` | `INVALID` |
|---|---|---|---|---|
| G02-1 | Does the candidate compile standalone under the strict flag set? | Clean `-c` compile | Compile error (CE-1) | Build engine unavailable |
| G02-2 | Does the candidate compile and link against the official test? | Clean compile+link | Test-side compile error (CE-2) or link error (LE) | Test assets unusable |

## Shared method

Stage 1 compiles the candidate translation unit alone (`g++ -std=c++17 -Wall -Wextra -Wpedantic -Werror -c`). Stage 2 compiles the official test with the candidate and links. Linker errors are detected via `undefined reference` diagnostics and reported with the missing definition named.

## Aggregation

Two kernels; each stage independent. A single-stage build previously lumped both failure kinds into one opaque compile error; the split keeps the learning signal attributable.

## Execution

`python verifier_02_two_stage_build.py --candidate-dir TASK --manifest MANIFEST --expected-manifest-sha256 DIGEST --output-dir OUT`

## Evidence

`generalized_verifier_docs/validation/VALIDATION.md` (CE vs LE separation on recorded cases; reference passes both stages).
