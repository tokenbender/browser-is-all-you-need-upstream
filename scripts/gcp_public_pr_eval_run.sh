#!/usr/bin/env bash
set -euo pipefail

: "${MODEL_DIR:?set MODEL_DIR to the staged GLM-4.7-Flash directory}"
: "${MODEL_MANIFEST_SHA256:?set the .source-manifest.sha256 digest}"
: "${ADAPTER_DIR:?set ADAPTER_DIR to the staged 50-epoch adapter directory}"
: "${RESULT_DIR:?set RESULT_DIR to a persistent result directory}"
: "${ADAPTER_CONFIG_SHA256:?set the adapter_config.json SHA-256}"
: "${RUN_ID:?set a new unique evaluation run ID}"

IMAGE_NAME="${IMAGE_NAME:-glm47-public-pr-gcp:synthmem-v1-ep50-thinking-v8}"
SUITE="${SUITE:-fmtlib-final-cleanup-verified-mechanisms-thinking}"
CHECKPOINT_PROFILE="${CHECKPOINT_PROFILE:-synthmem-v1-ep50}"
DOCKERFILE="${DOCKERFILE:-docker/public-pr-synthmem-v1-ep50-gcp/Dockerfile}"
BUILD_IMAGE="${BUILD_IMAGE:-1}"
TENSOR_PARALLEL_SIZE="${TENSOR_PARALLEL_SIZE:-4}"
DATA_PARALLEL_SIZE="${DATA_PARALLEL_SIZE:-1}"
EXPECTED_GPU_COUNT="${EXPECTED_GPU_COUNT:-4}"
EXPECTED_GPU_MODEL="${EXPECTED_GPU_MODEL:-A100}"
EXPECTED_GPU_MEMORY_MIB="${EXPECTED_GPU_MEMORY_MIB:-80000}"
EXECUTION_PROFILE="${EXECUTION_PROFILE:-gcp-a100-tp4}"
PROVISIONER="${PROVISIONER:-gcloud-shell}"

metadata_value() {
  curl --fail --silent --show-error --connect-timeout 2 --max-time 5 \
    --header 'Metadata-Flavor: Google' \
    "http://metadata.google.internal/computeMetadata/v1/$1"
}

if [[ -z "${GCP_PROJECT:-}" ]]; then
  GCP_PROJECT="$(metadata_value project/project-id)"
fi
if [[ -z "${GCP_ZONE:-}" ]]; then
  GCP_ZONE="$(basename "$(metadata_value instance/zone)")"
fi
if [[ -z "${GCP_INSTANCE:-}" ]]; then
  GCP_INSTANCE="$(metadata_value instance/name)"
fi
if [[ -z "${GCP_MACHINE_TYPE:-}" ]]; then
  GCP_MACHINE_TYPE="$(basename "$(metadata_value instance/machine-type)")"
fi
if [[ -z "${GCP_DLVM_IMAGE:-}" ]]; then
  GCP_DLVM_IMAGE="$(basename "$(metadata_value instance/image)")"
fi

: "${GCP_PROJECT:?could not discover the GCP project ID for the receipt}"
: "${GCP_ZONE:?could not discover the exact GCP zone for the receipt}"
: "${GCP_INSTANCE:?could not discover the GCP instance name for the receipt}"
: "${GCP_MACHINE_TYPE:?could not discover the GCP machine type for the receipt}"
: "${GCP_DLVM_IMAGE:?could not discover the resolved image for the receipt}"

test -f "${MODEL_DIR}/.source-revision"
test -f "${ADAPTER_DIR}/.training-run-id"
mkdir -p "${RESULT_DIR}"

case "${BUILD_IMAGE}" in
  1)
    sudo docker build --progress=plain \
      --file "${DOCKERFILE}" \
      --tag "${IMAGE_NAME}" \
      .
    ;;
  0)
    sudo docker image inspect "${IMAGE_NAME}" >/dev/null
    ;;
  *)
    echo "BUILD_IMAGE must be 0 or 1" >&2
    exit 2
    ;;
esac
EVAL_IMAGE_ID="$(sudo docker image inspect --format '{{.Id}}' "${IMAGE_NAME}")"

sudo docker run --rm \
  --gpus all \
  --network none \
  --ipc host \
  --shm-size 128g \
  --env "GCP_PROJECT=${GCP_PROJECT}" \
  --env "GCP_ZONE=${GCP_ZONE}" \
  --env "GCP_INSTANCE=${GCP_INSTANCE}" \
  --env "GCP_MACHINE_TYPE=${GCP_MACHINE_TYPE}" \
  --env "GCP_DLVM_IMAGE=${GCP_DLVM_IMAGE}" \
  --env "EVAL_IMAGE_ID=${EVAL_IMAGE_ID}" \
  --volume "${MODEL_DIR}:/models/GLM-4.7-Flash:ro" \
  --volume "${ADAPTER_DIR}:/adapter:ro" \
  --volume "${RESULT_DIR}:/results" \
  "${IMAGE_NAME}" \
  --model-path /models/GLM-4.7-Flash \
  --expected-model-manifest-sha256 "${MODEL_MANIFEST_SHA256}" \
  --adapter-path /adapter \
  --expected-adapter-config-sha256 "${ADAPTER_CONFIG_SHA256}" \
  --output-root /results \
  --run-id "${RUN_ID}" \
  --suite "${SUITE}" \
  --checkpoint-profile "${CHECKPOINT_PROFILE}" \
  --tensor-parallel-size "${TENSOR_PARALLEL_SIZE}" \
  --data-parallel-size "${DATA_PARALLEL_SIZE}" \
  --expected-gpu-count "${EXPECTED_GPU_COUNT}" \
  --expected-gpu-model "${EXPECTED_GPU_MODEL}" \
  --expected-gpu-memory-mib "${EXPECTED_GPU_MEMORY_MIB}" \
  --execution-profile "${EXECUTION_PROFILE}" \
  --provisioner "${PROVISIONER}"

echo "Suite: ${SUITE}"
echo "Result: ${RESULT_DIR}/runs/${RUN_ID}/run-receipt.json"
echo "Diagnosis: ${RESULT_DIR}/runs/${RUN_ID}/evaluation/diagnostic-report.md"
echo "Checkpoint profile: ${CHECKPOINT_PROFILE}"
echo "Execution profile: ${EXECUTION_PROFILE}"
echo "Tensor parallel size: ${TENSOR_PARALLEL_SIZE}"
echo "Data parallel size: ${DATA_PARALLEL_SIZE}"
