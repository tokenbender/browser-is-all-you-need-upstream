"""Stable, documented rule registry for reference-oracle certification."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OracleRuleDefinition:
    rule_id: str
    version: int
    description: str
    severity: str
    remediation: str


ORACLE_RULES: tuple[OracleRuleDefinition, ...] = (
    OracleRuleDefinition(
        "ORC-001",
        1,
        "A real, non-symlink .reference directory exists.",
        "critical",
        "Add a private .reference directory containing the canonical editable files.",
    ),
    OracleRuleDefinition(
        "ORC-002",
        1,
        "The reference package contains exactly the declared editable files.",
        "critical",
        "Make .reference filenames exactly match editable_files; remove all extras.",
    ),
    OracleRuleDefinition(
        "ORC-003",
        1,
        "Every reference file is a regular, direct-child, non-symlink file.",
        "critical",
        "Replace links or nested paths with regular files directly under .reference.",
    ),
    OracleRuleDefinition(
        "ORC-004",
        1,
        "The reference can be represented as an exact Aider whole-file response.",
        "critical",
        "Use UTF-8 C++ files within the response-size limit and exact file labels.",
    ),
    OracleRuleDefinition(
        "ORC-005",
        1,
        "The executed hidden grader matches the task-bound SHA-256.",
        "critical",
        "Restore the certified grader or update and re-review the rubric hash.",
    ),
    OracleRuleDefinition(
        "ORC-010",
        1,
        "Every oracle run completes without verifier infrastructure failure.",
        "critical",
        "Repair the compiler/sandbox runtime; do not score infrastructure faults as task failures.",
    ),
    OracleRuleDefinition(
        "ORC-011",
        1,
        "Every oracle run emits the exact 45-check Weighted45 receipt.",
        "critical",
        "Repair the policy/harness contract before certifying tasks.",
    ),
    OracleRuleDefinition(
        "ORC-012",
        1,
        "Every oracle run has normalized Weighted45 reward exactly 1.000000.",
        "critical",
        "Fix the reference implementation, task contract, or hidden grader.",
    ),
    OracleRuleDefinition(
        "ORC-013",
        1,
        "All 45 individual policy checks pass on every oracle run.",
        "critical",
        "Inspect failed check evidence and correct the reference or grader.",
    ),
    OracleRuleDefinition(
        "ORC-014",
        1,
        "Sanitizer and applicable concurrency checks pass on every oracle run.",
        "critical",
        "Remove memory/UB/race defects or repair a non-portable grader.",
    ),
    OracleRuleDefinition(
        "ORC-015",
        1,
        "Repeated oracle executions are deterministic within each compiler standard.",
        "critical",
        "Remove randomness, time, order, locale, race, or environmental dependence.",
    ),
    OracleRuleDefinition(
        "ORC-016",
        1,
        "The reference passes the required C++17 and C++20 certification matrix.",
        "critical",
        "Make the reference and grader portable across both configured language standards.",
    ),
)

ORACLE_RULES_BY_ID = {rule.rule_id: rule for rule in ORACLE_RULES}

if len(ORACLE_RULES_BY_ID) != len(ORACLE_RULES):
    raise RuntimeError("duplicate oracle rule ID")


def oracle_rule(rule_id: str) -> OracleRuleDefinition:
    try:
        return ORACLE_RULES_BY_ID[rule_id]
    except KeyError as exc:
        raise ValueError(f"unknown oracle rule ID: {rule_id}") from exc


__all__ = ["ORACLE_RULES", "ORACLE_RULES_BY_ID", "OracleRuleDefinition", "oracle_rule"]
