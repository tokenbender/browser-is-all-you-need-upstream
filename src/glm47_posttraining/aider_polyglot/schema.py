"""Persistent task and result models for Aider Polyglot C++ RL."""

from __future__ import annotations

import json
import math
from pathlib import Path, PurePath
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)


WEIGHTED45_TIER_CHECKS: dict[str, tuple[str, ...]] = {
    "forbidden_file_bypass": ("F1", "F2", "F3", "F4", "F5"),
    "clarification_no_file": ("C1", "C2", "C3", "C4", "C5"),
    "fatal_parse_failure": ("P1", "P2", "P3", "P4", "P5"),
    "wrong_file_label": ("L1", "L2", "L3", "L4", "L5"),
    "duplicate_file": ("D1", "D2", "D3", "D4", "D5"),
    "compilation": ("K1", "K2", "K3", "K4", "K5"),
    "runtime": ("R1", "R2", "R3", "R4", "R5"),
    "hidden_tests": ("H1", "H2", "H3", "H4", "H5"),
    "full_pass": ("A1", "A2", "A3", "A4", "A5"),
}
WEIGHTED45_CHECK_IDS = frozenset(
    check_id for check_ids in WEIGHTED45_TIER_CHECKS.values() for check_id in check_ids
)
WEIGHTED45_HARNESS_CHECK_IDS = frozenset(
    check_id
    for tier in ("compilation", "runtime", "hidden_tests", "full_pass")
    for check_id in WEIGHTED45_TIER_CHECKS[tier]
)
HYBRID45_POLICY_VERSION = "hybrid-bipolar45-v2"
HYBRID45_MEF_POLICY_VERSION = "hybrid-bipolar45-mef-v1"
HYBRID45_STAGE_SCORES: dict[int, float] = {
    0: -1.00,
    1: -0.75,
    2: -0.50,
    3: -0.25,
    4: 0.00,
    5: 0.25,
    6: 0.50,
    7: 0.75,
    8: 1.00,
}


class AiderChatMessage(BaseModel):
    """One turn of the exact chat aider sends to the model."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant"]
    content: str


class AiderPolyglotTask(BaseModel):
    """One relocatable shadow-training or official-evaluation C++ task."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    task_id: str
    exercise: str
    language: Literal["cpp"] = "cpp"
    split: Literal["train", "validation"]
    harness_kind: Literal["shadow_cpp17", "aider_cpp17", "official_cmake"]
    exercise_dir: str
    editable_files: list[str]
    prompt: list[AiderChatMessage]
    source_revision: str | None = None
    family: str | None = None
    category: str | None = None
    tags: list[str] = Field(default_factory=list)
    hidden_test_sha256: str | None = None
    source_prompt_sha256: str | None = None
    verification_gate: str | None = None
    prompt_contract: Literal[
        "aider-eval-wholefile-v1",
        "sft-v5-user-v1",
        "hybrid45-isolated-wholefile-v2",
    ] = (
        "aider-eval-wholefile-v1"
    )
    response_contract: Literal["aider-whole-file-v1"] = "aider-whole-file-v1"
    reward_contract: Literal[
        "binary-semantic-v1",
        "ordinal-partial-v1",
        "dense-semantic-v2",
        "weighted45-v1",
        "hybrid-bipolar45-v2",
        "hybrid-bipolar45-mef-v1",
    ] = "ordinal-partial-v1"

    @field_validator("prompt")
    @classmethod
    def _validate_prompt(cls, messages: list[AiderChatMessage]) -> list[AiderChatMessage]:
        if not messages or messages[-1].role != "user":
            raise ValueError("prompt must be a non-empty chat ending with a user turn")
        return messages

    @field_validator("editable_files")
    @classmethod
    def _validate_editable_files(cls, names: list[str]) -> list[str]:
        if not names:
            raise ValueError("Aider task requires at least one editable file")
        if len(set(names)) != len(names):
            raise ValueError("editable file names must be unique")
        for name in names:
            path = PurePath(name)
            if path.is_absolute() or len(path.parts) != 1 or name in {".", ".."}:
                raise ValueError(f"unsafe editable file name: {name}")
            if not name.endswith((".cpp", ".h", ".hpp", ".cc")):
                raise ValueError(f"unsupported editable file: {name}")
        return names

    @field_validator("exercise_dir")
    @classmethod
    def _validate_exercise_dir(cls, value: str) -> str:
        path = PurePath(value)
        if path.is_absolute() or not path.parts or ".." in path.parts:
            raise ValueError(f"unsafe exercise directory: {value}")
        return value

    @classmethod
    def read_json(cls, path: str | Path) -> "AiderPolyglotTask":
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))

    def write_json(self, path: str | Path) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(self.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return output


class AiderTestResult(BaseModel):
    """Outcome of applying a whole-file response and running the official tests."""

    status: Literal[
        "passed",
        "tests_failed",
        "compile_failed",
        "candidate_timeout",
        "infrastructure_error",
    ]
    tests_passed: int = Field(default=0, ge=0)
    tests_total: int = Field(default=0, ge=0)
    candidate_returncode: int | None = None
    logs: dict[str, str] = Field(default_factory=dict)
    weighted45_checks: dict[str, bool] = Field(default_factory=dict)
    weighted45_evidence: dict[str, str] = Field(default_factory=dict)
    verification_workspace_id: str | None = None

    @model_validator(mode="after")
    def _validate_weighted45_contract(self) -> "AiderTestResult":
        if not self.weighted45_checks:
            if self.weighted45_evidence:
                raise ValueError("weighted45 evidence requires weighted45 check outcomes")
            return self
        observed = set(self.weighted45_checks)
        if observed != WEIGHTED45_HARNESS_CHECK_IDS:
            missing = sorted(WEIGHTED45_HARNESS_CHECK_IDS - observed)
            extra = sorted(observed - WEIGHTED45_HARNESS_CHECK_IDS)
            raise ValueError(
                f"weighted45 harness contract mismatch: missing={missing} extra={extra}"
            )
        unknown_evidence = set(self.weighted45_evidence) - observed
        if unknown_evidence:
            raise ValueError(
                f"weighted45 evidence has unknown checks: {sorted(unknown_evidence)}"
            )
        return self

    @property
    def all_tests_pass(self) -> bool:
        return (
            self.status == "passed"
            and self.tests_total > 0
            and self.tests_passed == self.tests_total
        )

    @property
    def fraction_tests_passed(self) -> float:
        if self.tests_total <= 0:
            return 0.0
        return self.tests_passed / self.tests_total

    def to_json(self) -> str:
        return json.dumps(self.model_dump(), indent=2, sort_keys=True)


class AiderShadowRubric(BaseModel):
    """Checked-in, answer-free contract for one shadow training exercise."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2] = 2
    task_id: str
    language: Literal["cpp"] = "cpp"
    editable_files: list[str]
    hidden_test_file: str
    hidden_test_sha256: str
    source_prompt_sha256: str
    reference_answer_packaged: Literal[True]
    reference_answer_model_facing: Literal[False]
    verification_stage: Literal["passed"]
    verification_gate: str
    family: str
    category: str
    tags: list[str] = Field(default_factory=list)
    lineage: str | None = None

    @field_validator("editable_files")
    @classmethod
    def _validate_editables(cls, names: list[str]) -> list[str]:
        return AiderPolyglotTask._validate_editable_files(names)

    @field_validator("hidden_test_file")
    @classmethod
    def _validate_hidden_test(cls, name: str) -> str:
        path = PurePath(name)
        if path.is_absolute() or len(path.parts) != 1 or not name.endswith("_test.cpp"):
            raise ValueError(f"unsafe hidden test file: {name}")
        return name

    @field_validator("hidden_test_sha256", "source_prompt_sha256")
    @classmethod
    def _validate_sha256(cls, value: str) -> str:
        lowered = value.lower()
        if len(lowered) != 64 or any(character not in "0123456789abcdef" for character in lowered):
            raise ValueError("expected lowercase SHA-256")
        return lowered

    @classmethod
    def read_json(cls, path: str | Path) -> "AiderShadowRubric":
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))


class Hybrid45RepairTelemetry(BaseModel):
    """Non-rewarding transition telemetry for one isolated repair attempt."""

    model_config = ConfigDict(extra="forbid")

    attempt: int = Field(ge=2)
    previous_response_sha256: str | None = None
    feedback_sha256: str | None = None
    previous_optimizer_score: float = Field(ge=-1.0, le=1.0)
    optimizer_score: float = Field(ge=-1.0, le=1.0)
    reward_delta: float = Field(ge=-2.0, le=2.0)
    kernel_flips: list[str] = Field(default_factory=list)
    stage_before: int = Field(ge=0, le=8)
    stage_after: int = Field(ge=0, le=8)

    @field_validator("previous_response_sha256", "feedback_sha256")
    @classmethod
    def _validate_optional_sha256(cls, value: str | None) -> str | None:
        if value is None:
            return None
        lowered = value.lower()
        if len(lowered) != 64 or any(
            character not in "0123456789abcdef" for character in lowered
        ):
            raise ValueError("expected lowercase SHA-256")
        return lowered

    @model_validator(mode="after")
    def _validate_transition(self) -> "Hybrid45RepairTelemetry":
        expected = round(self.optimizer_score - self.previous_optimizer_score, 10)
        if not math.isclose(self.reward_delta, expected, abs_tol=1e-9):
            raise ValueError("repair reward_delta does not match optimizer-score transition")
        if len(self.kernel_flips) != len(set(self.kernel_flips)):
            raise ValueError("repair kernel flips must be unique")
        return self


class Hybrid45Receipt(BaseModel):
    """Exact optimizer-facing receipt for hybrid-bipolar45-v2."""

    model_config = ConfigDict(extra="forbid")

    policy_version: Literal["hybrid-bipolar45-v2"] = HYBRID45_POLICY_VERSION
    checks: dict[str, StrictBool]
    kernels: dict[str, Literal[-1, 1]]
    observed: dict[str, StrictBool]
    applicable: dict[str, StrictBool]
    evidence: dict[str, str]
    tier_pass_counts: dict[str, int]
    tier_observed_applicable_counts: dict[str, int]
    tier_binary_scores: dict[str, float]
    weighted_binary_contributions: dict[str, float]
    binary_score: float = Field(ge=-1.0, le=1.0)
    reachability_stage: int = Field(ge=0, le=8)
    reachability_reason: str
    discrete_score: float = Field(ge=-1.0, le=1.0)
    semantic_applicable: bool
    hidden_partitions_passed: int = Field(ge=0, le=5)
    hidden_partitions_total: Literal[5] = 5
    continuous_semantic_score: float = Field(ge=-1.0, le=1.0)
    mixed_score: float = Field(ge=-1.0, le=1.0)
    optimizer_score: float | None = Field(default=None, ge=-1.0, le=1.0)
    optimizer_override: Literal[
        "none",
        "complete_pass",
        "forbidden",
        "no_usable_payload",
        "no_op",
        "compile_or_link",
        "runtime_or_sanitizer",
        "infrastructure_mask",
    ]
    primary_failure_kernel: str | None = None
    failure_mechanism: str | None = None
    failure_stage: str | None = None
    consequence_kernels: list[str] = Field(default_factory=list)
    not_reached_kernels: list[str] = Field(default_factory=list)
    infrastructure_error: bool = False
    private_details_disclosed: Literal[False] = False
    repair: Hybrid45RepairTelemetry | None = None

    @field_validator("kernels", mode="before")
    @classmethod
    def _validate_strict_kernels(
        cls, values: object
    ) -> object:
        if isinstance(values, dict) and any(
            type(value) is not int or value not in {-1, 1}
            for value in values.values()
        ):
            raise ValueError("hybrid45 kernels must be exact integer -1 or +1")
        return values

    @field_validator("evidence", mode="before")
    @classmethod
    def _validate_strict_evidence(cls, values: object) -> object:
        if isinstance(values, dict) and any(
            type(value) is not str or not value for value in values.values()
        ):
            raise ValueError("hybrid45 evidence values must be non-empty strings")
        return values

    @model_validator(mode="after")
    def _validate_complete_contract(self) -> "Hybrid45Receipt":
        expected_checks = set(WEIGHTED45_CHECK_IDS)
        for name, values in (
            ("checks", self.checks),
            ("kernels", self.kernels),
            ("observed", self.observed),
            ("applicable", self.applicable),
            ("evidence", self.evidence),
        ):
            observed_keys = set(values)
            if observed_keys != expected_checks:
                missing = sorted(expected_checks - observed_keys)
                extra = sorted(observed_keys - expected_checks)
                raise ValueError(
                    f"hybrid45 {name} contract mismatch: missing={missing} extra={extra}"
                )

        for check_id in WEIGHTED45_CHECK_IDS:
            expected_kernel = 1 if self.checks[check_id] else -1
            if self.kernels[check_id] != expected_kernel:
                raise ValueError(f"hybrid45 kernel/check mismatch for {check_id}")
            if not self.observed[check_id] and self.checks[check_id]:
                raise ValueError(f"unobserved hybrid45 check cannot pass: {check_id}")
            if not isinstance(self.evidence[check_id], str) or not self.evidence[check_id]:
                raise ValueError(f"hybrid45 evidence must be non-empty: {check_id}")

        non_applicable = {
            check_id for check_id, value in self.applicable.items() if not value
        }
        if non_applicable - {"A4"}:
            raise ValueError("only A4 may be non-applicable in hybrid45-v2")
        if "A4" in non_applicable and (
            not self.observed["A4"] or not self.checks["A4"]
        ):
            raise ValueError("non-applicable A4 must be an observed diagnostic pass")

        tier_names = set(WEIGHTED45_TIER_CHECKS)
        for name, values in (
            ("tier_pass_counts", self.tier_pass_counts),
            ("tier_observed_applicable_counts", self.tier_observed_applicable_counts),
            ("tier_binary_scores", self.tier_binary_scores),
            ("weighted_binary_contributions", self.weighted_binary_contributions),
        ):
            if set(values) != tier_names:
                raise ValueError(f"hybrid45 {name} must contain all nine tiers")
        if any(not 0 <= value <= 5 for value in self.tier_pass_counts.values()):
            raise ValueError("hybrid45 tier pass counts must be within 0..5")
        if any(
            not 0 <= value <= 5
            for value in self.tier_observed_applicable_counts.values()
        ):
            raise ValueError("hybrid45 tier eligible counts must be within 0..5")

        numeric_values = [
            self.binary_score,
            self.discrete_score,
            self.continuous_semantic_score,
            self.mixed_score,
            *self.tier_binary_scores.values(),
            *self.weighted_binary_contributions.values(),
        ]
        if self.optimizer_score is not None:
            numeric_values.append(self.optimizer_score)
        if any(not math.isfinite(float(value)) for value in numeric_values):
            raise ValueError("hybrid45 numeric fields must be finite")

        if not math.isclose(
            self.discrete_score,
            HYBRID45_STAGE_SCORES[self.reachability_stage],
            abs_tol=1e-9,
        ):
            raise ValueError("hybrid45 discrete score does not match reachability stage")

        hidden_ids = [f"H{index}" for index in range(1, 6)]
        expected_hidden_passes = sum(self.checks[check_id] for check_id in hidden_ids)
        if self.hidden_partitions_passed != expected_hidden_passes:
            raise ValueError("hybrid45 hidden pass count does not match H kernels")
        hidden_observed = all(self.observed[check_id] for check_id in hidden_ids)
        if self.semantic_applicable != hidden_observed:
            raise ValueError("hybrid45 semantic applicability does not match H observation")
        expected_semantic = (
            2.0 * self.hidden_partitions_passed / 5.0 - 1.0
            if self.semantic_applicable
            else 0.0
        )
        if not math.isclose(
            self.continuous_semantic_score, expected_semantic, abs_tol=1e-9
        ):
            raise ValueError("hybrid45 semantic score does not match hidden partitions")

        expected_not_reached = sorted(
            check_id for check_id in WEIGHTED45_CHECK_IDS if not self.observed[check_id]
        )
        if self.not_reached_kernels != expected_not_reached:
            raise ValueError("hybrid45 not_reached_kernels does not match observation map")
        for field_name, values in (
            ("consequence_kernels", self.consequence_kernels),
            ("not_reached_kernels", self.not_reached_kernels),
        ):
            if len(values) != len(set(values)) or set(values) - expected_checks:
                raise ValueError(f"hybrid45 {field_name} contains invalid check IDs")
        if self.primary_failure_kernel is not None:
            if self.primary_failure_kernel not in expected_checks:
                raise ValueError("hybrid45 primary failure kernel is invalid")
            if self.checks[self.primary_failure_kernel]:
                raise ValueError("hybrid45 primary failure kernel must fail")
            if not self.observed[self.primary_failure_kernel]:
                raise ValueError("hybrid45 primary failure kernel must be observed")

        if self.infrastructure_error:
            if (
                self.optimizer_score is not None
                or self.optimizer_override != "infrastructure_mask"
            ):
                raise ValueError("hybrid45 infrastructure failure must mask optimizer score")
        elif self.optimizer_score is None:
            raise ValueError("hybrid45 non-infrastructure receipt requires optimizer score")
        return self

    def to_record(self) -> dict[str, object]:
        return self.model_dump(mode="json")
