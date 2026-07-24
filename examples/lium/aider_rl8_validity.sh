#!/usr/bin/env bash
set -euo pipefail

repo_root="${GLM47_REPRO_REPO_ROOT:-/workspace/glm47}"
assets_root="${GLM47_REPRO_ASSETS_ROOT:-/workspace/assets}"
runs_root="${GLM47_REPRO_RUNS_ROOT:-/workspace/runs}"
run_id="${GLM47_REPRO_RUN_ID:-glm47-aider-rl8-validity-$(date -u +%Y%m%dT%H%M%SZ)}"
run_root="${runs_root}/${run_id}"
source_adapter="${GLM47_REPRO_SOURCE_ADAPTER:-${assets_root}/sft-v3-r16-clean}"
task_root="${GLM47_AIDER_TASKS_DIR:-${assets_root}/aider-rl-tasks/tasks/aider_cpp_rl_tasks}"
task_split="${repo_root}/examples/lium/aider_rl8_task_split.json"
data_root="${run_root}/data"
reconstructed_adapter="${run_root}/inputs/sft-v3-r16-ep8"
preservation_root="${runs_root}/${run_id}-preservation"

expected_adapter_sha256="f1ea45bc327dc6e28d0287aea75c6b691e99d2ec2f7fdb7f07bbbf5ccd6cf36a"
expected_config_sha256="0bd6d85f88fc42fefa52627b3c261f1ad58bb2c9519332ae8034dd5dffe2498e"
expected_task_split_sha256="6f28255e9a2db2890f59cd06bc1cea5f58fb0f83126b0a72a7465e479015479a"
expected_rl_manifest_sha256="b37653def2cdad8c2e927af30c4de6e979c3af3ef0ea66a66671d5e7ff18d1ee"

verify_sha256() {
  local expected="$1"
  local path="$2"
  local actual
  if [[ ! -f "${path}" || -L "${path}" ]]; then
    echo "missing regular validity-run input: ${path}" >&2
    exit 2
  fi
  actual="$(sha256sum "${path}" | awk '{print $1}')"
  if [[ "${actual}" != "${expected}" ]]; then
    echo "SHA-256 mismatch for ${path}: ${actual} != ${expected}" >&2
    exit 2
  fi
}

if [[ -e "${run_root}" || -e "${preservation_root}" ]]; then
  echo "refusing to reuse validity-run output: ${run_root}" >&2
  exit 2
fi
verify_sha256 "${expected_adapter_sha256}" "${source_adapter}/adapter_model.bin"
verify_sha256 "${expected_config_sha256}" "${source_adapter}/adapter_config.json"
verify_sha256 "${expected_task_split_sha256}" "${task_split}"
verify_sha256 "${expected_rl_manifest_sha256}" "${task_root}/manifest.json"

mkdir -p "${run_root}/inputs" "${run_root}/runtime_state/tmp"
cp "${task_split}" "${run_root}/task_split.json"
verify_sha256 "${expected_task_split_sha256}" "${run_root}/task_split.json"
PYTHONPATH="${repo_root}/src:${PYTHONPATH:-}" python3 \
  "${repo_root}/scripts/reconstruct_megatron_lora.py" \
  "${source_adapter}" "${source_adapter}" "${reconstructed_adapter}" \
  --source-native-template \
  --expert-parallel-size 8 \
  --expected-source-sha256 "${expected_adapter_sha256}"
reconstruction_manifest="${reconstructed_adapter}/native_reconstruction_manifest.json"
reconstruction_sha256="$(sha256sum "${reconstruction_manifest}" | awk '{print $1}')"

PYTHONPATH="${repo_root}/src:${PYTHONPATH:-}" python3 -m \
  glm47_posttraining.integrations.miles_aider_polyglot build-data \
  --tasks-dir "${task_root}" \
  --out "${data_root}" \
  --task-split-file "${task_split}" \
  --profile glm47-aider-rl8-validity \
  --run-id "${run_id}"

RUN_ROOT="${run_root}" DATA_ROOT="${data_root}" TASK_SPLIT="${task_split}" \
RECONSTRUCTION_MANIFEST="${reconstruction_manifest}" SOURCE_COMMIT="$(git -C "${repo_root}" rev-parse HEAD)" \
python3 - <<'PY'
import hashlib
import json
import os
from pathlib import Path

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

run_root = Path(os.environ["RUN_ROOT"])
data_root = Path(os.environ["DATA_ROOT"])
split_path = Path(os.environ["TASK_SPLIT"])
manifest = json.loads((data_root / "manifest.json").read_text(encoding="utf-8"))
split = json.loads(split_path.read_text(encoding="utf-8"))
if manifest.get("counts") != {"available_rl_tasks": 253, "train": 6, "monitor": 2}:
    raise SystemExit(f"unexpected RL8 dataset counts: {manifest.get('counts')}")
selection = manifest.get("selection", {})
if selection.get("train_task_ids") != split.get("train_task_ids"):
    raise SystemExit("RL8 train task selection mismatch")
if selection.get("monitor_task_ids") != split.get("monitor_task_ids"):
    raise SystemExit("RL8 monitor task selection mismatch")
reconstruction = json.loads(
    Path(os.environ["RECONSTRUCTION_MANIFEST"]).read_text(encoding="utf-8")
)
roundtrip = reconstruction.get("mapping", {}).get("source_hf_roundtrip", {})
if not (
    reconstruction.get("status") == "passed"
    and roundtrip.get("status") == "passed"
    and roundtrip.get("coverage_fraction") == 1.0
    and roundtrip.get("all_source_hf_tensor_bytes_exact") is True
    and len(reconstruction.get("outputs", {}).get("native_shards", {})) == 8
):
    raise SystemExit("rank-16 TP4/EP8 reconstruction proof is incomplete")
receipt = {
    "schema_version": 1,
    "kind": "glm47-aider-rl8-input-receipt",
    "status": "passed",
    "run_id": run_root.name,
    "source_commit": os.environ["SOURCE_COMMIT"],
    "source_adapter_artifact": {
        "repo": "TokenBender/glm47-aider-cpp-grpo-20260721",
        "revision": "63eda446657d0ed762e17559642cb6f809121fa0",
        "path": "parents/complement-530/adapter",
        "adapter_model_sha256": "f1ea45bc327dc6e28d0287aea75c6b691e99d2ec2f7fdb7f07bbbf5ccd6cf36a",
    },
    "data_manifest_sha256": sha256(data_root / "manifest.json"),
    "train_jsonl_sha256": sha256(data_root / "grpo" / "train.jsonl"),
    "monitor_jsonl_sha256": sha256(data_root / "eval" / "train_monitor.jsonl"),
    "task_split_sha256": sha256(split_path),
    "native_reconstruction_manifest_sha256": sha256(
        Path(os.environ["RECONSTRUCTION_MANIFEST"])
    ),
    "selection": selection,
}
(run_root / "input_receipt.json").write_text(
    json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
PY

RUN_ROOT="${run_root}" RUN_ID="${run_id}" SOURCE_COMMIT="$(git -C "${repo_root}" rev-parse HEAD)" \
python3 - <<'PY'
import json
import os
import subprocess
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

def output(command: list[str], fallback: str = "unavailable") -> str:
    try:
        return subprocess.run(
            command, check=True, capture_output=True, text=True, timeout=30
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return fallback

def package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "unavailable"

container_id = output(["hostname"])
runtime_image_id = os.environ.get("GLM47_RUNTIME_IMAGE_ID") or output(
    ["docker", "inspect", "-f", "{{.Image}}", container_id]
)
gpu_rows = [
    line for line in output(
        ["nvidia-smi", "--query-gpu=index,name,uuid", "--format=csv,noheader"]
    ).splitlines()
    if line.strip()
]
receipt = {
    "schema_version": 1,
    "kind": "glm47-aider-rl8-runtime-receipt",
    "status": "passed",
    "run_id": os.environ["RUN_ID"],
    "source_commit": os.environ["SOURCE_COMMIT"],
    "container_id": container_id,
    "runtime_image_id": runtime_image_id,
    "miles_commit": output(["git", "-C", "/root/miles", "rev-parse", "HEAD"]),
    "sglang_version": package_version("sglang"),
    "torch_version": package_version("torch"),
    "gpu_count": len(gpu_rows),
    "gpus": gpu_rows,
}
if not runtime_image_id.startswith("sha256:") or len(gpu_rows) != 8:
    raise SystemExit(f"runtime identity preflight failed: {receipt}")
(Path(os.environ["RUN_ROOT"]) / "runtime_receipt.json").write_text(
    json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
PY

runtime_state="${run_root}/runtime_state"
ray_tmp="/workspace/tmp/ray-$(printf '%s' "${run_id}" | sha256sum | cut -c1-12)"
mkdir -p \
  "${run_root}/wandb" \
  "${run_root}/sync_metrics" \
  "${run_root}/signal_gates" \
  "${runtime_state}/wandb-cache" \
  "${runtime_state}/wandb-data" \
  "${runtime_state}/wandb-artifacts" \
  "${runtime_state}/xdg-cache" \
  "${runtime_state}/hf-home" \
  "${runtime_state}/tmp" \
  "${ray_tmp}"

export GLM47_CPP_REWARD_WORKERS=32
export GLM47_CPP_SANDBOX_BACKEND=docker
export GLM47_CPP_SANDBOX_CPU=1
export GLM47_CPP_SANDBOX_IMAGE=glm47-aider-polyglot-cpp:latest
export GLM47_EXPERIMENT_ID="${run_id}"
export GLM47_MODEL_REVISION=7dd20894a642a0aa287e9827cb1a1f7f91386b67
export GLM47_REGISTER_BRIDGE=1
export GLM47_SOURCE_COMMIT="$(git -C "${repo_root}" rev-parse HEAD)"
export GLM47_SYNC_METRICS_DIR="${run_root}/sync_metrics"
export GLM47_TIMING_STATUS=full

export GLM47_AIDER_EXPECTED_TRAIN_GROUPS=6
export GLM47_AIDER_EXPECTED_SAMPLES_PER_GROUP=8
export GLM47_AIDER_REQUIRE_SIGNAL=1
export GLM47_AIDER_MIN_POSITIVE_GROUPS=5
export GLM47_AIDER_MIN_SEMANTIC_VARIANCE_GROUPS=2
export GLM47_AIDER_MIN_REWARD_VARIANCE_GROUPS=4
export GLM47_AIDER_MIN_EXACT_FORMAT_RATE=0.65
# This is a signal-health gate, not a base-quality gate. Semantic-positive and
# variance checks above already ensure the reward path reaches compiled tests.
export GLM47_AIDER_MIN_COMPILE_RATE=0.70
export GLM47_AIDER_SIGNAL_GATE_DIR="${run_root}/signal_gates"

export MILES_APPLY_CHAT_TEMPLATE_KWARGS='{"enable_thinking": false}'
export MILES_ATTENTION_BACKEND=flash
export MILES_BALANCE_DATA=1
export MILES_CONTEXT_PARALLEL_SIZE=1
export MILES_CPP_DATA_DIR="${data_root}"
export MILES_CPP_TASKS_DIR="${task_root}"
export MILES_CPP_TASK_SPLIT_FILE="${task_split}"
export MILES_CUSTOM_RM_PATH=glm47_posttraining.integrations.miles_aider_polyglot.reward_func
export MILES_DATA_BUILD_MODULE=glm47_posttraining.integrations.miles_aider_polyglot
export MILES_EVAL_INTERVAL=2
export MILES_EVAL_MAX_RESPONSE_LEN=4096
export MILES_EVAL_NAME=aider_rl8_gradient_holdout
export MILES_EVAL_N_SAMPLES_PER_PROMPT=8
export MILES_EVAL_PROMPT_DATA="${data_root}/eval/train_monitor.jsonl"
export MILES_EXPECTED_DATASET_KIND=aider-cpp-rl-grpo
export MILES_EXPECTED_NATIVE_SHARDS=8
export MILES_EXPECTED_SOURCE_ADAPTER_SHA256="${expected_adapter_sha256}"
export MILES_EXPECTED_SOURCE_TENSORS=9741
export MILES_EXPECTED_STRIPPED_TENSORS=207
export MILES_EXPECTED_TRAIN_COUNT=6
export MILES_EXPERIMENTAL_ROLLOUT_REFACTOR=0
export MILES_EXPERTS_SHARED_OUTER_LORAS=1
export MILES_EXPERT_MODEL_PARALLEL_SIZE=8
export MILES_EXPERT_TENSOR_PARALLEL_SIZE=1
export MILES_EXTRA_ARGS="${MILES_EXTRA_ARGS:---rollout-seed 20260723}"
export MILES_GLOBAL_BATCH_SIZE=48
export MILES_GPUS_PER_NODE=8
export MILES_GRPO_CONTINUATION_MODE=none
export MILES_GRPO_ROLLOUT_SHUFFLE=1
export MILES_HF_CHECKPOINT="${GLM47_REPRO_MODEL_PATH:-/workspace/models/GLM-4.7-Flash}"
export MILES_KL_LOSS_COEF=0.02
export MILES_LORA_ADAPTER_PATH="${reconstructed_adapter}"
export MILES_LORA_ALPHA=32
export MILES_LORA_BASE_CPU_BACKUP=1
export MILES_LORA_RANK=16
export MILES_LORA_TARGET_MODULES=q_a_proj,kv_a_proj_with_mqa,o_proj,gate_proj,up_proj,down_proj
export MILES_LR=5e-7
export MILES_MAX_TOKENS_PER_GPU=12288
export MILES_MICRO_BATCH_SIZE=1
export MILES_MODEL_ARGS_FILE=glm4.7-flash.sh
export MILES_MOE_ENABLE_DEEPEP=1
export MILES_MOE_TOKEN_DISPATCHER_TYPE=flex
export MILES_NATIVE_RECONSTRUCTION_MANIFEST_PATH="${reconstruction_manifest}"
export MILES_EXPECTED_NATIVE_RECONSTRUCTION_MANIFEST_SHA256="${reconstruction_sha256}"
export MILES_NO_GRADIENT_ACCUMULATION_FUSION=1
export MILES_NO_REF=0
export MILES_NUM_ROLLOUT=2
export MILES_N_SAMPLES_PER_PROMPT=8
export MILES_PIPELINE_MODEL_PARALLEL_SIZE=1
export MILES_RECOMPUTE_GRANULARITY=full
export MILES_REF_LOAD_DIR="${GLM47_REPRO_REF_LOAD_DIR:-/workspace/models/GLM-4.7-Flash_torch_dist_tp4_pp1_ep8}"
export MILES_REWARD_PREFLIGHT_MODULE=glm47_posttraining.integrations.miles_aider_polyglot
export MILES_ROLLOUT_BATCH_SIZE=6
export MILES_ROLLOUT_MAX_RESPONSE_LEN=4096
export MILES_ROLLOUT_SAMPLE_FILTER_PATH=glm47_posttraining.integrations.miles_aider_polyglot.validate_aider_rollout_batch
export MILES_ROLLOUT_SKIP_SPECIAL_TOKENS=1
export MILES_ROLLOUT_STOP_TOKEN_IDS='154820 154827 154829'
export MILES_ROLLOUT_TEMPERATURE=0.7
export MILES_RUN_ID="${run_id}"
export MILES_RUN_ROOT="${run_root}"
export MILES_SAVE_INTERVAL=1
export MILES_SEQ_LENGTH=6144
export MILES_SGLANG_ATTENTION_BACKEND=flashinfer
export MILES_SGLANG_CUDA_GRAPH_MAX_BS=64
export MILES_SGLANG_DISABLE_CUSTOM_ALL_REDUCE=0
export MILES_SGLANG_DP_SIZE=8
export MILES_SGLANG_ENABLE_DP_ATTENTION=1
export MILES_SGLANG_ENABLE_DP_LM_HEAD=1
export MILES_SGLANG_LORA_TARGET_MODULES=q_a_proj,kv_a_proj_with_mqa,o_proj,gate_proj,up_proj,down_proj
export MILES_SGLANG_LORA_USE_VIRTUAL_EXPERTS=1
export MILES_SGLANG_MAX_RUNNING_REQUESTS=48
export MILES_SGLANG_MEM_FRACTION_STATIC=0.75
export MILES_SGLANG_MOE_DENSE_TP_SIZE=1
export MILES_SGLANG_SERVER_CONCURRENCY=128
export MILES_SGLANG_SPECULATIVE=0
export MILES_TENSOR_MODEL_PARALLEL_SIZE=4
export MILES_TRAIN_MODULE=glm47_posttraining.integrations.miles_train_with_glm47_bridge
export MILES_USE_DYNAMIC_BATCH_SIZE=1
export MILES_USE_KL_LOSS=1
export MILES_WANDB_GROUP="${run_id}"
export MILES_WANDB_JOB_TYPE=grpo
export MILES_WANDB_PROJECT="${MILES_WANDB_PROJECT:-glm47-aider-polyglot-cpp-grpo-validity}"
export MILES_WANDB_RUN_ID="${run_id}"

export NCCL_DEBUG=WARN
export NVSHMEM_DISABLE_NCCL=1
export WANDB_MODE=offline
export WANDB_TAGS="rl8-validity,gradient-heldout,2epoch,8xh100,lium,fail-closed"
export WANDB_DIR="${run_root}/wandb"
export WANDB_CACHE_DIR="${runtime_state}/wandb-cache"
export WANDB_DATA_DIR="${runtime_state}/wandb-data"
export WANDB_ARTIFACT_DIR="${runtime_state}/wandb-artifacts"
export XDG_CACHE_HOME="${runtime_state}/xdg-cache"
export HF_HOME="${runtime_state}/hf-home"
export TMPDIR="${ray_tmp}"

cd "${repo_root}"
bash examples/grpo.sh

python3 scripts/verify_grpo_preservation.py \
  "${run_root}" "${preservation_root}" \
  --expected-rollouts 2 \
  --expected-train-samples-per-dump 48 \
  --expected-eval-samples-per-dump 16 \
  --expected-train-samples 96 \
  --expected-eval-samples 32 \
  --expected-native-shards 8 \
  --expected-training-states 8 \
  --tensor-parallel-size 4 \
  --expert-parallel-size 8 \
  --require-signal-gates \
  --require-gpu-activity

python3 scripts/publish_aider_rl8_artifacts.py \
  "${run_root}" "${preservation_root}" \
  --token-file /workspace/hf_token \
  --dataset-repo TokenBender/glm47-aider-rl8-validity-rollouts-20260723 \
  --model-repo TokenBender/glm47-aider-rl8-validity-checkpoints-20260723 \
  --verify-root /workspace/rl8-remote-verification \
  --output "${run_root}/remote_publication_receipt.json"

echo "AIDER_RL8_VALIDITY_PASSED run_root=${run_root} preservation=${preservation_root}"
