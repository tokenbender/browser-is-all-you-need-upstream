# Policy 8 — Aider Response and Harness Integrity

Policy 8 decides whether a Grade School response is a valid effective Aider whole-file edit, stays within the authorized files, has clean response counters, completes evaluation, and retains a consistent hash-bound evidence chain.

## Kernel table

| Kernel | Verifier function | Exact question | `+1` | `-1` | Evidence |
|---|---|---|---|---|---|
| 8A | `verify_8a_aider_response_parse()` | Does the pinned parser accept at least one exact file listing? | `format_valid=true` | Reject or recovery-only parse | Raw response and parser result |
| 8B | `verify_8b_authorized_scope()` | Are parsed and changed files limited to the two editable files? | Authorized subset | Protected or unknown file | Parser and tree diff |
| 8C | `verify_8c_effective_change()` | Did parsed files produce real matching byte changes? | Nonempty exact parsed/changed set | No-op or unparsed change | Before/after hashes |
| 8D | `verify_8d_quality_and_compile()` | Are four response counters zero and compilation successful? | Clean counters and compiler pass | Counter or candidate compile failure | Harness receipt |
| 8E | `verify_8e_evaluation_completion()` | Did evaluation complete within its pinned limit? | Complete, in time, zero timeouts | Candidate crash/timeout | Timing receipt |
| 8F | `verify_8f_receipt_integrity()` | Do task, response, parser, tree, changed-file, log, and outcome bindings agree? | All bindings agree | Honest candidate failure may still pass | Recomputed hashes |

## Aggregation

The range is `-6` to `+6`; full pass is `+6`. The parser source hash is `82558ec14d4ed56ff88b170e36b196a15654e08b624857daf755e530641b3705`. Missing or corrupt evidence is `INVALID`.

## Explicit exclusions

- One-file edits are valid when the other file needs no change.
- Functional assertions are not rerun here.
- Kernel 8D intentionally overlaps compilation policies.
- Honest failure recording can pass 8F.

## Execution

```bash
python3 "Reward_GRPO/Grade_School Verifiers/verifiers/verifier_08_response_harness_integrity.py" --bundle-dir <integrity-bundle> --output-dir <new-empty-output>
```
