# Policy 2: Task semantics and boundary behavior

This policy checks rules that commonly survive a shallow compile check. For Robot Name: Each robot name must match two uppercase letters plus three digits, remain stable until reset, change on reset, and stay unique across allocation.

| Kernel | Binary pass condition | Evidence |
|---|---|---|
| 2A | format_stability behavior matches the independent probe. | Compile/run logs and probe/executable hashes |
| 2B | reset behavior matches the independent probe. | Compile/run logs and probe/executable hashes |
| 2C | uniqueness behavior matches the independent probe. | Compile/run logs and probe/executable hashes |

## Shared method

Each kernel compiles a deterministic probe against the candidate and expects an exact success marker. Probe source and executable are hashed, logs remain outside candidate source, and the source digest is checked again after execution.

## Semantic groups

The groups stay separate so GRPO can see which behavior failed instead of receiving one opaque terminal result. These probes supplement the official suite; they never replace it.

## Aggregation

Every applicable group returns only +1 or -1. An evaluator or contract failure makes the policy INVALID; full policy success requires every group to pass.

## Run

    python3 verifiers/verifier_02_semantic_boundaries.py --exercise-dir TASK --output-dir NEW_EMPTY_DIR
