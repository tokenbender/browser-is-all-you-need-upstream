#!/usr/bin/env bash
set -euo pipefail

MODE="${GLM47_SKYPILOT_MODE:-candidate}"
RUN_ID="${RUN_ID:-}"
CONFIG_REL="configs/full_v5_charm_grpo/gcp-r8-candidate-hybrid45-exact40-r87-skypilot.json"
DRIVER="scripts/gcp_full_v5_charm_grpo.py"

if ! [[ "${RUN_ID}" =~ ^charm-r8-r87-[A-Za-z0-9][A-Za-z0-9._-]{0,143}$ ]]; then
  echo "RUN_ID must begin with charm-r8-r87- and contain only safe characters" >&2
  exit 2
fi
if [[ "${MODE}" != "candidate" ]]; then
  echo "R8 is CANDIDATE_NOT_ADMITTED; smoke, canary, and full modes are blocked" >&2
  exit 2
fi

export PYTHONPATH="${PWD}/src${PYTHONPATH:+:${PYTHONPATH}}"
export GLM47_FULL_V5_CONFIG_PATH="${CONFIG_REL}"
export GLM47_PROVISIONER="skypilot"
export GLM47_EXECUTION_PROFILE="gcp-skypilot-h100-tp4-ep8-dp8-candidate-r8-hybrid45-r87"

# Validate and render the immutable candidate contract, then fail deliberately.
# This command never invokes host setup, Docker, Ray, or the optimizer.
python3 "${DRIVER}" inspect >/dev/null
python3 "${DRIVER}" render \
  --phase canary \
  --run-id "${RUN_ID}" >/dev/null

echo "R8 candidate validation passed, but paid execution is blocked until all" >&2
echo "pre-training gates, oracle replay, trainer proofs, and admission receipts pass." >&2
exit 2
