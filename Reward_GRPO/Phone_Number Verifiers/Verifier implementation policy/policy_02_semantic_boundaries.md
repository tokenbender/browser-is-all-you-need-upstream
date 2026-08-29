# Policy 2: Task semantics and boundary behavior

This policy checks rules that commonly survive a shallow compile check. For Phone Number: North American numbers must be cleaned only from allowed formatting, accept an optional leading 1, enforce area and exchange prefixes 2-9, reject bad input, and format exactly.

| Kernel | Binary pass condition | Evidence |
|---|---|---|
| 2A | clean_and_format behavior matches the independent probe. | Compile/run logs and probe/executable hashes |
| 2B | length_and_characters behavior matches the independent probe. | Compile/run logs and probe/executable hashes |
| 2C | nanp_prefixes behavior matches the independent probe. | Compile/run logs and probe/executable hashes |

## Shared method

Each kernel compiles a deterministic probe against the candidate and expects an exact success marker. Probe source and executable are hashed, logs remain outside candidate source, and the source digest is checked again after execution.

## Semantic groups

The groups stay separate so GRPO can see which behavior failed instead of receiving one opaque terminal result. These probes supplement the official suite; they never replace it.

## Aggregation

Every applicable group returns only +1 or -1. An evaluator or contract failure makes the policy INVALID; full policy success requires every group to pass.

## Run

    python3 verifiers/verifier_02_semantic_boundaries.py --exercise-dir TASK --output-dir NEW_EMPTY_DIR
