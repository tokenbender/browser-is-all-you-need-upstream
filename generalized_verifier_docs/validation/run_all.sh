#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."
VAL=generalized_verifier_docs/validation
if [[ -n "${GENERALIZED_VERIFIER_OUTPUT_DIR:-}" ]]; then
    OUT=$GENERALIZED_VERIFIER_OUTPUT_DIR
    mkdir -p "$OUT"
else
    OUT=$(mktemp -d "${TMPDIR:-/tmp}/generalized-verifier-host.XXXXXX")
fi

python3 "$VAL/self_check.py" \
    --receipt-dir "$OUT/receipts" \
    --gen-dir "$OUT/generated" \
    --report "$OUT/SELF_CHECK.md" \
    --json-out "$OUT/self_check_results.json"

echo "[self-check] artifacts: $OUT"
