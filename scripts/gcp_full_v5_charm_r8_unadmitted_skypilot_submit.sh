#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." &>/dev/null && pwd)"
CONFIG_REL="configs/full_v5_charm_grpo/gcp-r8-unadmitted-hybrid45-exact40-r87-skypilot.json"
AUTH_ENV="GLM47_CHARM_R8_UNADMITTED_FULL_AUTHORIZATION"
AUTH_PHRASE="I_AUTHORIZE_UNADMITTED_R8_HYBRID45_EXACT40_6_UPDATE_EXPERIMENT_AND_GCP_COSTS"
RUN_ID="${1:-unadmitted-r8-r87-$(date -u +%Y%m%dT%H%M%SZ)}"
TRANSPORT_TASK="../r8-skypilot-transport.yaml"
ONE_UPDATE_SMOKE="${GLM47_R8_ONE_UPDATE_SMOKE:-0}"
SMOKE_ARGS=()

if [[ "${ONE_UPDATE_SMOKE}" == "1" ]]; then
  SMOKE_ARGS=(--one-update-smoke)
elif [[ "${ONE_UPDATE_SMOKE}" != "0" ]]; then
  echo "GLM47_R8_ONE_UPDATE_SMOKE must be 0 or 1" >&2
  exit 2
fi

if ! [[ "${RUN_ID}" =~ ^unadmitted-r8-r87-[A-Za-z0-9][A-Za-z0-9._-]{0,94}$ ]]; then
  echo "RUN_ID must begin with unadmitted-r8-r87- and leave room for an attempt suffix" >&2
  exit 2
fi
if [[ "${!AUTH_ENV:-}" != "${AUTH_PHRASE}" ]]; then
  echo "No GPU was requested: ${AUTH_ENV} does not contain the exact R8 cost authorization." >&2
  exit 2
fi

cd "${REPO_ROOT}"
export PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
export GLM47_FULL_V5_CONFIG_PATH="${REPO_ROOT}/${CONFIG_REL}"

python3 scripts/gcp_full_v5_charm_grpo.py inspect >/dev/null
python3 scripts/gcp_full_v5_charm_grpo.py render \
  --phase experimental --run-id "${RUN_ID}-attempt-render" \
  "${SMOKE_ARGS[@]}" >/dev/null

RUNTIME_SOURCE="$(python3 -c '
import json, re, sys
p=json.load(open(sys.argv[1], encoding="utf-8"))
assert p["decision"] == "EXPERIMENTAL_UNADMITTED"
assert p["execution"]["admission_mode"] == "UNADMITTED_EXPERIMENT_ONLY"
assert p["execution"]["checkpoint_disposition"] == "QUARANTINE_ONLY"
assert p["execution"]["charm_eligible"] is False
assert p["full_v5_runtime"]["gcp_asset_status"] == "AVAILABLE"
assert p["training_image"]["gcp_asset_status"] == "AVAILABLE"
assert p["verifier_image"]["gcp_asset_status"] == "AVAILABLE"
for key in ("training_image", "verifier_image"):
    ref=p[key].get("immutable_ref", "")
    digest=p[key].get("registry_digest", "")
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
    assert ref.endswith("@" + digest)
print(p["gcp"]["runtime_source"])
' "${CONFIG_REL}")"

# Verify the private runtime exists before SkyPilot can provision an H100 VM.
gcloud storage ls "${RUNTIME_SOURCE}/manifest.json" >/dev/null

TRANSPORT_ROOT="$(mktemp -d "/tmp/glm47-r8-${RUN_ID}.XXXXXXXX")"
python3 scripts/build_r8_skypilot_workdir.py \
  --repo-root "${REPO_ROOT}" \
  --profile "${REPO_ROOT}/${CONFIG_REL}" \
  --output-root "${TRANSPORT_ROOT}"
cd "${TRANSPORT_ROOT}/workdir"

exec sky jobs launch \
  --name "${RUN_ID}" \
  --detach-run \
  --yes \
  --env "RUN_ID=${RUN_ID}" \
  --env "${AUTH_ENV}=${AUTH_PHRASE}" \
  --env "GLM47_R8_ONE_UPDATE_SMOKE=${ONE_UPDATE_SMOKE}" \
  "${TRANSPORT_TASK}"
