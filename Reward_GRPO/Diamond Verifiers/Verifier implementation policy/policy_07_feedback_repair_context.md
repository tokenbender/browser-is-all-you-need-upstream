# Policy 7 — Feedback Repair and Non-Regression

Policy 7 authenticates a two-turn trajectory; it does not rerun candidate code.

## Kernel table

| Kernel | Function | Verification | `+1` | `-1` | Evidence |
|---|---|---|---|---|---|
| 7A | `verify_7a_first_response_health()` | Turn-one response and receipt | Nonempty completed response; zero model/context errors | Empty/error/exhausted response | Response, receipt, hashes |
| 7B | `verify_7b_feedback_delivery()` | Generated versus delivered feedback | Nonempty byte-identical feedback | Missing/truncated/rewritten feedback | Both artifacts and hashes |
| 7C | `verify_7c_targeted_repair()` | Turn-two diff versus diagnostic files/tokens | Real relevant authorized edit | No edit or unrelated edit | Diagnostics, snapshots, diff |
| 7D | `verify_7d_diagnostic_reduction()` | Diagnostic IDs and phase order | Fewer original IDs and no regression | Persistent/increased IDs or phase regression | Both evaluation receipts |
| 7E | `verify_7e_pass_within_two_turns()` | Earliest authenticated complete pass | Exactly 5 selected and 5 passed by turn two | No complete pass | Per-turn receipts and hashes |

## Applicability and aggregation

Phase order is `format-or-apply < compile < link < tests < pass`. If turn one passes, only 7A and 7E apply and full pass is `+2`; 7B-7D are excluded as `not_needed_first_turn_pass`. Otherwise full pass is `+5`.

## Exclusions

Missing/corrupt evidence is `INVALID`. First-turn success never earns automatic repair points.

## Execution

```bash
python3 "Reward_GRPO/Diamond Verifiers/verifiers/verifier_07_feedback_repair_context.py" --bundle-dir <trajectory-bundle> --output-dir <new-output>
```
