# Policy 7 — Feedback Repair and Context Capacity

Policy 7 answers whether a Bank Account model attempt stayed healthy, received authentic failure feedback, made a repair in the reported region, reduced that failure, and passed within the two-turn budget. It evaluates saved trajectory evidence; it does not rerun or reinterpret the C++ candidate.

Every applicable condition is an equal binary kernel: a verified pass is `+1`, a model- or candidate-caused failure is `-1`, and missing, corrupt, or contradictory evaluator evidence is `INVALID`. When turn 1 already passes, only 7A and 7E apply; 7B–7D are recorded as `not_needed_first_turn_pass` and are not scored.

## Kernel table

| Kernel | Verifier function | What it asks | Exact implementation | `+1` condition | `-1` condition | Evidence |
|---|---|---|---|---|---|---|
| 7A | `verify_7a_first_response_health()` | Did the first response complete without a model or context failure? | Read the hash-bound turn-1 response and response receipt | Response is nonempty, status is `completed`, and both error counters are zero | Status reports a model/context failure, a counter is nonzero, or a completed response is empty | Raw response, response receipt, SHA-256 values |
| 7B | `verify_7b_feedback_delivery()` | Was the exact evaluator feedback delivered to turn 2? | Compare the generated-feedback and delivered-feedback bytes and hashes | Both artifacts are nonempty and byte-identical | Feedback is omitted, truncated, rewritten, or delivered differently | Both feedback artifacts and SHA-256 values |
| 7C | `verify_7c_targeted_repair()` | Did the second edit touch a region named by the first failure? | Parse the turn-2 unified diff and match changed files plus diagnostic target tokens | A real source change touches a diagnostic target file and its target token appears in that file's diff block | No source change or only unrelated files/regions are edited | Turn-1 diagnostics, source snapshots, unified diff |
| 7D | `verify_7d_diagnostic_reduction()` | Did the second attempt remove or reduce the reported failure without moving backward? | Compare stable diagnostic IDs and ordered evaluation phases between turns | Fewer turn-1 diagnostic IDs remain and the evaluation phase does not regress | The diagnostic count does not fall or evaluation regresses | Both evaluation receipts and diagnostic IDs |
| 7E | `verify_7e_pass_within_two_turns()` | Did Bank Account pass the complete parent suite by turn 2? | Inspect both evaluation receipts and accept the earliest authenticated full pass | Turn 1 or 2 records 17 selected, 17 passed, no timeout, and `passed=true` | Neither turn records a complete 17/17 pass | Per-turn official-test receipts and hashes |

## Trajectory bundle contract

The verifier takes a directory containing `trajectory_bundle.json`. The manifest uses relative paths only, rejects path traversal and symlinks, and binds every referenced artifact by SHA-256.

```json
{
  "schema_version": 1,
  "task_id": "bank-account",
  "turn_limit": 2,
  "turns": [
    {
      "turn": 1,
      "response": {"path": "turn1/response.txt", "sha256": "..."},
      "response_receipt": {"path": "turn1/response_receipt.json", "sha256": "..."},
      "source_snapshot": {"path": "turn1/source.txt", "sha256": "..."},
      "evaluation_receipt": {"path": "turn1/evaluation.json", "sha256": "..."},
      "generated_feedback": {"path": "turn1/feedback.txt", "sha256": "..."}
    },
    {
      "turn": 2,
      "delivered_feedback": {"path": "turn2/feedback.txt", "sha256": "..."},
      "response": {"path": "turn2/response.txt", "sha256": "..."},
      "response_receipt": {"path": "turn2/response_receipt.json", "sha256": "..."},
      "source_snapshot": {"path": "turn2/source.txt", "sha256": "..."},
      "edit_diff": {"path": "turn2/edit.diff", "sha256": "..."},
      "evaluation_receipt": {"path": "turn2/evaluation.json", "sha256": "..."}
    }
  ]
}
```

Each response receipt contains `status`, `num_error_outputs`, and `num_exhausted_context_windows`. Each evaluation receipt contains `task_id`, `phase`, `official_test_count`, `passed_test_count`, `passed`, `timed_out`, and `diagnostics`; every diagnostic has a stable `id`, at least one `target_file`, and at least one `target_token`.

## 7A — First-response health

The function verifies the turn-1 response and its receipt before reading their meaning. A completed response must contain non-whitespace text, have status `completed`, and record zero model-error outputs and zero exhausted context windows.

It returns `-1` for a declared model error, context exhaustion, nonzero error counter, or empty completed response. A missing receipt or bad hash is `INVALID` because the verifier cannot distinguish candidate behavior from lost evidence.

## 7B — Exact feedback delivery

This function applies only after an authenticated turn-1 failure. It compares the evaluator's generated feedback with the feedback supplied to turn 2 using both file bytes and the manifest-bound hashes.

It returns `+1` only for a nonempty byte-for-byte match. Missing delivery, shortening, paraphrasing, or adding unrelated text returns `-1`; corrupt artifacts or contradictory hashes are `INVALID`.

## 7C — Targeted second edit

The function parses the unified diff into changed file blocks. It then compares those blocks with the target files and target tokens recorded by the trusted turn-1 evaluator, such as `bank_account.cpp` and `Bankaccount::open` for the reopen-balance failure.

It returns `+1` when the source snapshot changed and at least one reported diagnostic is localized by both file and token in the relevant diff block. This proves that the edit was aimed at reported code; it does not prove that the repair was semantically correct.

## 7D — Diagnostic reduction

The function compares stable diagnostic IDs from the two evaluation receipts. It also orders the evaluation stages as `compile`, `link`, `tests`, and `pass` so a disappearing compiler error followed by an earlier configuration failure cannot be called progress.

It returns `+1` when fewer turn-1 IDs remain and the second evaluation reaches the same or a later stage. A persistent diagnostic, increased occurrence count, or phase regression returns `-1`; 7E separately decides whether the entire task passed.

## 7E — Pass within two turns

The function checks turn 1 first and then turn 2. A valid pass requires the Bank Account task identity, exactly 17 official tests selected, exactly 17 passed, `passed=true`, and no timeout.

It returns `+1` for the earliest complete pass. A partial suite, failed assertion, compiler failure, timeout, or absence of a pass by the end of turn 2 returns `-1`.

## Applicability and aggregation

```text
Turn 1 passes:
  Policy 7 kernel sum = 7A + 7E
  Applicable range    = -2 to +2
  Full pass           = +2
  7B, 7C, 7D          = excluded as not needed

Turn 1 fails:
  Policy 7 kernel sum = 7A + 7B + 7C + 7D + 7E
  Applicable range    = -5 to +5
  Full pass           = +5
```

Any applicable `INVALID` kernel cancels the policy sum and exits 2. A valid full pass exits 0, and a valid result containing any `-1` exits 1.

## Execution

```bash
python3 "Bank_Account Verifiers/verifiers/verifier_07_feedback_repair_context.py" \
  --bundle-dir <hash-bound-bank-account-trajectory-directory> \
  --output-dir <new-empty-receipt-directory>
```

The output directory receives `verification_receipt.json`. The input bundle remains read-only and its manifest digest is recorded.
