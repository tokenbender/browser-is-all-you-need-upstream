# GLM-4.7-Flash Post-Training on 8x H100

A focused Miles pipeline for supervised fine-tuning and GRPO on the PIE C++
performance task.

The repository provides one configuration:

| Component | Configuration |
| --- | --- |
| Model | GLM-4.7-Flash |
| Hardware | 8x NVIDIA H100 80 GB with NVLink |
| Training | Miles, Megatron-Core, LoRA rank 16 |
| Parallelism | TP4 / PP1 / EP8 / ETP1 |
| Sequence length | 4,096 |
| Packed tokens per GPU | 16,384 |
| MoE dispatch | DeepEP flex |
| Rollout serving | SGLang DP8 with FlashInfer |
| Tracking | W&B scalars, samples, evaluation tables, and checkpoint manifests |

## Results

Measurements were collected on a dedicated 8x H100 80 GB node with the
configuration in this repository. Base and SFT use the same 1,259 held-out
tasks, greedy decoding, a 1,536-token response cap, and the same C++ sandbox
scorer.

| Stage | Model or adapter | Evaluation data | Pass rate | Valid format | Correct and faster | Mean successful speedup |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| Base | [`zai-org/GLM-4.7-Flash`](https://huggingface.co/zai-org/GLM-4.7-Flash/tree/7dd20894a642a0aa287e9827cb1a1f7f91386b67) | [`TokenBender/glm47-pie-cpp-posttraining-data`](https://huggingface.co/datasets/TokenBender/glm47-pie-cpp-posttraining-data/tree/09bc0276a0ff8ab84a8db81880ca7f739057e654) | 20.89% | 40.03% | 10.56% | 1.31x |
| SFT | [`TokenBender/glm47-flash-pie-cpp-lora-r16-sft-h100`](https://huggingface.co/TokenBender/glm47-flash-pie-cpp-lora-r16-sft-h100/tree/f1ac8df367080cc040f7cf769db219ee58f20f63) | [`TokenBender/glm47-pie-cpp-posttraining-data`](https://huggingface.co/datasets/TokenBender/glm47-pie-cpp-posttraining-data/tree/09bc0276a0ff8ab84a8db81880ca7f739057e654) | **90.79%** | **97.70%** | **28.36%** | **1.43x** |

The selected SFT profile completed four measured optimizer steps with finite
loss, a 14.88-second steady actor time, and 72,397 MiB peak memory per GPU.
The verified GRPO runtime completed rollout, reward scoring, policy update,
adapter synchronization, checkpointing, and evaluation at 6,735.5 actor
tokens/second across eight GPUs. Estimated active-MoE MFU was 2.0691%.

The W&B integration records training curves, rollout samples, evaluation
samples, reward outcomes, metric catalogs, per-rank adapter synchronization
fingerprints, and checkpoint manifests.

## Requirements

- One 8x H100 80 GB NVLink node
- Docker with NVIDIA Container Toolkit
- Access to the GLM-4.7-Flash base model
- Approved access to the two gated `TokenBender` datasets listed below
- A Hugging Face token authenticated with `hf auth login`
- A W&B API key for online experiment tracking

The Miles base image supplies Miles, Megatron-Core, SGLang, Ray, and the
GLM-4.7 model definition.

## Replication BOM

The published training and evaluation results were produced on one node with
eight H100 80 GB GPUs, full NVLink connectivity, 1 TiB of host memory, and
10 TB of local storage.

| Component | Exact experiment configuration | Measured size |
| --- | --- | ---: |
| Base model | [`zai-org/GLM-4.7-Flash`](https://huggingface.co/zai-org/GLM-4.7-Flash/tree/7dd20894a642a0aa287e9827cb1a1f7f91386b67), revision `7dd20894a642a0aa287e9827cb1a1f7f91386b67` | 62.5 GB |
| GPUs | 8x NVIDIA H100 80 GB with NVLink | 75,957 MiB peak per GPU |
| Host memory | 1 TiB installed on the experiment node | About 130 GiB run delta |
| Local storage | 10 TB installed on the experiment node | 250 GB practical clean-run footprint |
| Training image | `radixark/miles:latest-cu12@sha256:efc8027fc47aaa9687dc4f1046093ed4e2f9789e52a932fcefb7031402aeff37` plus this repository's `Dockerfile`; Modal builds it directly through `examples/modal/modal_app.py` | 53.3 GB base image |
| Gated training and evaluation data | [`TokenBender/glm47-pie-cpp-posttraining-data`](https://huggingface.co/datasets/TokenBender/glm47-pie-cpp-posttraining-data/tree/09bc0276a0ff8ab84a8db81880ca7f739057e654) | 60 MB download; about 107 MB extracted |
| Gated Aider-style C++ RL tasks v1 | [`TokenBender/glm47-aider-cpp-rl-tasks`](https://huggingface.co/datasets/TokenBender/glm47-aider-cpp-rl-tasks/tree/155587aa7200979fe8f35ea08f4ffcb6bce67201), revision `155587aa7200979fe8f35ea08f4ffcb6bce67201` | 253 tasks; 1,519 files; 294 KiB archive |
| SFT adapter | [`TokenBender/glm47-flash-pie-cpp-lora-r16-sft-h100`](https://huggingface.co/TokenBender/glm47-flash-pie-cpp-lora-r16-sft-h100/tree/f1ac8df367080cc040f7cf769db219ee58f20f63) | 772 MB |
| Converted TP4/PP1/EP8 base checkpoint | Created by `scripts/convert_checkpoint.sh` | Reserve 65 GB |
| LoRA checkpoint and run evidence | Adapter, native shards, logs, samples, and metrics | Reserve 2 GB per saved run |

Provision at least 250 GB of free local storage for a clean installation. This
covers the base model, converted checkpoint, unpacked training image, adapter,
run artifacts, and temporary image-download/build space. Use 500 GB or more
when retaining multiple checkpoints or evaluation generations.

## Assets

Download the exact base model, prepared PIE dataset, validated SFT adapter,
and versioned Aider RL corpus:

```bash
hf auth login
python3 scripts/download_assets.py model --output-root /root/models
python3 scripts/download_assets.py data
python3 scripts/download_assets.py sft
python3 scripts/download_assets.py aider-rl-tasks
```

The base model is frozen to its Hugging Face commit. The two datasets require
approved gated access. Dataset and adapter files are additionally verified
against the SHA-256 manifests published with their repositories. The commands
write:

```text
/root/models/GLM-4.7-Flash
.glm47-posttraining/assets/data
.glm47-posttraining/assets/adapters/sft
.glm47-posttraining/assets/aider-rl-tasks/tasks/aider_cpp_rl_tasks
```

These revisions are pinned in `scripts/download_assets.py`; environment
variables can override them when intentionally testing a newer release.

## Modal 8x H100

The canonical Modal launcher is `examples/modal/modal_app.py`. It reproduces
the recorded machine and image configuration without requiring a separately
published project image:

| Modal setting | Value |
| --- | --- |
| GPU | `H100!:8` |
| CPU | 48 cores |
| Host memory | 256 GiB requested, 1 TiB limit |
| Timeout | 24 hours per stage |
| Base image | `radixark/miles:latest-cu12@sha256:efc8027fc47aaa9687dc4f1046093ed4e2f9789e52a932fcefb7031402aeff37` |
| Runtime additions | Repository `Dockerfile`, GCC/G++ 13, `rsync`, `gawk`, `util-linux`, and `git` |
| Persistent storage | `glm47-models`, `glm47-assets`, and `glm47-runs` Modal Volumes |
| Tracking secret | Modal secret `wandb-glm47` containing `WANDB_API_KEY` |
| Dataset secret | Modal secret `huggingface-token` containing an approved `HF_TOKEN` |

Install the Modal client, authenticate to a workspace, and create the secrets
once:

```bash
python3 -m pip install "modal==1.2.6"
modal secret create wandb-glm47 WANDB_API_KEY="$WANDB_API_KEY"
modal secret create huggingface-token HF_TOKEN="$HF_TOKEN"
```

Prepare the pinned model and assets, convert the checkpoint, and run either
training stage:

```bash
modal run examples/modal/modal_app.py::prepare
modal run examples/modal/modal_app.py::convert
modal run examples/modal/modal_app.py::sft
modal run examples/modal/modal_app.py::grpo
```

GRPO defaults to the published SFT adapter. To use a newly produced SFT
checkpoint, pass its path on the `glm47-runs` volume:

```bash
modal run examples/modal/modal_app.py::grpo \
  --adapter-path /workspace/runs/<sft-run>/checkpoints/sft_lora_r16/<adapter>
```

## Runtime

Build the aligned H100 image:

```bash
docker build -t glm47-h100-posttraining .
```

Start the container with the repository and model directory mounted:

```bash
docker run --rm -it \
  --gpus all \
  --ipc host \
  --network host \
  -v "$PWD:/workspace/glm47-h100-posttraining" \
  -v /root/models:/root/models \
  -v "$PWD/.glm47-posttraining/assets:/workspace/assets:ro" \
  glm47-h100-posttraining \
  bash
```

Inside the container:

```bash
cd /workspace/glm47-h100-posttraining
python3 -m pip install -e .
export MILES_CPP_DATA_DIR=/workspace/assets/data
export WANDB_API_KEY=...
```

## Convert

Create the TP4/PP1/EP8 Megatron checkpoint:

```bash
bash scripts/convert_checkpoint.sh
```

The default output is:

```text
/root/models/GLM-4.7-Flash_torch_dist_tp4_pp1_ep8
```

## SFT

```bash
bash examples/sft.sh
```

Runs are written under:

```text
.glm47-posttraining/miles/glm47-h100-cpp-perf/runs/
```

Each run contains the prepared dataset, training log, VRAM trace, receipt,
LoRA checkpoints, and W&B artifact manifest.

## GRPO

Start GRPO from an SFT adapter:

```bash
export MILES_LORA_ADAPTER_PATH=/workspace/assets/adapters/sft
bash examples/grpo.sh
```

The launcher prepares a serving-compatible adapter, starts SGLang across all
eight H100s, performs C++ reward scoring, updates the LoRA policy, synchronizes
the adapter, evaluates the checkpoint, and publishes the run results.

The default GRPO schedule uses 32 prompts, 8 samples per prompt, 100 rollouts,
evaluation every 20 rollouts, and checkpointing every 10 rollouts.

## Evaluate

Run the base-model evaluation on the complete held-out set:

```bash
PYTHONPATH=src python3 scripts/evaluate.py \
  --data-dir .glm47-posttraining/assets/data \
  --model /root/models/GLM-4.7-Flash \
  --output-dir .glm47-posttraining/eval/base \
  --label base \
  --tp-size 4 \
  --batch-size 32 \
  --temperature 0 \
  --top-p 1 \
  --max-tokens 1536 \
  --attention-backend flashinfer \
  --apply-chat-template \
  --chat-template-kwargs '{"enable_thinking": false}' \
  --score-workers 32
```

Run the same evaluation with the SFT adapter:

```bash
PYTHONPATH=src python3 scripts/evaluate.py \
  --data-dir .glm47-posttraining/assets/data \
  --model /root/models/GLM-4.7-Flash \
  --adapter .glm47-posttraining/assets/adapters/sft \
  --output-dir .glm47-posttraining/eval/sft \
  --label sft \
  --tp-size 4 \
  --batch-size 32 \
  --temperature 0 \
  --top-p 1 \
  --max-tokens 1536 \
  --attention-backend flashinfer \
  --apply-chat-template \
  --chat-template-kwargs '{"enable_thinking": false}' \
  --lora-target-modules q_a_proj,kv_a_proj_with_mqa,o_proj,gate_proj,up_proj,down_proj \
  --experts-shared-outer-loras \
  --lora-use-virtual-experts \
  --score-workers 32
```

Evaluation writes generated samples, scored records, an aggregate summary,
quality metrics, and a run receipt under the selected output directory. Add
`--wandb-project glm47-pie-cpp-posttraining --wandb-timing-status verified`
to either command to publish the same metrics and sample tables to W&B.

### Aider Polyglot C++

This lane asks whether targeted supervised data and executable-reward training
improve GLM-4.7-Flash on repository edits. Every reported score uses the same
fixed 26-task C++ set, whole-file edit format, temperature `0.7`, top-p `1.0`,
and at most two attempts. `pass@1` counts tasks solved by the initial answer.
`multi-turn-with-error-feedback@2` counts cumulative success after compiler or
test feedback and a repair attempt. It is not an independent-sampling pass@k
metric. The benchmark is
pinned to Aider commit `5dc9490bb35f9729ef2c95d00a19ccd30c26339c` and
Polyglot commit `7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f`.

The machine-readable ledger is
[`docs/aider_posttraining_runs.json`](docs/aider_posttraining_runs.json).
The evidence-linked SFT defect ledger and its deterministic audit report are
[`docs/aider_sft_defect_inventory.json`](docs/aider_sft_defect_inventory.json)
and
[`docs/AIDER_SFT_DEFECT_INVENTORY.md`](docs/AIDER_SFT_DEFECT_INVENTORY.md).
Verify their schema, measured counts, and the 790-row non-shrink invariant with
`python3 scripts/verify_aider_sft_defect_inventory.py`.
All project-tracked Aider dataset lineages are preserved in the private,
manual-approval
[`glm47-aider-posttraining-data`](https://huggingface.co/datasets/TokenBender/glm47-aider-posttraining-data/tree/27b7f1f43a123fe958104a5ba896f2ed3348ff43)
catalog. Evaluator-only histories and result JSONs are separately preserved in
[`glm47-aider-fixed26-responses`](https://huggingface.co/datasets/TokenBender/glm47-aider-fixed26-responses/tree/68b5b0fc0fe0dc694b849cff7e4bda39ab50c8a9).
Both repositories are private, manually gated, and pinned here to revisions
that passed a file-by-file authenticated round trip.

Approved identities can download and reverify those exact snapshots with:

```bash
python3 scripts/download_assets.py aider-data --output-root /workspace/assets
python3 scripts/download_assets.py aider-responses --output-root /workspace/assets
```

#### Progress ledger

All 17 Aider SFT training attempts, including failed and unpromoted engineering
runs, are now preserved under the `ahm-rimer` W&B entity. The authenticated
inventory and replay provenance are recorded in
[`docs/receipts/glm47-aider-sft-wandb-sync.json`](docs/receipts/glm47-aider-sft-wandb-sync.json).

| Stage | Training data | pass@1 | multi-turn-with-error-feedback@2 | Well formed | Total tokens | Evidence |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Base | No task-specific training | 0/26 | 4/26 | 26/26 | 2,212,419 | [Model](https://huggingface.co/zai-org/GLM-4.7-Flash/tree/7dd20894a642a0aa287e9827cb1a1f7f91386b67) · [responses](https://huggingface.co/datasets/TokenBender/glm47-aider-fixed26-responses/tree/d817c418b29eae23a97a83c70c896b56296b330c/evals/base-fixed26-20260711) |
| SFT v1 | 401 source / 321 train / 320 consumed | 1/26 | 5/26 | 26/26 | 1,732,287 | [Data](https://huggingface.co/datasets/TokenBender/glm47-aider-posttraining-data/tree/0f0f69346eaeeb13401e57863efd33cc501e0922/datasets/sft-v1-321) · [responses](https://huggingface.co/datasets/TokenBender/glm47-aider-fixed26-responses/tree/d817c418b29eae23a97a83c70c896b56296b330c/evals/sft-v1-fixed26-20260718) · [W&B](https://wandb.ai/ahm-rimer/glm47-aider-v1-sft/runs/glm47-aider-v1-sft-20260717T130336Z) |
| SFT v2 | 1,211 packaged / 1,184 consumed | 1/26 | 6/26 | 25/26 tasks | 1,582,781 | [Data](https://huggingface.co/datasets/TokenBender/glm47-aider-posttraining-data/tree/0f0f69346eaeeb13401e57863efd33cc501e0922/datasets/sft-v2-1211) · [responses](https://huggingface.co/datasets/TokenBender/glm47-aider-fixed26-responses/tree/d817c418b29eae23a97a83c70c896b56296b330c/evals/sft-v2-fixed26-20260719) · [W&B](https://wandb.ai/ahm-rimer/glm47-aider-v1-sft/runs/glm47-aider-1211-sft-20260718T192250Z) |
| SFT v3 | 530 packaged / 520 consumed | 0/26 | **7/26** | 26/26 | 1,611,304 | [Data](https://huggingface.co/datasets/TokenBender/glm47-aider-posttraining-data/tree/0f0f69346eaeeb13401e57863efd33cc501e0922/datasets/sft-v3-complement-530) · [responses](https://huggingface.co/datasets/TokenBender/glm47-aider-fixed26-responses/tree/d817c418b29eae23a97a83c70c896b56296b330c/evals/sft-v3-fixed26-20260721) · [W&B](https://wandb.ai/ahm-rimer/glm47-aider-v1-sft/runs/glm47-aider-complement-530-sft-20260721) |
| SFT v4 | 790 packaged / 780 consumed per epoch; 3 epochs | 0/26 | 6/26 | 26/26 | See receipt | [Data](https://huggingface.co/datasets/TokenBender/glm47-aider-posttraining-data/tree/c0db40db76fb16014103d131335fb15a2c0cfd19/datasets/sft-v4-holistic-790) · [responses](https://huggingface.co/datasets/TokenBender/glm47-aider-fixed26-responses/tree/1401f17c84d146b4cfa91bb67a6e625ea8cba2a9/evals/sft-v4-holistic-790-3ep-fixed26-20260723) · [W&B](https://wandb.ai/ahm-rimer/glm47-aider-v1-sft/runs/glm47-aider-sft-v4-holistic-790-modal-3ep-20260723T164628Z) |
| SFT v5 | 1,340 packaged and consumed per epoch; 3 epochs / 4,020 exposures | **2/26** | 5/26 | 26/26 | 1,680,607 | [Data](https://huggingface.co/datasets/TokenBender/glm47-aider-posttraining-data/tree/f21122d33f99e552aee0557699b5e3e71b6e12e5/datasets/sft-v5-experimental-1340) · [checkpoint](https://huggingface.co/TokenBender/glm47-aider-sft-v5-1340-modal-3ep/tree/43110cf15fa9cd87373b726638bf80c8f08858ce) · [responses](https://huggingface.co/datasets/TokenBender/glm47-aider-fixed26-responses/tree/53a7e4f41b72bdbe7c67db4408bca6796d33ceb3/evals/sft-v5-experimental-1340-3ep-fixed26-20260723) · [W&B](https://wandb.ai/ahm-rimer/glm47-aider-v1-sft/runs/glm47-aider-sft-v5-1340-modal-3ep-20260723T210506Z) · [reproduce](docs/AIDER_SFT_V5_1340_REPRODUCE.md) |
| RL v2 | 169 train + 22 monitor; 11 updates, about 2.08 epochs | 1/26 | 6/26 | 26/26 | 1,650,420 | [Data](https://huggingface.co/datasets/TokenBender/glm47-aider-posttraining-data/tree/27b7f1f43a123fe958104a5ba896f2ed3348ff43/datasets/rl-v2-169) · [response receipt](https://huggingface.co/datasets/TokenBender/glm47-aider-fixed26-responses/tree/d817c418b29eae23a97a83c70c896b56296b330c/evals/rl-v2-iter10-fixed26-20260722) |

SFT v3 remains the strongest completed result by the second assisted attempt:
7/26 versus the base model's 4/26, a 75% relative increase. SFT v5 is the
strongest first-attempt result at 2/26 and preserves valid formatting on all
26 tasks, but reaches only 5/26 on multi-turn-with-error-feedback@2. The
repaired RL run reaches 1/26 pass@1 and 6/26
multi-turn-with-error-feedback@2. These results are consistent with
the working hypothesis that the lane is limited by training duration and
high-signal data coverage, but the fixed-26 experiments do not prove that
diagnosis by themselves.

An earlier reward-parser trial is intentionally excluded from the table
because it produced no comparable fixed-26 receipt. It exposed terminal-token
handling that was corrected with skipped special tokens and explicit stop IDs
before RL v2.

#### Dataset and checkpoint identity

Large datasets and checkpoints are not stored in Git. The gated data catalog
contains 19 named dataset, candidate, rejection, and audit entries. Each entry
has a machine-readable `trainable` flag, status, split semantics, file hashes,
and exclusions; rejected and audit corpora are preserved without being
silently presented as positive training data. A reproduction must use the
exact catalog revision and match these identities before launching.

The 253-task Aider-style C++ RL runtime package is package `v1` at
[`155587aa7200979fe8f35ea08f4ffcb6bce67201`](https://huggingface.co/datasets/TokenBender/glm47-aider-cpp-rl-tasks/tree/155587aa7200979fe8f35ea08f4ffcb6bce67201).
Its deterministic archive SHA-256 is
`97d70ca9e6ab3ef76141169b188e1049524bdbfa651b2420dbbd5c78968c7c59`,
its source-manifest SHA-256 is
`b37653def2cdad8c2e927af30c4de6e979c3af3ef0ea66a66671d5e7ff18d1ee`,
and its canonical source-tree SHA-256 is
`a8bb8030f7ec287eee4f5c19146374d6722ec5af310cad632ed5938e7280f686`.
`scripts/download_assets.py aider-rl-tasks` verifies the published checksums,
rejects unsafe archive members, and requires all 253 tasks before extraction is
accepted. The archive contains private rubrics and hidden executable tests, so
its approval boundary is narrower than the ordinary training-data catalog:
only RL runtime and service identities should receive access. The Git image
explicitly excludes `rubrics/`; Modal and Lium consume only the controlled
extracted asset path.

| Stage | Dataset identity | Checkpoint or adapter |
| --- | --- | --- |
| SFT v1 | Source archive SHA-256 `2efe714c454de7ba1c5fd523f5849b3c6c9af65e8e5ca5bf4cf438017fb1e03a`; inner 401-row JSONL SHA-256 `2ddfe6966c828007f7d6c439e51bfaf07c8959dddc4423ceadb602dc3d49517b` | `glm47-runs:/glm47-aider-v1-sft-20260717T130336Z/checkpoints/sft_lora_r16/iter_0000009/adapter` |
| SFT v2 | Train JSONL SHA-256 `13219cae85551714d4280b60600bb7ef5336dffda54698340ba40f3405ccd51b` | `glm47-runs:/glm47-aider-1211-sft-20260718T192250Z/checkpoints/sft_lora_r16/iter_0000036/adapter` |
| SFT v3 | Train JSONL SHA-256 `805aa59bbc936ee20687a293ef47d2fb9bcaee12419c6539ecd6180dfab02089` | `glm47-runs:/glm47-aider-complement-530-sft-20260721/checkpoints/sft_lora_r16/iter_0000025/adapter` |
| SFT v5 | Manifest SHA-256 `0906e1abcec775ca52362679fe39d83af9ac1744c984faf1125f4de0c7b2e130`; train JSONL SHA-256 `a01a07c9d4e2706683814a3d5afc2bcd47172ff92b08f15e2c673729f185bd66` | `iter_0000200`; adapter SHA-256 `bdd808bf98d26b467af7fec1a20d7ed6502bac0ffd50eae9cb6a1e702613daaa`; [gated checkpoint](https://huggingface.co/TokenBender/glm47-aider-sft-v5-1340-modal-3ep/tree/43110cf15fa9cd87373b726638bf80c8f08858ce) |
| RL v2 | Manifest SHA-256 `a7e54c0245b97ae78f9b2fa57ff5278844585cf03004254137b6cfc8e91ef157`; train JSONL SHA-256 `b72394ab603b4b6faf22370ea70605446f112ab50c883eb61e308e2dd9ab4dd2` | Merged start adapter SHA-256 `dbea7d3e2d6603f278b94c6be134bca83bb5f0ebdc4840eb53898ec5b3affb91`; final adapter SHA-256 `046a1018b605aa29f8b8c4f2677f47ce55489105f6766155f4c009798f48abe2` |

The same data revision also maps, without omission, the heuristic-32,
high-confidence-14, Signal-v2, Signal-v3, Gold-v4, reverify-715, raw-concat,
Combined-v5, Pass1-600, both 253-task RL materializations, the difficulty
filter, the 169-task RL subset, and their audit/build ledgers.
`dataset_catalog_paths` in the progress ledger is the canonical
ID-to-Hugging-Face path map. Source licenses remain an independent approval
condition: private gating preserves data but does not grant redistribution
rights.

The data root contract is:

```text
<data-root>/manifest.json
<data-root>/sft/train.jsonl                 # SFT
<data-root>/grpo/train.jsonl                # RL
<data-root>/eval/train_monitor.jsonl        # RL monitor
```

After the catalog download above, the SFT v3 and RL v2 data roots are,
respectively, `/workspace/assets/aider-data/datasets/sft-v3-complement-530/data`
and `/workspace/assets/aider-data/datasets/rl-v2-169/data`.

#### Reproduce SFT v1-v3

Use one epoch and disable automatic PIE data rebuilding. Set the batch size to
`32` for SFT v1 and v2, or `20` for SFT v3. Use a fresh run ID for every
attempt.

```bash
export MILES_CPP_DATA_DIR=<data-root>
export MILES_CPP_AUTO_PREPARE_DATA=0
export MILES_SFT_NUM_EPOCH=1
export MILES_ROLLOUT_BATCH_SIZE=<32-or-20>
export MILES_GLOBAL_BATCH_SIZE=<32-or-20>
export MILES_RUN_ID=<fresh-run-id>
export MILES_WANDB_PROJECT=glm47-aider-v1-sft
export MILES_WANDB_GROUP="${MILES_RUN_ID}"
export MILES_WANDB_RUN_ID="${MILES_RUN_ID}"
bash examples/sft.sh
```

The loader consumes complete batches. That is why the measured counts are 320
of 321 rows for SFT v1, 1,184 of 1,211 for SFT v2, and 520 of 530 for SFT v3.
Prepare a serving adapter with `scripts/prepare_grpo_adapter.py` before SGLang
evaluation; it preserves the source adapter and removes the auxiliary
next-token-prediction layer from the serving copy.

#### Reproduce repaired RL v2

The recorded run used source commit
`c5cb63f15166ee3fdcf52dc2a882504758a594cd`, eight H100 GPUs, rank-32 LoRA,
11 updates, rollout batch 32, eight samples per prompt, learning rate `5e-7`,
KL coefficient `0.02`, temperature `0.7`, skipped special tokens, and stop IDs
`154820 154827 154829`. W&B was deliberately offline for this run.

Place the verified inputs at:

```text
/workspace/assets/aider-data/datasets/rl-v2-169/data
/workspace/assets/merged-1211-530-r32
/workspace/assets/aider-rl-tasks/tasks/aider_cpp_rl_tasks
/workspace/models/GLM-4.7-Flash
/workspace/models/GLM-4.7-Flash_torch_dist_tp4_pp1_ep8
```

Then run the checked-in, hash-gated specification with a fresh ID:

```bash
export GLM47_REPRO_RUN_ID=glm47-aider-grpo169-r32-2ep-repro-$(date -u +%Y%m%dT%H%M%SZ)
bash examples/lium/aider_grpo_2ep.sh
```

The script refuses to start when the canonical RL manifest, train JSONL, or
merged source adapter does not match its pinned SHA-256. The canonical
terminology migration changes only identifiers and paths in the 169-row
dataset: all prompts, problem IDs, splits, and other training metadata match
the recorded run input exactly.

#### Reproduce the fixed-26 evaluation

Build the pinned runtime image from the recorded training commit, prepare the
exact benchmark checkouts, and run two TP4 shards on one 8x H100 node:

```bash
git worktree add /workspace/glm47-c5 \
  c5cb63f15166ee3fdcf52dc2a882504758a594cd
docker build -t glm47-fixed:c5cb63f /workspace/glm47-c5

export GLM47_EVAL_ROOT=/workspace/eval-final-iter10
git clone https://github.com/Aider-AI/aider.git "${GLM47_EVAL_ROOT}/aider"
git -C "${GLM47_EVAL_ROOT}/aider" checkout \
  5dc9490bb35f9729ef2c95d00a19ccd30c26339c
git clone https://github.com/Aider-AI/polyglot-benchmark.git \
  "${GLM47_EVAL_ROOT}/aider/tmp.benchmarks/polyglot-benchmark"
git -C "${GLM47_EVAL_ROOT}/aider/tmp.benchmarks/polyglot-benchmark" checkout \
  7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f
python3 -m venv "${GLM47_EVAL_ROOT}/aider-venv"
"${GLM47_EVAL_ROOT}/aider-venv/bin/pip" install -e \
  "${GLM47_EVAL_ROOT}/aider[dev]"

export GLM47_EVAL_TRAIN_RUN_ID=<training-run-id>
export GLM47_EVAL_ADAPTER_PATH=<iter-10-adapter-path>
export GLM47_EVAL_ADAPTER_SHA256=<adapter-model-sha256>
python3 examples/lium/aider_fixed26_eval.py
```

The evaluator refuses stale result directories, verifies the adapter and both
benchmark commits, runs the two 13-task shards independently, and writes a
merged receipt only after all 26 unique task identities are present.

#### Reproducibility boundary

The repository versions the code, exact configuration, hashes, progress
ledger, publication receipt, and final RL receipt. Training/audit data and
fixed-26 response evidence are in separate private, manually gated Hugging
Face dataset repositories. Fifteen evaluations have all 26 chat histories and
26 result JSONs; the official RL v2 iter-10 entry is receipt-only because its
raw transcripts did not survive. Benchmark trees and hidden tests were not
copied into the response repository. The Aider-style C++ RL runtime package remains
separately gated at the pinned revision above. The base model is public at its
pinned revision. The recorded RL v2 W&B directory was offline and must be
synced separately if a web run is required.

#### Modal Aider-style C++ RL data

The Modal path trains on up to 253 Aider-style C++ RL tasks backed by controlled rubrics
and hidden executable tests. The official fixed 26 remain external and
evaluation-only. Prepare the pinned runtime-oracle corpus once per
`glm47-assets` volume:

```bash
modal run examples/modal/modal_app.py::prepare_aider_rl_assets
```

That command verifies the immutable Hugging Face revision and published
checksums before extraction. It does not need to be repeated for every run.
Routine continuations should use an already prepared, hash-gated dataset. This
one-update command starts from SFT v3, the strongest measured checkpoint:

```bash
modal run examples/modal/modal_app.py::aider_grpo \
  --run-id glm47-aider-sftv3-r16-one-update-YYYYMMDD \
  --adapter-path /workspace/runs/glm47-aider-complement-530-sft-20260721/checkpoints/sft_lora_r16/iter_0000025/adapter \
  --adapter-sha256 f1ea45bc327dc6e28d0287aea75c6b691e99d2ec2f7fdb7f07bbbf5ccd6cf36a \
  --data-dir /workspace/assets/aider-data/datasets/rl-v2-169/data \
  --lora-rank 16 \
  --lora-alpha 32 \
  --num-rollout 1
```

Rebuild from all 253 source tasks only when intentionally creating a new
prepared dataset. In that case omit `--data-dir`; the builder performs the
full per-task rubric and hidden-test validation once while materializing it.

For the fixed-26 Modal evaluator, pass the expected task count and LoRA rank
when they differ from the Aider C++ RL defaults:

```bash
GLM47_EXPECTED_TRAINING_TASK_COUNT=169 \
GLM47_EVAL_LORA_RANK=32 \
modal run examples/modal/aider_eval_app.py --parallel \
  --adapter-path /runs/<run>/checkpoints/grpo_lora_r16/iter_<N>/adapter \
  --expected-adapter-sha256 <checkpoint-sha256> \
  --expected-data-manifest-sha256 <manifest-sha256> \
  --run-id <fresh-fixed26-run-id>
```

## Repository

```text
Dockerfile                         H100 runtime
examples/sft.sh                    canonical SFT configuration
examples/grpo.sh                   canonical GRPO configuration
examples/lium/aider_grpo_2ep.sh    hash-gated repaired-RL reproduction
examples/lium/aider_fixed26_eval.py  two-shard fixed-26 Lium evaluator
examples/modal/modal_app.py        Modal 8x H100 reproduction
examples/modal/aider_eval_app.py   provenance-gated fixed-26 Aider evaluation
docs/aider_posttraining_runs.json  machine-readable Aider progress ledger
docs/aider_sft_defect_inventory.json  machine-verifiable SFT defect ledger
docs/AIDER_SFT_DEFECT_INVENTORY.md  human-readable SFT defect report
docs/receipts/                     immutable measured evaluation receipts
scripts/convert_checkpoint.sh      TP4/PP1/EP8 conversion
scripts/download_assets.py         verified Hugging Face asset download
scripts/package_aider_cpp_rl.py    deterministic Aider C++ RL archive builder
scripts/publish_aider_data_catalog.py  gated data/evaluation publication
scripts/verify_aider_sft_defect_inventory.py  SFT defect and size-invariant check
scripts/evaluate.py                held-out generation and scoring
scripts/prepare_grpo_adapter.py    serving adapter preparation
scripts/create_grpo_training_gate.py  Aider GRPO checkpoint provenance gate
scripts/publish_results.py         W&B results publishing
src/glm47_posttraining/            GLM-4.7 Miles integrations and rewards
```
