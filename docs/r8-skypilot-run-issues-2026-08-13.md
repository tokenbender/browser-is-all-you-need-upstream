# R8 SkyPilot run issue ledger — 2026-08-13

## Purpose and claim boundary

This is the chronological incident ledger for the experimental R8 SkyPilot
lane, beginning with the first managed launch and ending with the latest known
attempt. Append new attempts; do not rewrite an earlier failure as a PASS after
a later fix.

The active profile is explicitly `UNADMITTED_EXPERIMENT_ONLY`. Its checkpoint
disposition is `QUARANTINE_ONLY`. Pre-training admission, canary, training
dynamics, checkpoint promotion, and deployment certification are all
`NOT_COMPLETED`. Jobs 1-18 did not reach an optimizer update. Job 19 completed
one update and published one complete checkpoint before failing during the
next SGLang memory-resume boundary. Job 22 later completed all six configured
updates and checkpoints. Job 30 completed the fixed-26 evaluation of Job 22's
final adapter; none of these results changes the unadmitted/quarantine labels.

The configured durable result root is:

```text
gs://lifeandhalf-24122025-w8-biayn/runs/glm47/experiments/unadmitted-r8-hybrid45-exact40-r87
```

## Current outcome

No managed job is currently running. Managed job 22, base run
`unadmitted-r8-r87-run21-20260814T030808Z`, completed all six optimizer updates
and published complete checkpoints `iter_0000000` through `iter_0000005`.
Its terminal execution receipt is `passed`, with 51 consecutive successful
result synchronizations and no periodic sync failure. Its final GRPO LoRA
adapter SHA-256 is
`7fb350de045fb1d476fefcdaeb59a5c69ea7f5e2fe744516b63e146f26d8bfc2`.

Managed job 30 then completed a two-attempt fixed-26 evaluation of that final
adapter: pass@1 `0/26`, pass@2 `4/26`, well-formed `26/26`, errors/context
exhausted `9`, malformed `0`, and timeouts `0`. This ties the single raw base
receipt at pass@1/pass@2 and is therefore not evidence of benchmark uplift.
It is also not directly matched to the historical SFT trials because those
used the `fixed26-contract-v2` prompt overlay while job 30 used the raw suite.

## Chronological ledger

| Incident | Run/job | Stage | Confirmed result | Status |
| --- | --- | --- | --- | --- |
| R8-SKY-001 | `unadmitted-r8-r87-20260813T103246Z`, job 1 | SkyPilot setup | `sudo: command not found` in `scripts/gcp_h100_host_setup.sh`; setup returned 127. | Resolved in later attempts; later host setup passes. |
| R8-SKY-002 | same run ID, job 2 | Cancellation/cleanup | A cancelled launch could not delete its ephemeral GCS bucket because the controller reported invalid OAuth service-account credentials. | Historical controller cleanup failure; not a worker or model failure. |
| R8-SKY-003 | `unadmitted-r8-r87-20260813T105309Z`, job 3 | Driver import | `ModuleNotFoundError: No module named 'pydantic'`. | Resolved by the pinned host-side Pydantic environment; jobs 5-8 pass this import. |
| R8-SKY-004 | `r8-host-python-smoke-20260813-1`, job 4 | CPU smoke provisioning | Operator-cancelled before a worker log was recovered; log sync then saw SSH connection refused. | Cancelled, not a pipeline PASS or failure diagnosis. |
| R8-SKY-005 | `unadmitted-r8-r87-20260813T114613Z`, job 5 | Provenance preflight | Frozen workdir had no `.git`; `git rev-parse` failed and source commit was unavailable. | Resolved by frozen `GLM47_SOURCE_COMMIT` provenance. |
| R8-SKY-006 | `unadmitted-r8-r87-20260813T123051Z`, job 6 | Prepare | Only generic exit 2 survived in the SkyPilot worker log. The redirected prepare log was lost with the worker. | Observability defect resolved; the original application exception remains unknown. |
| R8-SKY-007 | `unadmitted-r8-r87-20260813T142344Z`, no managed job | Local transport upload | SkyPilot `StorageUploadError` while scanning a transport workdir nested inside the parent Git worktree. | Resolved by constructing transport workdirs under `/tmp`. No H100 job was submitted. |
| R8-SKY-008 | `unadmitted-r8-r87-20260813T143001Z`, job 7 | Checkpoint conversion precheck | Pinned image lacked `/root/miles/scripts/models/glm4.7-flash.sh`; conversion returned 2. | Resolved by a read-only compatibility adapter; job 8 passed this check. |
| R8-SKY-009 | `unadmitted-r8-r87-20260813T151037Z`, job 8 | Prepare / checkpoint conversion | The PP1 bridge expected an obsolete exact source marker and rejected the pinned Miles converter. All eight ranks exited 1. | Host source was repaired, but that repair was not propagated to the pinned runtime image. |
| R8-SKY-010 | `unadmitted-r8-r87-20260813T160115Z`, job 9 | Prepare / checkpoint conversion | Frozen upload and preflights passed, but conversion used the unchanged image-embedded wrapper and reproduced R8-SKY-009. | Failed. Source-propagation and preflight-fidelity defects are open. |
| R8-SKY-011 | local image publication preflight | Image build / exact-runtime preflight | Repaired PP1 image built and verified at digest `sha256:97d43765c92ceb07414cbe03ed869c7365b12969e50d716f4b83757f439a237f`. | Published for job 10; PP1 failure resolved. |
| R8-SKY-012 | `unadmitted-r8-r87-20260813T165011Z`, job 10 | Prepare / checkpoint conversion import | Bridge callback accessed removed `log_utils.log_passrate`; all conversion ranks terminated before weight conversion. | Repaired locally with current/legacy Miles API compatibility; replacement image publication pending. |
| R8-SKY-013 | `unadmitted-r8-r87-20260813T173458Z`, job 11 | Train / exact-40 schedule staging | Preparation and checkpoint conversion passed; the host dispatcher rejected valid phase `experimental` as an unsupported R7 phase. | Repaired locally; focused schedule/profile/transport tests pass. Next paid run not yet launched. |
| R8-SKY-014 | `unadmitted-r8-r87-20260813T182102Z`, job 12 | Training container / quarantine contract | Job 11 schedule repair passed and the training container started, but its image-resident run-ID whitelist omitted `unadmitted-r8-r87-*`. | Repaired in a new locally validated image; remote publication pending. No optimizer update. |
| R8-SKY-015 | `unadmitted-r8-r87-20260813T191050Z`, job 13 | Miles training import / W&B compatibility | Current W&B removed the legacy callable `wandb.util.generate_id` expected by pinned Miles. | Resolved with a compatibility alias to `wandb.sdk.lib.runid.generate_id`; no optimizer update. |
| R8-SKY-016 | `unadmitted-r8-r87-20260813T200320Z`, job 14 | H100 runtime preflight | The in-image FlashInfer and SGLang kernel family was incompatible with the runtime contract. | Resolved by aligned pins: FlashInfer 0.6.14 and `sglang-kernel` 0.4.5 for CUDA 12.9; no optimizer update. |
| R8-SKY-017 | `unadmitted-r8-r87-20260813T210637Z`, job 15 | First training rollout / context isolation | The 160-sample rollout completed, but executed reward evidence lacked required `verification_workspace_id`. | Resolved with the schema-v2 isolated verifier-workspace receipt; no optimizer update. |
| R8-SKY-018 | `unadmitted-r8-r87-20260813T221420Z`, job 16 | First training rollout / DP sharding | Initial eval and all 160 rollout samples completed; bridge raised `AttributeError` because `miles.utils.data.ray` does not exist. | Resolved by lazy import of the installed Ray API; no optimizer update. |
| R8-SKY-019 | `unadmitted-r8-r87-20260813T231944Z`, job 17 | First optimizer boundary | Native Ray sharding passed, but copied rollout handling assumed `Timer` was re-exported from `miles.utils.data`. | Resolved by delegating fetching and sharding to pinned Miles; job 17 produced no optimizer update. |
| R8-SKY-020 | `unadmitted-r8-r87-20260814T003005Z`, job 18 | Trainer lifecycle | All eight actors segfaulted at `Timer data_preprocess start` because the bridge paused TMS and destroyed groups without setting `_asleep=True`, so `train()` skipped `wake_up()`. | State transition fixed in source and image `sha256:5df1c41e...`; run 19 also bypasses this path with resident training. |
| R8-SKY-021 | `unadmitted-r8-r87-20260814T014330Z`, job 19 | Post-update SGLang resume | Optimizer update 1 and checkpoint `iter_0000000` completed, then `resume_memory_occupation` lost the SGLang scheduler connection; the scheduler exited `-3` and peers reported Gloo/TCPStore/NCCL teardown errors. | Failed after one durable checkpoint; later resident-trainer structure in job 22 passed this boundary. |
| R8-SKY-022 | eval job 20 | Evaluation setup | Setup assumed `sudo`, which was absent in the worker image; exit 127. | Failed setup; packaging repaired. |
| R8-SKY-023 | eval jobs 21 and 26 | Evaluation dependencies | Full Aider development dependencies could not resolve on Python 3.10 because `contourpy==1.3.3` requires Python 3.11+. | Failed setup; replaced with minimal benchmark dependencies. |
| R8-SKY-024 | `unadmitted-r8-r87-run21-20260814T030808Z`, job 22 | Full GRPO execution | Six optimizer updates, six complete checkpoints, terminal receipt PASS, and 51 consecutive successful syncs. | Training execution passed; remains `UNADMITTED_EXPERIMENT_ONLY` and `QUARANTINE_ONLY`. |
| R8-SKY-025 | eval job 23 | Evaluation import | `ModuleNotFoundError: lox`. | Failed; dependency added to the minimal eval environment. |
| R8-SKY-026 | eval jobs 24, 25, 27 and 28 | Evaluation provisioning | Attempts were cancelled; later attempts included Spot availability and on-demand quota/capacity paths. | Cancelled, not scored. |
| R8-SKY-027 | eval job 29 | Benchmark path | Tasks ran against a hard-coded `/aider/benchmark/cpp-test.sh`, but `/aider` was absent. | Cancelled/no score; canonical `/aider` symlink added. |
| R8-SKY-028 | `job22-iter5-fixed26-v5-pathfix-20260814T071410Z`, job 30 | Fixed-26 evaluation | Complete two-attempt evaluation: pass@1 0/26, pass@2 4/26; all 26 outputs well formed; 9 error/context-exhaustion cases. | Evaluation PASS/complete; no uplift over the single raw base receipt, and not matched to the historical SFT overlay. |

## Incident details

### R8-SKY-001 — worker image did not provide `sudo`

Job 1 verified the frozen archive and all eight H100s, then setup stopped at:

```text
scripts/gcp_h100_host_setup.sh: line 62: sudo: command not found
```

This is an image/setup compatibility problem, not a GPU-capacity failure.
Subsequent jobs completed the same host setup, so the active path has moved
past it.

### R8-SKY-002 — cancelled controller cleanup lost GCS authorization

Job 2 was cancelled while launching. Cleanup reported:

```text
StorageBucketDeleteError: Your "OAuth 2.0 Service Account" credentials are invalid
```

This terminal state is `FAILED_CONTROLLER`. It must not be merged with job 1's
worker setup failure. Later launches prove that the controller regained enough
GCP authorization to provision and clean up new jobs; they do not prove that
the old ephemeral bucket was deleted.

### R8-SKY-003 — missing host Pydantic dependency

Job 3 reached the Python driver but import of the task schema failed:

```text
ModuleNotFoundError: No module named 'pydantic'
```

The frozen driver imports repository modules before Docker launch, so the host
requires the exact Pydantic dependency set. Later setup logs show the pinned
Pydantic 2.12.5 environment installing successfully.

### R8-SKY-004 — cancelled CPU dependency smoke

The low-cost CPU smoke was cancelled during provisioning. Its later SSH error
is a log-recovery consequence after teardown, not evidence of a Python or R8
application failure. No PASS may be claimed for this smoke.

### R8-SKY-005 — source provenance unavailable outside Git

Job 5 ran from a digest-frozen workdir without `.git` and failed with:

```text
fatal: not a git repository (or any of the parent directories): .git
FULL_V5_CHARM_GCP_FAILED: source commit is unavailable
```

The transport now records and supplies source revision
`19c68240991563e4ddbc0171485b1850101e7e2b` through
`GLM47_SOURCE_COMMIT`. This preserves provenance without pretending that the
transport directory is a Git checkout.

### R8-SKY-006 — generic exit 2 with lost stage diagnostics

Job 6 passed host dependency installation but the worker log retained only:

```text
ERROR: Job 1 failed with return code list: [2]
```

The exact application exception is unrecoverable because the stage output was
redirected to the ephemeral worker and the worker was deleted. It is incorrect
to assign a guessed root cause retroactively.

The remediation streams each stage to SkyPilot and mirrors logs and stage
markers to:

```text
<durable-root>/attempt-index/<base-run-id>/<attempt-run-id>/control/
<durable-root>/attempt-index/<base-run-id>/<attempt-run-id>/stages/
```

A Docker digest-verification defect was also corrected during this
remediation: a local Docker image ID is not the same identity as a registry
manifest digest. That defect was real, but the missing job 6 evidence does not
prove it was job 6's terminal cause.

### R8-SKY-007 — SkyPilot Git scanner followed broken parent metadata

The local transport for run `20260813T142344Z` passed its own frozen-source
checks and created a SkyPilot GCS bucket, but upload failed before managed-job
submission. SkyPilot treated the nested transport directory as part of the
parent repository and invoked Git submodule scanning. The parent `.gitmodules`
state contained a submodule path with no URL, producing exit 128.

The submitter now builds the transport under a fresh `/tmp/glm47-r8-*`
directory outside the repository. An exact SkyPilot scanner preflight passed
there. Because upload failed before submission, this incident allocated no
managed H100 worker.

### R8-SKY-008 — Miles model-argument filename mismatch

Job 7 passed reward-sandbox preflight and then failed before loading weights:

```text
Missing model args: /root/miles/scripts/models/glm4.7-flash.sh
```

Pinned Miles commit `8f0d065080076186ab152ee0129aceae34be756f`
contains `scripts/models/glm4.7-flash.py`, not the shell file expected by the
existing conversion script. The repository now supplies
`configs/miles/glm4.7-flash.sh` as a read-only compatibility adapter and binds
the relevant Miles source hashes. Job 8 reached the next conversion guard,
which is execution evidence that this missing-file issue is resolved.

### R8-SKY-009 — stale PP1 source-patching contract

Job 8 passed host check, image inspection, the Miles GRPO advantage contract,
and the Hybrid45 zero-update reward preflight. It then launched checkpoint
conversion with `--gpus all`, TP4/PP1/EP8, and eight ranks.

The repository wrapper currently expects this exact old Miles source marker:

```python
if args.pipeline_model_parallel_size == 1 and world_size > 1:
```

The pinned image actually contains a native opt-out guard:

```python
if args.pipeline_model_parallel_size == 1 and world_size > 1 and not os.environ.get("CONVERT_KEEP_PP1"):
```

Therefore the wrapper stopped every rank with:

```text
RuntimeError: GLM47_KEEP_PP1=1 but the PP-override marker is missing ...;
inspect the converter before forcing PP1
```

This is a repository-to-pinned-image compatibility mismatch. It is not a CUDA
failure and not a slow conversion. The pinned Miles converter already provides
the intended native mechanism.

The implemented remediation:

1. uses the pinned converter's native `CONVERT_KEEP_PP1=1` contract without
   changing its source bytes;
2. retains the compatibility patch only for the known legacy source shape and
   fails closed for an unknown converter;
3. binds `tools/convert_hf_to_torch_dist.py` at SHA-256
   `0c2541d30073777a30344273a3773844a70ca1961287520c0496a1cec18d43f6`;
4. tests native, legacy, disabled, and unknown converter cases;
5. attempted an immutable-image validation by mounting the repaired repository
   at `/workspace` and setting `PYTHONPATH=/workspace/src`;
6. passes the nine-file Miles source contract with zero optimizer updates;
7. passes the complete repository suite: 646 tests in 137.52 seconds;
8. regenerates the 78-file effective-source manifest at SHA-256
   `674613c066c4c6fc59f6e776567131a776dbf6d4724efc1ed86a2e4f702f73f9`
   and source-set SHA-256
   `9786c9799433f7e465b1d2c009a950ccca15bf0327c6d3e90e942e57072f9bd5`;
   and
9. builds a PASS transport with 80 members and archive SHA-256
   `801aeffe74e65e3ad9e633420e02eb573afddba57aafaf458797a04fdebf2a4a`.

Postmortem correction after job 9: item 5 did not validate the code path used
by the paid run. It imported the mounted `/workspace` wrapper, while the real
conversion command imported `/opt/full-v5-charm/src` from the immutable image.
The local unit, source-contract, and transport results remain valid for their
declared scopes, but they do not resolve runtime source propagation and never
proved remote checkpoint conversion, training, admission, canary, promotion,
or deployment.

### R8-SKY-010 — repaired transport source was not used by the container

Job 9's frozen archive contains the repaired wrapper:

```text
d8a0725974625d06a485a5afc2248e8af863516d69a0926cdbb5fcd4b63463bc
```

The unchanged pinned training image contains the old wrapper:

```text
a69553183ebc6d87b7a154962331fc77c11d4ebff5fc6c59b4e685ab7c46af2f
```

The conversion command mounts the model directory and the model-argument
adapter only. It does not mount the transported conversion script or wrapper,
and it invokes:

```text
/opt/full-v5-charm/scripts/convert_checkpoint.sh
```

from immutable image digest
`sha256:21a7bedf3c0fa066fb1a44f338684f438c51f5d47000378d4f6249075fac96f0`.
That is the same image used by job 8. Consequently all eight ranks executed
the old `_load_source()` and raised the same obsolete-marker error.

The next launch must be blocked until one exact runtime strategy passes:

1. rebuild and publish an immutable training image containing the repaired
   conversion script and wrapper, then update every image digest binding; or
2. mount both repaired files read-only at their exact `/opt/full-v5-charm`
   runtime paths, bind their hashes in the preparation contract, and validate
   the exact production `docker run` command.

Testing a substitute `PYTHONPATH` or mounted source tree is insufficient. The
preflight must assert the hashes of the files at the paths the production
command will execute.

Job 9's durable attempt is:

```text
unadmitted-r8-r87-20260813T160115Z-attempt-20260813T161425Z-b8dc750c
```

Its durable stage markers report a terminal `prepare` failure. Host-check,
image inspection, rendering, the nine-file Miles source contract, and the
Hybrid45 zero-update preflight completed before conversion failed. No optimizer
update occurred.

Job 8's durable terminal evidence is under:

```text
gs://lifeandhalf-24122025-w8-biayn/runs/glm47/experiments/unadmitted-r8-hybrid45-exact40-r87/attempt-index/unadmitted-r8-r87-20260813T151037Z/unadmitted-r8-r87-20260813T151037Z-attempt-20260813T151952Z-045fb0ca/
```

The durable markers report `last_stage=prepare`, `exit_code=2`, and
`checkpoint_disposition=QUARANTINE_ONLY`. `prepare.log`, stage markers, the
advantage-contract receipt, and the Hybrid45 zero-update receipt are present.

### R8-SKY-011 — repaired image built locally; registry publication not yet authorized

A replacement image was built under a new, non-overwriting local tag:

```text
glm47-full-v5-unadmitted-grpo:gcp-r8-hybrid45-exact40-r87-pp1fix-20260813
```

The build enforced the pinned Miles commit and all nine source-file hashes,
including `tools/convert_hf_to_torch_dist.py` at SHA-256
`0c2541d30073777a30344273a3773844a70ca1961287520c0496a1cec18d43f6`.
Its embedded zero-update GRPO advantage contract returned `status: PASS` and
`optimizer_updates: 0`. The local image identity is:

```text
sha256:97d43765c92ceb07414cbe03ed869c7365b12969e50d716f4b83757f439a237f
```

An exact-image, no-network, no-host-mount preflight verified these production
runtime paths:

```text
d8a0725974625d06a485a5afc2248e8af863516d69a0926cdbb5fcd4b63463bc  /opt/full-v5-charm/src/glm47_posttraining/integrations/miles_convert_with_glm47_bridge.py
a328235337927d331f1853253528d5e599855d4e352619aaa1f516fd63dd3db1  /opt/full-v5-charm/scripts/convert_checkpoint.sh
0c2541d30073777a30344273a3773844a70ca1961287520c0496a1cec18d43f6  /root/miles/tools/convert_hf_to_torch_dist.py
```

The image-resident wrapper preserved the pinned converter source unchanged,
detected its native `CONVERT_KEEP_PP1` guard, and set
`CONVERT_KEEP_PP1=1`; the semantic probe returned
`EXACT_IMAGE_PP1_PREFLIGHT_PASS`. The local publication gate also passed with
effective-source manifest SHA-256
`1cc2d4ded08b403e30b20bdff99ee526baaa1f80f9216598c1bae40985837d92`
and source-set SHA-256
`eff19ac97e584f507deefd4df95ccec86ee59f529166dabd3205c19e469331e2`.
Focused PP1, R8 image-binding, asset-publication, and SkyPilot launch tests
passed: 86 tests in 4.93 seconds.

No registry upload or GPU launch followed this local proof. The repository's
separate image-publication authorization
`GLM47_R8_IMAGE_PUBLICATION_AUTHORIZATION` was not present. Until an upload is
explicitly authorized, the training-image status remains
`LOCAL_VALIDATED_UPLOAD_PENDING` and the submitter blocks a paid run. The
staged immutable digest is
`sha256:97d43765c92ceb07414cbe03ed869c7365b12969e50d716f4b83757f439a237f`;
it is not claimed remotely available until publication verifies the registry.
Training admission, canary, promotion, and deployment certification remain
`NOT_COMPLETED`.

### R8-SKY-012 — pinned Miles moved pass-rate logging out of `log_utils`

Job 10 pulled and executed the new immutable image digest
`sha256:97d43765c92ceb07414cbe03ed869c7365b12969e50d716f4b83757f439a237f`.
It found the model-argument adapter, accepted the native PP1 guard, and began
the eight-rank converter import. This is execution evidence that R8-SKY-008
through R8-SKY-010 were resolved in the job-10 image.

The new terminal exception was:

```text
AttributeError: partially initialized module
'miles.backends.training_utils.log_utils' has no attribute 'log_passrate'
```

The `partially initialized` suffix is Python import-context wording, not the
underlying API contract. Pinned Miles commit
`8f0d065080076186ab152ee0129aceae34be756f` defines
`log_rollout_data` in `miles.backends.training_utils.log_utils` but defines no
`log_passrate` there. Pass-rate calculation moved to rollout-side
`miles.ray.rollout.metrics._compute_passrate_from_samples`, before train-data
DP sharding. The repository bridge still unconditionally read
`module.log_passrate` while installing its DP-local correct-sample logging
patch, so the import hook failed before checkpoint weights were converted.

The TorchAO syntax/import messages, Qwen3-ASR docstring diagnostics, and
ModelOpt/Transformers version warnings preceded the traceback but were not the
terminal cause.

The remediation supports both pinned APIs:

1. current Miles, without trainer-side `log_passrate`, temporarily exposes
   DP-local rewards only to `log_rollout_data` and restores the global reward
   vector afterward; and
2. legacy Miles, with trainer-side `log_passrate`, retains the temporary
   global-reward pass-rate view while correct-sample rows remain DP-local.

A new non-overwriting local image was built:

```text
glm47-full-v5-unadmitted-grpo:gcp-r8-hybrid45-exact40-r87-loghookfix-20260813
sha256:67fbcfd8327644506bfd5c75669e7c0d250fbf5ddf12e3d723fccc7506a0ea5b
```

Its embedded bridge hash is
`8bfe3afff55a2376b4c97dd456805f9e4b4a26e4d6ef4b65457805c95bb6c6c1`.
The image returned `EXACT_IMAGE_CURRENT_MILES_LOG_API_PASS` and retained
`EXACT_IMAGE_PP1_PREFLIGHT_PASS`. Its nine-file Miles source/advantage build
contract and the local asset-publication gate passed with zero optimizer
updates. The effective-source manifest SHA-256 is
`5022d73e6d2ff3e33217dfbfa07a7d657992cbfa26e2c2d85d70df78258416a2`
and source-set SHA-256 is
`444026ef3403f6a82448bdb083151e1d30ce305e0a3ee32175dd72f5077c2f69`.
The complete repository suite passed: 647 tests in 136.87 seconds.

The full converter import cannot be replayed on the local CPU-only Docker host
because Transformer Engine loads `libcuda.so.1` before reaching `log_utils`.
Therefore a GPU worker remains the final proof of the complete import chain.
The replacement image is locally validated but remains
`LOCAL_VALIDATED_UPLOAD_PENDING`; no optimizer update, admission, canary,
promotion, or deployment PASS is claimed.

### R8-SKY-013 — successful preparation reached a stale phase whitelist

Job 11 used the published immutable training image:

```text
sha256:67fbcfd8327644506bfd5c75669e7c0d250fbf5ddf12e3d723fccc7506a0ea5b
```

All eight ranks loaded the model, and the converter reported:

```text
successfully saved checkpoint from iteration 1 to
/root/models/GLM-4.7-Flash_torch_dist_tp4_pp1_ep8 [ t 1/4, p 1/1 ]
```

The subsequent preparation receipt recorded `status: passed`, the no-update
canary recorded `decision: PASS` with zero optimizer updates, and the trainer
contract recorded `status: PASS`. This is execution evidence that the image,
model-argument adapter, PP1 bridge, current Miles logging API, CUDA visibility,
and checkpoint conversion are no longer the active blockers.

Training then failed before Docker training launch because
`train()` routed every exact-40 runtime through `stage_r7_training_data()`.
The unadmitted R8 profile correctly supplied `phase=experimental`, while the
stager's stale whitelist allowed only `canary` and `full`. The terminal message
was:

```text
FULL_V5_CHARM_GCP_FAILED: unsupported R7 phase: experimental
```

The remediation allows `experimental` only as another full-schedule staging
mode. It selects `grpo_train` plus `full_schedule`, produces
`grpo/full-3ep-train.jsonl`, requires 40 unique tasks and 120 expanded rows,
and preserves `schedule_phase=experimental`. Existing `train()` authorization
still restricts this phase to the exact quarantined profile and authorization
phrase, so the change does not admit an R7 or production-full launch.

The Docker image is unchanged: the repaired driver is included in the frozen
SkyPilot transport and verified by the refreshed effective-source manifest.
Current bindings are:

```text
manifest_sha256=5c32a08b09dd9bf61c08b268eb3dac3a01e811b3aae389b467fcfbdffb6583b1
source_set_sha256=2942faebec19bb0b8d22adabef3ce66cd16676560632822a2bf893c9f7f84c82
file_count=78
```

Focused R7/R8 profile, schedule, staging, and frozen-transport tests pass:
24 tests in 5.68 seconds. The complete repository suite also passes: 648 tests
in 138.20 seconds. A final production-shaped frozen transport returned `PASS`
with 80 archive members, archive SHA-256
`e27f6ecbe2d49114d6362ab775071fefebbb8a591fa423db0286042243c51a00`,
profile SHA-256
`0de051ad5357c329e2de92b58a86d5fbc6dca5506048d89b057ecd35b7501b76`,
and the source bindings above. Job 11 remains a terminal failure, and no
optimizer update, admission, canary, promotion, or deployment PASS is claimed.

### R8-SKY-014 — image quarantine whitelist omitted the R8 run prefix

Job 12 reached `/opt/full-v5-charm/examples/grpo.sh` using image digest
`sha256:67fbcfd8327644506bfd5c75669e7c0d250fbf5ddf12e3d723fccc7506a0ea5b`.
The H100 runtime preflight passed, the SynthMem adapter was transformed into
the hybrid adapter, and the frozen R8 schedule paths and environment were
present. This proves R8-SKY-013 is resolved.

The terminal guard reported:

```text
quarantine-only runs require unadmitted status, zero CHARM eligibility,
no retroactive admission, and a bound unadmitted run ID
```

The command itself shows the first three conditions were correct:
`GLM47_ADMISSION_STATUS=NOT_COMPLETED`, `GLM47_CHARM_ELIGIBLE=0`, and
`GLM47_RETROACTIVE_ADMISSION_ALLOWED=0`. The attempt ID was also correctly
bound as
`unadmitted-r8-r87-20260813T182102Z-attempt-20260813T183109Z-8c8324c2`.
The remaining cause was the hard-coded whitelist in the image's
`/opt/full-v5-charm/scripts/train_grpo.sh`: it ended at the R6 prefixes and
omitted `unadmitted-r8-r87-*`.

The remediation adds only that exact R8 prefix. A local executable test uses
Job 12's full attempt-ID shape and verifies that the quarantine error is no
longer emitted. A non-overwriting replacement image was built:

```text
glm47-full-v5-unadmitted-grpo:gcp-r8-hybrid45-exact40-r87-quarantineprefixfix-20260813
sha256:8a688fe00bf4af378b3049e40a623b841bbe6a23fc93d71b80eb90d56bdbb479
```

The image's embedded nine-file pinned Miles advantage contract returned
`status: PASS` with zero optimizer updates. Its embedded `train_grpo.sh` hash
matches the repaired host source at
`2d14721891e48036454ba09a785915d0729663f589eaa5d2e6cc9d2d57fc7f4c`.
The repository-owned local publication gate returned
`LOCAL_PASS_REMOTE_PUBLICATION_NOT_VERIFIED`, binding the 244-file runtime,
zero-update Hybrid45 replay, and effective source:

```text
manifest_sha256=6e4a1231127f7202f26bbb0f39ba1e13e5b4f627655f5a9b76463f8fdb3ab462
source_set_sha256=be4a6f1c7b3a9eee4d34516012ef4f4437cb1edcc9b87bd11f2529f0a25a7db0
file_count=78
```

The replacement image has not yet been verified in Artifact Registry. Its
profile status is `LOCAL_VALIDATED_UPLOAD_PENDING`; the submitter must continue
to block another GPU run until separately authorized publication succeeds.
The complete repository suite passes: 648 tests in 135.38 seconds. Job 12
remains a failure, and no optimizer update, admission, canary, promotion, or
deployment PASS is claimed.

### R8-SKY-015 — current W&B removed the Miles run-ID alias

Job 13's durable attempt ID is:

```text
unadmitted-r8-r87-20260813T191050Z-attempt-20260813T192647Z-03896bea
```

The repaired quarantine prefix was accepted and Miles reached its training
import path. Pinned Miles then called the removed `wandb.util.generate_id`
alias. The active W&B package still provides the implementation at
`wandb.sdk.lib.runid.generate_id`, so the bridge installs that callable only
when the legacy public alias is absent and preserves it when already present.
Focused tests cover both cases. Job 13 failed before optimizer update 1.

### R8-SKY-016 — the CUDA 12.9 kernel package family was not aligned

Job 14's durable attempt ID is:

```text
unadmitted-r8-r87-20260813T200320Z-attempt-20260813T201451Z-32da88a9
```

The W&B compatibility path passed. The H100 runtime preflight then detected an
incompatible FlashInfer/SGLang kernel package set. The replacement image pins
`flashinfer-python` and `flashinfer-cubin` to 0.6.14,
`flashinfer-jit-cache` to 0.6.14+cu129, and `sglang-kernel` to 0.4.5+cu129.
The runtime checker rejects a stale or mixed package family. Job 14 failed
before an optimizer update.

### R8-SKY-017 — executed rewards lacked verifier-workspace identity

Job 15's durable attempt ID is:

```text
unadmitted-r8-r87-20260813T210637Z-attempt-20260813T211802Z-4a1329fe
```

The job completed initial evaluation and all 160 responses in its first
training rollout. The fail-closed context-isolation contract then rejected
executed reward evidence because `verification_workspace_id` was missing. The
remediation upgrades the receipt to the schema-v2 isolated-workspace contract:
every executed candidate is bound to its actual verifier workspace, while a
static malformed response that is never executed uses a distinct isolated
receipt workspace. This preserves the verifier and its context-isolation gate;
it does not bypass reward execution. Job 15 failed before optimizer update 1.

### R8-SKY-018 — bridge assumed Ray was re-exported by `miles.utils.data`

Job 16's durable attempt ID is:

```text
unadmitted-r8-r87-20260813T221420Z-attempt-20260813T222805Z-e81e5675
```

The context-isolation repair passed. Initial evaluation completed 11/11 rows
with mean reward `-0.45454545`, and the first training rollout completed all
160 responses. Immediately before DP sharding, the bridge called:

```text
module.ray.get(...)
```

where `module` is pinned `miles.utils.data`. That module imports selected Ray
helpers but does not export a `ray` attribute, so all training ranks failed
with:

```text
AttributeError: module 'miles.utils.data' has no attribute 'ray'
```

The bridge now uses an existing module attribute when supplied by a compatible
Miles version and otherwise lazily imports the installed top-level `ray`
module inside `process_rollout_data`. The import is deliberately lazy so
conversion and CPU-only contract imports do not start Ray services. A
regression test exercises the pinned-Miles shape without `module.ray`.

The replacement immutable image is published at:

```text
sha256:0cf1a3b3e8233057b4008478a9fb1d2c81068a5465b1ed259188071b71d112d7
```

Its embedded bridge SHA-256 matches the host source at
`2172c85c128e0c4dbd6db8ff37c0b55d811a81b9abfd98d78950a371774476f6`.
The nine-file pinned Miles contract passed with zero optimizer updates; the
complete repository suite passed 652 tests in 133.95 seconds. The refreshed
effective-source bindings are:

```text
manifest_sha256=a8d8b0b2198813665b16a2f84077ba666318f6f640f9fb904bc71110399ebc28
source_set_sha256=1749c38b0456a122557435ce0cdc49fd7d747227fc4854cf685f2b45a52e895b
file_count=78
```

Job 16 remains a terminal failure with no optimizer update. Managed job 17 is
the authorized execution test of this remediation.

### R8-SKY-019 — copied rollout fetch path assumed `Timer` was re-exported

Job 17's durable attempt ID is:

```text
unadmitted-r8-r87-20260813T231944Z-attempt-20260813T232904Z-dcf5116e
```

The Ray fallback from R8-SKY-018 passed. Initial evaluation completed, the
first training rollout completed all 160 responses, per-sample verification
completed, and the pre-optimizer signal gate passed. Training then entered the
DP-shard bridge on all eight actors and failed before optimizer update 1 with:

```text
AttributeError: module 'miles.utils.data' has no attribute 'Timer'
```

The direct symbol failure was accurate, but adding only a `Timer` fallback
would have retained a copied legacy fetch implementation. The pinned Miles
revision owns Ray/object-store fetching in `miles.utils.data.process_rollout_data`,
returns both rollout data and the object-store receipt, and owns length/timer
handling in `miles.ray.rollout.train_data_conversion.process_rollout_data_shard`.
The remediation therefore no longer replaces the fetch function. It wraps only
the native shard function, captures the saved partition before delegation, and
adds the DP-local raw-reward view after Miles performs its native sharding.

The exact Job 17 image passed a mounted-source contract test proving that the
native fetch function remains owned by `miles.utils.data` and that the wrapper
produces aligned lengths and rewards. Focused R8/GCP/Miles validation passed 92
tests; the complete repository suite passed 652 tests in 138.37 seconds. The
new image's embedded bridge hash matches the host at:

```text
106beaecd41c77b5521304e64f755148b590dc10f0c046a2ebaba7775c7584dd
```

The replacement image was published and remotely byte-verified at:

```text
sha256:6f69ff6617a448c03ec990d33adff88f504b7394bc0a7ba2c73f179efd531cc6
```

Its repository-source bindings are:

```text
manifest_sha256=4384e00b176bd7f40e48ea5ec20270dad0772cc560005545bd161b7fc32de5bf
source_set_sha256=b55ec277d652e70e5edbcc0f07337f92976624370a792d74177ea128a8cb81be
file_count=78
```

Job 17 remains a terminal failure with no optimizer update. Managed Job 18,
base run `unadmitted-r8-r87-20260814T003005Z`, is the authorized Spot execution
test of this remediation. Later optimizer, weight-refresh, checkpoint, and
final-evaluation boundaries remain `not_completed` until observed live.

### R8-SKY-020 — missing trainer asleep state skipped wake-up

Managed Job 18 durable attempt ID is:

```text
unadmitted-r8-r87-20260814T003005Z-attempt-20260814T004034Z-dc0f00e5
```

The native DP-sharding remediation passed. Initial evaluation completed, the
first rollout completed all 160 responses, the signal gate passed, and Miles
precomputed a 25-microbatch DP schedule. All eight trainer actors then entered
`data_preprocess` and exited with SIGSEGV before optimizer update 1. GPU
telemetry peaked at 69,307 MiB, below the 81,559 MiB device capacity, and
SkyPilot recorded zero recoveries.

The exact lifecycle defect was in the bridge `sleep()` override. It paused
`torch_memory_saver` and destroyed trainer process groups but did not set
`self._asleep = True`. Pinned Miles uses that state to make `train()` call
`wake_up()`. With the flag left false, the first CUDA operation in
`data_preprocess` ran while trainer memory remained paused and process groups
remained destroyed. The bridge now makes `sleep()` idempotent and sets the
state immediately after a successful pause; the regression test asserts that
transition.

A corrected immutable fallback image was published and byte-verified at:

```text
sha256:5df1c41efb6062a292ac68a49d68ad955d9f8209c182d3fc2f7e8c634ca076a2
```

Its embedded bridge SHA-256 matches the active source at
`6a302dd06a9bf7b2e57804930b60aaeaa96883afd95c68e9ca68e14ee094df6f`.
The R8 profile also uses Miles supported resident-trainer mode
(`--no-offload-train`) and lowers only SGLang static memory reservation from
0.75 to 0.60. This bypasses the offload/resume transition and preserves about
12 GiB of additional headroom; no reward, signal, optimizer, checkpoint, or
evaluation threshold is disabled or lowered.

Managed Job 19 subsequently completed optimizer update 1 and durably published
checkpoint `iter_0000000`, then failed during the following SGLang memory-resume
transition. R8-SKY-021 records that terminal result. Managed Job 22 later
completed all six optimizer/checkpoint cycles; R8-SKY-024 records the passed
execution without changing its quarantine or admission status.

### R8-SKY-021 — post-update SGLang resume failure after checkpoint 1

Job 19's durable attempt ID is:

```text
unadmitted-r8-r87-20260814T014330Z-attempt-20260814T015326Z-a8e0fd49
```

The first optimizer update and complete checkpoint `iter_0000000` were durable.
The next transition failed inside `SGLangEngine.resume_memory_occupation` when
the rollout manager's `onload_kv` request lost the scheduler connection.
The scheduler child exited `-3`; Gloo, TCPStore, and NCCL messages that followed
were peer-teardown consequences. SkyPilot recorded zero recoveries, meaning no
Spot preemption/recovery event occurred during the attempt.

### R8-SKY-024 — Job 22 completed the six-update GRPO contract

Job 22's durable attempt ID is:

```text
unadmitted-r8-r87-run21-20260814T030808Z-attempt-20260814T031719Z-d951d40e
```

It published six complete checkpoints, `iter_0000000` through
`iter_0000005`, each with `COMPLETE.json` and `adapter_model.bin`. The final
adapter is rank 16, alpha 32, SHA-256
`7fb350de045fb1d476fefcdaeb59a5c69ea7f5e2fe744516b63e146f26d8bfc2`.
The run warm-started from SynthMem v1 epoch 50 SFT adapter SHA-256
`4acb7f23c295f45380155c5d9ee6bc59422262f0cb51f0c02f7e550d405b575a`.
The execution receipt ended `passed`, with 51 consecutive successful result
syncs and no periodic failure. This is an execution PASS only: admission is
`NOT_COMPLETED`, CHARM eligibility is false, checkpoint disposition is
`QUARANTINE_ONLY`, and retroactive admission is false.

### R8-SKY-028 — Job 30 completed the Job-22 fixed-26 evaluation

Job 30 evaluated the final Job-22 adapter with two attempts per task. It
completed with pass@1 `0/26`, pass@2 `4/26`, all `26/26` responses well formed,
no malformed responses or timeouts, and 9 error/context-exhaustion cases. The
attempt-two-only passes were `allergies`, `complex-numbers`, `knapsack`, and
`space-age`.

The result is complete and durable, but not a matched comparison to the
historical SynthMem v1 epoch-50 SFT figures. Those four historical trials used
the `fixed26-contract-v2` prompt overlay and averaged pass@1 `9.5/26` and
pass@2 `12/26`; Job 30 used the raw fixed-26 task prompts. A causal SFT-versus-
GRPO claim requires both adapters to be evaluated with identical task bytes,
overlay, harness, decoding controls, and repeated trials.

## Non-blocking warnings and labels

| Message | Classification | Evidence |
| --- | --- | --- |
| `WARNING: The NVIDIA Driver was not detected` | Expected in the CPU-only source/advantage-contract container, which is launched without `--gpus`. | The contract ended with `status: PASS`; the later reward and conversion containers used `--gpus all`. |
| Triton CPU fallback and `libcuda.so.1` shim warnings | Consequences of the same CPU-only contract import. | They did not block the contract PASS. |
| Docker credentials stored unencrypted | Security-hardening warning, not the terminal error. | Setup and later image pulls completed. Do not copy the credential file into receipts. |
| APT legacy `trusted.gpg` warnings | Package-key deprecation warning. | Package installation completed successfully. |
| GPU Direct enabled `gvnic` | SkyPilot/GCP informational configuration change. | Provisioning continued. |
| `unadmitted` in job and cluster names | Intentional profile identity, not a queue state. | The profile is `UNADMITTED_EXPERIMENT_ONLY`; skipping admission/canary cannot be relabelled as admitted. |

## Operator commands

Queue and terminal status:

```bash
sky jobs queue
```

Complete worker and controller logs for an attempt:

```bash
sky jobs logs <JOB_ID> --tail 0
sky jobs logs --controller <JOB_ID> --tail 0
```

Durable attempt evidence:

```bash
gcloud storage ls --recursive \
  gs://lifeandhalf-24122025-w8-biayn/runs/glm47/experiments/unadmitted-r8-hybrid45-exact40-r87/attempt-index/<BASE_RUN_ID>/
```

For each future attempt, append the run ID, managed-job ID, worker attempt ID,
stage, terminal message, GPU-allocation impact, verified root cause, remediation
commit/source digest, validation evidence, and truthful outcome to this file.
