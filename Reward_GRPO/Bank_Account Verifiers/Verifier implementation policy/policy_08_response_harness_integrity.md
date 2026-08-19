# Policy 8 — Response and Evaluation-Harness Integrity

Policy 8 answers whether a Bank Account response was safely parseable, changed only the two authorized source files, remained free of recorded response-quality events, completed evaluation on time, and produced a complete evidence chain. It checks the response and evaluator rather than awarding functional correctness again.

All five conditions apply and use equal binary kernels. A verified pass is `+1`, a candidate-caused failure is `-1`, and missing, corrupt, contradictory, or infrastructure-owned evidence is `INVALID`; the full policy ranges from `-5` to `+5` and passes only at `+5`.

## Kernel table

| Kernel | Verifier function | What it asks | Exact implementation | `+1` condition | `-1` condition | Evidence |
|---|---|---|---|---|---|---|
| 8A | `verify_8a_aider_response_parse()` | Is the response a valid Aider whole-file edit? | Run the repository's pinned whole-file parser with only `bank_account.h` and `bank_account.cpp` editable | Parser returns at least one file and `format_valid=true` | Parser rejects the response or accepts it only through a recoverable formatting path | Raw response, parser digest, parsed-file list |
| 8B | `verify_8b_authorized_file_scope()` | Did the response change only authorized files? | Compute complete before/after tree manifests and compare actual changed files with the parser result | Changed files are nonempty, equal the parsed files, and are a subset of the two authorized files | A protected/unlisted file changes, a parsed file is unchanged, or an unparsed change appears | Before/after trees, tree digests, changed-file list |
| 8C | `verify_8c_response_quality_counters()` | Did the response avoid recorded syntax, indentation, lazy-comment, and malformed-response events? | Read normalized harness counters plus the compiler-stage result | All four counters are zero and candidate compilation succeeded | Any counter is nonzero or the candidate compiler stage failed | Harness receipt and compiler result |
| 8D | `verify_8d_evaluation_completion()` | Did evaluation finish within the pinned limit? | Compare terminal status, elapsed seconds, timeout seconds, and timeout counter | Status is `complete`, elapsed time is within the limit, and timeout count is zero | Candidate timeout, candidate crash, over-limit duration, or nonzero timeout count | Evaluation timing fields and terminal receipt |
| 8E | `verify_8e_receipt_integrity()` | Is the complete result evidence internally consistent and hash-bound? | Recompute response, task, parser, tree, log, parser-result, changed-file, and outcome bindings | Every required field, artifact, hash, task identity, parser result, and outcome agrees | A complete but honestly recorded candidate outcome may pass 8E even when another kernel fails | Bundle, harness receipt, logs, hashes, task manifest |

## Integrity bundle contract

The verifier takes a directory containing `integrity_bundle.json`, two complete source-tree snapshots, the raw model response, one task manifest, one normalized harness receipt, and the referenced logs. Paths must be relative, remain inside the bundle, and contain no symlink.

```json
{
  "schema_version": 1,
  "task_id": "bank-account",
  "parser_source_sha256": "c8881a8bbe51715ecfbf8b35b9bdc099be7a73b228347af5ac18a64248bd97e2",
  "response": {"path": "response.txt", "sha256": "..."},
  "task_manifest": {"path": "task_manifest.json", "sha256": "..."},
  "harness_receipt": {"path": "harness_receipt.json", "sha256": "..."},
  "before_tree": {"path": "before", "tree_sha256": "..."},
  "after_tree": {"path": "after", "tree_sha256": "..."}
}
```

The task manifest fixes `task_id`, `source_revision`, the two editable files, and the required benchmark files. The harness receipt records run identity, model, attempt, response/task/tree/parser hashes, parser outcome, changed files, response counters, compiler result, evaluation timing, tests outcomes, final outcome, and hash-bound configure plus build/test logs.

## 8A — Aider response parsing

The function imports `parse_whole_file_response()` from the repository only after verifying the parser source against the pinned SHA-256. It passes the raw response and exactly two editable names to that parser.

It returns `+1` only when at least one full file is extracted and `format_valid` is true. Forbidden paths, duplicate files, missing filename labels, unsupported fence labels, oversized output, or recoverable-but-imperfect formatting return `-1`; a missing or altered parser is `INVALID`.

## 8B — Authorized file scope

The function hashes every regular file in the complete before and after snapshots, including nested fixed test assets. It identifies additions, deletions, and content changes, then compares the result with files extracted from the response.

It returns `+1` only when the actual changed set is nonempty, exactly equals the parsed set, and contains only `bank_account.h` and `bank_account.cpp`. Changes to tests, CMake, hidden files, or unmentioned files return `-1`; unsafe paths or symlinks make the evidence `INVALID`.

## 8C — Response-quality counters

The function reads `num_malformed_responses`, `syntax_errors`, `indentation_errors`, and `lazy_comments` as nonnegative integers. It also reads a normalized compiler result so zero counters cannot hide a source file that did not compile.

It returns `+1` when all four counters are zero and compiler status is `passed` with return code zero. A recorded event or candidate compile failure returns `-1`; missing or wrongly typed receipt fields are `INVALID`.

## 8D — Evaluation completion

The function reads the terminal evaluation status, elapsed time, pinned limit, and `test_timeouts`. A normal test failure can still pass this integrity condition when evaluation completed cleanly and on time.

It returns `+1` only for `complete`, elapsed time at or below the positive timeout, and zero timeout events. Candidate timeout, crash, or over-limit execution returns `-1`; an infrastructure error is `INVALID` and requires a rerun.

## 8E — Complete receipt binding

The function validates task identity, source revision, run ID, model, attempt number, edit format, tries, tests outcomes, parser result, changed-file list, final outcome, and all artifact hashes. Configure and build/test logs must both exist, be nonempty, and match their recorded hashes.

It returns `+1` when the receipt describes exactly what the verifier independently observes. An invalid response may still earn 8E when the receipt honestly records that parser failure; missing logs, bad hashes, contradictory identities, or fabricated outcomes are `INVALID`, because no trustworthy candidate score can be produced.

## Aggregation

```text
Policy 8 kernel sum = 8A + 8B + 8C + 8D + 8E
Range               = -5 to +5
Full pass           = +5
```

Any applicable `INVALID` kernel cancels the policy sum and exits 2. A valid full pass exits 0, and a valid result containing any `-1` exits 1.

## Execution

```bash
python3 "Bank_Account Verifiers/verifiers/verifier_08_response_harness_integrity.py" \
  --bundle-dir <hash-bound-bank-account-integrity-bundle> \
  --output-dir <new-empty-receipt-directory>
```

The output directory receives `verification_receipt.json`. Input artifacts remain read-only.
