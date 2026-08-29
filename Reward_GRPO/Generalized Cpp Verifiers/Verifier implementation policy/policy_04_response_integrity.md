# Policy G04 — Response Integrity

## Purpose

Classify degeneration in the raw model output before any build work: empty answer channel, end-of-generation repetition loops, and output-cap truncation — each as a distinct verdict.

| Kernel | Question | `+1` | `-1` | `INVALID` |
|---|---|---|---|---|
| G04-A | Is the raw response structurally usable? | Complete response with parseable listings | EMPTY (no usable answer), LOOP (end-of-stream repetition), or TRUNCATED (cut at the generation cap) | No response available in the manifest trajectory |

## Shared method

Pure-text analysis of the response. Loops are verdicted only when the repeated run reaches the end of the text (recorded end-loops terminate within 100 chars of the end; mid-trace loops that recover are not penalized). Truncation requires an unclosed listing at the generation cap. Verdicts are distinct so training can treat degeneration differently from genuine task failure.

## Aggregation

Single-kernel policy. Degeneration verdicts are model-behavior failures (`-1`) with the degeneration class in facts; a missing response channel is `INVALID`.

## Execution

`python verifier_04_response_integrity.py --candidate-dir TASK --manifest MANIFEST --expected-manifest-sha256 DIGEST --output-dir OUT` (requires `trajectory` response text or `response_file` in the manifest)

## Evidence

`generalized_verifier_docs/validation/VALIDATION_05.md` (126/126 recorded empty-answer events and 63/63 truncated rows caught; zero false positives on 4,946 clean rows and 324 good replies).
