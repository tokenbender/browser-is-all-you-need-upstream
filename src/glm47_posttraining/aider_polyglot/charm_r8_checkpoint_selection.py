"""Deterministically select an R8 canary checkpoint from development-only metrics."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Sequence

from glm47_posttraining.aider_polyglot.charm_grpo import (
    CharmGRPOProjectionError,
    _canonical_bytes,
    sha256_file,
)
from glm47_posttraining.aider_polyglot.charm_r8_promotion import (
    validate_r8_promotion_split,
)


METRICS_SCHEMA = "charm-r8-checkpoint-development-metrics-v1"
RECEIPT_SCHEMA = "charm-r8-checkpoint-selection-receipt-v1"


def _read_object(path: str | Path, label: str) -> tuple[Path, dict[str, Any]]:
    resolved = Path(path).resolve()
    if resolved.is_symlink() or not resolved.is_file():
        raise CharmGRPOProjectionError(f"{label} is missing or unsafe: {resolved}")
    value = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CharmGRPOProjectionError(f"{label} must be a JSON object")
    return resolved, value


def _finite_rate(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and 0.0 <= float(value) <= 1.0
    )


def _finite_loss(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) >= 0.0
    )


def select_r8_checkpoint(
    *,
    split_file: str | Path,
    metrics_file: str | Path,
    output: str | Path,
) -> dict[str, Any]:
    """Score every checkpoint as 40% compile, 40% hidden, 20% loss utility."""

    frozen = validate_r8_promotion_split(split_file)
    metrics_path, metrics = _read_object(metrics_file, "checkpoint metrics")
    output_path = Path(output).resolve()
    if output_path.exists() or output_path.is_symlink():
        raise FileExistsError(f"refusing to overwrite checkpoint receipt: {output_path}")

    contract = frozen["split"].get("checkpoint_selection_contract")
    expected_weights = {
        "compile_rate": 0.4,
        "hidden_test_pass_rate": 0.4,
        "validation_loss": 0.2,
    }
    checkpoints = metrics.get("checkpoints")
    expected_count = contract.get("expected_canary_checkpoint_count") if isinstance(
        contract, dict
    ) else None
    if (
        not isinstance(contract, dict)
        or contract.get("weights") != expected_weights
        or contract.get("validation_loss_utility") != "one_over_one_plus_loss"
        or contract.get("always_final") is not False
        or contract.get("final_checkpoint_competes_on_metrics") is not True
        or contract.get("shadow_metrics_excluded") is not True
        or metrics.get("schema_version") != METRICS_SCHEMA
        or metrics.get("decision") != "COMPLETE"
        or metrics.get("split_sha256") != frozen["split_sha256"]
        or metrics.get("development_task_ids") != frozen["development_ids"]
        or metrics.get("development_task_count") != len(frozen["development_ids"])
        or metrics.get("shadow_checkpoint_selection_exposure_count") != 0
        or metrics.get("official_fixed26_checkpoint_selection_exposure_count") != 0
        or not isinstance(checkpoints, list)
        or len(checkpoints) != expected_count
    ):
        raise CharmGRPOProjectionError("R8 checkpoint metrics violate the frozen split contract")

    seen_ids: set[str] = set()
    seen_steps: set[int] = set()
    scored: list[dict[str, Any]] = []
    for index, checkpoint in enumerate(checkpoints):
        if not isinstance(checkpoint, dict):
            raise CharmGRPOProjectionError(f"checkpoint metric {index} is not an object")
        checkpoint_id = checkpoint.get("checkpoint_id")
        optimizer_step = checkpoint.get("optimizer_step")
        compile_rate = checkpoint.get("compile_rate")
        hidden_rate = checkpoint.get("hidden_test_pass_rate")
        validation_loss = checkpoint.get("target_token_validation_loss")
        adapter_sha256 = checkpoint.get("adapter_sha256")
        if (
            not isinstance(checkpoint_id, str)
            or not checkpoint_id
            or checkpoint_id in seen_ids
            or not isinstance(optimizer_step, int)
            or isinstance(optimizer_step, bool)
            or optimizer_step <= 0
            or optimizer_step in seen_steps
            or not _finite_rate(compile_rate)
            or not _finite_rate(hidden_rate)
            or not _finite_loss(validation_loss)
            or not isinstance(adapter_sha256, str)
            or len(adapter_sha256) != 64
            or checkpoint.get("development_task_count") != 6
            or checkpoint.get("infrastructure_failure_count") != 0
            or checkpoint.get("malformed_output_count") != 0
            or not _finite_rate(checkpoint.get("context_exhaustion_rate"))
            or float(checkpoint["context_exhaustion_rate"]) > 0.01
            or not isinstance(checkpoint.get("is_final"), bool)
        ):
            raise CharmGRPOProjectionError(
                f"checkpoint metric {index} is incomplete, unsafe, or non-finite"
            )
        seen_ids.add(checkpoint_id)
        seen_steps.add(optimizer_step)
        loss_utility = 1.0 / (1.0 + float(validation_loss))
        composite = math.fsum(
            (
                0.4 * float(compile_rate),
                0.4 * float(hidden_rate),
                0.2 * loss_utility,
            )
        )
        scored.append(
            {
                "checkpoint_id": checkpoint_id,
                "optimizer_step": optimizer_step,
                "adapter_sha256": adapter_sha256,
                "is_final": checkpoint["is_final"],
                "compile_rate": float(compile_rate),
                "hidden_test_pass_rate": float(hidden_rate),
                "target_token_validation_loss": float(validation_loss),
                "validation_loss_utility": loss_utility,
                "composite_score": composite,
                "eligible": True,
            }
        )

    final_rows = [row for row in scored if row["is_final"]]
    if len(final_rows) != 1 or final_rows[0]["optimizer_step"] != max(seen_steps):
        raise CharmGRPOProjectionError(
            "R8 checkpoint metrics require exactly one highest-step final checkpoint"
        )

    ranked = sorted(
        scored,
        key=lambda row: (
            -row["composite_score"],
            -row["hidden_test_pass_rate"],
            -row["compile_rate"],
            row["target_token_validation_loss"],
            row["optimizer_step"],
            row["checkpoint_id"],
        ),
    )
    selected = ranked[0]
    payload = {
        "schema_version": RECEIPT_SCHEMA,
        "decision": "PASS",
        "split_path": str(frozen["split_path"]),
        "split_sha256": frozen["split_sha256"],
        "metrics_path": str(metrics_path),
        "metrics_file_sha256": sha256_file(metrics_path),
        "development_task_count": 6,
        "shadow_checkpoint_selection_exposure_count": 0,
        "official_fixed26_checkpoint_selection_exposure_count": 0,
        "weights": expected_weights,
        "validation_loss_utility": "one_over_one_plus_loss",
        "always_final": False,
        "final_checkpoint_competes_on_metrics": True,
        "selected_checkpoint_id": selected["checkpoint_id"],
        "selected_optimizer_step": selected["optimizer_step"],
        "selected_adapter_sha256": selected["adapter_sha256"],
        "selected_checkpoint_is_final": selected["is_final"],
        "final_checkpoint_selected_by_position": False,
        "ranking": ranked,
    }
    payload["receipt_sha256"] = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, output_path)
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", required=True)
    parser.add_argument("--metrics", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    result = select_r8_checkpoint(
        split_file=args.split,
        metrics_file=args.metrics,
        output=args.output,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
