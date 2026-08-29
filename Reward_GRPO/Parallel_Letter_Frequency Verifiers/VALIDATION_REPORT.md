# parallel letter frequency verifier validation certificate

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
| package readiness | `ready` for the pinned canonical parallel letter frequency task |
| live grpo readiness | `conditional`: e03 must remain the terminal gate and evaluator-invalid samples must be discarded |

## certified evidence

- six authenticated model candidates from four trials were replayed: two agreement passes and four agreement failures, with zero missed failures and zero restrictions.
- three structurally different positive implementations produced 45/45 passing kernel decisions.
- dependency, unsafe range, digit-filter, shared-map, and lost-aggregation defects were rejected while legitimate api credit remained visible.
- tampered protected assets and a missing compiler were classified as evaluator-invalid rather than model failures.
- all five policy decisions and 15 kernel vectors were repeatable, and candidate sources remained immutable.

## receipt identities

| campaign | sha-256 |
|---|---|
| failure-gap replay | `0c1edb3a55fd055263b0610a9da8db9bc61844323abb679fcfa2c61fd620d08f` |
| control validation | `cd1243c97d9ac2f8ebf29ce7fa000c9f050832e05bd29afc958e0d2d8ac163ac` |
| structure validation | `9963f0e042e626d0f28f9724aa380323903ef8c1fc3359d6e6bff9173635555c` |

## certification

the retained policy and verifier package is certified for the pinned task boundary described above. raw candidates, replay scripts, manifests, logs, and receipt bodies are intentionally excluded from this cleaned package; the recorded identities certify the completed validation campaign.
