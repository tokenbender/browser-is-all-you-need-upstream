# Policy 08: Response, context, and harness integrity

## Purpose

Authenticate raw Aider output, actual changed-file scope, response counters, terminal evaluation, and receipt bindings separately from C++ correctness.

## Kernels

| ID | Function | Claim |
|---|---|---|
| 8a | `verify_8a_pinned_aider_parse` | The repository-root pinned parser safely parses the raw answer |
| 8b | `verify_8b_authorized_changed_file_scope` | Parsed and actual changes agree and stay within the two editable files |
| 8c | `verify_8c_response_context_counters` | Malformed, truncation, duplicate, no-op, and context-exhaustion counters are healthy |
| 8d | `verify_8d_evaluation_completion` | The harness reached a trustworthy terminal result |
| 8e | `verify_8e_hash_bound_receipt_integrity` | Task, parser, trees, response, commands, logs, counters, and timing are hash-bound |

## Execution

Malformed or unauthorized candidate responses are `-1`. Missing parser, bundle artifacts, hashes, or terminal evidence are `INVALID`. A functional pass does not erase a response-health failure.

`bundle_manifest.json` has `schema_version: 1`, `task_id: local-aider-cpp/sublist`, and hash-bound artifact entries named `response`, `changed_files`, `response_counters`, `harness_receipt`, `task_manifest`, `before_sublist_cpp`, `after_sublist_cpp`, `before_sublist_h`, and `after_sublist_h`. `changed_files` contains the delivered changed-file list. The harness receipt contains `terminal`, `status`, ISO-style `started_at` and `finished_at` strings, and at least one command with an argument list and return code.

## Aggregation

All five kernels apply with maximum sum `5`.

## Command

`python3 verifier_08_response_context_harness_integrity.py --bundle-dir BUNDLE --output-dir OUTPUT`
