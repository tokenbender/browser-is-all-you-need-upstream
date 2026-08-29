# Policy 5: Sanitized extended oracle

A correct-looking small matrix may still use out-of-range coordinates. This policy combines an independent oracle with sanitizer-backed execution for larger sizes.

| Kernel | Binary pass condition | Evidence |
|---|---|---|
| 5A | Sizes 6–40 exactly match an independent spiral oracle. | Probe compile/run logs and hashes |
| 5B | Sizes 1–64 are square permutations of `1..n²`. | Probe compile/run logs and hashes |
| 5C | The extended probe passes under AddressSanitizer and UndefinedBehaviorSanitizer. | Sanitized compile/run logs and executable hash |

The oracle is generated in verifier-owned source outside the candidate directory. Sanitizer availability is part of the pinned evaluator environment; a missing sanitizer runtime makes the run `INVALID`, not a candidate failure.

The sanitizer kernel is more expensive and can run periodically, while Policy 4 and the official gate remain suitable for routine scoring.

## Run

    python3 verifiers/verifier_05_sanitized_extended_oracle.py --exercise-dir TASK --output-dir NEW_EMPTY_DIR
