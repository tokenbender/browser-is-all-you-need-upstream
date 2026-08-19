# Policy 7 — Feedback Repair and Two-Turn Progress

Policy 7 evaluates authenticated trajectory evidence rather than rerunning candidate C++. It decides whether the first response was healthy, feedback reached turn 2 unchanged, the repair targeted the diagnostic, failures decreased, and an 8/8 pass occurred within two turns.

## Kernel table

| Kernel | Verifier function | Exact question | `+1` | `-1` | Evidence |
|---|---|---|---|---|---|
| 7A | `verify_7a_first_response_health()` | Did turn 1 complete with a nonempty response and zero model/context errors? | Healthy response | Declared model/context failure or empty completion | Response and receipt |
| 7B | `verify_7b_feedback_delivery()` | Was generated feedback delivered byte-for-byte? | Nonempty exact match | Omitted or altered feedback | Both feedback artifacts |
| 7C | `verify_7c_targeted_repair()` | Does the turn-2 diff touch a diagnostic target file and token? | Targeted source change | No or unrelated change | Diagnostic and diff |
| 7D | `verify_7d_diagnostic_reduction()` | Did stable diagnostic IDs decrease without phase regression? | Fewer IDs and same/later phase | No reduction or regression | Both evaluations |
| 7E | `verify_7e_pass_within_two_turns()` | Did either turn authenticate 8 selected and 8 passed? | Full pass by turn 2 | No full pass | Evaluation receipts |

## Applicability and aggregation

If turn 1 passes, only 7A and 7E apply and full pass is `+2`. If turn 1 fails, all five apply and full pass is `+5`. Missing or corrupt evidence is `INVALID`.

## Explicit exclusions

- Targeting proves repair intent, not correctness.
- Turn 3 and later are outside the contract.
- Unauthenticated or missing feedback cannot be assumed to be a model failure.

## Execution

```bash
python3 "Reward_GRPO/Grade_School Verifiers/verifiers/verifier_07_feedback_repair_context.py" --bundle-dir <trajectory-bundle> --output-dir <new-empty-output>
```
