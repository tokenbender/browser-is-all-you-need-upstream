"""Versioned MEF projection over the exact Hybrid45 V2 diagnostic receipt."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .hybrid45 import validate_hybrid45_receipt
from .schema import (
    HYBRID45_MEF_POLICY_VERSION,
    HYBRID45_POLICY_VERSION,
    Hybrid45Receipt,
    WEIGHTED45_CHECK_IDS,
)


CurriculumRole = Literal["ordinary", "repair", "calibration", "monitor"]


class MEF45Receipt(BaseModel):
    """Optimizer projection that preserves the complete V2 diagnostic receipt."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["hybrid45-mef-receipt-v1"] = "hybrid45-mef-receipt-v1"
    policy_version: Literal["hybrid-bipolar45-mef-v1"] = HYBRID45_MEF_POLICY_VERSION
    base_policy_version: Literal["hybrid-bipolar45-v2"] = HYBRID45_POLICY_VERSION
    curriculum_role: CurriculumRole
    base_receipt_sha256: str
    base_optimizer_score: float = Field(ge=-1.0, le=1.0)
    optimizer_score: float = Field(ge=-1.0, le=1.0)
    optimizer_override: Literal[
        "complete_pass",
        "calibration_exact_no_change",
        "calibration_unnecessary_change",
        "forbidden",
        "no_usable_payload",
        "ordinary_no_op",
        "syntax_failure",
        "api_failure",
        "link_failure",
        "warning_failure",
        "runtime_or_sanitizer_failure",
        "compile_failure",
        "zero_hidden_semantics",
        "partial_hidden_semantics",
        "base_projection",
    ]
    failure_mechanism: str | None = None
    primary_failure_kernel: str | None = None
    calibration_exact_no_change: bool = False
    strong_negative_syntax_api_link: Literal[True] = True
    repair_bonus: Literal[False] = False
    private_details_disclosed: Literal[False] = False

    @model_validator(mode="after")
    def _validate_receipt(self) -> "MEF45Receipt":
        if len(self.base_receipt_sha256) != 64 or any(
            character not in "0123456789abcdef"
            for character in self.base_receipt_sha256
        ):
            raise ValueError("MEF45 base receipt binding must be lowercase SHA-256")
        if not math.isfinite(self.base_optimizer_score) or not math.isfinite(
            self.optimizer_score
        ):
            raise ValueError("MEF45 scores must be finite")
        if self.calibration_exact_no_change != (
            self.optimizer_override == "calibration_exact_no_change"
        ):
            raise ValueError("MEF45 calibration no-change flag/override mismatch")
        if self.optimizer_override.startswith("calibration_") and self.curriculum_role != "calibration":
            raise ValueError("MEF45 calibration override requires calibration role")
        return self

    def to_record(self) -> dict[str, object]:
        return self.model_dump(mode="json")


def mef45_reward_contract_record() -> dict[str, object]:
    """Return immutable optimizer-facing policy metadata."""

    return {
        "policy": HYBRID45_MEF_POLICY_VERSION,
        "base_diagnostic_policy": HYBRID45_POLICY_VERSION,
        "activation_status": "ADMISSION_REQUIRED",
        "repair_bonus": False,
        "curriculum": {
            "ordinary_fraction": 0.75,
            "repair_fraction": 0.25,
            "repair_context": "failure_then_sanitized_feedback_then_repair",
        },
        "endpoint_scores": {
            "complete_pass": 1.0,
            "forbidden": -1.0,
            "no_usable_payload": -0.9,
            "ordinary_no_op": -0.35,
            "syntax_failure": -0.85,
            "api_failure": -0.8,
            "link_failure": -0.75,
            "warning_failure": -0.65,
            "runtime_or_sanitizer_failure": -0.7,
        },
        "calibration": {
            "exact_unchanged_and_full_hidden_pass": 1.0,
            "unnecessary_changed_payload": -0.35,
        },
        "infrastructure_failure": "MASK_AND_ABORT_BATCH",
        "private_feedback": "sanitized",
    }


def _base_sha256(base: Hybrid45Receipt) -> str:
    payload = json.dumps(
        base.to_record(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _calibration_exact_no_change(base: Hybrid45Receipt) -> bool:
    if base.checks["C3"] or base.optimizer_override != "no_op":
        return False
    return all(
        not base.applicable[check_id]
        or check_id == "C3"
        or (base.observed[check_id] and base.checks[check_id])
        for check_id in WEIGHTED45_CHECK_IDS
    )


def project_mef45(
    base: Hybrid45Receipt,
    curriculum_role: CurriculumRole,
) -> MEF45Receipt:
    """Deterministically project V2 diagnostics to the R7 optimizer scalar."""

    if base.infrastructure_error or base.optimizer_score is None:
        raise ValueError("MEF45 cannot project an infrastructure-masked V2 receipt")
    mechanism = base.failure_mechanism
    score: float
    override: str
    calibration_no_change = False
    if curriculum_role == "calibration" and _calibration_exact_no_change(base):
        score, override, calibration_no_change = 1.0, "calibration_exact_no_change", True
    elif curriculum_role == "calibration" and base.checks["C3"]:
        score, override = -0.35, "calibration_unnecessary_change"
    elif base.optimizer_override == "complete_pass":
        score, override = 1.0, "complete_pass"
    elif base.optimizer_override == "forbidden":
        score, override = -1.0, "forbidden"
    elif base.optimizer_override == "no_usable_payload":
        score, override = -0.9, "no_usable_payload"
    elif base.optimizer_override == "no_op":
        score, override = -0.35, "ordinary_no_op"
    elif mechanism == "candidate_syntax_failure" or base.primary_failure_kernel == "K3":
        score, override = -0.85, "syntax_failure"
    elif mechanism in {
        "public_api_signature_mismatch",
        "public_symbol_missing",
        "missing_include_or_type",
    } or base.primary_failure_kernel == "K2":
        score, override = -0.8, "api_failure"
    elif mechanism == "linkage_failure" or base.primary_failure_kernel in {"K1", "K5"}:
        score, override = -0.75, "link_failure"
    elif mechanism == "warning_clean_compile_failure" or base.primary_failure_kernel == "K4":
        score, override = -0.65, "warning_failure"
    elif mechanism in {
        "sanitizer_failure",
        "candidate_inner_timeout",
        "runtime_failure",
    } or base.optimizer_override == "runtime_or_sanitizer":
        score, override = -0.7, "runtime_or_sanitizer_failure"
    elif base.failure_stage == "compilation":
        score, override = -0.7, "compile_failure"
    elif base.semantic_applicable and base.hidden_partitions_passed == 0:
        score, override = -0.7, "zero_hidden_semantics"
    elif base.semantic_applicable and 0 < base.hidden_partitions_passed < 5:
        score = max(-0.25, min(0.75, float(base.optimizer_score)))
        override = "partial_hidden_semantics"
    else:
        score, override = float(base.optimizer_score), "base_projection"
    return MEF45Receipt(
        curriculum_role=curriculum_role,
        base_receipt_sha256=_base_sha256(base),
        base_optimizer_score=float(base.optimizer_score),
        optimizer_score=round(score, 10),
        optimizer_override=override,
        failure_mechanism=mechanism,
        primary_failure_kernel=base.primary_failure_kernel,
        calibration_exact_no_change=calibration_no_change,
    )


def validate_mef45_receipt(
    record: Mapping[str, object],
    base_record: Mapping[str, object],
) -> MEF45Receipt:
    """Validate both the exact V2 receipt and deterministic MEF projection."""

    base = validate_hybrid45_receipt(base_record)
    receipt = MEF45Receipt.model_validate(record)
    expected = project_mef45(base, receipt.curriculum_role)
    if receipt.model_dump(mode="json") != expected.model_dump(mode="json"):
        raise ValueError("MEF45 receipt does not match deterministic recomputation")
    return receipt
