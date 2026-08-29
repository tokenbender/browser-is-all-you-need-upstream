#!/usr/bin/env bash
set -euo pipefail

TOOLKIT_VERSION="1.19.1-1"
EXPECTED_GPU_COUNT="${EXPECTED_GPU_COUNT:-4}"
EXPECTED_GPU_MODEL="${EXPECTED_GPU_MODEL:-A100}"
EXPECTED_GPU_MEMORY_MIB="${EXPECTED_GPU_MEMORY_MIB:-80000}"

if [[ "$#" -ne 0 ]]; then
  echo "This script accepts no arguments; configure GPU checks with EXPECTED_GPU_* variables" >&2
  exit 2
fi

if ! [[ "${EXPECTED_GPU_COUNT}" =~ ^[1-9][0-9]*$ ]]; then
  echo "EXPECTED_GPU_COUNT must be a positive integer" >&2
  exit 2
fi
if [[ -z "${EXPECTED_GPU_MODEL}" ]]; then
  echo "EXPECTED_GPU_MODEL must not be empty" >&2
  exit 2
fi
if ! [[ "${EXPECTED_GPU_MEMORY_MIB}" =~ ^[1-9][0-9]*$ ]]; then
  echo "EXPECTED_GPU_MEMORY_MIB must be a positive integer" >&2
  exit 2
fi
NVIDIA_SMI_BIN="$(command -v nvidia-smi || true)"
if [[ -z "${NVIDIA_SMI_BIN}" ]]; then
  echo "nvidia-smi was not found" >&2
  exit 2
fi

run_nvidia_smi() {
  if [[ -x "${NVIDIA_SMI_BIN}" ]]; then
    "${NVIDIA_SMI_BIN}" "$@"
  else
    sudo -n "${NVIDIA_SMI_BIN}" "$@"
  fi
}


observed_gpu_count="$(run_nvidia_smi --query-gpu=name --format=csv,noheader | wc -l)"
if [[ "${observed_gpu_count}" -ne "${EXPECTED_GPU_COUNT}" ]]; then
  echo "Expected ${EXPECTED_GPU_COUNT} GPUs, found ${observed_gpu_count}" >&2
  exit 2
fi
if run_nvidia_smi --query-gpu=name,memory.total --format=csv,noheader,nounits | \
    awk -F, -v model="${EXPECTED_GPU_MODEL}" -v memory="${EXPECTED_GPU_MEMORY_MIB}" \
      'index($1, model) == 0 || $2 + 0 < memory { bad=1 } END { exit bad }'; then
  echo "Verified ${EXPECTED_GPU_COUNT} ${EXPECTED_GPU_MODEL} GPUs with at least ${EXPECTED_GPU_MEMORY_MIB} MiB each"
else
  echo "GPU type or memory does not match ${EXPECTED_GPU_COUNT} ${EXPECTED_GPU_MODEL} devices with at least ${EXPECTED_GPU_MEMORY_MIB} MiB each" >&2
  exit 2
fi

if command -v docker >/dev/null && command -v nvidia-ctk >/dev/null && \
    sudo docker info >/dev/null 2>&1 && \
    sudo docker info --format '{{json .Runtimes}}' | grep -q '"nvidia"'; then
  echo "Docker and the NVIDIA Container Toolkit are already ready"
  exit 0
fi

sudo apt-get update
sudo apt-get install -y --no-install-recommends docker.io ca-certificates curl gnupg2
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor --yes -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -sSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null
sudo apt-get update
sudo apt-get install -y \
  "nvidia-container-toolkit=${TOOLKIT_VERSION}" \
  "nvidia-container-toolkit-base=${TOOLKIT_VERSION}" \
  "libnvidia-container-tools=${TOOLKIT_VERSION}" \
  "libnvidia-container1=${TOOLKIT_VERSION}"
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl enable --now docker
sudo systemctl restart docker
sudo docker info >/dev/null
echo "Docker and NVIDIA Container Toolkit ${TOOLKIT_VERSION} are ready"
