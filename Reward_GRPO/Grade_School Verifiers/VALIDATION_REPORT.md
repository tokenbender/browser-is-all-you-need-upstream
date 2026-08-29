# grade school verifier validation certificate

| field | certified value |
|---|---|
| status | `passed` |
| validation date | 2026-08-23 |
| source evaluation | `execution-bank-RL-v2-think-r2/fixed26-mt2-4x-20260818` |
| source checkpoint | `execution-bank-RL-v2-think-r2/checkpoints/grpo_lora_r16/iter_0000019/adapter` |
| source package commit | `be2cc9e8cabd277c7cc36bbc217c4856c87b9f30` |
| validation image | `glm47-reward-grpo-bank-account@sha256:e4d1090d07cab73e5c4137637beccebe1dac0f6aa440e7d4cbfc466c4f226932` |
| compiler | gcc 13.3.0 |
| inventory | 10 policy documents, 10 verifier implementations, 32 source kernels and 43 complete-campaign kernels |
| source outcomes | pass@1 2/4; pass by turn 2 2/4; one context-exhausted trial |
| package readiness | `ready` for the pinned canonical grade school task |
| live grpo readiness | `conditional`: e05 and e06 jointly gate semantic success; e07 and e08 require authenticated evidence bundles |

## certified evidence

- five authenticated model candidates from four trials were replayed: two agreement passes and three agreement failures, with zero missed failures and zero restrictions.
- three distinct positive implementations produced 84/84 passing static kernel decisions.
- real include and declaration failures plus an api-correct unsorted-name mutant were rejected while earned api and build credit remained visible.
- tampered protected assets and a missing compiler were classified as evaluator-invalid rather than model failures.
- ten policy documents pair one-to-one with ten verifier implementations; source decisions and kernel vectors were repeatable and candidate sources remained immutable.

## receipt identities

| campaign | sha-256 |
|---|---|
| failure-gap replay | `f5eda225e82482d589e7c2b4344e908ed88c1bdd24e3a17d7b8e6bd195008105` |
| control validation | `e852047bfddc6c726f60f284cb5469dc18a208f1b6a39969eea1d77b98744bf4` |
| structure validation | `4b8b0025eacb5513669bc21516e577761535a43f8175b0899baf02120695126b` |

## certification

the retained policy and verifier package is certified for the pinned task boundary described above. raw candidates, replay scripts, manifests, logs, and receipt bodies are intentionally excluded from this cleaned package; the recorded identities certify the completed validation campaign.
