"""Manifest validation entry point for the generalized verifier pack.

The direct runner loads this module and calls ``validate_manifest`` before
dispatching any wrapper.  Validation is structural only; digest binding is
performed by the runner and re-checked by every wrapper.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

_TASK_ID = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_SHA256 = re.compile(r"[0-9a-f]{64}")


class ManifestValidationError(ValueError):
    """The manifest does not satisfy the pack's structural contract."""


def _check_relative_path(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value:
        raise ManifestValidationError(f"{label} must be a non-empty string")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ManifestValidationError(
            f"{label} must be a relative path inside the candidate: {value}")


def validate_manifest(manifest: Any) -> None:
    if not isinstance(manifest, dict):
        raise ManifestValidationError("manifest root must be an object")

    task_id = manifest.get("task_id")
    if not isinstance(task_id, str) or _TASK_ID.fullmatch(task_id) is None:
        raise ManifestValidationError(
            "task_id must be a lowercase slug (digits, '.', '_', '-')")

    candidate_files = manifest.get("candidate_files")
    if not isinstance(candidate_files, list) or not candidate_files:
        raise ManifestValidationError(
            "candidate_files must be a non-empty list of relative paths")
    for item in candidate_files:
        _check_relative_path(item, "candidate_files entry")

    protected = manifest.get("protected_files", {})
    if not isinstance(protected, dict):
        raise ManifestValidationError("protected_files must be an object")
    for name, digest in protected.items():
        _check_relative_path(name, "protected_files entry")
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            raise ManifestValidationError(
                f"protected_files digest for {name} must be 64 lowercase hex")

    policies = manifest.get("policies")
    if not isinstance(policies, dict):
        raise ManifestValidationError("policies must be an object keyed by "
                                      "policy id (G01..G06)")

    fixture_dir = manifest.get("fixture_dir")
    if fixture_dir is not None and not isinstance(fixture_dir, str):
        raise ManifestValidationError("fixture_dir must be a string path")

    trajectory = manifest.get("trajectory")
    if trajectory is not None:
        if not isinstance(trajectory, dict):
            raise ManifestValidationError("trajectory must be an object")
        turns = trajectory.get("turns")
        if turns is not None and not (
                isinstance(turns, list)
                and all(isinstance(turn, dict) for turn in turns)):
            raise ManifestValidationError("trajectory.turns must be a list "
                                          "of objects")
