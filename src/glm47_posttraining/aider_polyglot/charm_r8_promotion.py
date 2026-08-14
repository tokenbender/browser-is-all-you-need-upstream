"""R8 wrappers for versioned checkpoint-development and unseen-shadow bundles."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from glm47_posttraining.aider_polyglot.charm_grpo import CharmGRPOProjectionError
from glm47_posttraining.aider_polyglot.charm_r7_promotion import (
    R8_SPLIT_SCHEMA,
    build_r7_private_validation_targets,
    build_r7_public_evaluation_bundle,
    validate_r7_private_validation_targets,
    validate_r7_promotion_split,
    validate_r7_public_evaluation_bundle,
)


def validate_r8_promotion_split(split_file: str | Path) -> dict[str, Any]:
    result = validate_r7_promotion_split(split_file)
    if result["split"].get("schema_version") != R8_SPLIT_SCHEMA:
        raise CharmGRPOProjectionError("expected the frozen R8 promotion split")
    return result


def build_r8_public_evaluation_bundle(
    split_file: str | Path,
    output_dir: str | Path,
    *,
    force: bool = False,
) -> dict[str, Path]:
    validate_r8_promotion_split(split_file)
    return build_r7_public_evaluation_bundle(split_file, output_dir, force=force)


def build_r8_private_validation_targets(
    split_file: str | Path,
    output_dir: str | Path,
    *,
    force: bool = False,
) -> dict[str, Path]:
    validate_r8_promotion_split(split_file)
    return build_r7_private_validation_targets(split_file, output_dir, force=force)


def validate_r8_public_evaluation_bundle(
    split_file: str | Path,
    bundle_dir: str | Path,
) -> dict[str, Any]:
    validate_r8_promotion_split(split_file)
    return validate_r7_public_evaluation_bundle(split_file, bundle_dir)


def validate_r8_private_validation_targets(
    split_file: str | Path,
    bundle_dir: str | Path,
) -> dict[str, Any]:
    validate_r8_promotion_split(split_file)
    return validate_r7_private_validation_targets(split_file, bundle_dir)
