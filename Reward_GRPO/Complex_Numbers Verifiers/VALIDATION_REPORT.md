# complex numbers verifier validation certificate

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
| source outcomes | pass@1 0/4; pass by turn 2 1/4 |
| package readiness | `ready` for the pinned canonical complex numbers task |
| live grpo readiness | `conditional`: e03 must remain the terminal gate and evaluator-invalid samples must be discarded |

## certified evidence

- eight authenticated model candidates from four trials were replayed: seven agreement failures and one agreement pass, with zero missed failures and zero restrictions after the format-contract correction.
- three positive implementations passed all five policies and all 15 kernels.
- eight real or controlled defects were rejected, covering member drift, private access, incomplete friendship, scalar operators, and numerical behavior.
- one undocumented exact stream-format restriction was removed after it rejected an official-positive implementation; semantic and terminal checks remained strict.
- tampered protected assets and a missing compiler were classified as evaluator-invalid, all policy vectors were repeatable, and candidate sources remained immutable.

## receipt identities

| campaign | sha-256 |
|---|---|
| failure-gap replay | `cbe0fe31b079471aa89b32e8c7f8fb4bc0b0c1f7358476b44786537aaf05e803` |
| control validation | `c23364cfbc45ae848b5b8c7bd6658e84f6759374f155b02431cc87cc4a841b9d` |
| structure validation | `4ab5bb204272d1ad7d7dee6628bae42f71bda42a5f3e742cf883439a9a5bb2a1` |

## certification

the retained policy and verifier package is certified for the pinned task boundary described above. raw candidates, replay scripts, manifests, logs, and receipt bodies are intentionally excluded from this cleaned package; the recorded identities certify the completed validation campaign.
