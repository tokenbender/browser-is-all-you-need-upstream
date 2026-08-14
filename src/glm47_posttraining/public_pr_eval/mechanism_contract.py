"""Static contract checks for optional executable mechanism verification."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path, PurePosixPath
from typing import Any

from .mechanisms import FMT_MECHANISM_IDS


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _safe_relative(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        bool(value)
        and not path.is_absolute()
        and ".." not in path.parts
        and not any(part in {"", "."} for part in path.parts)
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def mechanism_contract_findings(
    row: dict[str, Any], repo_root: Path
) -> list[tuple[str, str]]:
    hidden = row.get("hidden_validation")
    if not isinstance(hidden, dict):
        return []
    mechanism = hidden.get("mechanism_verification")
    if mechanism is None:
        return []
    if not isinstance(mechanism, dict):
        return [("PPR-MECHANISM-001", "mechanism_verification must be an object")]

    findings: list[tuple[str, str]] = []
    verifiers = mechanism.get("verifiers")
    verifier_ids = (
        [str(item.get("id", "")) for item in verifiers]
        if isinstance(verifiers, list)
        and all(isinstance(item, dict) for item in verifiers)
        else []
    )
    checklist = row.get("diagnostic_checklist")
    checklist_bindings = (
        [str(item.get("verifier_id", "")) for item in checklist]
        if isinstance(checklist, list)
        and all(isinstance(item, dict) for item in checklist)
        else []
    )
    if not (
        mechanism.get("schema_version") == "public-pr-mechanism-verification-v1"
        and mechanism.get("required_for_pass") is True
        and mechanism.get("structure_verifier_id") == "fmt-chrono-structure-v1"
        and mechanism.get("source_path") == "include/fmt/chrono.h"
        and verifier_ids == list(FMT_MECHANISM_IDS)
        and checklist_bindings == list(FMT_MECHANISM_IDS)
    ):
        findings.append(
            (
                "PPR-MECHANISM-001",
                "mechanism verification must bind all twelve named structure verifiers",
            )
        )

    binding = mechanism.get("probe")
    binding = binding if isinstance(binding, dict) else {}
    binding_path = str(binding.get("path", ""))
    probe = repo_root / binding_path
    probe_hash = str(binding.get("sha256", ""))
    if not (
        _safe_relative(binding_path)
        and probe.is_file()
        and _SHA256_RE.fullmatch(probe_hash) is not None
        and _sha256(probe) == probe_hash
    ):
        findings.append(
            (
                "PPR-MECHANISM-002",
                "focused mechanism probe is missing or digest-mismatched",
            )
        )

    commands = mechanism.get("commands")
    command_rows = (
        commands
        if isinstance(commands, list)
        and commands
        and all(isinstance(item, dict) for item in commands)
        else []
    )
    command_names = {str(item.get("name", "")) for item in command_rows}
    build_names = {
        str(item.get("name", ""))
        for item in hidden.get("build_commands", [])
        if isinstance(item, dict)
    }
    compile_names = {
        str(name) for name in mechanism.get("compile_gate_command_names", [])
    }
    build_compile_names = {
        str(name)
        for name in mechanism.get("build_compile_gate_command_names", [])
    }
    referenced_names = {
        str(name)
        for item in verifiers or []
        if isinstance(item, dict)
        for key in ("command_names", "platform_gate_command_names")
        for name in item.get(key, [])
        if isinstance(name, str)
    }
    command_shapes_ok = all(
        isinstance(item.get("name"), str)
        and isinstance(item.get("argv"), list)
        and bool(item["argv"])
        and all(isinstance(arg, str) and arg for arg in item["argv"])
        and isinstance(item.get("timeout_seconds"), int)
        and item["timeout_seconds"] > 0
        and item.get("continue_on_failure") is True
        for item in command_rows
    )
    if not (
        command_shapes_ok
        and bool(build_compile_names)
        and build_compile_names.issubset(build_names)
        and bool(compile_names)
        and compile_names.issubset(build_names | command_names)
        and referenced_names.issubset(command_names)
    ):
        findings.append(
            (
                "PPR-MECHANISM-003",
                "compile gates and mechanism verifiers must reference valid declared commands",
            )
        )
    return findings
