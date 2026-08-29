#!/usr/bin/env bash
# run_sandboxed.sh -- execute the full check-layer validation suite INSIDE
# the pinned sandbox image, with controls mirroring the sandbox launcher:
#
#   --network none            no network
#   --read-only               read-only root filesystem
#   --tmpfs /tmp              scratch build space (explicit `exec` flag:
#                             dockerd mounts tmpfs noexec by default, and
#                             verifier 04 runs freshly built test binaries
#                             from TMPDIR)
#   --cap-drop ALL            no Linux capabilities
#   --security-opt no-new-privileges
#   --user 65534:65534        non-root (nobody/nogroup)
#   repo mounted read-only at /workspace; only /out is writable
#
# Produces generalized_verifier_docs/validation/sandbox_run_receipt.json
# (image id, controls, per-verifier verdicts, sha256 of inputs/outputs) --
# the end-to-end sandbox receipt. Artifacts stay in
# generalized_verifier_docs/validation/sandbox_out/.
set -u
cd "$(dirname "$0")/../.."   # repo root
REPO=$(pwd)
VAL=generalized_verifier_docs/validation
IMAGE=glm47-strange-multi-env:gcc13.3-v2
OUT=$REPO/$VAL/sandbox_out

IMAGE_ID=$(docker image inspect "$IMAGE" --format '{{.Id}}' 2>/dev/null) || {
    echo "error: cannot inspect image $IMAGE (docker unavailable?)" >&2
    exit 2
}
echo "[sandbox] image: $IMAGE"
echo "[sandbox] image id: $IMAGE_ID"

mkdir -p "$OUT"
chmod 777 "$OUT"   # container runs as nobody; /out must be writable
# Clear stale artifacts from a previous run (files are owned by the
# container's nobody uid, so the cleanup must happen container-side).
docker run --rm -v "$OUT:/out" "$IMAGE" sh -c 'rm -rf /out/receipts /out/sandbox_run_receipt.json /out/self_check_results.json /out/SELF_CHECK.sandbox.md'

CONTROLS='{"network":"none","read_only_root":true,"tmpfs_tmp":"rw,nosuid,nodev,exec,size=512m (exec required: verifier 04 runs freshly built test binaries from TMPDIR; dockerd mounts tmpfs noexec unless exec is explicit)","cap_drop":"ALL","no_new_privileges":true,"user":"65534:65534 (nobody)","repo_mount":"/workspace:ro","writable_mount":"/out:rw","python_dont_write_bytecode":true}'

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
    "$IMAGE" \
    python3 generalized_verifier_docs/validation/self_check.py \
        --receipt-dir /out/receipts \
        --gen-dir /tmp/self_check_generated \
        --report /out/SELF_CHECK.sandbox.md \
        --json-out /out/self_check_results.json \
        --sandbox-receipt /out/sandbox_run_receipt.json
rc=$?
echo "[sandbox] container exit: $rc"

if [ -f "$OUT/sandbox_run_receipt.json" ]; then
    cp "$OUT/sandbox_run_receipt.json" "$VAL/sandbox_run_receipt.json"
    echo "[sandbox] receipt: $VAL/sandbox_run_receipt.json"
else
    echo "[sandbox] WARNING: no sandbox receipt produced" >&2
    rc=1
fi
exit $rc
