# Phone Number kernel12 GRPO20 release

## Release identity

| Field | Value |
| --- | --- |
| Public release name | `phone-number-kernel12-GRPO20` |
| Full training run ID | `phone-number-kernel12-grpo20-spot-20260822-102653` |
| Scored checkpoint | `iter_0000014` |
| Training status | Passed |
| Fixed26 evaluation | Four authoritative trials, 104 task-trial samples |
| Hugging Face archive | [TokenBender/phone-number-kernel12-GRPO20](https://huggingface.co/TokenBender/phone-number-kernel12-GRPO20) |
| W&B run | [phone-number-kernel12-grpo20-spot-20260822-102653](https://wandb.ai/models-iit-bhu-news/glm47-phone-number-dnd-grpo/runs/phone-number-kernel12-grpo20-spot-20260822-102653) |
| Dataset | [Phone_Number_train.jsonl](https://huggingface.co/TokenBender/phone-number-kernel12-GRPO20/blob/main/Phone_Number_train.jsonl) |

## Release checklist

| # | Item | Status |
| ---: | --- | --- |
| 1 | Public release | Published as `phone-number-kernel12-GRPO20`. |
| 2 | Hugging Face run archive | Public under `TokenBender`; contains adapters from iterations 4, 9, 14, and 19. |
| 3 | Direct scored adapter | [iter_0000014 adapter](https://huggingface.co/TokenBender/phone-number-kernel12-GRPO20/tree/main/checkpoints/iter_0000014/adapter). |
| 4 | Fixed26 evaluation archive | Four aggregate and eight shard receipts are committed under [`trials/`](trials/); complete raw workspaces remain in durable GCS. |
| 5 | Training/evaluation configs | Published on this GitHub branch: [reward implementation](../../Reward_GRPO/phone_number_grpo.py), [training YAML](../../Reward_GRPO/phone_number_grpo_skypilot.yaml), and [evaluation YAML](../../eval-job22-contractv2/phone-number-iter14-skypilot.yaml). |
| 6 | W&B | Public run link recorded above. |
| 7 | Result | Pass@1 `11.25/26 (43.27%)`; multi turn with feedback (turn=2) `15.25/26 (58.65%)`; four trials and 104 samples. |
| 8 | Statistics | Pass@1 CI `7.5-15.0`; turn-2 CI `11.0-19.25`; recovery `16/59 (27.1%)`, CI `13.1-44.2%`. |
| 9 | Repository statistics | Recorded in [statistics.md](../statistics.md) and [per_task_success.csv](../per_task_success.csv). |
| 10 | Reproduction evidence | Launch configurations and compact evaluation receipts are committed; complete raw workspaces remain in durable GCS. |
| 11 | Sky launch command | Recorded below. |
| 12 | PR #3 | Its Phone Number source/config/statistics commits are integrated into `client/26-aug-release`. |

## Uploaded checkpoints

| Checkpoint | Adapter SHA-256 | Size | Role |
| --- | --- | ---: | --- |
| `iter_0000004` | `633e9a9e5889e520e64a25497e1634c9f3a755ea8022dffb79e5e98c60c90338` | 485,940,769 bytes | Early checkpoint |
| `iter_0000009` | `53c68961fcb348f0f7da36c2361081df8711d1ee34731fa0d2b2f7e6327f19c9` | 485,940,769 bytes | Mid checkpoint |
| `iter_0000014` | `62fa190ad26e30fc1b5dd9543936ef549a49dd8cfa8220e4af726a1d499e575a` | 485,940,769 bytes | Scored checkpoint |
| `iter_0000019` | `394b1b732c4983c87085516ec4e1da58bba9661869a4329fa5093bb27f9e7bd6` | 485,940,769 bytes | Final checkpoint |

Each checkpoint includes a 256-byte `adapter_config.json` with SHA-256:

```text
0bd6d85f88fc42fefa52627b3c261f1ad58bb2c9519332ae8034dd5dffe2498e
```

Upload verification:

- Files committed: 8/8
- Adapter data: 1.81 GiB
- Remote LFS hashes: matched the original GCS artifacts
- Repository visibility: public

## Training configuration

| Field | Value |
| --- | --- |
| Base model | GLM-4.7-Flash |
| Warm start | D&D Character GRPO20 `iter_0000019` |
| Warm-start SHA-256 | `c9afe1ede8223e154c6efd1f3023ffb74b4a62c1705cae92efd1ebbf0a63d766` |
| GRPO updates | 20 |
| Reward function | `Reward_GRPO.phone_number_grpo.reward_func` |
| LoRA rank / alpha / dropout | 16 / 32 / 0.0 |
| Learning rate | `3e-5` |
| KL coefficient | `0.1` |
| Rollout batch | 8 |
| Samples per prompt | 32 |
| Global batch | 256 |
| Response limit | 8192 |
| Sequence length | 12288 |
| Hardware | 8 x NVIDIA H100 80GB |
| Training duration | 8,057 seconds (approximately 2h 14m) |
| Peak GPU memory | 70,342 MiB |
| Data-manifest SHA-256 | `2c0e004d56f650a30c71068e433273dc94849d92dce43bcdd39f6f6cb240d50c` |

LoRA target modules:

- `q_a_proj`
- `kv_a_proj_with_mqa`
- `o_proj`
- `gate_proj`
- `up_proj`
- `down_proj`

## Dataset

Dataset artifact: [TokenBender/phone-number-kernel12-GRPO20/Phone_Number_train.jsonl](https://huggingface.co/TokenBender/phone-number-kernel12-GRPO20/blob/main/Phone_Number_train.jsonl)

| Field | Value |
| --- | --- |
| Rows | 8 |
| SHA-256 | `9c5e1349ae6c2375b069a82107ae85404a80f4254b4478b0c79a80434e9612a6` |
| Durable training-data comparison | Byte-for-byte match |
| Dataset profile | `phone-number-dnd-grpo20` |
| Dataset kind | `aider-polyglot-cpp-shadow-grpo` |

## Fixed26 evaluations

| Trial run ID | Pass@1 | Multi turn with feedback (turn=2) | Phone Number |
| --- | ---: | ---: | --- |
| `phone-number-iter14-fixed26-thinking-spot-20260822-142309` | 11/26 | 15/26 | Passed turn 0 |
| `phone-number-iter14-fixed26-thinking-spot-20260822-152052` | 12/26 | 15/26 | Passed turn 0 |
| `phone-number-iter14-fixed26-thinking-spot-20260822-172835` | 11/26 | 15/26 | Passed turn 0 |
| `phone-number-iter14-fixed26-thinking-spot-20260822-190309` | 11/26 | 16/26 | Passed turn 0 |
| **Average** | **11.25/26 (43.27%)** | **15.25/26 (58.65%)** | **4/4 (100%)** |

Statistics:

- Pass@1 SD: 0.50
- Pass@1 range: 11-12
- Pass@1 95% CI: 7.5-15.0
- Pass@2 SD: 0.50
- Pass@2 range: 15-16
- Pass@2 95% CI: 11.0-19.25
- First-turn failures: 59
- Conditional recovery: 16/59 (27.1%)
- Recovery 95% CI: 13.1-44.2%

## Training reproduction

```bash
cd /data/Tirtha/browser-is-all-you-need

set -euo pipefail
test -f .env
grep -q '^WANDB_API_KEY=.' .env

STAMP="$(date -u +%Y%m%d-%H%M%S)"
RUN_ID="phone-number-kernel12-grpo20-spot-${STAMP}"
CLUSTER_NAME="glm47-phone-number-spot-${STAMP}"
SOURCE_COMMIT="$(git rev-parse HEAD)"

sky launch -y \
  --retry-until-up \
  -c "${CLUSTER_NAME}" \
  Reward_GRPO/phone_number_grpo_skypilot.yaml \
  --env "MILES_RUN_ID=${RUN_ID}" \
  --env "GLM47_SOURCE_COMMIT=${SOURCE_COMMIT}" \
  --secret-file .env
```

The scored Fixed26 evaluation configuration is [phone-number-iter14-skypilot.yaml](../../eval-job22-contractv2/phone-number-iter14-skypilot.yaml).

## Committed evaluation evidence

- [Release manifest](manifest.json)
- [Selected checkpoint](selected_checkpoint.json)
- [Evaluation manifest](evaluation_manifest.json)
- [Training receipts](evidence/training/)
- [Four aggregate and eight shard receipts](trials/)
- [Run-era evaluation method](method/)
- [Effective configurations](launch-configs/)

```bash
python3 results/phone-number-kernel12-GRPO20/recompute.py --check
```

```bash
sky jobs launch -y \
  --env EVAL_RUN_ID=<fresh-fixed26-run-id> \
  eval-job22-contractv2/phone-number-iter14-skypilot.yaml
```
