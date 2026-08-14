"""Observation-aware Hybrid45 V2 projection for Aider C++ rewards.

Weighted45 V1 remains in policy45.py.  This module deliberately treats
unreached and non-applicable kernels as diagnostic values outside the binary
optimizer denominator, while retaining an exact signed 45-kernel vector.
"""

from __future__ import annotations

import math
from pathlib import Path
import re
from typing import Mapping

from .parser import AiderResponseError, ParsedAiderResponse
from .policy45 import evaluate_response_checks
from .schema import (
    AiderPolyglotTask,
    HYBRID45_POLICY_VERSION,
    HYBRID45_STAGE_SCORES,
    Hybrid45Receipt,
    Hybrid45RepairTelemetry,
    WEIGHTED45_CHECK_IDS,
    WEIGHTED45_HARNESS_CHECK_IDS,
    WEIGHTED45_TIER_CHECKS,
)


HYBRID45_TIER_WEIGHTS: dict[str, float] = {
    "forbidden_file_bypass": 0.15,
    "clarification_no_file": 0.05,
    "fatal_parse_failure": 0.05,
    "wrong_file_label": 0.10,
    "duplicate_file": 0.05,
    "compilation": 0.20,
    "runtime": 0.10,
    "hidden_tests": 0.20,
    "full_pass": 0.10,
}
HYBRID45_BINARY_WEIGHT = 0.50
HYBRID45_DISCRETE_WEIGHT = 0.20
HYBRID45_SEMANTIC_WEIGHT = 0.30
HYBRID45_TIER_ORDER = tuple(WEIGHTED45_TIER_CHECKS)
HYBRID45_COMPILATION_CAUSAL_ORDER = ("K3", "K2", "K4", "K1", "K5")
HYBRID45_HIDDEN_IDS = tuple(f"H{index}" for index in range(1, 6))
HYBRID45_REQUIRED_PAYLOAD_IDS = ("C1", "C2", "C3", "C4", "C5", "P5", "L5")
_PRIVATE_PATH_RE = re.compile(
    r"(?:^|\s)(?:/[A-Za-z0-9_.-]+)+|(?:\.grader|\.reference)(?:/[^\s:]*)?"
)


def hybrid45_reward_contract_record() -> dict[str, object]:
    """Return immutable V2 manifest metadata without implying admission."""

    return {
        "policy": HYBRID45_POLICY_VERSION,
        "activation_status": "NOT_ADMITTED",
        "tiers": 9,
        "checks_per_tier": 5,
        "total_checks": 45,
        "kernel_values": [-1, 1],
        "tier_formula": "sum(applicable*observed*kernel)/sum(applicable*observed)",
        "empty_tier_contribution": 0.0,
        "tier_weights": dict(HYBRID45_TIER_WEIGHTS),
        "projection": {
            "binary": HYBRID45_BINARY_WEIGHT,
            "discrete": HYBRID45_DISCRETE_WEIGHT,
            "continuous_semantic": HYBRID45_SEMANTIC_WEIGHT,
        },
        "hidden_suite_partitions": 5,
        "infrastructure_failure": "MASK_AND_ABORT_BATCH",
        "repair_bonus": False,
    }


def evaluate_hybrid45_response_checks(
    task: AiderPolyglotTask,
    exercise_dir: Path,
    response: str,
    *,
    parsed: ParsedAiderResponse | None,
    parse_error: AiderResponseError | None,
) -> tuple[dict[str, bool], dict[str, str]]:
    """Evaluate the static V2 contract without changing Weighted45 V1.

    V2 requires complete replacements for every declared editable file and a
    non-empty production delta from the digest-bound starter state.
    """

    checks, evidence = evaluate_response_checks(
        task,
        exercise_dir,
        response,
        parsed=parsed,
        parse_error=parse_error,
    )
    if parsed is None or set(parsed.files) != set(task.editable_files):
        checks["C3"] = False
        evidence["C3"] = "complete substantive production delta unavailable"
        return checks, evidence

    changed_files: list[str] = []
    for name in task.editable_files:
        starter = exercise_dir / name
        if not starter.is_file() or starter.read_text(encoding="utf-8") != parsed.files[name]:
            changed_files.append(name)
    checks["C3"] = checks["C3"] and bool(changed_files)
    evidence["C3"] = (
        f"substantive changed production files={sorted(changed_files)}"
        if checks["C3"]
        else "no substantive production delta from starter"
    )
    return checks, evidence


def derive_hybrid45_observation(
    checks: Mapping[str, bool],
    evidence: Mapping[str, str],
) -> tuple[dict[str, bool], dict[str, bool], dict[str, str]]:
    """Derive observation/applicability from explicit harness stage evidence."""

    _require_exact_check_map("checks", checks)
    _require_exact_check_map("evidence", evidence)
    observed = {check_id: True for check_id in WEIGHTED45_CHECK_IDS}
    applicable = {check_id: True for check_id in WEIGHTED45_CHECK_IDS}
    compact_evidence: dict[str, str] = {}
    for check_id in WEIGHTED45_CHECK_IDS:
        value = str(evidence[check_id]).strip()
        lowered = value.lower()
        if check_id in WEIGHTED45_HARNESS_CHECK_IDS and (
            lowered.startswith("stage not reached")
            or lowered.startswith("not executed:")
        ):
            observed[check_id] = False
        if check_id == "A4" and lowered.startswith("not applicable:"):
            applicable[check_id] = False
        compact_evidence[check_id] = _compact_evidence(value)
    return observed, applicable, compact_evidence


def score_hybrid45(
    checks: Mapping[str, bool],
    evidence: Mapping[str, str],
    observed: Mapping[str, bool],
    applicable: Mapping[str, bool],
    *,
    failure_mechanism: str | None = None,
) -> Hybrid45Receipt:
    """Project the exact diagnostic contract to one bounded optimizer scalar."""

    for name, values in (
        ("checks", checks),
        ("evidence", evidence),
        ("observed", observed),
        ("applicable", applicable),
    ):
        _require_exact_check_map(name, values)
    if any(not isinstance(value, bool) for value in checks.values()):
        raise TypeError("hybrid45 outcomes must be booleans")
    if any(not isinstance(value, bool) for value in observed.values()):
        raise TypeError("hybrid45 observation values must be booleans")
    if any(not isinstance(value, bool) for value in applicable.values()):
        raise TypeError("hybrid45 applicability values must be booleans")

    checks_dict = dict(checks)
    observed_dict = dict(observed)
    applicable_dict = dict(applicable)
    evidence_dict = {check_id: _compact_evidence(str(evidence[check_id])) for check_id in checks}
    kernels = {
        check_id: 1 if checks_dict[check_id] else -1 for check_id in WEIGHTED45_CHECK_IDS
    }
    primary = _primary_failure(checks_dict, observed_dict, applicable_dict)
    not_reached = sorted(
        check_id for check_id in WEIGHTED45_CHECK_IDS if not observed_dict[check_id]
    )
    if not_reached:
        cause = primary or "upstream stage"
        for check_id in not_reached:
            evidence_dict[check_id] = f"not reached because {cause} failed"

    pass_counts: dict[str, int] = {}
    eligible_counts: dict[str, int] = {}
    tier_scores: dict[str, float] = {}
    contributions: dict[str, float] = {}
    for tier, check_ids in WEIGHTED45_TIER_CHECKS.items():
        eligible = [
            check_id
            for check_id in check_ids
            if observed_dict[check_id] and applicable_dict[check_id]
        ]
        pass_counts[tier] = sum(checks_dict[check_id] for check_id in check_ids)
        eligible_counts[tier] = len(eligible)
        tier_score = (
            math.fsum(kernels[check_id] for check_id in eligible) / len(eligible)
            if eligible
            else 0.0
        )
        tier_scores[tier] = round(tier_score, 10)
        contributions[tier] = round(tier_score * HYBRID45_TIER_WEIGHTS[tier], 10)
    binary_score = round(math.fsum(contributions.values()), 10)

    semantic_applicable = all(observed_dict[check_id] for check_id in HYBRID45_HIDDEN_IDS)
    hidden_passed = sum(checks_dict[check_id] for check_id in HYBRID45_HIDDEN_IDS)
    continuous = (
        round(2.0 * hidden_passed / len(HYBRID45_HIDDEN_IDS) - 1.0, 10)
        if semantic_applicable
        else 0.0
    )
    complete = all(
        not applicable_dict[check_id]
        or (observed_dict[check_id] and checks_dict[check_id])
        for check_id in WEIGHTED45_CHECK_IDS
    )
    stage, stage_reason = _reachability(
        checks_dict,
        observed_dict,
        applicable_dict,
        complete=complete,
    )
    discrete = HYBRID45_STAGE_SCORES[stage]
    mixed = round(
        HYBRID45_BINARY_WEIGHT * binary_score
        + HYBRID45_DISCRETE_WEIGHT * discrete
        + HYBRID45_SEMANTIC_WEIGHT * continuous,
        10,
    )
    optimizer_score, override = _apply_override(
        mixed,
        checks_dict,
        observed_dict,
        applicable_dict,
        complete=complete,
    )
    consequence = _consequence_kernels(primary, checks_dict, observed_dict)
    mechanism = failure_mechanism or _default_failure_mechanism(primary)
    failure_stage = _failure_stage(primary)
    return Hybrid45Receipt(
        checks=checks_dict,
        kernels=kernels,
        observed=observed_dict,
        applicable=applicable_dict,
        evidence=evidence_dict,
        tier_pass_counts=pass_counts,
        tier_observed_applicable_counts=eligible_counts,
        tier_binary_scores=tier_scores,
        weighted_binary_contributions=contributions,
        binary_score=binary_score,
        reachability_stage=stage,
        reachability_reason=stage_reason,
        discrete_score=discrete,
        semantic_applicable=semantic_applicable,
        hidden_partitions_passed=hidden_passed,
        continuous_semantic_score=continuous,
        mixed_score=mixed,
        optimizer_score=round(optimizer_score, 10),
        optimizer_override=override,
        primary_failure_kernel=primary,
        failure_mechanism=mechanism,
        failure_stage=failure_stage,
        consequence_kernels=consequence,
        not_reached_kernels=not_reached,
        infrastructure_error=False,
    )


def validate_hybrid45_receipt(record: Mapping[str, object]) -> Hybrid45Receipt:
    """Reject incomplete or arithmetically inconsistent V2 receipts."""

    parsed = Hybrid45Receipt.model_validate(record)
    recomputed = score_hybrid45(
        parsed.checks,
        parsed.evidence,
        parsed.observed,
        parsed.applicable,
        failure_mechanism=parsed.failure_mechanism,
    )
    expected = recomputed.model_dump(mode="json", exclude={"repair"})
    actual = parsed.model_dump(mode="json", exclude={"repair"})
    if actual != expected:
        raise ValueError("hybrid45 receipt does not match deterministic recomputation")
    return parsed


def build_repair_telemetry(
    previous: Hybrid45Receipt,
    current: Hybrid45Receipt,
    *,
    attempt: int = 2,
    previous_response_sha256: str | None = None,
    feedback_sha256: str | None = None,
) -> Hybrid45RepairTelemetry:
    """Describe a repair transition without modifying either optimizer score."""

    flips = [
        f"{check_id}:{previous.kernels[check_id]:+d}->{current.kernels[check_id]:+d}"
        for check_id in sorted(WEIGHTED45_CHECK_IDS)
        if previous.kernels[check_id] != current.kernels[check_id]
    ]
    assert previous.optimizer_score is not None and current.optimizer_score is not None
    return Hybrid45RepairTelemetry(
        attempt=attempt,
        previous_response_sha256=previous_response_sha256,
        feedback_sha256=feedback_sha256,
        previous_optimizer_score=previous.optimizer_score,
        optimizer_score=current.optimizer_score,
        reward_delta=round(current.optimizer_score - previous.optimizer_score, 10),
        kernel_flips=flips,
        stage_before=previous.reachability_stage,
        stage_after=current.reachability_stage,
    )


def _require_exact_check_map(name: str, values: Mapping[str, object]) -> None:
    observed_ids = set(values)
    if observed_ids != WEIGHTED45_CHECK_IDS:
        missing = sorted(WEIGHTED45_CHECK_IDS - observed_ids)
        extra = sorted(observed_ids - WEIGHTED45_CHECK_IDS)
        raise ValueError(f"hybrid45 {name} contract mismatch: missing={missing} extra={extra}")


def _primary_failure(
    checks: Mapping[str, bool],
    observed: Mapping[str, bool],
    applicable: Mapping[str, bool],
) -> str | None:
    for tier, check_ids in WEIGHTED45_TIER_CHECKS.items():
        ordered = (
            HYBRID45_COMPILATION_CAUSAL_ORDER if tier == "compilation" else check_ids
        )
        for check_id in ordered:
            if (
                observed[check_id]
                and applicable[check_id]
                and not checks[check_id]
            ):
                return check_id
    return None


def _reachability(
    checks: Mapping[str, bool],
    observed: Mapping[str, bool],
    applicable: Mapping[str, bool],
    *,
    complete: bool,
) -> tuple[int, str]:
    del applicable
    if any(not checks[f"F{index}"] for index in range(1, 6)):
        return 0, "unsafe, escaped, bypassed, or spoofed output"
    if not all(checks[check_id] for check_id in HYBRID45_REQUIRED_PAYLOAD_IDS):
        return 0, "no complete usable production-file payload"
    if not any(observed[check_id] for check_id in HYBRID45_COMPILATION_CAUSAL_ORDER):
        return 1, "parseable, scope-valid complete files; compilation not reached"
    if not checks["K4"]:
        return 2, "candidate syntax/API compilation reached but strict compilation failed"
    if not (checks["K1"] and checks["K5"]):
        return 3, "strict compilation passed; linkage or executable creation failed"
    runtime_ids = ("R1", "R2", "R3", "R4", "R5", "A3")
    if not all(observed[check_id] and checks[check_id] for check_id in runtime_ids):
        return 4, "linked executable exists; bounded safe runtime did not pass"
    hidden_passed = sum(checks[check_id] for check_id in HYBRID45_HIDDEN_IDS)
    if hidden_passed == 0:
        return 5, "safe bounded runtime reached; no hidden partition passed"
    if hidden_passed < len(HYBRID45_HIDDEN_IDS):
        return 6, "safe runtime and at least one hidden partition passed"
    if complete:
        return 8, "complete functional, safety, and verification pass"
    return 7, "all hidden partitions passed; complete safety verification remains"


def _apply_override(
    mixed: float,
    checks: Mapping[str, bool],
    observed: Mapping[str, bool],
    applicable: Mapping[str, bool],
    *,
    complete: bool,
) -> tuple[float, str]:
    if any(not checks[f"F{index}"] for index in range(1, 6)):
        return -1.0, "forbidden"
    if not all(checks[check_id] for check_id in ("C1", "C2", "P5", "L5")):
        return min(mixed, -0.75), "no_usable_payload"
    if not checks["C3"]:
        return min(mixed, 0.0), "no_op"
    runtime_failure_ids = (
        "R1",
        "R2",
        "R3",
        "R4",
        "R5",
        "A2",
        "A3",
        "A4",
        "A5",
    )
    if any(
        observed[check_id]
        and applicable[check_id]
        and not checks[check_id]
        for check_id in runtime_failure_ids
    ):
        return min(mixed, -0.50), "runtime_or_sanitizer"
    if any(
        observed[check_id] and not checks[check_id]
        for check_id in HYBRID45_COMPILATION_CAUSAL_ORDER
    ):
        return min(mixed, 0.0), "compile_or_link"
    if complete:
        return 1.0, "complete_pass"
    return mixed, "none"


def _consequence_kernels(
    primary: str | None,
    checks: Mapping[str, bool],
    observed: Mapping[str, bool],
) -> list[str]:
    if primary not in HYBRID45_COMPILATION_CAUSAL_ORDER:
        return []
    start = HYBRID45_COMPILATION_CAUSAL_ORDER.index(primary) + 1
    return [
        check_id
        for check_id in HYBRID45_COMPILATION_CAUSAL_ORDER[start:]
        if observed[check_id] and not checks[check_id]
    ]


def _failure_stage(primary: str | None) -> str | None:
    if primary is None:
        return None
    return {
        "F": "safety",
        "C": "payload",
        "P": "parsing",
        "L": "file_api_integrity",
        "D": "duplication",
        "K": "compilation",
        "R": "runtime",
        "H": "hidden_semantics",
        "A": "full_verification",
    }[primary[0]]


def _default_failure_mechanism(primary: str | None) -> str | None:
    if primary is None:
        return None
    return {
        "C1": "no_file_payload",
        "C2": "incomplete_editable_file_set",
        "C3": "no_substantive_production_delta",
        "K1": "linkage_failure",
        "K2": "public_api_signature_mismatch",
        "K3": "candidate_syntax_failure",
        "K4": "warning_clean_compile_failure",
        "K5": "executable_creation_failure",
        "A2": "sanitizer_failure",
        "A4": "concurrency_sanitizer_failure",
        "A5": "nondeterministic_verification",
    }.get(primary, f"{_failure_stage(primary)}_failure")


def _compact_evidence(value: str) -> str:
    compact = " ".join(value.split())
    lowered = compact.lower()
    if "build failed:" in lowered:
        compact = compact.split(":", 1)[0]
    compact = _PRIVATE_PATH_RE.sub(" <private-path>", compact)
    return compact[:500] or "no public evidence text"
