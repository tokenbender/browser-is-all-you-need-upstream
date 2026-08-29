# Policy 07: Feedback repair and two-turn convergence

## Purpose

Authenticate a two-turn trajectory and distinguish exact feedback delivery, targeted repair, diagnostic progress, and final functional success.

## Kernels

| ID | Function | Claim |
|---|---|---|
| 7a | `verify_7a_first_response_health` | Turn-one response is complete, parseable, and not context-exhausted |
| 7b | `verify_7b_exact_feedback_delivery` | Generated and delivered feedback bytes are identical |
| 7c | `verify_7c_targeted_repair` | Turn-two diff changes an authorized diagnosed source |
| 7d | `verify_7d_diagnostic_reduction` | Turn two removes diagnostics or advances the failing stage |
| 7e | `verify_7e_pass_within_two_turns` | Authenticated 18/18 success occurs by turn two |

## Evidence bundle

The hash-bound manifest references both raw responses, parser receipts, source snapshots, evaluation receipts, generated and delivered feedback, and the second-turn diff. Missing or inconsistent evidence is `INVALID`.

`bundle_manifest.json` has `schema_version: 1`, `task_id: local-aider-cpp/sublist`, and an `artifacts` object. Every artifact entry contains a safe relative `path` and lowercase `sha256`. A first-turn-pass bundle requires `turn_1_response`, `turn_1_parser_receipt`, and `turn_1_evaluation_receipt`. A repair bundle additionally requires `feedback_generated`, `feedback_delivered`, `turn_2_response`, `turn_2_parser_receipt`, `turn_1_source_snapshot`, `turn_2_source_snapshot`, `turn_2_diff`, and `turn_2_evaluation_receipt`.

## Applicability and aggregation

If turn one passes, 7b–7d are excluded as `repair_not_required`; 7a and 7e remain applicable. Otherwise all five apply. Candidate exhaustion or failure to repair is `-1` when the completed evidence proves it.

## Command

`python3 verifier_07_feedback_repair_two_turn_convergence.py --bundle-dir BUNDLE --output-dir OUTPUT`
