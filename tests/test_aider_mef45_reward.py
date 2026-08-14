from __future__ import annotations

import math

import pytest

from glm47_posttraining.aider_polyglot.hybrid45 import score_hybrid45
from glm47_posttraining.aider_polyglot.mef45 import (
    mef45_reward_contract_record,
    project_mef45,
    validate_mef45_receipt,
)
from glm47_posttraining.aider_polyglot.schema import (
    WEIGHTED45_CHECK_IDS,
    WEIGHTED45_TIER_CHECKS,
)


def _base(
    *,
    failed: tuple[str, ...] = (),
    mechanism: str | None = None,
):
    checks = {check_id: check_id not in failed for check_id in WEIGHTED45_CHECK_IDS}
    observed = {check_id: True for check_id in WEIGHTED45_CHECK_IDS}
    applicable = {check_id: True for check_id in WEIGHTED45_CHECK_IDS}
    evidence = {
        check_id: "pass" if checks[check_id] else "deterministic public failure"
        for check_id in WEIGHTED45_CHECK_IDS
    }
    return score_hybrid45(
        checks,
        evidence,
        observed,
        applicable,
        failure_mechanism=mechanism,
    )


@pytest.mark.parametrize(
    ("failed", "mechanism", "expected", "override"),
    [
        (("F1",), "protected_scope_escape_bypass_or_spoofing", -1.0, "forbidden"),
        (("C1",), "no_file_payload", -0.9, "no_usable_payload"),
        (("C3",), "no_substantive_production_delta", -0.35, "ordinary_no_op"),
        (("K3",), "candidate_syntax_failure", -0.85, "syntax_failure"),
        (("K2",), "public_api_signature_mismatch", -0.8, "api_failure"),
        (("K1",), "linkage_failure", -0.75, "link_failure"),
        (("K4",), "warning_clean_compile_failure", -0.65, "warning_failure"),
        (("R1",), "runtime_failure", -0.7, "runtime_or_sanitizer_failure"),
    ],
)
def test_mef45_strong_failure_projection(
    failed: tuple[str, ...],
    mechanism: str,
    expected: float,
    override: str,
) -> None:
    receipt = project_mef45(_base(failed=failed, mechanism=mechanism), "ordinary")
    assert receipt.optimizer_score == expected
    assert receipt.optimizer_override == override
    assert receipt.repair_bonus is False
    assert receipt.private_details_disclosed is False


def test_mef45_complete_pass_has_no_repair_bonus() -> None:
    ordinary = project_mef45(_base(), "ordinary")
    repair = project_mef45(_base(), "repair")
    assert ordinary.optimizer_score == repair.optimizer_score == 1.0
    assert ordinary.optimizer_override == repair.optimizer_override == "complete_pass"


def test_mef45_calibration_exact_no_change_is_positive_control() -> None:
    no_change = project_mef45(
        _base(failed=("C3",), mechanism="no_substantive_production_delta"),
        "calibration",
    )
    changed = project_mef45(_base(), "calibration")
    assert no_change.optimizer_score == 1.0
    assert no_change.optimizer_override == "calibration_exact_no_change"
    assert no_change.calibration_exact_no_change is True
    assert changed.optimizer_score == -0.35
    assert changed.optimizer_override == "calibration_unnecessary_change"


def test_mef45_receipt_recomputes_and_rejects_score_tampering() -> None:
    base = _base(failed=("K3",), mechanism="candidate_syntax_failure")
    projected = project_mef45(base, "repair")
    validated = validate_mef45_receipt(projected.to_record(), base.to_record())
    assert validated == projected
    tampered = projected.to_record()
    tampered["optimizer_score"] = -0.1
    with pytest.raises(ValueError, match="deterministic recomputation"):
        validate_mef45_receipt(tampered, base.to_record())


def test_mef45_policy_record_is_exact_and_bounded() -> None:
    record = mef45_reward_contract_record()
    assert record["policy"] == "hybrid-bipolar45-mef-v1"
    assert record["base_diagnostic_policy"] == "hybrid-bipolar45-v2"
    assert record["repair_bonus"] is False
    assert record["curriculum"]["ordinary_fraction"] == 0.75
    assert record["curriculum"]["repair_fraction"] == 0.25
    assert record["endpoint_scores"]["syntax_failure"] == -0.85
    assert record["endpoint_scores"]["api_failure"] == -0.8
    assert record["endpoint_scores"]["link_failure"] == -0.75
    assert all(
        math.isfinite(value) and -1.0 <= value <= 1.0
        for value in record["endpoint_scores"].values()
    )
    assert sum(len(values) for values in WEIGHTED45_TIER_CHECKS.values()) == 45
