---
base_model: zai-org/GLM-4.7-Flash
library_name: peft
tags:
- lora
- grpo
- code
- cpp
---

# Phone Number kernel12 GRPO20

LoRA checkpoints from the 20-update Phone Number kernel12 GRPO run
`phone-number-kernel12-grpo20-spot-20260822-102653`, warm-started from the
D&D Character GRPO20 iter-19 adapter.

## Selected checkpoint

The scored checkpoint is `iter_0000014`.

| Field | Value |
| --- | --- |
| Base model | `zai-org/GLM-4.7-Flash@7dd20894a642a0aa287e9827cb1a1f7f91386b67` |
| Adapter SHA-256 | `62fa190ad26e30fc1b5dd9543936ef549a49dd8cfa8220e4af726a1d499e575a` |
| LoRA rank / alpha | 16 / 32 |
| Training data | `Phone_Number_train.jsonl`, 8 rows |
| Training-data SHA-256 | `9c5e1349ae6c2375b069a82107ae85404a80f4254b4478b0c79a80434e9612a6` |

## Fixed26 regression result

| Metric | Trial scores | Mean |
| --- | --- | ---: |
| Pass@1 | 11, 12, 11, 11 | 11.25/26 |
| Multi turn with feedback (turn=2) | 15, 15, 15, 16 | 15.25/26 |

Conditional turn-2 recovery was `16/59` (27.1%). Evaluation used
`fixed26-contract-v2`, thinking enabled, temperature 0.7, top-p 1.0, and a
32,768-token response limit.

## Checkpoints

| Checkpoint | Adapter SHA-256 |
| --- | --- |
| `iter_0000004` | `633e9a9e5889e520e64a25497e1634c9f3a755ea8022dffb79e5e98c60c90338` |
| `iter_0000009` | `53c68961fcb348f0f7da36c2361081df8711d1ee34731fa0d2b2f7e6327f19c9` |
| `iter_0000014` | `62fa190ad26e30fc1b5dd9543936ef549a49dd8cfa8220e4af726a1d499e575a` |
| `iter_0000019` | `394b1b732c4983c87085516ec4e1da58bba9661869a4329fa5093bb27f9e7bd6` |

## Reproduction and evidence

The launch configurations, training receipts, selected-checkpoint manifest,
four aggregate evaluation receipts, eight shard receipts, and statistics code
are in the
[`client/26-aug-release`](https://github.com/tokenbender/browser-is-all-you-need-upstream/tree/client/26-aug-release/results/phone-number-kernel12-GRPO20)
release package.

This is an assisted Fixed26 regression result, not a pristine held-out
benchmark claim.
