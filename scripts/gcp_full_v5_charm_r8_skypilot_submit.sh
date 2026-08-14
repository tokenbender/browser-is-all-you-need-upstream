#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." &>/dev/null && pwd)"
CONFIG_REL="configs/full_v5_charm_grpo/gcp-r8-candidate-hybrid45-exact40-r87-skypilot.json"
TASK_REL="grpo_h100_full_v5_charm_r8.yaml"
RUN_ID="${1:-charm-r8-r87-$(date -u +%Y%m%dT%H%M%SZ)}"

if ! [[ "${RUN_ID}" =~ ^charm-r8-r87-[A-Za-z0-9][A-Za-z0-9._-]{0,143}$ ]]; then
  echo "RUN_ID must begin with charm-r8-r87- and contain only safe characters" >&2
  exit 2
fi

cd "${REPO_ROOT}"
export PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
export GLM47_FULL_V5_CONFIG_PATH="${REPO_ROOT}/${CONFIG_REL}"

# All checks below run locally and without GPUs.  Never move the SkyPilot call
# above them: a VM-side rejection would still incur H100 provisioning cost.
python3 scripts/gcp_full_v5_charm_grpo.py inspect >/dev/null
python3 scripts/gcp_full_v5_charm_grpo.py render \
  --phase canary \
  --run-id "${RUN_ID}" >/dev/null

decision="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["decision"])' "${CONFIG_REL}")"
admission_mode="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["execution"]["admission_mode"])' "${CONFIG_REL}")"
if [[ "${decision}" != "PASS" || "${admission_mode}" != "PRETRAINING_PASS_CANARY_REQUIRED" ]]; then
  echo "Refusing SkyPilot provisioning: decision=${decision}, admission_mode=${admission_mode}." >&2
  echo "No GPU instance was requested. Regenerate an admitted profile after every required gate passes." >&2
  exit 2
fi

# This path becomes reachable only after owner-controlled admitted-profile
# regeneration.  SkyPilot managed jobs is the sole execution route for R8.
exec sky jobs launch \
  --name "${RUN_ID}" \
  --env "RUN_ID=${RUN_ID}" \
  --env "GLM47_SKYPILOT_MODE=canary" \
  "${TASK_REL}"
