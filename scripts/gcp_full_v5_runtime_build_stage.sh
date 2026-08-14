#!/usr/bin/env bash
set -euo pipefail

# Build the frozen full-v5 runtime from local producer inputs, then optionally
# stage the independently verified extracted bytes to GCS. This script never
# contacts a model host and never provisions accelerator resources.

MODE="${1:-preflight}"
PRODUCER_DIR="${FULL_V5_PRODUCER_DIR:-}"
INPUT_ROOT="${FULL_V5_PRODUCER_INPUT_ROOT:-}"
BUILD_ROOT="${FULL_V5_RUNTIME_BUILD_ROOT:-}"
GCS_URI="${FULL_V5_RUNTIME_GCS_URI:-gs://lifeandhalf-24122025-w8-biayn/glm47-full-v5/assets/runtime/aider_cpp_rl_full_v5}"

EXPECTED_PRODUCER_REVISION="0efce27cd2c333f769afc74c9f9b852823256322"
EXPECTED_V5_TRAIN_SHA256="a01a07c9d4e2706683814a3d5afc2bcd47172ff92b08f15e2c673729f185bd66"
EXPECTED_REGISTRY_MANIFEST_SHA256="28e2ea54261704866ed4d1b566a0037d7ebae111faf0c01706bd315bf93dc142"
EXPECTED_REGISTRY_ROWS_SHA256="ff13441e968eca08387339e43f1fbbcf3993337c69ddd2ed8754a7cf0287a745"
EXPECTED_REGISTRY_TARGETS_SHA256="c59538796e828530842f8fd36c2f0effa13fbf9a493d995c749973db4d6c28cc"
EXPECTED_INVENTORY_MANIFEST_SHA256="bfcac4247182b11edad690d8cfd4b9437e2e291eb68d54fb85fc187b76f2272a"
EXPECTED_INVENTORY_EXECUTABLE_SHA256="6e537a40c8e6fcd6c0f43b3cd0dc13f3309121ae812cfe3d5f5a1b75f9630df3"
EXPECTED_INVENTORY_EXCLUDED_SHA256="f7355ef61301f0c492f9373d5d3d07aab12cab4b1a64a887833baa7a1ce7902e"
EXPECTED_SPLIT_SHA256="e7691f8889babdf05a1254c58ba902ae13a42ddf17a0473281928b035fc8d7d5"
EXPECTED_RUNTIME_MANIFEST_SHA256="93d671faa44abcc6deca21c6a49e247d76436835bfa2905ee33968a478fb532a"
EXPECTED_RUNTIME_TREE_SHA256="0a3df3ce40eed45814651c933277bfc5ca17359a2b3e6f0a7027b184e3569c7e"
EXPECTED_ARCHIVE_SHA256="d2a4c413f8944dc2d560b3ca156b5543455f4dbeb24cbfa8e1f7770d356861f5"
EXPECTED_ARTIFACT_MANIFEST_SHA256="5490c109fd2ed746f5680f0e996e847112872940b8e5eb466cd6af86bc6579e2"

usage() {
  cat <<'EOF'
Usage: scripts/gcp_full_v5_runtime_build_stage.sh MODE

MODE is one of:
  preflight   Verify the pinned producer checkout and all local input identities.
  build       Preflight, build, archive, extract, and verify locally.
  stage       Upload a previously verified local build to the empty GCS prefix.
  build-stage Run build and then stage.

Required environment:
  FULL_V5_PRODUCER_DIR       Checkout at 0efce27cd2c333f769afc74c9f9b852823256322.
  FULL_V5_PRODUCER_INPUT_ROOT
                             Root of the normalized private producer inputs.
  FULL_V5_RUNTIME_BUILD_ROOT Fresh local output directory for build modes, or
                             an existing verified build directory for stage.

Optional environment:
  FULL_V5_RUNTIME_GCS_URI    Destination prefix. The default is the frozen GCP
                             full-v5 runtime prefix used by SkyPilot.

Normalized input layout:
  v5/train.jsonl
  registry/{manifest.json,rows.jsonl,targets.jsonl}
  inventory/{manifest.json,executable.jsonl,excluded.jsonl}
  current-tasks/cpp/exercises/practice/...
  holistic-packages/<slug>/...
  exercism-cpp/exercises/{practice,concept}/...
  signals/<family>/<task>/...
  split/split.jsonl

This command does not use a model-host credential and does not start a VM or GPU.
EOF
}

fail() {
  echo "FULL_V5_RUNTIME_BUILD_STAGE_ERROR: $*" >&2
  exit 2
}

require_value() {
  local name="$1"
  [[ -n "${!name:-}" ]] || fail "${name} is required"
}

require_file() {
  local path="$1"
  [[ -f "${path}" ]] || fail "required file is missing: ${path}"
}

require_directory() {
  local path="$1"
  [[ -d "${path}" ]] || fail "required directory is missing: ${path}"
}

verify_sha256() {
  local expected="$1"
  local path="$2"
  local observed
  require_file "${path}"
  observed="$(sha256sum "${path}" | awk '{print $1}')"
  [[ "${observed}" == "${expected}" ]] ||
    fail "SHA-256 mismatch for ${path}: expected ${expected}, observed ${observed}"
}

preflight() {
  require_value FULL_V5_PRODUCER_DIR
  require_value FULL_V5_PRODUCER_INPUT_ROOT
  require_directory "${PRODUCER_DIR}/.git"
  require_file "${PRODUCER_DIR}/scripts/package_aider_full_v5_rl.py"
  require_file "${PRODUCER_DIR}/scripts/package_aider_full_v5_archive.py"
  require_file "${PRODUCER_DIR}/scripts/verify_aider_full_v5_archive.py"

  local producer_revision
  producer_revision="$(git -C "${PRODUCER_DIR}" rev-parse HEAD)"
  [[ "${producer_revision}" == "${EXPECTED_PRODUCER_REVISION}" ]] ||
    fail "producer revision mismatch: expected ${EXPECTED_PRODUCER_REVISION}, observed ${producer_revision}"

  verify_sha256 "${EXPECTED_V5_TRAIN_SHA256}" "${INPUT_ROOT}/v5/train.jsonl"
  verify_sha256 "${EXPECTED_REGISTRY_MANIFEST_SHA256}" "${INPUT_ROOT}/registry/manifest.json"
  verify_sha256 "${EXPECTED_REGISTRY_ROWS_SHA256}" "${INPUT_ROOT}/registry/rows.jsonl"
  verify_sha256 "${EXPECTED_REGISTRY_TARGETS_SHA256}" "${INPUT_ROOT}/registry/targets.jsonl"
  verify_sha256 "${EXPECTED_INVENTORY_MANIFEST_SHA256}" "${INPUT_ROOT}/inventory/manifest.json"
  verify_sha256 "${EXPECTED_INVENTORY_EXECUTABLE_SHA256}" "${INPUT_ROOT}/inventory/executable.jsonl"
  verify_sha256 "${EXPECTED_INVENTORY_EXCLUDED_SHA256}" "${INPUT_ROOT}/inventory/excluded.jsonl"
  verify_sha256 "${EXPECTED_SPLIT_SHA256}" "${INPUT_ROOT}/split/split.jsonl"

  require_directory "${INPUT_ROOT}/current-tasks/cpp/exercises/practice"
  require_directory "${INPUT_ROOT}/holistic-packages"
  require_directory "${INPUT_ROOT}/exercism-cpp/exercises/practice"
  require_directory "${INPUT_ROOT}/signals"

  echo "FULL_V5_RUNTIME_PREFLIGHT=passed"
  echo "PRODUCER_REVISION=${producer_revision}"
}

verify_bundle_identities() {
  local bundle_root="$1"
  verify_sha256 "${EXPECTED_ARCHIVE_SHA256}" "${bundle_root}/aider-cpp-rl-full-v5-runtime.tar.gz"
  verify_sha256 "${EXPECTED_ARTIFACT_MANIFEST_SHA256}" "${bundle_root}/artifact_manifest.json"

  local manifest_sha256
  local tree_sha256
  manifest_sha256="$(jq -er '.runtime_manifest_sha256' "${bundle_root}/artifact_manifest.json")"
  tree_sha256="$(jq -er '.runtime_tree_sha256' "${bundle_root}/artifact_manifest.json")"
  [[ "${manifest_sha256}" == "${EXPECTED_RUNTIME_MANIFEST_SHA256}" ]] ||
    fail "runtime manifest identity mismatch in artifact_manifest.json"
  [[ "${tree_sha256}" == "${EXPECTED_RUNTIME_TREE_SHA256}" ]] ||
    fail "runtime tree identity mismatch in artifact_manifest.json"
}

build_runtime() {
  require_value FULL_V5_RUNTIME_BUILD_ROOT
  [[ ! -e "${BUILD_ROOT}" ]] || fail "build root must not already exist: ${BUILD_ROOT}"
  preflight

  mkdir -p "${BUILD_ROOT}/runtime"
  mkdir -p "${BUILD_ROOT}/bundle"

  PYTHONPATH="${PRODUCER_DIR}/src" python3 +    "${PRODUCER_DIR}/scripts/package_aider_full_v5_rl.py" +    --v5-train "${INPUT_ROOT}/v5/train.jsonl" +    --registry-dir "${INPUT_ROOT}/registry" +    --inventory-dir "${INPUT_ROOT}/inventory" +    --current-tasks-root "${INPUT_ROOT}/current-tasks" +    --holistic-packages-root "${INPUT_ROOT}/holistic-packages" +    --exercism-repo-root "${INPUT_ROOT}/exercism-cpp" +    --signal-root "${INPUT_ROOT}/signals" +    --split-plan "${INPUT_ROOT}/split/split.jsonl" +    --output-dir "${BUILD_ROOT}/runtime/aider_cpp_rl_full_v5"

  verify_sha256 "${EXPECTED_RUNTIME_MANIFEST_SHA256}" +    "${BUILD_ROOT}/runtime/aider_cpp_rl_full_v5/manifest.json"

  PYTHONPATH="${PRODUCER_DIR}/src" python3 +    "${PRODUCER_DIR}/scripts/package_aider_full_v5_archive.py" +    --package-dir "${BUILD_ROOT}/runtime/aider_cpp_rl_full_v5" +    --output-dir "${BUILD_ROOT}/bundle"

  verify_bundle_identities "${BUILD_ROOT}/bundle"

  PYTHONPATH="${PRODUCER_DIR}/src" python3 +    "${PRODUCER_DIR}/scripts/verify_aider_full_v5_archive.py" +    --bundle-dir "${BUILD_ROOT}/bundle" +    --destination "${BUILD_ROOT}/verified"

  echo "FULL_V5_RUNTIME_BUILD=passed"
  echo "VERIFIED_RUNTIME=${BUILD_ROOT}/verified/aider_cpp_rl_full_v5"
}

stage_runtime() {
  require_value FULL_V5_RUNTIME_BUILD_ROOT
  require_directory "${BUILD_ROOT}/verified/aider_cpp_rl_full_v5"
  require_file "${BUILD_ROOT}/bundle/artifact_manifest.json"
  verify_bundle_identities "${BUILD_ROOT}/bundle"
  verify_sha256 "${EXPECTED_RUNTIME_MANIFEST_SHA256}" +    "${BUILD_ROOT}/verified/aider_cpp_rl_full_v5/manifest.json"

  command -v gcloud >/dev/null 2>&1 || fail "gcloud is required for GCS staging"
  [[ "${GCS_URI}" == gs://* ]] || fail "FULL_V5_RUNTIME_GCS_URI must be a gs:// URI"

  local existing_object
  existing_object="$(gcloud storage objects list "${GCS_URI%/}/**" --limit=1 --format='value(name)')"
  [[ -z "${existing_object}" ]] ||
    fail "GCS destination is not empty; refusing to overwrite: ${GCS_URI}"

  gcloud storage rsync --recursive +    "${BUILD_ROOT}/verified/aider_cpp_rl_full_v5" +    "${GCS_URI%/}"

  [[ ! -e "${BUILD_ROOT}/gcs-roundtrip" ]] ||
    fail "round-trip directory already exists: ${BUILD_ROOT}/gcs-roundtrip"
  mkdir -p "${BUILD_ROOT}/gcs-roundtrip/aider_cpp_rl_full_v5"
  gcloud storage rsync --recursive +    "${GCS_URI%/}" +    "${BUILD_ROOT}/gcs-roundtrip/aider_cpp_rl_full_v5"

  mkdir -p "${BUILD_ROOT}/gcs-roundtrip-bundle"
  PYTHONPATH="${PRODUCER_DIR}/src" python3 +    "${PRODUCER_DIR}/scripts/package_aider_full_v5_archive.py" +    --package-dir "${BUILD_ROOT}/gcs-roundtrip/aider_cpp_rl_full_v5" +    --output-dir "${BUILD_ROOT}/gcs-roundtrip-bundle"
  verify_bundle_identities "${BUILD_ROOT}/gcs-roundtrip-bundle"

  echo "FULL_V5_RUNTIME_GCS_STAGE=passed"
  echo "FULL_V5_RUNTIME_GCS_URI=${GCS_URI%/}"
}

case "${MODE}" in
  preflight)
    preflight
    ;;
  build)
    build_runtime
    ;;
  stage)
    stage_runtime
    ;;
  build-stage)
    build_runtime
    stage_runtime
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    usage >&2
    fail "unsupported mode: ${MODE}"
    ;;
esac
