#!/usr/bin/env bash
set -euo pipefail

CONFIG_REL="configs/full_v5_charm_grpo/gcp-r8-unadmitted-hybrid45-exact40-r87-skypilot.json"
DRIVER="scripts/gcp_full_v5_charm_grpo.py"
AUTH_ENV="GLM47_CHARM_R8_UNADMITTED_FULL_AUTHORIZATION"
AUTH_PHRASE="I_AUTHORIZE_UNADMITTED_R8_HYBRID45_EXACT40_6_UPDATE_EXPERIMENT_AND_GCP_COSTS"
BASE_RUN_ID="${RUN_ID:-}"
ONE_UPDATE_SMOKE="${GLM47_R8_ONE_UPDATE_SMOKE:-0}"
SMOKE_ARGS=()
RESULT_ROOT="${GLM47_FULL_V5_RESULT_ROOT:-${HOME}/glm47-full-v5-local-results}"
DURABLE_ROOT="${GLM47_FULL_V5_DURABLE_RESULT_ROOT:-${HOME}/glm47-results-store/runs/glm47/experiments/unadmitted-r8-hybrid45-exact40-r87}"

if [[ "${ONE_UPDATE_SMOKE}" == "1" ]]; then
  SMOKE_ARGS=(--one-update-smoke)
elif [[ "${ONE_UPDATE_SMOKE}" != "0" ]]; then
  echo "GLM47_R8_ONE_UPDATE_SMOKE must be 0 or 1" >&2
  exit 2
fi

if ! [[ "${BASE_RUN_ID}" =~ ^unadmitted-r8-r87-[A-Za-z0-9][A-Za-z0-9._-]{0,94}$ ]]; then
  echo "RUN_ID must begin with unadmitted-r8-r87- and leave room for an attempt suffix" >&2
  exit 2
fi
if [[ "${!AUTH_ENV:-}" != "${AUTH_PHRASE}" ]]; then
  echo "${AUTH_ENV} must explicitly authorize the quarantine-only 8xH100 R8 cost" >&2
  exit 2
fi

ATTEMPT_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ATTEMPT_NONCE="$(python3 -c 'import secrets; print(secrets.token_hex(4))')"
ATTEMPT_RUN_ID="${BASE_RUN_ID}-attempt-${ATTEMPT_STAMP}-${ATTEMPT_NONCE}"
CONTROL_ROOT="${RESULT_ROOT}/attempt-control/${ATTEMPT_RUN_ID}"
ATTEMPT_INDEX_ROOT="${DURABLE_ROOT}/attempt-index/${BASE_RUN_ID}"
ATTEMPT_EVIDENCE_ROOT="${ATTEMPT_INDEX_ROOT}/${ATTEMPT_RUN_ID}"
CURRENT_STAGE="bootstrap"

umask 077
mkdir -p \
  "${CONTROL_ROOT}" \
  "${ATTEMPT_INDEX_ROOT}" \
  "${ATTEMPT_EVIDENCE_ROOT}/control" \
  "${ATTEMPT_EVIDENCE_ROOT}/stages"
if [[ -e "${ATTEMPT_INDEX_ROOT}/${ATTEMPT_RUN_ID}.started.json" ]]; then
  echo "refusing to reuse Spot attempt ID: ${ATTEMPT_RUN_ID}" >&2
  exit 2
fi

export PYTHONPATH="${PWD}/src${PYTHONPATH:+:${PYTHONPATH}}"
export GLM47_FULL_V5_CONFIG_PATH="${CONFIG_REL}"
export GLM47_PROVISIONER="skypilot"
export GLM47_EXECUTION_PROFILE="gcp-skypilot-h100-tp4-ep8-dp8-unadmitted-r8-hybrid45-r87"

readarray -t IMAGE_REFS < <(python3 -c '
import json, sys
p=json.load(open(sys.argv[1], encoding="utf-8"))
print(p["training_image"]["immutable_ref"])
print(p["verifier_image"]["immutable_ref"])
' "${CONFIG_REL}")
TRAIN_IMAGE_REF="${IMAGE_REFS[0]}"
VERIFIER_IMAGE_REF="${IMAGE_REFS[1]}"

write_attempt_record() {
  local state="$1"
  local timestamp="$2"
  local exit_code="$3"
  local destination="${ATTEMPT_INDEX_ROOT}/${ATTEMPT_RUN_ID}.${state}.json"
  local temporary="${destination}.tmp.$$"
  printf '{"attempt_nonce":"%s","attempt_run_id":"%s","base_run_id":"%s","checkpoint_disposition":"QUARANTINE_ONLY","exit_code":%s,"last_stage":"%s","recorded_at_utc":"%s","status":"%s"}\n' \
    "${ATTEMPT_NONCE}" "${ATTEMPT_RUN_ID}" "${BASE_RUN_ID}" "${exit_code}" \
    "${CURRENT_STAGE}" "${timestamp}" "${state}" >"${temporary}"
  mv "${temporary}" "${destination}"
}

write_stage_record() {
  local stage="$1"
  local state="$2"
  local timestamp="$3"
  local exit_code="$4"
  local destination="${ATTEMPT_EVIDENCE_ROOT}/stages/${stage}.${state}.json"
  local temporary="${destination}.tmp.$$"
  printf '{"attempt_run_id":"%s","base_run_id":"%s","checkpoint_disposition":"QUARANTINE_ONLY","exit_code":%s,"recorded_at_utc":"%s","stage":"%s","status":"%s"}\n' \
    "${ATTEMPT_RUN_ID}" "${BASE_RUN_ID}" "${exit_code}" "${timestamp}" \
    "${stage}" "${state}" >"${temporary}"
  mv "${temporary}" "${destination}"
}

persist_control_artifacts() {
  local durable_control_root="${ATTEMPT_EVIDENCE_ROOT}/control"
  local artifact
  local target
  local temporary
  mkdir -p "${durable_control_root}"
  while IFS= read -r -d '' artifact; do
    target="${durable_control_root}/$(basename "${artifact}")"
    if [[ -e "${target}" ]]; then
      continue
    fi
    temporary="${target}.tmp.$$"
    cp -- "${artifact}" "${temporary}"
    mv "${temporary}" "${target}"
  done < <(find "${CONTROL_ROOT}" -maxdepth 1 -type f -print0)
}

run_json_stage() {
  local stage="$1"
  local output_path="$2"
  local stderr_path
  local exit_code
  shift 2
  CURRENT_STAGE="${stage}"
  stderr_path="${CONTROL_ROOT}/${stage}.stderr.log"
  write_stage_record "${stage}" "started" "$(date -u +%Y%m%dT%H%M%SZ)" 0
  set +e
  "$@" >"${output_path}" 2>"${stderr_path}"
  exit_code="$?"
  set -e
  if [[ -s "${stderr_path}" ]]; then
    cat "${stderr_path}" >&2
  fi
  persist_control_artifacts
  if [[ "${exit_code}" -ne 0 ]]; then
    write_stage_record "${stage}" "failed" "$(date -u +%Y%m%dT%H%M%SZ)" "${exit_code}"
    return "${exit_code}"
  fi
  write_stage_record "${stage}" "passed" "$(date -u +%Y%m%dT%H%M%SZ)" 0
}

run_logged_stage() {
  local stage="$1"
  local log_path
  local durable_log_path
  local command_exit_code
  local tee_exit_code
  local exit_code
  local -a pipeline_status
  shift
  CURRENT_STAGE="${stage}"
  log_path="${CONTROL_ROOT}/${stage}.log"
  durable_log_path="${ATTEMPT_EVIDENCE_ROOT}/control/${stage}.log"
  write_stage_record "${stage}" "started" "$(date -u +%Y%m%dT%H%M%SZ)" 0
  set +e
  "$@" 2>&1 | tee "${log_path}" "${durable_log_path}"
  pipeline_status=("${PIPESTATUS[@]}")
  command_exit_code="${pipeline_status[0]}"
  tee_exit_code="${pipeline_status[1]}"
  set -e
  exit_code="${command_exit_code}"
  if [[ "${exit_code}" -eq 0 && "${tee_exit_code}" -ne 0 ]]; then
    exit_code="${tee_exit_code}"
  fi
  persist_control_artifacts
  if [[ "${exit_code}" -ne 0 ]]; then
    write_stage_record "${stage}" "failed" "$(date -u +%Y%m%dT%H%M%SZ)" "${exit_code}"
    return "${exit_code}"
  fi
  write_stage_record "${stage}" "passed" "$(date -u +%Y%m%dT%H%M%SZ)" 0
}

on_exit() {
  local exit_code="$?"
  if [[ "${exit_code}" -ne 0 ]]; then
    set +e
    persist_control_artifacts
    write_stage_record "${CURRENT_STAGE}" "terminal-failure" \
      "$(date -u +%Y%m%dT%H%M%SZ)" "${exit_code}"
    write_attempt_record "failed" "$(date -u +%Y%m%dT%H%M%SZ)" "${exit_code}"
    true
  fi
}
trap on_exit EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
write_attempt_record "started" "${ATTEMPT_STAMP}" 0

run_json_stage inspect "${CONTROL_ROOT}/inspect.json" \
  python3 "${DRIVER}" inspect
run_json_stage render "${CONTROL_ROOT}/render.json" \
  python3 "${DRIVER}" render --phase experimental --run-id "${ATTEMPT_RUN_ID}" \
  "${SMOKE_ARGS[@]}"
run_logged_stage host-check \
  python3 "${DRIVER}" host-check
run_logged_stage prepare \
  python3 "${DRIVER}" prepare \
  --result-root "${RESULT_ROOT}" \
  --receipt "${CONTROL_ROOT}/preparation-receipt.json" \
  --prebuilt-images \
  --train-image "${TRAIN_IMAGE_REF}" \
  --verifier-image "${VERIFIER_IMAGE_REF}"

run_logged_stage train \
  python3 "${DRIVER}" train \
  --phase experimental \
  --run-id "${ATTEMPT_RUN_ID}" \
  --result-root "${RESULT_ROOT}" \
  --train-image "${TRAIN_IMAGE_REF}" \
  --verifier-image "${VERIFIER_IMAGE_REF}" \
  "${SMOKE_ARGS[@]}"

COMPLETED_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
CURRENT_STAGE="complete"
write_attempt_record "passed" "${COMPLETED_STAMP}" 0
trap - EXIT TERM INT
