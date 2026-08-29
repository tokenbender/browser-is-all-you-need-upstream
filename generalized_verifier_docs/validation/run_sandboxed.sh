#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."
REPO=$(pwd)
VAL=generalized_verifier_docs/validation
IMAGE=${GENERALIZED_VERIFIER_IMAGE:-glm47-strange-multi-env:gcc13.3-v2}
if [[ -n "${GENERALIZED_VERIFIER_OUTPUT_DIR:-}" ]]; then
    OUT=$GENERALIZED_VERIFIER_OUTPUT_DIR
    mkdir -p "$OUT"
else
    OUT=$(mktemp -d "${TMPDIR:-/tmp}/generalized-verifier-sandbox.XXXXXX")
fi
if [[ -n "$(find "$OUT" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
    echo "error: output directory must be empty: $OUT" >&2
    exit 2
fi

IMAGE_ID=$(docker image inspect "$IMAGE" --format '{{.Id}}')
echo "[sandbox] image: $IMAGE"
echo "[sandbox] resolved immutable id: $IMAGE_ID"

chmod 0777 "$OUT"
CONTROLS='{"network":"none","read_only_root":true,"tmpfs_tmp":"rw,nosuid,nodev,exec,size=512m","cap_drop":"ALL","no_new_privileges":true,"user":"65534:65534","repo_mount":"/workspace:ro","writable_mount":"/out:rw","python_dont_write_bytecode":true}'

docker run --rm \
    --network none \
    --read-only \
    --tmpfs /tmp:rw,nosuid,nodev,exec,size=512m \
    --cap-drop ALL \
    --security-opt no-new-privileges \
    --user 65534:65534 \
    -e SANDBOX_INSIDE=1 \
    -e "SANDBOX_IMAGE=$IMAGE" \
    -e "SANDBOX_IMAGE_ID=$IMAGE_ID" \
    -e "SANDBOX_CONTROLS=$CONTROLS" \
    -e PYTHONDONTWRITEBYTECODE=1 \
    -v "$REPO:/workspace:ro" \
    -v "$OUT:/out:rw" \
    -w /workspace \
    "$IMAGE_ID" \
    python3 "$VAL/self_check.py" \
        --receipt-dir /out/receipts \
        --gen-dir /tmp/self_check_generated \
        --report /out/SELF_CHECK.md \
        --json-out /out/self_check_results.json \
        --sandbox-receipt /out/sandbox_run_receipt.json

echo "[sandbox] artifacts: $OUT"
echo "[sandbox] receipt: $OUT/sandbox_run_receipt.json"
