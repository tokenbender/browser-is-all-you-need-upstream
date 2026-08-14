"""Aggregate and persist deterministic oracle-certification evidence."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from .oracle_receipt import OracleCertificationReceipt, assert_receipt_integrity, canonical_sha256


class OracleCertificationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    kind: Literal["glm47-aider-oracle-certification-report"] = (
        "glm47-aider-oracle-certification-report"
    )
    status: Literal["certified", "rejected"]
    task_count: int
    certified_count: int
    rejected_count: int
    failed_rule_counts: dict[str, int]
    receipt_sha256: dict[str, str]
    report_sha256: str


def build_oracle_certification_report(
    receipts: list[OracleCertificationReceipt],
) -> OracleCertificationReport:
    for receipt in receipts:
        assert_receipt_integrity(receipt)
    failed_rules = Counter(
        rule_id for receipt in receipts for rule_id in receipt.failed_rule_ids
    )
    certified_count = sum(receipt.status == "certified" for receipt in receipts)
    payload = {
        "schema_version": 1,
        "kind": "glm47-aider-oracle-certification-report",
        "status": "certified" if certified_count == len(receipts) else "rejected",
        "task_count": len(receipts),
        "certified_count": certified_count,
        "rejected_count": len(receipts) - certified_count,
        "failed_rule_counts": dict(sorted(failed_rules.items())),
        "receipt_sha256": {
            receipt.task_id: receipt.certification_sha256
            for receipt in sorted(receipts, key=lambda item: item.task_id)
        },
    }
    return OracleCertificationReport(**payload, report_sha256=canonical_sha256(payload))


def write_oracle_certification_report(
    output_dir: str | Path, receipts: list[OracleCertificationReceipt]
) -> OracleCertificationReport:
    root = Path(output_dir)
    receipt_dir = root / "receipts"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    for receipt in sorted(receipts, key=lambda item: item.task_id):
        assert_receipt_integrity(receipt)
        slug = receipt.task_id.rsplit("/", 1)[-1]
        (receipt_dir / f"{slug}.json").write_text(
            json.dumps(receipt.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    report = build_oracle_certification_report(receipts)
    (root / "report.json").write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


__all__ = [
    "OracleCertificationReport",
    "build_oracle_certification_report",
    "write_oracle_certification_report",
]
