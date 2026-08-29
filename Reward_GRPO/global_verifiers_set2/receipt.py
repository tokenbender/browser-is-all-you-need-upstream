"""Structured, hashable verifier receipts shared by every Set 2 policy."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

Status = Literal["PASS", "FAIL", "INVALID", "NOT_RUN"]


@dataclass
class PolicyReceipt:
    policy: str
    status: Status
    reason: str
    facts: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)


@dataclass
class VerificationReceipt:
    schema_version: int
    task_id: str
    manifest_sha256: str
    candidate_sha256: str
    status: Status
    policies: list[PolicyReceipt]
    returned_files: list[str] = field(default_factory=list)
    inherited_files: list[str] = field(default_factory=list)
    format_valid: bool = True

    def payload(self) -> dict[str, Any]:
        return asdict(self)

    def write(self, path: Path) -> None:
        payload = self.payload()
        payload["receipt_sha256"] = receipt_sha256(payload)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def canonical_receipt(payload: dict[str, Any]) -> bytes:
    unsigned = {key: value for key, value in payload.items() if key != "receipt_sha256"}
    return json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()


def receipt_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_receipt(payload)).hexdigest()


def read_verified(path: Path) -> dict[str, Any]:
    """Read a disk receipt and authenticate its canonical digest."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("verification receipt must be an object")
    expected = payload.get("receipt_sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError("verification receipt lacks a valid digest")
    actual = receipt_sha256(payload)
    if actual != expected:
        raise ValueError("verification receipt digest mismatch")
    return payload


def policy(policy: str, status: Status, reason: str, **facts: Any) -> PolicyReceipt:
    return PolicyReceipt(policy=policy, status=status, reason=reason, facts=facts)
