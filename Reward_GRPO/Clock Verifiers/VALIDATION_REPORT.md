# clock verifier validation certificate

| field | certified value |
|---|---|
| status | `passed` |
| validation date | 2026-08-23 |
| source evaluation | `execution-bank-RL-v2-think-r2/fixed26-mt2-4x-20260818` |
| source checkpoint | `execution-bank-RL-v2-think-r2/checkpoints/grpo_lora_r16/iter_0000019/adapter` |
| source package commit | `be2cc9e8cabd277c7cc36bbc217c4856c87b9f30` |
| validation image | `glm47-reward-grpo-bank-account@sha256:e4d1090d07cab73e5c4137637beccebe1dac0f6aa440e7d4cbfc466c4f226932` |
| compiler | gcc 13.3.0 |
| inventory | 5 policy documents, 5 verifier implementations, 15 candidate kernels |
| source outcomes | pass@1 2/4; pass by turn 2 2/4 |
| package readiness | `ready` for the pinned canonical clock task |
| live grpo readiness | `conditional`: e03 must remain the terminal gate and evaluator-invalid samples must be discarded |

## certified evidence

- six authenticated model candidates from four trials were replayed: four agreement failures and two agreement passes, with zero missed failures and zero restrictions.
- three structurally different positive implementations passed all five policies and all 15 kernels.
- five real or controlled defects were rejected, covering normalization, duplicate definitions, static and const misuse, and plus-one arithmetic.
- tampered protected assets and a missing compiler were classified as evaluator-invalid rather than model failures.
- all five policy decisions and kernel vectors were repeatable, and candidate sources remained immutable.

## receipt identities

| campaign | sha-256 |
|---|---|
| failure-gap replay | `e90197288812cde61aaaa755d2935f85275908678eaaa438d6e7dcd5c174648b` |
| control validation | `2adfcf38339c3c734c802e59a5bb2403a3e3dc89ea4722e1fb428224f6a4f13c` |
| structure validation | `772a7dc22135fa144fcf55cc595c360ba035a02ec6dd84a8c202c5b21cf32019` |

## certification

the retained policy and verifier package is certified for the pinned task boundary described above. raw candidates, replay scripts, manifests, logs, and receipt bodies are intentionally excluded from this cleaned package; the recorded identities certify the completed validation campaign.
