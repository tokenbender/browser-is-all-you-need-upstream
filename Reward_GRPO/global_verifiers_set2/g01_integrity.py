"""G01: authenticate task boundaries and immutable assets."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePath
from typing import Any

from receipt import PolicyReceipt, policy


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def verify(workspace: Path, manifest: dict[str, Any]) -> PolicyReceipt:
    editable = manifest.get("editable_files")
    protected = manifest.get("protected_files")
    if not isinstance(editable, list) or not isinstance(protected, dict):
        return policy("G01", "INVALID", "INVALID_MANIFEST")
    for name in [*editable, *protected]:
        relative = PurePath(str(name))
        if relative.is_absolute() or ".." in relative.parts:
            return policy("G01", "INVALID", "UNSAFE_MANIFEST_PATH", path=str(name))
    for name, expected in protected.items():
        path = workspace / name
        if not path.is_file() or path.is_symlink():
            return policy("G01", "INVALID", "PROTECTED_ASSET_MISSING", path=name)
        actual = _digest(path)
        if actual != expected:
            return policy("G01", "INVALID", "PROTECTED_ASSET_CORRUPTED", path=name,
                          expected_sha256=expected, actual_sha256=actual)
    return policy("G01", "PASS", "BOUNDARY_AUTHENTICATED",
                  editable_files=sorted(editable), protected_files=sorted(protected))
