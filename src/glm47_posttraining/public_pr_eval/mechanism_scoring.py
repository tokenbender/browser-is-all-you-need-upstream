"""Compile-gated aggregation for public-PR mechanism evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .mechanisms import run_structure_verifier


def textual_hint_summary(checklist: list[dict[str, Any]]) -> dict[str, Any]:
    present = sum(1 for item in checklist if item.get("status") == "present")
    partial = sum(1 for item in checklist if item.get("status") == "partial")
    missing = sum(1 for item in checklist if item.get("status") == "missing")
    return {
        "status": "diagnostic_only",
        "present": present,
        "partial": partial,
        "missing": missing,
        "total": len(checklist),
        "interpretation_limit": (
            "literal token hints do not establish scope, compilation, or behavior"
        ),
    }


def structure_summary(row: dict[str, Any], repo: Path) -> dict[str, Any]:
    config = row.get("hidden_validation", {}).get("mechanism_verification")
    if not isinstance(config, dict):
        return {"status": "not_configured", "valid": 0, "total": 0, "items": []}
    verifier_id = str(config.get("structure_verifier_id", ""))
    source_path = str(config.get("source_path", ""))
    if not verifier_id or not source_path:
        return {"status": "invalid_contract", "valid": 0, "total": 0, "items": []}
    items = run_structure_verifier(verifier_id, repo / source_path)
    valid = sum(item.get("status") == "valid" for item in items)
    return {
        "status": "complete",
        "verifier_id": verifier_id,
        "valid": valid,
        "invalid": len(items) - valid,
        "total": len(items),
        "items": items,
        "interpretation_limit": (
            "tokenized scope checks are diagnostic until compiler and focused probes pass"
        ),
    }


def _receipt_by_name(*groups: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(receipt.get("name")): receipt
        for group in groups
        for receipt in group
    }


def build_compile_gate_ready(
    config: dict[str, Any], build_receipts: list[dict[str, Any]]
) -> bool:
    receipts = _receipt_by_name(build_receipts)
    names = [str(name) for name in config.get("build_compile_gate_command_names", [])]
    return bool(names) and all(
        name in receipts and int(receipts[name].get("returncode", 1)) == 0
        for name in names
    )


def verified_mechanism_summary(
    row: dict[str, Any],
    *,
    scope_passed: bool,
    build_receipts: list[dict[str, Any]],
    mechanism_receipts: list[dict[str, Any]],
    structure: dict[str, Any],
) -> dict[str, Any]:
    config = row.get("hidden_validation", {}).get("mechanism_verification")
    if not isinstance(config, dict):
        return {"status": "not_configured", "verified": 0, "total": 0}
    all_receipts = _receipt_by_name(build_receipts, mechanism_receipts)
    compile_names = [str(name) for name in config.get("compile_gate_command_names", [])]
    missing_compile = [name for name in compile_names if name not in all_receipts]
    failed_compile = [
        name
        for name in compile_names
        if name in all_receipts
        and int(all_receipts[name].get("returncode", 1)) != 0
    ]
    if not scope_passed:
        reason = "scope_gate_failed"
    elif not compile_names or missing_compile or failed_compile:
        reason = "compile_gate_failed"
    else:
        reason = ""
    if reason:
        return {
            "status": "unavailable",
            "reason": reason,
            "verified": 0,
            "total": len(config.get("verifiers", [])),
            "compile_gate": {
                "required_commands": compile_names,
                "missing_commands": missing_compile,
                "failed_commands": failed_compile,
            },
            "items": [],
        }

    structure_by_id = {
        str(item.get("verifier_id")): item for item in structure.get("items", [])
    }
    gate_codes = {
        int(code) for code in config.get("platform_gate_returncodes", [77, 127])
    }
    items: list[dict[str, Any]] = []
    for verifier in config.get("verifiers", []):
        verifier_id = str(verifier.get("id", ""))
        structural = structure_by_id.get(verifier_id)
        command_names = [str(name) for name in verifier.get("command_names", [])]
        platform_names = [
            str(name) for name in verifier.get("platform_gate_command_names", [])
        ]
        missing = [name for name in command_names if name not in all_receipts]
        failed = [
            name
            for name in command_names
            if name in all_receipts
            and int(all_receipts[name].get("returncode", 1)) != 0
        ]
        gated = [
            name
            for name in failed
            if name in platform_names
            and int(all_receipts[name].get("returncode", 1)) in gate_codes
        ]
        platform_unavailable = (
            bool(failed)
            and not missing
            and set(failed) == set(gated)
        )
        if structural is None or structural.get("status") != "valid":
            status, reason = "failed", "structural_verifier_failed"
        elif platform_unavailable:
            status, reason = "platform_gated", "platform_feature_unavailable"
        elif missing:
            status, reason = "unverified", "focused_command_not_executed"
        elif failed:
            status, reason = "failed", "focused_command_failed"
        else:
            status, reason = "verified", "structure_compile_and_focused_probe_passed"
        items.append(
            {
                "id": verifier_id,
                "status": status,
                "reason": reason,
                "structure": structural,
                "required_commands": command_names,
                "missing_commands": missing,
                "failed_commands": failed,
                "platform_gate_commands": gated,
            }
        )

    verified = sum(item["status"] == "verified" for item in items)
    gated = sum(item["status"] == "platform_gated" for item in items)
    failed = sum(item["status"] == "failed" for item in items)
    unverified = sum(item["status"] == "unverified" for item in items)
    applicable = len(items) - gated
    status = (
        "complete"
        if verified == applicable and not failed and not unverified
        else "incomplete"
    )
    optional_names = [
        str(name) for name in config.get("optional_portability_commands", [])
    ]
    portability = {
        name: (
            "not_available"
            if name not in all_receipts
            or int(all_receipts[name].get("returncode", 1)) in gate_codes
            else "passed"
            if int(all_receipts[name].get("returncode", 1)) == 0
            else "failed"
        )
        for name in optional_names
    }
    return {
        "status": status,
        "verified": verified,
        "applicable_total": applicable,
        "platform_gated": gated,
        "total": len(items),
        "failed": failed,
        "unverified": unverified,
        "compile_gate": {
            "required_commands": compile_names,
            "missing_commands": [],
            "failed_commands": [],
        },
        "optional_portability": portability,
        "items": items,
    }
