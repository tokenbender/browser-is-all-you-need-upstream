# Policy 5 — Feedback-Repair Closure

This policy authenticates a two-turn Allergies repair and decides whether the model removed the reported enum-versus-string diagnostic, avoided leaving a related API incompatibility, and reached a complete 50-test pass. It is derived from four comparable repairs: two complete passes and two partial repairs that moved failure to `get_allergies()`.

## Kernel table

| Kernel | Verifier function | What it asks | Exact implementation | `+1` condition | `-1` condition | Evidence |
|---|---|---|---|---|---|---|
| 5A | `verify_5a_bundle_integrity()` | Is the trajectory evidence complete and hash-bound? | Validate the manifest, safe relative paths, regular files, SHA-256 values, task identity, both turn receipts, and receipt-to-source/output hash bindings | Every required binding is valid | Not used; corrupt evaluator evidence is `INVALID` | Manifest, artifact hashes, task identities |
| 5B | `verify_5b_feedback_binding()` | Was the exact generated feedback delivered to turn 2? | Compare generated and delivered feedback byte-for-byte | Both are nonempty and identical | Not used; missing or changed feedback is `INVALID` | Both feedback files and hashes |
| 5C | `verify_5c_reported_diagnostic_removed()` | Did the repair remove the reported parameter-type failure? | Normalize both evaluation outputs and compare the `api.is_allergic_to.parameter_type` diagnostic | Present at turn 1 and absent at turn 2 | Diagnostic remains or the repair makes no effective progress | Both score receipts and normalized diagnostic IDs |
| 5D | `verify_5d_official_consumer_compile()` | Did the repaired candidate pass the complete official consumer build? | Require authenticated turn-2 compile and link stages to succeed | Turn-2 return code is 0 and no compile/link diagnostic remains | Candidate still fails compilation or linkage, including list-return incompatibility | Turn-2 output, return code, diagnostic IDs |
| 5E | `verify_5e_complete_suite_closure()` | Did the repair reach the complete pinned suite? | Require a successful receipt whose output proves 50 assertions in 50 test cases | Status is `passed`, return code is 0, and the exact 50/50 summary is present | Completed candidate evaluation fails, times out, or lacks complete 50/50 success | Turn-2 score receipt and output hash |

## Trajectory bundle contract

```text
manifest.json
turn_1/
├── response.txt
├── source/allergies.h
├── source/allergies.cpp
├── score_receipt.json
└── generated_feedback.txt
turn_2/
├── delivered_feedback.txt
├── response.txt
├── source/allergies.h
├── source/allergies.cpp
├── score_receipt.json
└── source.diff
```

The manifest contains `schema_version`, `task_id`, `trajectory_kind`, and an `artifacts` object. Each required artifact entry contains a safe relative `path` and lowercase SHA-256 value. `trajectory_kind: single_turn` makes the policy explicitly excluded; omission of required evidence from a declared two-turn bundle is `INVALID`.

## 5A — Bundle integrity

All paths are resolved beneath the bundle without symlinks. JSON receipts must be objects and must identify task `allergies` or `local-aider-cpp/allergies`. Each receipt’s candidate-file hashes must match that turn’s source snapshot, and its output hash must match the recorded output. Hash or identity disagreement is evaluator failure, never candidate `-1`.

## 5B — Exact feedback delivery

Generated and delivered feedback must be byte-identical and nonempty. A candidate cannot be penalized for missing, truncated, or rewritten evaluator feedback.

## 5C — Reported diagnostic removal

The stable diagnostic is recognized from `cannot initialize a parameter of type ... with an lvalue of type const char[...]` together with `is_allergic_to`. It must be present in turn 1 and absent from turn 2.

## 5D — Official consumer compilation

Turn 2 must complete compilation and linkage. Compiler markers such as `error:`, `undefined reference`, `linker command failed`, or a nonzero return code are candidate failure when the authenticated receipt reports a completed evaluation.

## 5E — Complete suite closure

The final receipt must record `status: passed`, return code 0, and the exact Catch summary `All tests passed (50 assertions in 50 test cases)`. Removing only the first diagnostic is insufficient.

## Aggregation

```text
applicable kernels = 5 for a two-turn trajectory
maximum kernel sum = +5
PASS           = all five kernels are +1
FAIL           = at least one candidate kernel is -1 and none is INVALID
INVALID        = at least one kernel is INVALID
NOT_APPLICABLE = trajectory_kind is single_turn; excluded from all denominators
```

## Execution

```bash
python3 "Reward_GRPO/Allergies Verifiers/verifiers/verifier_05_feedback_repair_closure.py" \
  --bundle-dir /path/to/allergies-trajectory \
  --output-dir /new/output/policy-05
```
