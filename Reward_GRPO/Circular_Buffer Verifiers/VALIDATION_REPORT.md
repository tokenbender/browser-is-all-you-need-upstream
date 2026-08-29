# circular buffer verifier validation certificate

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
| source outcomes | pass@1 1/4; pass by turn 2 2/4 |
| package readiness | `ready` for the pinned canonical circular buffer task |
| live grpo readiness | `conditional`: e03 must remain the terminal gate and evaluator-invalid samples must be discarded |

## certified evidence

- five authenticated model candidates from four trials were replayed: three agreement failures and two agreement passes, with zero missed failures and zero restrictions after the two-file contract correction.
- three structurally different positive implementations passed all five policies and all 15 kernels.
- four real or controlled defects were rejected, including head/tail aliasing, duplicate definitions, overwrite-count failure, and overwrite-head mutation.
- tampered protected assets and a missing compiler were classified as evaluator-invalid rather than model failures.
- all five policy decisions and kernel vectors were repeatable, and candidate sources remained immutable.

## receipt identities

| campaign | sha-256 |
|---|---|
| failure-gap replay | `0903759a2288a09cd7da74c99a3859556a9a8827a28552752b8fb6cc3a46ec95` |
| control validation | `4985472b64c78e1f58c470c7417d90996403c058fdfa45a3cd23fbc8c31a9feb` |
| structure validation | `5cb623b1b7c9b0b6d232a07bfba43e0b406005f39468ca490dd3f056671c5dd1` |

## certification

the retained policy and verifier package is certified for the pinned task boundary described above. raw candidates, replay scripts, manifests, logs, and receipt bodies are intentionally excluded from this cleaned package; the recorded identities certify the completed validation campaign.
