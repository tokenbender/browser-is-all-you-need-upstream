"""Strict, checksum-bound receipts for oracle certification."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ...policy45 import WEIGHTED45_POLICY_VERSION
from ...schema import WEIGHTED45_CHECK_IDS
from .oracle_rules import ORACLE_RULES, ORACLE_RULES_BY_ID


ORACLE_RECEIPT_KIND = "glm47-aider-oracle-certification"
ORACLE_VALIDATOR_VERSION = "oracle-v1"
SHA256_ZERO = "0" * 64


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class OracleValidationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    standards: tuple[Literal["c++17", "c++20"], ...] = ("c++17", "c++20")
    runs_per_standard: int = Field(default=3, ge=3)
    expected_reward: Literal[1.0] = 1.0
    policy_version: Literal[WEIGHTED45_POLICY_VERSION] = WEIGHTED45_POLICY_VERSION

    @model_validator(mode="after")
    def _validate_matrix(self) -> "OracleValidationConfig":
        if self.standards != ("c++17", "c++20"):
            raise ValueError("oracle certification requires the exact C++17/C++20 matrix")
        return self

    @property
    def config_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class OracleRuleResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str
    rule_version: int
    passed: bool
    severity: Literal["critical", "major", "minor"]
    deterministic: bool = True
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    observed: str
    expected: str
    evidence: str
    remediation: str

    @model_validator(mode="after")
    def _validate_registry_binding(self) -> "OracleRuleResult":
        definition = ORACLE_RULES_BY_ID.get(self.rule_id)
        if definition is None:
            raise ValueError(f"unregistered oracle rule: {self.rule_id}")
        if self.rule_version != definition.version:
            raise ValueError(
                f"oracle rule version mismatch for {self.rule_id}: "
                f"{self.rule_version} != {definition.version}"
            )
        if self.severity != definition.severity:
            raise ValueError(
                f"oracle rule severity mismatch for {self.rule_id}: "
                f"{self.severity} != {definition.severity}"
            )
        return self


class OracleRunReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    standard: Literal["c++17", "c++20"]
    run_index: int = Field(ge=1)
    reward: float
    normalized_percentage: float
    reason: str
    infrastructure_error: bool
    infrastructure_detail: str | None = None
    harness_status: str | None = None
    tests_passed: int = Field(ge=0)
    tests_total: int = Field(ge=0)
    checks: dict[str, bool]
    checks_sha256: str
    duration_ms: int = Field(ge=0)

    @field_validator("checks_sha256")
    @classmethod
    def _validate_checks_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("invalid checks SHA-256")
        return value

    @model_validator(mode="after")
    def _validate_checks_binding(self) -> "OracleRunReceipt":
        expected = canonical_sha256(dict(sorted(self.checks.items())))
        if self.checks_sha256 != expected:
            raise ValueError(
                f"oracle checks SHA-256 mismatch: {self.checks_sha256} != {expected}"
            )
        return self


class OracleInputBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_descriptor_sha256: str
    starter_tree_sha256: str
    reference_tree_sha256: str
    hidden_test_sha256: str
    source_prompt_sha256: str | None = None

    @field_validator(
        "task_descriptor_sha256",
        "starter_tree_sha256",
        "reference_tree_sha256",
        "hidden_test_sha256",
        "source_prompt_sha256",
    )
    @classmethod
    def _validate_sha256(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("invalid oracle input SHA-256")
        return value


class OracleEnvironment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    python_version: str
    platform: str
    compiler: str
    sandbox_backend: str
    sandbox_unshare_net: str


class OracleCertificationReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    kind: Literal[ORACLE_RECEIPT_KIND] = ORACLE_RECEIPT_KIND
    validator_version: Literal[ORACLE_VALIDATOR_VERSION] = ORACLE_VALIDATOR_VERSION
    task_id: str
    status: Literal["certified", "rejected"]
    config: OracleValidationConfig
    config_sha256: str
    input_binding: OracleInputBinding
    environment: OracleEnvironment
    runs: tuple[OracleRunReceipt, ...]
    rules: tuple[OracleRuleResult, ...]
    certification_sha256: str

    @model_validator(mode="after")
    def _validate_contract(self) -> "OracleCertificationReceipt":
        if self.config_sha256 != self.config.config_sha256:
            raise ValueError("oracle config SHA-256 mismatch")
        observed_rules = [result.rule_id for result in self.rules]
        if len(observed_rules) != len(set(observed_rules)):
            raise ValueError("oracle receipt contains duplicate rule results")
        expected_rules = [definition.rule_id for definition in ORACLE_RULES]
        if observed_rules != expected_rules:
            raise ValueError(
                f"oracle receipt rule registry mismatch: {observed_rules} != {expected_rules}"
            )
        expected_status = "certified" if all(result.passed for result in self.rules) else "rejected"
        if self.status != expected_status:
            raise ValueError(
                f"oracle status/rules mismatch: {self.status} != {expected_status}"
            )
        expected_runs = {
            (standard, run_index)
            for standard in self.config.standards
            for run_index in range(1, self.config.runs_per_standard + 1)
        }
        observed_runs = {(run.standard, run.run_index) for run in self.runs}
        if len(observed_runs) != len(self.runs):
            raise ValueError("oracle receipt contains duplicate standard/run entries")
        if self.status == "certified" and observed_runs != expected_runs:
            raise ValueError(
                f"certified oracle run matrix mismatch: {sorted(observed_runs)} != "
                f"{sorted(expected_runs)}"
            )
        if self.status == "certified":
            for run in self.runs:
                if (
                    run.infrastructure_error
                    or run.reward != self.config.expected_reward
                    or set(run.checks) != WEIGHTED45_CHECK_IDS
                    or not all(run.checks.values())
                    or run.checks.get("A2") is not True
                    or run.checks.get("A4") is not True
                ):
                    raise ValueError(
                        "certified oracle contains a non-perfect run: "
                        f"{run.standard}#{run.run_index}"
                    )
        return self

    @property
    def failed_rule_ids(self) -> tuple[str, ...]:
        return tuple(result.rule_id for result in self.rules if not result.passed)


def receipt_certification_payload(receipt: OracleCertificationReceipt) -> dict[str, object]:
    payload = receipt.model_dump(mode="json")
    payload.pop("certification_sha256", None)
    for run in payload["runs"]:
        run.pop("duration_ms", None)
    return payload


def compute_certification_sha256(receipt: OracleCertificationReceipt) -> str:
    return canonical_sha256(receipt_certification_payload(receipt))


def assert_receipt_integrity(receipt: OracleCertificationReceipt) -> None:
    observed = compute_certification_sha256(receipt)
    if observed != receipt.certification_sha256:
        raise ValueError(
            f"oracle certification SHA-256 mismatch: {observed} != "
            f"{receipt.certification_sha256}"
        )


__all__ = [
    "ORACLE_RECEIPT_KIND",
    "ORACLE_VALIDATOR_VERSION",
    "OracleCertificationReceipt",
    "OracleEnvironment",
    "OracleInputBinding",
    "OracleRuleResult",
    "OracleRunReceipt",
    "OracleValidationConfig",
    "SHA256_ZERO",
    "assert_receipt_integrity",
    "canonical_sha256",
    "compute_certification_sha256",
]
