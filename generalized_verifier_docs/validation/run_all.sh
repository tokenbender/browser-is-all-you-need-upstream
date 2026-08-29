#!/usr/bin/env bash
# Run the full three-control self-validation matrix (6 verifiers x
# positive/fault/tamper) on the host. Emits validation/SELF_CHECK.md,
# per-case kernel receipts under validation/self_check_receipts/, and
# machine-readable results at validation/self_check_results.json.
set -u
cd "$(dirname "$0")/../.."   # repo root
VAL=generalized_verifier_docs/validation

python3 "$VAL/self_check.py" \
    --json-out "$VAL/self_check_results.json" "$@"
