# Modal V5 Setup vs Current R6 GRPO Infrastructure

## Scope and comparison identity

| Side | Frozen identity | Comparison boundary |
| --- | --- | --- |
| Modal V5 setup | Commit `f71e9fc5fed7ff1f85c9e00a635375ecb9a2d185` | Checked-in Lium Aider GRPO launcher, common Miles launcher, container definition, reward bridge, sandbox, adapter preparation, checkpoint gate, and tests |
| Current R6 | Active worktree at committed HEAD `19c68240991563e4ddbc0171485b1850101e7e2b`, plus the effective local R6 changes present on 2026-08-12 | Direct GCP/GCE launch, Full-V5 schedule projection, Hybrid45 reward, isolated verifier, signal gates, smoke certification, checkpoint publication, and quarantine controls |

## Environment and dependency comparison

| Area | Modal V5 setup | Current R6 Full-V5 | Exact evidence |
| --- | --- | --- | --- |
| Execution platform | Preconfigured Lium node with eight H100 GPUs. The launcher assumes `/workspace/glm47`, `/workspace/assets`, `/workspace/models`, and `/workspace/runs` already exist. | Existing GCE `a3-highgpu-8g` Spot VM named `glm47-full-v5-charm-h100-8`. The submit script checks the VM state, starts it when terminated, stages the run bytes, and stops a VM it started if startup fails. | `examples/lium/aider_grpo_2ep.sh:4-16` · `configs/full_v5_charm_grpo/gcp-r6-hybrid45-v2-full.json:27-50` · `scripts/gcp_full_v5_unadmitted_r6_v2_submit.sh:80-157` |
| Host provisioning | Not implemented by the Aider GRPO launcher. The machine, drivers, Docker daemon, model, converted checkpoint, data, and adapter are external prerequisites. | The named VM must already exist, but lifecycle control is automated. The pipeline validates the provisioning model, GPU inventory, Docker daemon, and free storage before training. | `examples/lium/aider_grpo_2ep.sh:4-16` · `scripts/gcp_full_v5_charm_grpo.py:1681-1709` |
| GPU and distributed topology | Declares 8 GPUs with TP4 / PP1 / CP1 / EP8 / ETP1 and SGLang DP8. | Uses the same training and serving topology. Current adapter preparation additionally computes and validates the native shard-owner topology from TP, EP, and world size. | `examples/lium/aider_grpo_2ep.sh:77-125` · `configs/full_v5_charm_grpo/gcp-r6-hybrid45-v2-full.json:147-153` · `examples/grpo.sh:23-67` |
| Training base image | `radixark/miles:latest-cu12` pinned to digest `efc8027f…`. | Same exact base-image digest. | `Dockerfile:1-2` · `docker/full-v5-charm-grpo-gcp/Dockerfile:1` |
| GPU kernel alignment | Pins `flashinfer-python`, `flashinfer-cubin`, and `flashinfer-jit-cache` to `0.6.12`; `sglang-kernel` to `0.4.4`; and `torch-memory-saver` to `0.0.9.post1`. | Uses the same package versions and CUDA 12.9 indexes. | `Dockerfile:4-30` · `docker/full-v5-charm-grpo-gcp/Dockerfile:3-24` |
| Runtime dependency preflight | Checks that all five GPU runtime packages exist, meet minimum versions, and that all FlashInfer components have the same release. | Reuses the same `scripts/check_runtime.py` bytes and runs the check through `examples/grpo.sh`. | `scripts/check_runtime.py:12-75` · `scripts/check_runtime.py:12` · `examples/grpo.sh:134` |
| Python project dependencies | Direct dependencies are `huggingface-hub`, `pydantic`, and `wandb`. The core Miles/PyTorch/SGLang stack is supplied by the base image. | Adds direct Jinja, Tokenizers, and Transformers requirements for current prompt, tokenizer, and evaluation surfaces. The effective GCP training image still relies on the base image and individually installed packages rather than installing from `uv.lock`. | `pyproject.toml:5-20` · `pyproject.toml:5-26` · `docker/full-v5-charm-grpo-gcp/Dockerfile:3-38` |
| Static C++ analysis | No dedicated libclang evaluator is present in the Aider reward path. | Installs `libclang==18.1.1`, validates the runtime while building the image, and runs AST-backed checks before executable grading. | `docker/full-v5-charm-grpo-gcp/Dockerfile:29-55` · `src/glm47_posttraining/aider_polyglot/ast_evaluator.py:67` |
| Verifier image | The Lium launcher expects `glm47-aider-polyglot-cpp:latest`; the harness can build an Aider sandbox rooted in `gcc:13`. The launcher does not bind the mutable tag to an image digest. | Builds a separate `gcc:13` verifier image containing CMake, coreutils, and make. The runtime records the resulting immutable local image ID, although the upstream base tag and apt package versions are not digest-pinned. | `examples/lium/aider_grpo_2ep.sh:44-48` · `src/glm47_posttraining/aider_polyglot/harness.py:76-94` · `docker/full-v5-charm-grpo-gcp/Verifier.Dockerfile:1-12` · `scripts/gcp_full_v5_charm_grpo.py:1822-1840` |
| Candidate sandbox | Docker sandbox disables networking, caps CPU/memory/processes, uses a read-only root, drops all capabilities, applies `no-new-privileges`, and mounts only scratch read-write. | Preserves the locked-down Docker sandbox and places it behind a distinct verifier image. Training and reward preflight also run with networking disabled. | `src/glm47_posttraining/cpp_perf/sandbox.py:145-179` · `scripts/gcp_full_v5_charm_grpo.py:1526-1529` · `scripts/gcp_full_v5_charm_grpo.py:1741-1779` |
| Asset location | Reads the model, converted checkpoint, dataset, shadow task package, and warm-start adapter from fixed `/workspace` paths. | Reads model, SynthMem adapter, and Full-V5 API-contract runtime from declared GCS prefixes and validates their manifests and content digests on the VM. | `examples/lium/aider_grpo_2ep.sh:4-16` · `configs/full_v5_charm_grpo/gcp-r6-hybrid45-v2-full.json:46-96` · `scripts/gcp_full_v5_charm_grpo.py:1210` |
| Input identity checks | Before launch, verifies the data manifest, GRPO JSONL, adapter model, and shadow manifest against four hard-coded SHA-256 values. | Verifies model manifest, adapter files, reconstruction manifest, runtime manifest/tree, selected-task digest, staged source aggregate, container image IDs, and smoke receipt where applicable. | `examples/lium/aider_grpo_2ep.sh:10-40` · `configs/full_v5_charm_grpo/gcp-r6-hybrid45-v2-full.json:52-107` · `scripts/gcp_full_v5_unadmitted_r6_v2_submit.sh:216-230` |
| Process supervision | Runs `examples/grpo.sh` in the foreground and leaves external supervision to the Lium environment/operator. | Starts the remote driver in a named `tmux` session, retains PID/session/control files, and uploads the control directory to GCS. | `examples/lium/aider_grpo_2ep.sh:139-141` · `scripts/gcp_full_v5_unadmitted_r6_v2_headless.sh:82-125` |
| Artifact persistence | Writes checkpoints, W&B files, sync metrics, logs, and gates under `/workspace/runs/<run-id>`. Long-term copying is outside the Lium launcher. | Synchronizes non-checkpoint results periodically and publishes complete checkpoints to GCS only after content inventory and `COMPLETE.json` creation. | `examples/lium/aider_grpo_2ep.sh:6-8` · `scripts/gcp_full_v5_charm_grpo.py:994-1076` · `scripts/gcp_full_v5_charm_grpo.py:1115-1169` |
| Tracking and receipts | Offline W&B, sync metrics, the Miles run receipt, and a final GRPO checkpoint provenance gate. | Offline W&B plus raw rollout preservation, component rewards, per-update signal receipts, preparation receipt, execution receipt, GCS sync receipts, image identities, and smoke receipt. | `examples/lium/aider_grpo_2ep.sh:129-137` · `scripts/create_grpo_training_gate.py:127-148` · `configs/full_v5_charm_grpo/gcp-r6-hybrid45-v2-full.json:188-207` |

## Actual GRPO profile comparison

| Setting | Modal V5 GRPO | Current R6 full | Exact evidence |
| --- | ---: | ---: | --- |
| Starting adapter | Merged rank-32 SFT-1211 + SFT-530 | SynthMem-v1 ep50 rank-16, checkpoint `iter_0000649` | `examples/lium/aider_grpo_2ep.sh:10-16` · `configs/full_v5_charm_grpo/gcp-r6-hybrid45-v2-full.json:57-73` |
| Training task count | 169 | 475 deterministically selected `aider_cpp17` tasks | `examples/lium/aider_grpo_2ep.sh:70-75` · `configs/full_v5_charm_grpo/gcp-r6-hybrid45-v2-full.json:209-213` |
| Planned optimizer updates | 11 | 57 | `examples/lium/aider_grpo_2ep.sh:97` · `configs/full_v5_charm_grpo/gcp-r6-hybrid45-v2-full.json:125-145` |
| Approximate corpus exposure | `11 × 32 / 169 = 2.08` task slots per task | Three scheduled epochs | Same references as optimizer updates and task counts |
| Prompts per update | 32 | 25 | `examples/lium/aider_grpo_2ep.sh:103` · `configs/full_v5_charm_grpo/gcp-r6-hybrid45-v2-full.json:129` |
| Samples per prompt | 8 | 8 | `examples/lium/aider_grpo_2ep.sh:98` · `configs/full_v5_charm_grpo/gcp-r6-hybrid45-v2-full.json:130` |
| Global batch | 256 | 200 | `examples/lium/aider_grpo_2ep.sh:79` · `configs/full_v5_charm_grpo/gcp-r6-hybrid45-v2-full.json:131` |
| Sequence length | 6,144 | 34,816 | `examples/lium/aider_grpo_2ep.sh:111` · `configs/full_v5_charm_grpo/gcp-r6-hybrid45-v2-full.json:135` |
| Maximum response length | 4,096 | 16,384 | `examples/lium/aider_grpo_2ep.sh:104` · `configs/full_v5_charm_grpo/gcp-r6-hybrid45-v2-full.json:136` |
| Maximum packed tokens/GPU | 12,288 | 18,432 | `examples/lium/aider_grpo_2ep.sh:90` · `configs/full_v5_charm_grpo/gcp-r6-hybrid45-v2-full.json:137` |
| Thinking mode | Disabled | Enabled | `examples/lium/aider_grpo_2ep.sh:56-57` · `configs/full_v5_charm_grpo/gcp-r6-hybrid45-v2-full.json:133` |
| Temperature | 0.7 | 0.7 | `examples/lium/aider_grpo_2ep.sh:107` · `configs/full_v5_charm_grpo/gcp-r6-hybrid45-v2-full.json:134` |
| Learning rate | `5e-7` | `5e-7` | `examples/lium/aider_grpo_2ep.sh:89` · `configs/full_v5_charm_grpo/gcp-r6-hybrid45-v2-full.json:138` |
| Reference model and KL | Enabled, coefficient `0.02` | Same | `examples/lium/aider_grpo_2ep.sh:83-128` · `configs/full_v5_charm_grpo/gcp-r6-hybrid45-v2-full.json:139-141` |
| Reward workers | 32 | 32 | `examples/lium/aider_grpo_2ep.sh:44` · `configs/full_v5_charm_grpo/gcp-r6-hybrid45-v2-full.json:155-175` |
| Reward contract | Whole-file parser plus executable correctness. Passing tests earn `1.0`; partial tests earn `0.6 × fraction`; compile/timeout earns `-0.5`; invalid format earns `-0.8`; forbidden behavior earns `-1.0`. | Hybrid45 combines 25 static response checks and 20 executable checks into 45 outcomes, with explicit failure evidence and signal gating. | `src/glm47_posttraining/aider_polyglot/reward.py:28-70` · `src/glm47_posttraining/aider_polyglot/hybrid45.py:52` · `configs/full_v5_charm_grpo/gcp-r6-hybrid45-v2-full.json:155-175` |
| Infrastructure failure handling | Produces a numeric `0.0` record marked `infrastructure_error`. | Refuses a numeric model reward and aborts the scoring path with `AiderRewardInfrastructureError`. | `src/glm47_posttraining/aider_polyglot/reward.py:51-57` · `src/glm47_posttraining/integrations/miles_aider_polyglot.py:56` |
| Development evaluation frequency | Every update | Every 19 updates in the full profile | `examples/lium/aider_grpo_2ep.sh:65` · `configs/full_v5_charm_grpo/gcp-r6-hybrid45-v2-full.json:144` |
| Checkpoint frequency | Every update | Every update | `examples/lium/aider_grpo_2ep.sh:110` · `configs/full_v5_charm_grpo/gcp-r6-hybrid45-v2-full.json:142` |

## Pipeline code inherited and extended

| Modal V5 component | Modal V5 reference | Current counterpart | Relationship |
| --- | --- | --- | --- |
| Runtime dependency checker | `scripts/check_runtime.py:1-80` | `scripts/check_runtime.py:1` | Byte-for-byte identical at inspection time |
| Checkpoint conversion | `scripts/convert_checkpoint.sh:1-90` | `scripts/convert_checkpoint.sh:1` | Byte-for-byte identical at inspection time |
| Kernel-aligned base image | `Dockerfile:1-32` | `docker/full-v5-charm-grpo-gcp/Dockerfile:1` | Same Miles and GPU-kernel foundation; current adds Docker tooling, libclang, source packaging, and image preflight |
| Common GRPO environment | `examples/grpo.sh:1-117` | `examples/grpo.sh:1` | Expanded from 117 to 178 lines; adds TP/EP native-owner calculation, corrected chat-template handling, and reconstruction-manifest binding |
| Miles/Ray/SGLang launcher | `scripts/train_grpo.sh:1-693` | `scripts/train_grpo.sh:1` | Expanded from 693 to 865 lines; adds continuation provenance, quarantine enforcement, rollout validation hook, bounded Ray temp path, and richer worker environment |
| Adapter preparation | `scripts/prepare_grpo_adapter.py:1-188` | `scripts/prepare_grpo_adapter.py:1` | Expanded from 188 to 436 lines; verifies EP-aware shard ownership and a digest-bound native reconstruction proof |
| Checkpoint provenance gate | `scripts/create_grpo_training_gate.py:1-194` | `scripts/create_grpo_training_gate.py:1` | Expanded from 194 to 393 lines; validates TP/EP shard names and native reconstruction/round-trip evidence |
| Miles Aider reward bridge | `src/glm47_posttraining/integrations/miles_aider_polyglot.py:1-251` | `src/glm47_posttraining/integrations/miles_aider_polyglot.py:1` | Expanded from 251 to 862 lines; adds reward modes, no-update canary, fail-closed infrastructure behavior, and pre-optimizer rollout signal validation |
| Aider executable harness | `src/glm47_posttraining/aider_polyglot/harness.py:1-439` | `src/glm47_posttraining/aider_polyglot/harness.py:1` | Expanded from 439 to 1,361 lines; adds Weighted45 evidence, hidden partitions, sanitizers/concurrency paths, workspace integrity checks, and verifier handshakes |
| Whole-file parser | `src/glm47_posttraining/aider_polyglot/parser.py:1-114` | `src/glm47_posttraining/aider_polyglot/parser.py:1` | Expanded from 114 to 188 lines for segmented thinking/final-answer handling and stricter response contracts |
| Reward implementation | `src/glm47_posttraining/aider_polyglot/reward.py:1-73` | `src/glm47_posttraining/aider_polyglot/reward.py:1` and `src/glm47_posttraining/aider_polyglot/hybrid45.py:1` | Replaces the small partial-correctness calculation with multiple versioned reward contracts and exact receipt validation |

## What current R6 added

| Addition | Detailed behavior | Exact current implementation |
| --- | --- | --- |
| Deterministic Full-V5 task selection | Filters the frozen runtime by compatible harness kind, ranks task IDs deterministically, verifies the selected-set SHA-256, and rejects missing or duplicate selections. | `scripts/gcp_full_v5_charm_grpo.py:688` · `configs/full_v5_charm_grpo/gcp-r6-hybrid45-v2-full.json:209` |
| Schedule and prompt projection | Copies the validated Full-V5 package, rotates prompt variants by epoch, projects tasks to the isolated Hybrid45 prompt contract, rewrites development prompts, and records row/task/prompt digests. | `src/glm47_posttraining/aider_polyglot/full_v5_charm.py:265` |
| Native TP/EP shard-owner validation | Derives native checkpoint owners from TP4, EP8, and world size 8 instead of assuming native shard count equals TP size. | `examples/grpo.sh:23-67` · `scripts/train_grpo.sh:41-79` |
| Native reconstruction-manifest verification | Requires the reconstructed native shards to bind the exact Hugging Face tensor content, topology, round-trip proof, and manifest SHA-256 before continuation. | `scripts/prepare_grpo_adapter.py:154-284` · `scripts/create_grpo_training_gate.py:168-286` |
| Rollout validation before optimizer update | Validates group count, samples per group, task metadata, Hybrid45 receipts, format rate, compile rate, and multiple forms of reward variance before a batch reaches the optimizer. | `src/glm47_posttraining/integrations/miles_aider_polyglot.py:499` · `scripts/gcp_full_v5_charm_grpo.py:1520` |
| Hybrid45 no-update preflight | Executes reward-policy self-checks without an optimizer update and requires a PASS receipt with the exact policy identity before preparation completes. | `src/glm47_posttraining/integrations/miles_aider_polyglot.py:80` · `scripts/gcp_full_v5_charm_grpo.py:1739` |
| Format, compile, semantic, reward, and kernel-variance signal gates | Measures whether each rollout has enough usable output and within-task variation to create a meaningful GRPO gradient. A failed threshold aborts before optimization. | `configs/full_v5_charm_grpo/gcp-r6-hybrid45-v2-full.json:155-175` · `src/glm47_posttraining/integrations/miles_aider_polyglot.py:499` |
| Fail-closed verifier infrastructure handling | Separates verifier/platform failure from model failure and raises `AiderRewardInfrastructureError` instead of silently assigning a numeric model reward. | `src/glm47_posttraining/integrations/miles_aider_polyglot.py:56` · `src/glm47_posttraining/integrations/miles_aider_polyglot.py:258` |
| AST/libclang checks | Adds a libclang-backed C++ structural evaluator and validates the clang runtime while building the training image. | `src/glm47_posttraining/aider_polyglot/ast_evaluator.py:67` · `docker/full-v5-charm-grpo-gcp/Dockerfile:54` |
| Network-isolated verifier image | Builds verifier tooling separately from the GPU trainer and runs candidate evaluation with networking disabled and restricted sandbox permissions. | `docker/full-v5-charm-grpo-gcp/Verifier.Dockerfile:1` · `scripts/gcp_full_v5_charm_grpo.py:1526` |
| GCE staging with local/remote byte comparison | Stages only declared inputs to a fresh remote directory, hashes the complete local and remote build contexts, and refuses execution on any mismatch. | `scripts/gcp_full_v5_unadmitted_r6_v2_submit.sh:216-230` · `scripts/gcp_full_v5_unadmitted_r6_v2_smoke_submit.sh:166-180` |
| One-update smoke certification | Requires one optimizer update, one valid signal-gate receipt, changed weights, immutable image IDs, matching local/GCS checkpoint bytes, and a durable synchronization receipt. | `scripts/create_unadmitted_grpo_smoke_receipt.py:217-369` · `scripts/gcp_full_v5_unadmitted_r6_v2_smoke_finalize.sh:26` |
| Periodic GCS synchronization | Synchronizes durable non-checkpoint artifacts throughout the Spot run and records success/failure cycles instead of waiting for process exit. | `scripts/gcp_full_v5_charm_grpo.py:1115` |
| Checkpoint `COMPLETE` markers | Inventories and hashes a complete checkpoint, copies its tree, and writes the marker last so consumers do not accept partial uploads. | `scripts/gcp_full_v5_charm_grpo.py:1012` · `scripts/gcp_full_v5_charm_grpo.py:994` |
| Explicit unadmitted/quarantine status | Records incomplete admission, disables CHARM eligibility and retroactive admission, and constrains checkpoints to quarantine-only use. Training completion cannot change that status. | `configs/full_v5_charm_grpo/gcp-r6-hybrid45-v2-full.json:177-207` · `scripts/train_grpo.sh:143` |

| Central orchestration | Coordinates preparation, validation, image construction, training, receipt creation, checkpoint publication, and execution status. | `scripts/gcp_full_v5_charm_grpo.py:1622` |

## Where the Modal V5 setup was better

| Advantage | Detail | File |
| --- | --- | --- |
| Compact launch profile | One 141-line shell specification declares the principal paths and hyperparameters before calling the common GRPO launcher. | `examples/lium/aider_grpo_2ep.sh:1-141` |
| Clear input identity checks | Four SHA-256 checks at the start of the launcher make the immediate warm-start prerequisites easy to audit. | `examples/lium/aider_grpo_2ep.sh:10-40` |
| Small reward implementation | The reward contract is compact enough to audit end-to-end in one file. | `src/glm47_posttraining/aider_polyglot/reward.py:1-73` |
| Smaller direct dependency surface | Three direct runtime dependencies are declared while the GPU training stack comes from the pinned Miles image. | `pyproject.toml:5-20` |
| Immutable tested revision | The exact source revision is fixed and its selected GRPO infrastructure suite passed 92 tests. | Commit `f71e9fc5fed7ff1f85c9e00a635375ecb9a2d185` |

## Current setup problems found

| Finding | Evidence | Operational consequence | Required correction |
| --- | --- | --- | --- |
| Provisioning-policy test drift | The R6 profiles declare `SPOT` (`configs/full_v5_charm_grpo/gcp-r6-hybrid45-v2-full.json:41`), while `tests/test_gcp_full_v5_hybrid45_v2.py:56` expects `STANDARD`. | The selected current infrastructure suite reports one failure even though the launch scripts explicitly require Spot. | Decide the frozen policy and update the test or profiles consistently. Do not treat a red suite as release-ready. |
| Effective R6 code is not fully committed | At inspection time, R6 profiles, submit/headless/finalization scripts, smoke certifier, and `hybrid45.py` were untracked; the driver, harness, integration, Full-V5 projector, and GCP Dockerfile were modified. | Committed HEAD alone cannot reproduce the executed R6 pipeline or its six-update reduced run. | Commit a reviewed, digest-bound snapshot and rerun the infrastructure suite from a clean checkout. |
| Development-count drift | The runtime identity declares 60 development targets (`configs/full_v5_charm_grpo/gcp-r6-hybrid45-v2-full.json:91`), while `full_training` declares 64 (`configs/full_v5_charm_grpo/gcp-r6-hybrid45-v2-full.json:127`). The Hybrid45 projector filters development rows by compatible harness. | Receipts and capacity planning can disagree about the evaluation denominator. Existing targeted tests do not catch this mismatch. | Bind the projected development count and digest in the profile and validate it before training. |
| Detailed verifier logs are disabled | `build_training_env` sets `MILES_CPP_INCLUDE_LOGS=0` (`scripts/gcp_full_v5_charm_grpo.py:1525`). | The recent `concurrent-tag-factory` infrastructure abort retained the task identity but not the low-level compiler/sanitizer failure. | Retain bounded infrastructure logs separately from model-facing reward data, with redaction and size limits. |
| Duplicate logical task groups are permitted | `require_unique_task_groups` is false (`configs/full_v5_charm_grpo/gcp-r6-hybrid45-v2-full.json:171`). | The full run can proceed with multiple variants of the same logical task in one rollout, altering the independence assumption for GRPO groups. | Define a variant-aware sampler contract or enforce unique logical tasks per optimizer batch. |
| Format threshold was relaxed | The current minimum exact-format rate is `0.35` (`configs/full_v5_charm_grpo/gcp-r6-hybrid45-v2-full.json:172`) after the R6 smoke observed 0.39 against the earlier 0.50 gate. | A threshold change can permit launch without showing that response formatting improved. | Freeze a justified threshold before the next smoke and report behavioral improvement separately from policy relaxation. |
| Verifier base is not fully immutable | `docker/full-v5-charm-grpo-gcp/Verifier.Dockerfile:1-6` uses `gcc:13` plus unpinned apt packages. | A later rebuild can change compiler, CMake, make, or libc behavior while retaining the same source Dockerfile. | Pin the verifier base digest and preserve installed-package/version inventory in the preparation receipt. |
| Project lockfile is not the effective GPU-image lock | The GCP image installs selected packages directly and copies source files (`docker/full-v5-charm-grpo-gcp/Dockerfile:3-52`); it does not install the project from `uv.lock`. | A green local locked environment does not prove the remote trainer has the same full Python dependency graph. | Produce an image-level Python BOM and either install a frozen project lock or digest-bind the complete inherited environment. |
| Full 475-task execution is not yet demonstrated | The full attempt stopped on duplicate task groups; its retry stopped on a verifier infrastructure failure. Only the narrowed 40-task, six-update run completed. | The successful reduced run proves the selected non-concurrent path, not the complete R6 schedule. | Resolve grouping and concurrency-verifier behavior, then obtain a fresh full-corpus smoke and complete run. |
| R6 remains unadmitted | Admission, canary, and promotion receipts remain `NOT_COMPLETED`, and the checkpoint disposition is `QUARANTINE_ONLY` (`configs/full_v5_charm_grpo/gcp-r6-hybrid45-v2-full.json:177-207`). | Even a technically successful optimizer run cannot be treated as a promotable CHARM checkpoint. | Complete the required admission and canary gates under a separately authorized run. |

## Targeted test evidence

| Revision | Command scope | Result |
| --- | --- | ---: |
| Modal V5 setup `f71e9fc5…` | `test_glm47_h100.py`, `test_grpo_training_gate.py`, `test_miles_aider_polyglot.py` | **92 passed** |
| Current active worktree | Same three core files plus current GCP Full-V5, Hybrid45 V2, and unadmitted-smoke tests | **159 passed, 1 failed** |

## System flow comparison

| Flow | System sequence |
| --- | --- |
| Modal V5 setup | Pinned Miles image ------> runtime dependency check ------> checkpoint conversion ------> adapter preparation ------> Ray startup ------> SGLang rollout serving ------> Aider reward workers ------> optimizer updates ------> checkpoint provenance gate ------> Lium run directory |
| Current R6 | Existing GCE Spot VM ------> H100/Docker/storage host check ------> digest-bound GCS assets ------> local/remote source-byte verification ------> training and verifier image builds ------> Full-V5 task filtering ------> Hybrid45 prompt projection ------> no-update reward preflight ------> Ray and SGLang GRPO ------> pre-optimizer signal gate ------> isolated 45-check verifier ------> optimizer update ------> complete-checkpoint marker ------> periodic GCS publication ------> quarantine-only receipt |
| Relationship | Modal V5 Miles/Ray/SGLang foundation ------> current topology and reconstruction hardening ------> Full-V5 schedule projection ------> Hybrid45 reward and signal gates ------> GCP durability and smoke certification ------> explicit quarantine/admission boundary |
