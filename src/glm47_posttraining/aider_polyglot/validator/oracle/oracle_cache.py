"""Content-addressed cache for successful oracle certification receipts."""

from __future__ import annotations

import json
from pathlib import Path

from .oracle_receipt import (
    ORACLE_VALIDATOR_VERSION,
    OracleCertificationReceipt,
    assert_receipt_integrity,
    canonical_sha256,
)


def oracle_cache_key(receipt: OracleCertificationReceipt) -> str:
    return canonical_sha256(
        {
            "validator_version": ORACLE_VALIDATOR_VERSION,
            "task_id": receipt.task_id,
            "config_sha256": receipt.config_sha256,
            "input_binding": receipt.input_binding.model_dump(mode="json"),
            "environment": receipt.environment.model_dump(mode="json"),
        }
    )


class OracleReceiptCache:
    """Store only integrity-checked, certified receipts under their input key."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def load(self, key: str, *, task_id: str) -> OracleCertificationReceipt | None:
        path = self.root / f"{key}.json"
        if not path.is_file() or path.is_symlink():
            return None
        receipt = OracleCertificationReceipt.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        assert_receipt_integrity(receipt)
        if receipt.status != "certified" or receipt.task_id != task_id:
            return None
        if oracle_cache_key(receipt) != key:
            return None
        return receipt

    def store(self, receipt: OracleCertificationReceipt) -> Path:
        assert_receipt_integrity(receipt)
        if receipt.status != "certified":
            raise ValueError("refusing to cache a rejected oracle receipt")
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise ValueError(f"oracle cache must not be a symlink: {self.root}")
        key = oracle_cache_key(receipt)
        output = self.root / f"{key}.json"
        temporary = output.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(receipt.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(output)
        return output


__all__ = ["OracleReceiptCache", "oracle_cache_key"]
