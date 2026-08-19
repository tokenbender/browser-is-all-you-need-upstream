# Policy 8 — Response and Evaluation-Harness Integrity

Policy 8 authenticates Aider parsing, changed-file scope, response counters, evaluation completion, and the receipt chain.

## Kernel table

| Kernel | Function | Verification | `+1` | `-1` | Evidence |
|---|---|---|---|---|---|
| 8A | `verify_8a_aider_response_parse()` | Pinned parser with only `diamond.h`, `diamond.cpp` editable | Nonempty strict parse | Malformed or recoverably invalid response | Response, parser hash, parsed files |
| 8B | `verify_8b_authorized_file_scope()` | Parsed names and bodies versus the authenticated after tree | Same nonempty authorized set and byte-identical post-edit contents | Unauthorized, missing, unparsed, or content-mismatched change | Tree manifests, changed list, and content comparison |
| 8C | `verify_8c_response_quality_counters()` | Four quality counters plus compiler result | All zero and compile passed | Counter event or candidate compile failure | Harness receipt |
| 8D | `verify_8d_evaluation_completion()` | Status, elapsed time, limit, timeout count | Completed within limit | Candidate timeout/crash/incomplete run | Timing receipt and logs |
| 8E | `verify_8e_receipt_integrity()` | Recompute task, parser, response, tree, log, and outcome bindings | Everything agrees | Not used; contradictions are `INVALID` | Bundle and all hashes |

## Method and aggregation

The parser SHA-256 is `82558ec14d4ed56ff88b170e36b196a15654e08b624857daf755e530641b3705`. Full pass is `+5`.

## Exclusions

A semantically wrong but honestly parsed/applied response may pass integrity kernels. Functional scoring remains Policies 5 and 6.

## Execution

```bash
python3 "Reward_GRPO/Diamond Verifiers/verifiers/verifier_08_response_harness_integrity.py" --bundle-dir <integrity-bundle> --output-dir <new-output>
```
