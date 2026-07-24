#!/usr/bin/env bash
set -euo pipefail

repo_root="${GLM47_REPRO_REPO_ROOT:-/workspace/glm47}"
assets_root="${GLM47_REPRO_ASSETS_ROOT:-/workspace/assets}"
runs_root="${GLM47_REPRO_RUNS_ROOT:-/workspace/runs}"
run_id="${GLM47_REPRO_RUN_ID:-glm47-aider-grpo169-merge1211-530-r32-2ep-fixed-repro-$(date -u +%Y%m%dT%H%M%SZ)}"
run_root="${runs_root}/${run_id}"

expected_manifest_sha256="65b50a6532abc87f78cf43e673b07625c4056a62ecfdacc9a49f5849e6318105"
expected_train_sha256="bb7472bb551d95e180d391351567372c62fd72bee33a0ca4cf8186d294f2c882"
expected_adapter_sha256="${GLM47_REPRO_PARENT_ADAPTER_SHA256:-dbea7d3e2d6603f278b94c6be134bca83bb5f0ebdc4840eb53898ec5b3affb91}"
iter10_adapter_sha256="046a1018b605aa29f8b8c4f2677f47ce55489105f6766155f4c009798f48abe2"
iter10_native_manifest_sha256="5839772926ea3a58f9182783242731cc168bc6d5da1867375efa4c19e81b9005"
expected_rl_manifest_sha256="b37653def2cdad8c2e927af30c4de6e979c3af3ef0ea66a66671d5e7ff18d1ee"
data_root="${GLM47_REPRO_DATA_ROOT:-${assets_root}/aider-data/datasets/rl-v2-169/data}"
adapter_root="${GLM47_REPRO_PARENT_ADAPTER_ROOT:-${assets_root}/merged-1211-530-r32}"
aider_tasks_root="${GLM47_AIDER_TASKS_DIR:-${assets_root}/aider-rl-tasks/tasks/aider_cpp_rl_tasks}"

verify_sha256() {
  local expected="$1"
  local path="$2"
  local actual
  if [[ ! -f "${path}" ]]; then
    echo "missing required reproduction input: ${path}" >&2
    exit 1
  fi
  if command -v sha256sum >/dev/null 2>&1; then
    actual="$(sha256sum "${path}" | awk '{print $1}')"
  else
    actual="$(shasum -a 256 "${path}" | awk '{print $1}')"
  fi
  if [[ "${actual}" != "${expected}" ]]; then
    echo "SHA-256 mismatch for ${path}: ${actual} != ${expected}" >&2
    exit 1
  fi
}

verify_sha256 "${expected_manifest_sha256}" "${data_root}/manifest.json"
verify_sha256 "${expected_train_sha256}" "${data_root}/grpo/train.jsonl"
verify_sha256 "${expected_adapter_sha256}" "${adapter_root}/adapter_model.bin"
verify_sha256 "${expected_rl_manifest_sha256}" "${aider_tasks_root}/manifest.json"

native_manifest_path="${GLM47_REPRO_PARENT_NATIVE_MANIFEST_PATH:-}"
native_manifest_sha256="${GLM47_REPRO_PARENT_NATIVE_MANIFEST_SHA256:-}"
if [[ "${expected_adapter_sha256}" = "${iter10_adapter_sha256}" && \
      "${MILES_GRPO_CONTINUATION_MODE:-none}" = "none" ]]; then
  echo "the pinned RL iter10 adapter requires explicit continuation provenance" >&2
  exit 2
fi
if [[ "${MILES_GRPO_CONTINUATION_MODE:-none}" != "none" ]]; then
  if [[ "${expected_adapter_sha256}" = "${iter10_adapter_sha256}" ]]; then
    native_manifest_path="${native_manifest_path:-${adapter_root}/native_reconstruction_manifest.json}"
    native_manifest_sha256="${native_manifest_sha256:-${iter10_native_manifest_sha256}}"
  elif [[ -z "${native_manifest_path}" || -z "${native_manifest_sha256}" ]]; then
    echo "continuation adapters require an explicitly pinned native reconstruction manifest" >&2
    exit 2
  fi
fi
if [[ -n "${native_manifest_path}" || -n "${native_manifest_sha256}" ]]; then
  if [[ -z "${native_manifest_path}" || -z "${native_manifest_sha256}" ]]; then
    echo "native reconstruction manifest path and SHA-256 are required together" >&2
    exit 2
  fi
  verify_sha256 "${native_manifest_sha256}" "${native_manifest_path}"
  export MILES_NATIVE_RECONSTRUCTION_MANIFEST_PATH="${native_manifest_path}"
  export MILES_EXPECTED_NATIVE_RECONSTRUCTION_MANIFEST_SHA256="${native_manifest_sha256}"
fi

source_commit="$(git -C "${repo_root}" rev-parse HEAD)"

export GLM47_CPP_REWARD_WORKERS=32
export GLM47_CPP_SANDBOX_BACKEND=docker
export GLM47_CPP_SANDBOX_CPU=1
export GLM47_CPP_SANDBOX_IMAGE=glm47-aider-polyglot-cpp:latest
export GLM47_EXPERIMENT_ID="${run_id}"
export GLM47_MODEL_REVISION=7dd20894a642a0aa287e9827cb1a1f7f91386b67
export GLM47_REGISTER_BRIDGE=1
export GLM47_SOURCE_COMMIT="${source_commit}"
export GLM47_SYNC_METRICS_DIR="${run_root}/sync_metrics"
export GLM47_TIMING_STATUS=full
export GLM47_TRAINING_IMAGE='radixark/miles:latest-cu12@sha256:efc8027fc47aaa9687dc4f1046093ed4e2f9789e52a932fcefb7031402aeff37'

# examples/grpo.sh appends its parameter-expansion closing brace to this value.
export MILES_APPLY_CHAT_TEMPLATE_KWARGS='{"enable_thinking": false'
export MILES_ATTENTION_BACKEND=flash
export MILES_BALANCE_DATA=1
export MILES_CONTEXT_PARALLEL_SIZE=1
export MILES_CPP_DATA_DIR="${data_root}"
export MILES_CPP_TASKS_DIR="${aider_tasks_root}"
export MILES_CUSTOM_RM_PATH=glm47_posttraining.integrations.miles_aider_polyglot.reward_func
export MILES_DATA_BUILD_MODULE=glm47_posttraining.integrations.miles_aider_polyglot
export MILES_EVAL_INTERVAL=1
export MILES_EVAL_MAX_RESPONSE_LEN=4096
export MILES_EVAL_NAME=aider_cpp_rl_train_monitor
export MILES_EVAL_N_SAMPLES_PER_PROMPT=1
export MILES_EVAL_PROMPT_DATA="${data_root}/eval/train_monitor.jsonl"
export MILES_EXPECTED_DATASET_KIND=aider-cpp-rl-grpo
export MILES_EXPECTED_NATIVE_SHARDS="${MILES_EXPECTED_NATIVE_SHARDS:-8}"
export MILES_EXPECTED_SOURCE_ADAPTER_SHA256="${expected_adapter_sha256}"
export MILES_EXPECTED_SOURCE_TENSORS="${MILES_EXPECTED_SOURCE_TENSORS:-9741}"
export MILES_EXPECTED_STRIPPED_TENSORS="${MILES_EXPECTED_STRIPPED_TENSORS:-207}"
export MILES_EXPECTED_TRAIN_COUNT=169
export MILES_EXPERTS_SHARED_OUTER_LORAS=1
export MILES_EXPERT_MODEL_PARALLEL_SIZE=8
export MILES_EXPERT_TENSOR_PARALLEL_SIZE=1
export MILES_GLOBAL_BATCH_SIZE=256
export MILES_GPUS_PER_NODE=8
export MILES_GRPO_ROLLOUT_SHUFFLE=1
export MILES_HF_CHECKPOINT="${GLM47_REPRO_MODEL_PATH:-/workspace/models/GLM-4.7-Flash}"
export MILES_KL_LOSS_COEF=0.02
export MILES_LORA_ADAPTER_PATH="${adapter_root}"
export MILES_LORA_ALPHA=32
export MILES_LORA_BASE_CPU_BACKUP=1
export MILES_LORA_RANK=32
export MILES_LORA_TARGET_MODULES=q_a_proj,kv_a_proj_with_mqa,o_proj,gate_proj,up_proj,down_proj
export MILES_LR=5e-7
export MILES_MAX_TOKENS_PER_GPU=12288
export MILES_MICRO_BATCH_SIZE=1
export MILES_MODEL_ARGS_FILE=glm4.7-flash.sh
export MILES_MOE_ENABLE_DEEPEP=1
export MILES_MOE_TOKEN_DISPATCHER_TYPE=flex
export MILES_NO_GRADIENT_ACCUMULATION_FUSION=1
export MILES_NO_REF=0
export MILES_NUM_ROLLOUT="${MILES_NUM_ROLLOUT:-11}"
export MILES_N_SAMPLES_PER_PROMPT=8
export MILES_PIPELINE_MODEL_PARALLEL_SIZE=1
export MILES_RECOMPUTE_GRANULARITY=full
export MILES_REF_LOAD_DIR="${GLM47_REPRO_REF_LOAD_DIR:-/workspace/models/GLM-4.7-Flash_torch_dist_tp4_pp1_ep8}"
export MILES_REWARD_PREFLIGHT_MODULE=glm47_posttraining.integrations.miles_aider_polyglot
export MILES_ROLLOUT_BATCH_SIZE=32
export MILES_ROLLOUT_MAX_RESPONSE_LEN=4096
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
export MILES_SGLANG_MAX_RUNNING_REQUESTS=256
export MILES_SGLANG_MEM_FRACTION_STATIC=0.75
export MILES_SGLANG_MOE_DENSE_TP_SIZE=1
export MILES_SGLANG_SERVER_CONCURRENCY=1024
export MILES_SGLANG_SPECULATIVE=0
export MILES_TENSOR_MODEL_PARALLEL_SIZE=4
export MILES_TRAIN_MODULE=glm47_posttraining.integrations.miles_train_with_glm47_bridge
export MILES_USE_DYNAMIC_BATCH_SIZE=1
export MILES_USE_KL_LOSS=1
export MILES_WANDB_GROUP="${run_id}"
export MILES_WANDB_JOB_TYPE=grpo
export MILES_WANDB_PROJECT="${MILES_WANDB_PROJECT:-glm47-aider-polyglot-cpp-grpo}"
export MILES_WANDB_RUN_ID="${run_id}"
if [[ "${MILES_GRPO_CONTINUATION_MODE:-none}" != "none" ]]; then
  export MILES_GRPO_PARENT_ADAPTER_SHA256="${MILES_GRPO_PARENT_ADAPTER_SHA256:-${expected_adapter_sha256}}"
fi

export NCCL_DEBUG=WARN
export NVSHMEM_DISABLE_NCCL=1
export WANDB_MODE="${WANDB_MODE:-offline}"
export WANDB_TAGS="${WANDB_TAGS:-canonical,aider-polyglot-cpp,grpo,2epoch,8xh100,lium,parser-fixed}"

mkdir -p "${run_root}"
cd "${repo_root}"
exec bash examples/grpo.sh
