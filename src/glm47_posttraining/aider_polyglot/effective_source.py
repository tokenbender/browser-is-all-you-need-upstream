"""Digest-bind the exact local source bytes used by an R8 SkyPilot run."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "glm47-r8-effective-source-manifest-v1"
SOURCE_INPUTS = (
    ".dockerignore",
    ".skyignore",
    "grpo_h100_full_v5_charm_r8.yaml",
    "grpo_h100_full_v5_charm_r8_unadmitted.yaml",
    "docker/full-v5-charm-grpo-gcp/Dockerfile",
    "docker/full-v5-charm-grpo-gcp/Verifier.Dockerfile",
    "src/glm47_posttraining/__init__.py",
    "src/glm47_posttraining/constants.py",
    "src/glm47_posttraining/aider_polyglot",
    "src/glm47_posttraining/cpp_perf",
    "src/glm47_posttraining/integrations",
    "scripts/train_grpo.sh",
    "scripts/check_runtime.py",
    "scripts/prepare_grpo_adapter.py",
    "scripts/convert_checkpoint.sh",
    "configs/miles/glm4.7-flash.sh",
    "scripts/publish_results.py",
    "scripts/gcp_full_v5_charm_grpo.py",
    "scripts/gcp_full_v5_charm_r8_skypilot.sh",
    "scripts/gcp_full_v5_charm_r8_skypilot_submit.sh",
    "scripts/gcp_full_v5_charm_r8_unadmitted_skypilot.sh",
    "scripts/gcp_full_v5_charm_r8_publish_assets.py",
    "scripts/gcp_full_v5_charm_r8_unadmitted_skypilot_submit.sh",
    "scripts/gcp_h100_host_setup.sh",
    "examples/grpo.sh",
    "configs/full_v5_charm_grpo/gcp-r1.json",
    "configs/full_v5_charm_grpo/r8-candidate-hybrid45-exact40-r87-selection.json",
    "configs/full_v5_charm_grpo/r8-candidate-hybrid45-exact40-r87-canary.json",
    "configs/full_v5_charm_grpo/r8-r87-promotion-evaluation-split.json",
    "dataset/configs/glm47-flash-tokenizer-manifest.json",
    "dataset/configs/glm47-flash-chat-template.jinja",
)
EXCLUDED_SUFFIXES = (".pyc", ".pyo", ".orig", ".rej")
EXCLUDED_PARTS = {"__pycache__"}


class EffectiveSourceError(ValueError):
    """The executable R8 source set is incomplete or has drifted."""


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _source_files(repo_root: Path) -> list[Path]:
    repo = repo_root.resolve()
    files: set[Path] = set()
    for raw in SOURCE_INPUTS:
        path = repo / raw
        if path.is_symlink() or not path.exists():
            raise EffectiveSourceError(f"effective-source input is missing or unsafe: {raw}")
        candidates = [path] if path.is_file() else list(path.rglob("*"))
        for candidate in candidates:
            if not candidate.is_file() or candidate.is_symlink():
                continue
            relative = candidate.relative_to(repo)
            if set(relative.parts) & EXCLUDED_PARTS or relative.suffix in EXCLUDED_SUFFIXES:
                continue
            files.add(candidate)
    return sorted(files, key=lambda item: item.relative_to(repo).as_posix())


def build_effective_source_manifest(repo_root: str | Path) -> dict[str, Any]:
    repo = Path(repo_root).resolve()
    entries = [
        {
            "path": path.relative_to(repo).as_posix(),
            "sha256": _sha256_bytes(path.read_bytes()),
            "size_bytes": path.stat().st_size,
        }
        for path in _source_files(repo)
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "decision": "PASS",
        "scope": "r8-skypilot-host-training-and-verifier-effective-bytes",
        "generated_artifact_excluded_from_its_own_digest": True,
        "generated_profile_excluded_to_avoid_digest_cycle": True,
        "source_input_roots": list(SOURCE_INPUTS),
        "file_count": len(entries),
        "files": entries,
        "source_set_sha256": _sha256_bytes(_canonical_bytes(entries)),
    }


def write_effective_source_manifest(
    repo_root: str | Path,
    output: str | Path,
    *,
    force: bool = False,
) -> dict[str, Any]:
    destination = Path(output).resolve()
    if destination.is_symlink() or (destination.exists() and not force):
        raise FileExistsError(f"refusing to overwrite source manifest: {destination}")
    payload = build_effective_source_manifest(repo_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, destination)
    return payload


def validate_effective_source_manifest(
    repo_root: str | Path,
    manifest_path: str | Path,
    *,
    expected_file_sha256: str | None = None,
) -> dict[str, Any]:
    repo = Path(repo_root).resolve()
    path = Path(manifest_path).resolve()
    if path.is_symlink() or not path.is_file():
        raise EffectiveSourceError("effective-source manifest is missing or unsafe")
    observed_file_sha256 = _sha256_bytes(path.read_bytes())
    if expected_file_sha256 is not None and observed_file_sha256 != expected_file_sha256:
        raise EffectiveSourceError("effective-source manifest file digest mismatch")
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = build_effective_source_manifest(repo)
    if payload != expected:
        raise EffectiveSourceError("effective-source bytes or inventory have drifted")
    return {
        "decision": "PASS",
        "manifest_file_sha256": observed_file_sha256,
        "source_set_sha256": payload["source_set_sha256"],
        "file_count": payload["file_count"],
    }
