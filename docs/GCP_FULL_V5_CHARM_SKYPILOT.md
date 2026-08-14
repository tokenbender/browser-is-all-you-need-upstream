# SkyPilot smoke and canary operation for full-v5 + CHARM GRPO

This is the active SkyPilot entrypoint for the
`aider-full-v5-production-ast17-gcp-r1` profile. It provisions a separate,
ephemeral GCP `a3-highgpu-8g` node. It does not adopt or modify the manually
provisioned `glm47-full-v5-charm-h100-8` VM.

The task definition is `grpo_h100_full_v5_charm.yaml`. Its default mode is a
non-training smoke run. Full 57-update training is intentionally not exposed
through this task.

## Frozen execution profile

| Attribute | Value |
| --- | --- |
| Cloud | GCP project `lifeandhalf-24122025` |
| Provisioner | SkyPilot |
| Machine | `a3-highgpu-8g` |
| GPUs | Exactly 8x H100, at least 80,000 MiB each |
| Network | SkyPilot `network_tier: best` |
| Provisioning | Spot with autostop/down fallback |
| Boot disk | 500 GB high-tier ephemeral boot disk |
| Model | GLM-4.7-Flash revision `7dd20894a642a0aa287e9827cb1a1f7f91386b67` |
| Starting adapter | SynthMem-v1 ep50, epoch 50, `iter_0000649`, SHA-256 `4acb7f23c295f45380155c5d9ee6bc59422262f0cb51f0c02f7e550d405b575a` |
| Training topology | TP4 / PP1 / CP1 / EP8 / ETP1 |
| Rollout serving | SGLang DP8 |
| Smoke optimizer updates | Zero |
| Durable output | GCS under `runs/glm47/full-v5-charm` |
| Modal | Denied by the repository authorization guard |

## What the smoke run proves

The smoke mode executes only `host-check` and `prepare`. It proves:

1. the node exposes exactly eight qualifying H100 GPUs;
2. Docker and the NVIDIA runtime work;
3. at least 250 GiB of local storage remains;
4. every model-manifest entry passes SHA-256 verification;
5. the selected SynthMem-v1 ep50 adapter and all eight reconstructed native
   shards match their receipts;
6. the full-v5 package has the exact frozen manifest/tree digests, 615 targets,
   split isolation, unique executable oracles, and no packaged answers;
7. the training and network-isolated verifier images build successfully; and
8. the production reward preflight passes with verifier networking disabled.

It performs no optimizer update and does not claim CHARM pre-training
admission, canary success, promotion, or deployment readiness.

## Required GCS objects

These objects must exist before SkyPilot can start the task:

Current check on 2026-08-11: the selected ep50 adapter exists, but the complete
runtime prefix matches no GCS objects. Do not launch the paid smoke until that
exact runtime package is staged and its two frozen digests are independently verified.

```text
gs://lifeandhalf-24122025-w8-biayn/glm47-public-pr-eval/assets/model/GLM-4.7-Flash/
gs://lifeandhalf-24122025-w8-biayn/glm47-full-v5/assets/synthmem-v1-ep50-grpo-adapter/
gs://lifeandhalf-24122025-w8-biayn/glm47-full-v5/assets/runtime/aider_cpp_rl_full_v5/
gs://lifeandhalf-24122025-w8-biayn/runs/glm47/full-v5-charm/
```

The runtime prefix must contain `manifest.json` with SHA-256
`93d671faa44abcc6deca21c6a49e247d76436835bfa2905ee33968a478fb532a`
and tree SHA-256
`0a3df3ce40eed45814651c933277bfc5ca17359a2b3e6f0a7027b184e3569c7e`.

Check the external prerequisites without provisioning a GPU:

```bash
gcloud config set project lifeandhalf-24122025

gcloud storage ls \
  gs://lifeandhalf-24122025-w8-biayn/glm47-full-v5/assets/runtime/aider_cpp_rl_full_v5/manifest.json

gcloud storage ls \
  gs://lifeandhalf-24122025-w8-biayn/glm47-full-v5/assets/synthmem-v1-ep50-grpo-adapter/adapter_model.bin
```

## Install and validate the control plane

Run from this repository root:

```bash
python3 -m venv .venv-skypilot
source .venv-skypilot/bin/activate
python3 -m pip install "skypilot[gcp]"

gcloud auth login
gcloud auth application-default login
gcloud config set project lifeandhalf-24122025

sky check gcp
sky gpus list H100:8
sky launch --dryrun --yes grpo_h100_full_v5_charm.yaml
```

A dry run validates the SkyPilot request but does not validate remote asset
bytes or CHARM receipts.

## Launch the zero-update smoke

Use a fresh run ID:

```bash
export RUN_ID="full-v5-charm-skypilot-smoke-$(date -u +%Y%m%dT%H%M%SZ)"

sky launch \
  -c full-v5-charm-smoke \
  grpo_h100_full_v5_charm.yaml \
  --env GLM47_SKYPILOT_MODE=smoke \
  --env RUN_ID="${RUN_ID}" \
  --down \
  --yes
```

Monitor it while the cluster exists:

```bash
sky status
sky logs full-v5-charm-smoke
```

The durable preparation receipt is written to:

```text
gs://lifeandhalf-24122025-w8-biayn/runs/glm47/full-v5-charm/preparations/<RUN_ID>/preparation-receipt.json
```

After any provisioning, synchronization, or setup failure, check for a
remaining cluster and remove it explicitly:

```bash
sky status
sky down full-v5-charm-smoke --yes
```

## Canary launch boundary

Do not use canary mode until Generator Admission V4.1 `pre-training` returns
an exact PASS and the frozen manifest contains exactly 20 unique train tasks
and at least four matched trial IDs.

For each frozen matched trial, use a fresh run ID and immutable GCS object
versions:

```bash
export RUN_ID="full-v5-charm-canary-trial1-$(date -u +%Y%m%dT%H%M%SZ)"

sky jobs launch \
  -n "${RUN_ID}" \
  grpo_h100_full_v5_charm.yaml \
  --env GLM47_SKYPILOT_MODE=canary \
  --env RUN_ID="${RUN_ID}" \
  --env PRETRAINING_RECEIPT_GCS_URI="gs://<immutable-pretraining-receipt>" \
  --env PRETRAINING_RECEIPT_SHA256="<sha256>" \
  --env CANARY_TASK_MANIFEST_GCS_URI="gs://<immutable-canary-manifest>" \
  --env CANARY_TASK_MANIFEST_SHA256="<sha256>" \
  --yes
```

Managed jobs are used for canaries because they own the temporary cluster
lifecycle and recover infrastructure failures. The training driver still
fails closed on application, asset, reward-signal, receipt, or hash errors.
A completed canary does not authorize full training; the four matched trials
must first produce a CHARM promotion PASS.
