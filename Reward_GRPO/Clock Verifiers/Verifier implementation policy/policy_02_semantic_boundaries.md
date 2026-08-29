# Policy 2: Task semantics and boundary behavior

This policy checks rules that commonly survive a shallow compile check. For Clock: A date-independent 24-hour clock must normalize arbitrary positive and negative times, format HH:MM exactly, support plus/minus, and compare normalized values.

| Kernel | Binary pass condition | Evidence |
|---|---|---|
| 2A | normalization behavior matches the independent probe. | Compile/run logs and probe/executable hashes |
| 2B | arithmetic behavior matches the independent probe. | Compile/run logs and probe/executable hashes |
| 2C | format_equality behavior matches the independent probe. | Compile/run logs and probe/executable hashes |

## Shared method

Each kernel compiles a deterministic probe against the candidate and expects an exact success marker. Probe source and executable are hashed, logs remain outside candidate source, and the source digest is checked again after execution.

## Semantic groups

The groups stay separate so GRPO can see which behavior failed instead of receiving one opaque terminal result. These probes supplement the official suite; they never replace it.

## Aggregation

Every applicable group returns only +1 or -1. An evaluator or contract failure makes the policy INVALID; full policy success requires every group to pass.

## Run

    python3 verifiers/verifier_02_semantic_boundaries.py --exercise-dir TASK --output-dir NEW_EMPTY_DIR
