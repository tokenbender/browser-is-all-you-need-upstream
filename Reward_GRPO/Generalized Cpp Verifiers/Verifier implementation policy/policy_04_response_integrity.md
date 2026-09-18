# Policy G04 — Response Integrity

## Purpose

Classify degeneration in the raw model output before any build work: empty answer channel, end-of-generation repetition loops, and output-cap truncation — each as a distinct verdict.

| Kernel | Question | `+1` | `-1` | `INVALID` |
|---|---|---|---|---|
| G04-1 | Is the raw response structurally usable? | Complete response with parseable listings | EMPTY (no usable answer), LOOP (end-of-stream repetition), or TRUNCATED (cut at the generation cap) | No response available in the manifest trajectory |

## Shared method

Pure-text analysis of the response. A loop must reach within 100 characters of the stream end; earlier repetition that recovers is not penalized. An unclosed deliverable fence is TRUNCATED even when token counts are unavailable. A reported token-cap hit with an unclean ending is also TRUNCATED; a clean complete ending at the cap is not sufficient evidence of truncation. Precedence is LOOP, TRUNCATED, EMPTY, then OK. These text verdicts never establish successful program execution.

## Aggregation

Single-kernel policy. Degeneration verdicts are model-behavior failures (`-1`) with the degeneration class in facts; a missing response channel is `INVALID`.

## Execution

`python verifier_04_response_integrity.py --candidate-dir TASK --manifest MANIFEST --expected-manifest-sha256 DIGEST --output-dir OUT` (requires `trajectory` response text or `response_file` in the manifest)

## Evidence boundary

The previous release cited the following historical evidence (not bundled or
revalidated by this focused PR):

> `generalized_verifier_docs/validation/VALIDATION_05.md` (126/126 recorded empty-answer events and 63/63 truncated rows caught; zero false positives on 4,946 clean rows and 324 good replies).

For current implementation checks, run the repository's hermetic
`generalized_verifier_docs/validation/self_check.py` and
`tests/test_generalized_cpp_reward_reliability.py`. Synthetic local checks do not
establish those historical counts or full benchmark/task coverage.
