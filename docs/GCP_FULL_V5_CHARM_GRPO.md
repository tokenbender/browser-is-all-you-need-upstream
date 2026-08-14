# GCP full-v5 + CHARM GRPO production profile

> This document preserves the manually provisioned VM workflow as a fallback.
> The active ephemeral SkyPilot smoke and canary entrypoint is
> [GCP_FULL_V5_CHARM_SKYPILOT.md](GCP_FULL_V5_CHARM_SKYPILOT.md). SkyPilot
> provisions a separate cluster and does not repurpose the manual VM.

This guide operates the versioned `aider-full-v5-production-ast17-gcp-r1`
profile. It does not authorize training by itself. The profile is fail-closed:
full training requires immutable full-v5 assets, CHARM pre-training admission,
the exact promotion canary, a promotion PASS, and an explicit cost
authorization.

## Current cloud state (2026-08-10)

| Check | Observed state | Consequence |
| --- | --- | --- |
| GCP project | `lifeandhalf-24122025` | Bound in the profile |
| H100 training target | `glm47-full-v5-charm-h100-8`, TERMINATED (stopped) | Spot VM built in `us-central1-a`; boot and Local SSD state preserved |
| Existing A100 VM | `glm47-synthmem-50ep-pr-eval`, 4xA100 | Preserved and not modified for GRPO |
| Machine | `a3-highgpu-8g`, 208 vCPU, about 1.8 TiB RAM | Exactly 8xH100 80 GB; each reports 81,559 MiB |
| H100 fabric | Every pair reports `NV18` | Eight-GPU NVLink topology verified |
| Boot storage | 500 GB `pd-ssd`; 335 GiB free after assets and images | Spot results must still be synchronized to GCS |
| Base model | Installed locally; revision `7dd20894...` | Source manifest and every listed file are checked before use |
| Starting adapter | SynthMem-v1 ep50, `iter_0000649`, SHA `4acb7f23...575a` | Installed with eight proof-checked TP4/EP8 native shards |
| Full-v5 runtime package | Missing from GCS and inaccessible at the pinned private source | Preparation stops before Docker build or GRPO |
| Training status | `NOT_COMPLETED` | No canary, optimizer update, or paid full training has started |

## Final profile

| Surface | Frozen setting |
| --- | --- |
| Orchestrator | Native GCP Compute Engine; no Modal |
| Instance | `glm47-full-v5-charm-h100-8` |
| Hardware | `a3-highgpu-8g`, exactly 8×H100 with at least 80,000 MiB each |
| Base model | `zai-org/GLM-4.7-Flash@7dd20894a642a0aa287e9827cb1a1f7f91386b67` |
| Starting adapter | SynthMem-v1 ep50, epoch 50 / `iter_0000649`, SHA-256 `4acb7f23c295f45380155c5d9ee6bc59422262f0cb51f0c02f7e550d405b575a`, LoRA 16/32 |
| Runtime | Full-v5 manifest `93d671faa44abcc6deca21c6a49e247d76436835bfa2905ee33968a478fb532a`, tree `0a3df3ce40eed45814651c933277bfc5ca17359a2b3e6f0a7027b184e3569c7e` |
| Full data | 551 train targets, 64 disjoint development targets, 661/83 prompt variants |
| Full schedule | 3 epochs, 57 updates, 29 prompts/update, 8 samples/prompt, global rollout 232 |
| Canary | Exactly 20 frozen tasks × 5 epochs, 5 updates, 8 samples/prompt, at least 4 matched trials |
| Generation | Thinking on, temperature 0.7, sequence 34,816, response 32,768, max tokens/GPU 49,152 |
| Optimizer | Learning rate `5e-7`; reference model on; KL loss `0.02` |
| Parallelism | TP4, PP1, CP1, EP8, ETP1; SGLang DP8 with repository GLM LoRA flags |
| Reward | `production_ast17_fullv5_r1` logical profile backed by `production_ast17` |
| Reward sandbox | Docker, networking disabled, 32 workers, component receipts retained |
| Gates | Runtime preflight, reward preflight, rollout validator, unique groups, signal gate |
| Checkpoints | Every update, the safe superset required to retain epoch boundaries 19, 38, and 57 with Miles' single save cadence |
| Tracking | W&B offline durable directory; publish deliberately after the run |
| Persistence | Local run tree copied to GCS every 60 seconds and once at completion |
| Fixed-26 | Frozen post-training evaluation only; never reward or rubric feedback |

## Ten execution steps

### 1. Validate the exact source revision

Run locally from the repository root:

```bash
git rev-parse --show-toplevel
git status --short
python3 -m py_compile \
  scripts/gcp_full_v5_charm_grpo.py \
  src/glm47_posttraining/aider_polyglot/full_v5_charm.py
PYTHONPATH=src python3 scripts/gcp_full_v5_charm_grpo.py inspect
PYTHONPATH=src python3 scripts/gcp_full_v5_charm_grpo.py render --phase canary
PYTHONPATH=src python3 scripts/gcp_full_v5_charm_grpo.py render --phase full
```

The inspection decision must remain `NOT_COMPLETED` until all later gates pass.

### 2. Prove Modal is denied

Every `examples/modal/*.py` entrypoint calls the authorization gate before
importing the Modal SDK. An accidental launch exits with code 64 and prints:

```text
MODAL EXECUTION BLOCKED: You have accidentally started a Modal run, which is not authorized. Continue only after explicit full authorization by setting GLM47_MODAL_FULL_AUTHORIZATION=I_FULLY_AUTHORIZE_MODAL_EXECUTION_AND_COSTS.
```

Verify the guard:

```bash
env -u GLM47_MODAL_FULL_AUTHORIZATION \
  python3 examples/modal/modal_app.py
test "$?" -eq 64
```

Do not set the authorization variable for this GCP profile.

### 3. Recheck project, quota, and target absence

```bash
gcloud config set project lifeandhalf-24122025

gcloud compute instances list \
  --filter='name=glm47-full-v5-charm-h100-8' \
  --format='table(name,zone.basename(),machineType.basename(),status)'

gcloud compute machine-types list \
  --filter='name=a3-highgpu-8g AND zone:(us-central1-a us-central1-b us-central1-c)' \
  --format='table(name,zone.basename(),guestCpus,memoryMb)'

gcloud storage ls \
  gs://lifeandhalf-24122025-w8-biayn/glm47-full-v5/assets/synthmem-v1-ep50-grpo-adapter/ \
  gs://lifeandhalf-24122025-w8-biayn/glm47-full-v5/assets/runtime/
```

Stop if the target has an unexpected machine type or if the selected adapter
prefix is empty. The runtime prefix is currently expected to be empty and blocks GRPO.

### 4. Stage the one missing immutable asset

The selected SynthMem-v1 ep50 adapter is already stored at the bound GCS prefix
and installed on the H100 VM. Its HF bytes, config, training-run marker,
reconstruction receipt, and every native shard have passed remote verification.

Only the exact answer-blind full-v5 runtime remains missing. Obtain revision
`bfe0f68d85bd3d2899eb275043f7f42d669e4819` through an authorized source,
verify the archive and runtime digests, then upload it:

```bash
gcloud storage rsync --recursive \
  /approved/assets/aider_cpp_rl_full_v5 \
  gs://lifeandhalf-24122025-w8-biayn/glm47-full-v5/assets/runtime/aider_cpp_rl_full_v5
```

Required identities are in `configs/full_v5_charm_grpo/gcp-r1.json`. The host
driver verifies the model manifest and every listed model file; the ep50 marker,
HF/config/reconstruction/shard digests and byte-exact round-trip proof; then all
615 runtime task descriptors, oracle digests, split isolation, prompt weights,
privacy contract, and the full runtime tree digest.

### 5. Confirm the already-provisioned H100 target

Do not rerun the create command. The separate Spot VM already exists:

```bash
gcloud compute instances describe glm47-full-v5-charm-h100-8 \
  --project=lifeandhalf-24122025 \
  --zone=us-central1-a \
  --format='yaml(name,status,machineType,scheduling.provisioningModel)'

gcloud compute instances start glm47-full-v5-charm-h100-8 \
  --project=lifeandhalf-24122025 \
  --zone=us-central1-a

gcloud compute ssh glm47-full-v5-charm-h100-8 \
  --project=lifeandhalf-24122025 \
  --zone=us-central1-a
```

The VM is Spot with termination action STOP. Preserve run artifacts in GCS;
do not silently change machine type, checkpoint, zone, or provisioning model.

### 6. Install the source and copy assets to local storage

Copy the exact checked-out source to the VM, SSH into it, then stage assets:

```bash
gcloud compute scp --recurse \
  README.md configs docker examples scripts src \
  glm47-full-v5-charm-h100-8:~/browser-is-all-you-need \
  --zone=us-central1-a

gcloud compute ssh glm47-full-v5-charm-h100-8 --zone=us-central1-a

sudo mkdir -p /opt/glm47-full-v5/assets /opt/glm47-full-v5/results
sudo chown -R "$(id -u):$(id -g)" /opt/glm47-full-v5

gcloud storage rsync --recursive \
  gs://lifeandhalf-24122025-w8-biayn/glm47-public-pr-eval/assets/model/GLM-4.7-Flash \
  /opt/glm47-full-v5/assets/model/GLM-4.7-Flash

gcloud storage rsync --recursive \
  gs://lifeandhalf-24122025-w8-biayn/glm47-full-v5/assets/synthmem-v1-ep50-grpo-adapter \
  /opt/glm47-full-v5/assets/synthmem-v1-ep50/adapter

gcloud storage rsync --recursive \
  gs://lifeandhalf-24122025-w8-biayn/glm47-full-v5/assets/runtime/aider_cpp_rl_full_v5 \
  /opt/glm47-full-v5/assets/runtime/aider_cpp_rl_full_v5
```

### 7. Validate the host and build the isolated images

On the H100 VM:

```bash
cd ~/browser-is-all-you-need
PYTHONPATH=src .venv-gcp/bin/python scripts/gcp_full_v5_charm_grpo.py host-check
PYTHONPATH=src .venv-gcp/bin/python scripts/gcp_full_v5_charm_grpo.py prepare
```

`host-check` requires exactly eight H100 80 GB GPUs, Docker, and at least 250
GiB free. `prepare` verifies all immutable assets, builds the training and
verifier images once, runs the Docker reward preflight with networking off, and
writes a non-overwriting preparation receipt.

### 8. Complete CHARM admission and freeze the canary

Run Generator Admission V4.1 at `pre-training`. It must return an exact PASS
receipt for this corpus. Freeze a task manifest containing exactly 20 unique
full-v5 train task IDs and at least four matched trial IDs. Record SHA-256 for
both files:

```bash
sha256sum /approved/receipts/pre-training.json
sha256sum /approved/receipts/canary-task-manifest.json
```

Missing evidence is `not_completed`. Do not create a hand-written PASS receipt,
do not use fixed-26 failures to select tasks, and do not proceed on a judge-only
or score-only result.

### 9. Run the exact canary and obtain promotion PASS

For each of at least four matched trial IDs, use a fresh run ID and the exact
same 20-task manifest:

```bash
export RUN_ID="full-v5-charm-canary-trial1-$(date -u +%Y%m%dT%H%M%SZ)"

PYTHONPATH=src python3 scripts/gcp_full_v5_charm_grpo.py train \
  --phase canary \
  --run-id "${RUN_ID}" \
  --pretraining-receipt /approved/receipts/pre-training.json \
  --expected-pretraining-sha256 <PRETRAINING_RECEIPT_SHA256> \
  --canary-task-manifest /approved/receipts/canary-task-manifest.json \
  --expected-canary-task-manifest-sha256 <CANARY_MANIFEST_SHA256>
```

After all matched trials, run the CHARM promotion evaluator. Selection weights
are compile rate 0.4, hidden-test rate 0.4, validation loss 0.2; `always_final`
is false. Freeze the exact promotion PASS receipt and digest. A canary run alone
does not authorize full training.

### 10. Explicitly authorize and run the 57-update profile

Only after the exact promotion PASS:

```bash
export RUN_ID="aider-full-v5-production-ast17-r1-$(date -u +%Y%m%dT%H%M%SZ)"
export GLM47_FULL_V5_CHARM_FULL_TRAINING_AUTHORIZATION=I_AUTHORIZE_FULL_V5_CHARM_57_UPDATE_TRAINING

PYTHONPATH=src python3 scripts/gcp_full_v5_charm_grpo.py train \
  --phase full \
  --run-id "${RUN_ID}" \
  --promotion-receipt /approved/receipts/promotion.json \
  --expected-promotion-sha256 <PROMOTION_RECEIPT_SHA256>
```

The driver refuses reused run roots, allows only one GPU-heavy job, writes a
launch contract before Docker starts, keeps reward networking disabled, syncs
the run to GCS every 60 seconds, requires Miles `status=success`, writes an
execution receipt, and performs one final GCS sync. Afterward, run the disjoint
development evaluation and only then one frozen fixed-26 evaluation against a
matched baseline. Stop or delete the Spot VM after verifying the GCS receipt.

## Files that implement the profile

| File | Purpose |
| --- | --- |
| `configs/full_v5_charm_grpo/gcp-r1.json` | Frozen identities, schedule, hardware, reward, and admission state |
| `scripts/gcp_full_v5_charm_grpo.py` | Inspection, host validation, asset verification, image preparation, guarded canary/full execution, GCS sync |
| `src/glm47_posttraining/aider_polyglot/full_v5_charm.py` | Runtime privacy/oracle validation and deterministic equal-exposure schedule |
| `docker/full-v5-charm-grpo-gcp/Dockerfile` | Modal-free Miles training image |
| `docker/full-v5-charm-grpo-gcp/Verifier.Dockerfile` | Network-isolated C++ verifier image |
| `examples/modal/_authorization.py` | Default-deny Modal authorization boundary |

## Status semantics

Repository tests, H100 provisioning, hardware validation, and selected-adapter
validation are complete. Full-v5 runtime validation, image preparation, CHARM
pre-training admission, canary, promotion, full training, and deployment are
separate statuses and remain `not_completed` until their exact receipts pass.
