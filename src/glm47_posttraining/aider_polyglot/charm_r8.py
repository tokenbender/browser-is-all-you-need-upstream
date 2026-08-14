"""Corrected Hybrid45 V2 projection of the frozen CHARM exact-40 curriculum.

This module preserves the certified 51-task source and 25% repair-prompt
topology from R7 while changing the optimizer reward identity from the
historical MEF wrapper to Hybrid45 V2 itself.  Certified calibration no-op tasks
are monitor-only because they cannot provide optimizer signal.  Dataset validation is separate from CHARM
pre-training admission; these helpers never authorize an optimizer run.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from glm47_posttraining.aider_polyglot.charm_grpo import (
    CharmGRPOProjectionError,
    _canonical_bytes,
    _load_object,
    _sha256_bytes,
    _validate_task,
    sha256_file,
)
from glm47_posttraining.aider_polyglot.charm_r7 import (
    R8_HYBRID45_PROJECTION_CONTRACT,
    _composition,
    build_charm_r7_exact40_dataset,
    validate_charm_r7_exact40_dataset,
    validate_r7_selection,
    verify_charm_r7_exact40_oracles,
)
from glm47_posttraining.aider_polyglot.public_api_manifest import (
    build_public_api_manifest,
    validate_public_api_manifest,
)


CONTRACT = R8_HYBRID45_PROJECTION_CONTRACT
REWARDABILITY_REPLAY_SCHEMA = "charm-r8-hybrid45-corpus-no-update-replay-v1"
CALIBRATION_REPLACEMENTS = {
    "charm-v1r87-37414-dcb547c5-bezier-complex-samples": (
        "charm-v1r87-37414-dcb547c5-decontamination-cover"
    ),
    "charm-v1r87-37414-dcb547c5-rubric-cap-scores": (
        "charm-v1r87-37414-dcb547c5-crop-rotation-audit"
    ),
    "charm-v1r87-37414-dcb547c5-successor-thread-audit": (
        "charm-v1r87-37414-dcb547c5-quota-lane-drain"
    ),
}


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _replace_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _add_public_api_manifests(
    projection: Path,
    frozen: dict[str, Any],
) -> dict[str, Any]:
    """Add private, reference-proved API manifests to an R8 staging tree."""

    manifest_path = projection / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    receipts = {
        str(item.get("task_id")): item
        for item in manifest.get("task_receipts", [])
        if isinstance(item, dict)
    }
    manifest_bindings: list[dict[str, str]] = []
    for selected in sorted(frozen["all_tasks"], key=lambda item: str(item["task_id"])):
        task_id = str(selected["task_id"])
        source_root, rubric = _validate_task(selected)
        public_api = selected.get("public_api")
        if not isinstance(public_api, list):
            raise CharmGRPOProjectionError(f"R8 public API contract is missing: {task_id}")
        api_manifest = build_public_api_manifest(
            task_id=task_id,
            public_api=public_api,
            editable_files=rubric.editable_files,
            reference_root=source_root / ".reference",
            source_tree_sha256=str(selected["tree_sha256"]),
        )
        destination = projection / "shadow" / task_id / ".grader" / "public_api_manifest.json"
        if destination.exists() or destination.is_symlink():
            raise CharmGRPOProjectionError(
                f"R8 public API destination unexpectedly exists: {task_id}"
            )
        _replace_json(destination, api_manifest)
        file_sha256 = sha256_file(destination)
        receipt = receipts.get(task_id)
        if receipt is None:
            raise CharmGRPOProjectionError(f"R8 task receipt is missing: {task_id}")
        receipt["public_api_manifest_sha256"] = file_sha256
        receipt["public_api_contract_sha256"] = api_manifest["public_api_contract_sha256"]
        manifest_bindings.append(
            {
                "task_id": task_id,
                "public_api_manifest_sha256": file_sha256,
            }
        )
    manifest["public_api_contract"] = {
        "status": "PASS",
        "schema_version": "glm47-public-api-ast-manifest-v1",
        "compiler": "clang-18",
        "language_standard": "c++17",
        "task_count": len(manifest_bindings),
        "manifest_set_sha256": _canonical_sha256(manifest_bindings),
        "authoritative_for_k2": True,
        "reward_weights_changed": False,
    }
    _replace_json(manifest_path, manifest)
    return manifest["public_api_contract"]


def write_corrected_selection(
    historical_selection: str | Path,
    output: str | Path,
) -> dict[str, Any]:
    """Derive a new immutable selection contract from verified historical R7."""

    source_path = Path(historical_selection).resolve()
    historical = validate_r7_selection(source_path)
    destination = Path(output).resolve()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"refusing to overwrite corrected selection: {destination}")
    payload = copy.deepcopy(historical["selection"])
    payload["schema_version"] = CONTRACT.selection_schema
    payload["reward_policy"] = CONTRACT.reward_policy
    payload["rubric_update"] = {
        "status": "CANDIDATE_NOT_ADMITTED",
        "historical_selection_path": str(source_path),
        "historical_selection_sha256": sha256_file(source_path),
        "curriculum_task_ids_changed": False,
        "prompt_topology_changed": False,
        "repair_prompt_fraction": 0.25,
        "repair_reward_bonus": False,
        "optimizer_reward_policy": CONTRACT.reward_policy,
        "formula_changed": False,
        "downstream_admission_invalidated": True,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, destination)
    validate_corrected_selection(destination)
    return payload


def _composition_json(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    observed = _composition(tasks)
    return {
        "task_count": observed["task_count"],
        "role_counts": dict(sorted(observed["role_counts"].items())),
        "starter_counts": dict(sorted(observed["starter_counts"].items())),
        "layout_counts": dict(sorted(observed["layout_counts"].items())),
        "header_mode_counts": dict(sorted(observed["header_mode_counts"].items())),
        "repair_type_counts": dict(sorted(observed["repair_type_counts"].items())),
        "api_capability_counts": dict(sorted(observed["api_capability_counts"].items())),
        "multi_file_gt2": observed["multi_file_gt2"],
    }


def _validate_failed_rewardability_replay(
    replay_path: Path,
    failed_selection_path: Path,
) -> dict[str, Any]:
    replay = _load_object(replay_path)
    failed_ids = sorted(CALIBRATION_REPLACEMENTS)
    receipt_sha256 = replay.get("receipt_sha256")
    without_receipt = dict(replay)
    without_receipt.pop("receipt_sha256", None)
    if (
        replay.get("schema_version") != REWARDABILITY_REPLAY_SCHEMA
        or replay.get("decision") != "FAIL"
        or replay.get("optimizer_updates") != 0
        or replay.get("policy_version") != CONTRACT.reward_policy
        or replay.get("task_count") != 51
        or replay.get("functional_reference_pass_count") != 51
        or replay.get("functional_failures") != []
        or replay.get("gradient_task_count") != 40
        or replay.get("gradient_full_positive_reward_count") != 37
        or replay.get("full_positive_reward_count") != 48
        or replay.get("gradient_reward_failures") != failed_ids
        or replay.get("calibration_gradient_failures") != failed_ids
        or replay.get("selection_sha256") != sha256_file(failed_selection_path)
        or receipt_sha256 != _sha256_bytes(_canonical_bytes(without_receipt))
    ):
        raise CharmGRPOProjectionError("invalid R8 rewardability failure replay")
    return replay


def write_rewardable_selection(
    historical_selection: str | Path,
    failed_selection: str | Path,
    failed_replay: str | Path,
    output: str | Path,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Replace gradient-incompatible calibration tasks using a bound replay."""

    historical_path = Path(historical_selection).resolve()
    historical = validate_r7_selection(historical_path)
    failed_selection_path = Path(failed_selection).resolve()
    failed = validate_corrected_selection(failed_selection_path)
    if failed.get("rewardability_ready") is not False:
        raise CharmGRPOProjectionError("R8 failed selection is not the legacy exact-40")
    replay_path = Path(failed_replay).resolve()
    replay = _validate_failed_rewardability_replay(replay_path, failed_selection_path)

    payload = copy.deepcopy(historical["selection"])
    payload["schema_version"] = CONTRACT.selection_schema
    payload["reward_policy"] = CONTRACT.reward_policy
    for group, task_ids in payload["groups"].items():
        payload["groups"][group] = [
            CALIBRATION_REPLACEMENTS.get(task_id, task_id) for task_id in task_ids
        ]
    payload["canary_task_ids"] = [
        CALIBRATION_REPLACEMENTS.get(task_id, task_id)
        for task_id in payload["canary_task_ids"]
    ]

    by_id = {str(item["task_id"]): item for item in historical["all_tasks"]}
    ordered_ids = [
        task_id
        for group in payload["groups"].values()
        for task_id in group
    ]
    selected_tasks = [by_id[task_id] for task_id in ordered_ids]
    canary_tasks = [by_id[task_id] for task_id in payload["canary_task_ids"]]
    payload["expected_full_composition"] = {
        **_composition_json(selected_tasks),
        "group_counts": {group: 10 for group in payload["groups"]},
    }
    canary_composition = _composition_json(canary_tasks)
    payload["expected_canary_composition"] = {
        "task_count": 20,
        "role_counts": canary_composition["role_counts"],
        "starter_counts": canary_composition["starter_counts"],
        "layout_counts": canary_composition["layout_counts"],
        "group_count_each": 5,
        "header_mode_count_each": 4,
        "repair_types_present": sorted(canary_composition["repair_type_counts"]),
        "multi_file_gt2": canary_composition["multi_file_gt2"],
    }
    payload["rubric_update"] = {
        "status": "CANDIDATE_NOT_ADMITTED",
        "historical_selection_path": str(historical_path),
        "historical_selection_sha256": sha256_file(historical_path),
        "failed_selection_sha256": sha256_file(failed_selection_path),
        "failed_rewardability_replay": {
            "schema_version": replay["schema_version"],
            "file_sha256": sha256_file(replay_path),
            "receipt_sha256": replay["receipt_sha256"],
            "optimizer_updates": replay["optimizer_updates"],
            "task_count": replay["task_count"],
            "functional_reference_pass_count": replay["functional_reference_pass_count"],
            "gradient_task_count": replay["gradient_task_count"],
            "gradient_full_positive_reward_count": replay[
                "gradient_full_positive_reward_count"
            ],
            "failed_task_ids": replay["gradient_reward_failures"],
            "raw_artifact_preserved_locally": True,
        },
        "curriculum_task_ids_changed": True,
        "prompt_topology_changed": False,
        "repair_prompt_fraction": 0.25,
        "repair_reward_bonus": False,
        "optimizer_reward_policy": CONTRACT.reward_policy,
        "formula_changed": False,
        "calibration_gradient_task_count": 0,
        "task_replacements": dict(sorted(CALIBRATION_REPLACEMENTS.items())),
        "downstream_admission_invalidated": True,
    }
    destination = Path(output).resolve()
    if destination.is_symlink() or (destination.exists() and not force):
        raise FileExistsError(f"refusing to overwrite corrected selection: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, destination)
    validated = validate_corrected_selection(destination)
    if validated.get("rewardability_ready") is not True:
        raise CharmGRPOProjectionError("R8 rewardable selection validation failed")
    return payload


def validate_corrected_selection(selection_file: str | Path) -> dict[str, Any]:
    result = validate_r7_selection(selection_file, contract=CONTRACT)
    update = result["selection"].get("rubric_update")
    if isinstance(update, dict) and update.get("curriculum_task_ids_changed") is False:
        if (
            update.get("status") != "CANDIDATE_NOT_ADMITTED"
            or update.get("prompt_topology_changed") is not False
            or update.get("repair_prompt_fraction") != 0.25
            or update.get("repair_reward_bonus") is not False
            or update.get("optimizer_reward_policy") != CONTRACT.reward_policy
            or update.get("formula_changed") is not False
            or update.get("downstream_admission_invalidated") is not True
        ):
            raise CharmGRPOProjectionError("corrected exact-40 rubric-update contract drift")
        historical_path = Path(str(update.get("historical_selection_path", ""))).resolve()
        if not historical_path.is_file() or sha256_file(historical_path) != update.get(
            "historical_selection_sha256"
        ):
            raise CharmGRPOProjectionError("corrected selection lost historical R7 binding")
        return {**result, "rewardability_ready": False}
    if (
        not isinstance(update, dict)
        or update.get("status") != "CANDIDATE_NOT_ADMITTED"
        or update.get("curriculum_task_ids_changed") is not True
        or update.get("prompt_topology_changed") is not False
        or update.get("repair_prompt_fraction") != 0.25
        or update.get("repair_reward_bonus") is not False
        or update.get("optimizer_reward_policy") != CONTRACT.reward_policy
        or update.get("formula_changed") is not False
        or update.get("calibration_gradient_task_count") != 0
        or update.get("task_replacements") != dict(sorted(CALIBRATION_REPLACEMENTS.items()))
        or update.get("downstream_admission_invalidated") is not True
    ):
        raise CharmGRPOProjectionError("corrected exact-40 rubric-update contract drift")
    historical_path = Path(str(update.get("historical_selection_path", ""))).resolve()
    if not historical_path.is_file() or sha256_file(historical_path) != update.get(
        "historical_selection_sha256"
    ):
        raise CharmGRPOProjectionError("corrected selection lost historical R7 binding")
    replay = update.get("failed_rewardability_replay")
    if (
        not isinstance(replay, dict)
        or replay.get("schema_version") != REWARDABILITY_REPLAY_SCHEMA
        or not isinstance(replay.get("file_sha256"), str)
        or len(replay["file_sha256"]) != 64
        or not isinstance(replay.get("receipt_sha256"), str)
        or len(replay["receipt_sha256"]) != 64
        or replay.get("optimizer_updates") != 0
        or replay.get("task_count") != 51
        or replay.get("functional_reference_pass_count") != 51
        or replay.get("gradient_task_count") != 40
        or replay.get("gradient_full_positive_reward_count") != 37
        or replay.get("failed_task_ids") != sorted(CALIBRATION_REPLACEMENTS)
        or replay.get("raw_artifact_preserved_locally") is not True
    ):
        raise CharmGRPOProjectionError("corrected selection rewardability evidence drift")
    if any(item.get("role") == "calibration" for item in result["selected_tasks"]):
        raise CharmGRPOProjectionError("calibration task remains gradient-bearing")
    return {**result, "rewardability_ready": True}


def build_corrected_exact40_dataset(
    selection_file: str | Path,
    output_dir: str | Path,
    *,
    run_id: str | None = None,
    force: bool = False,
) -> dict[str, Path]:
    frozen = validate_corrected_selection(selection_file)
    if frozen.get("rewardability_ready") is not True:
        raise CharmGRPOProjectionError("R8 exact-40 is not rewardability-remediated")
    output = Path(output_dir).resolve()
    if output.exists() and output.is_symlink():
        raise CharmGRPOProjectionError(f"refusing to replace symlink: {output}")
    if output.exists() and any(output.iterdir()) and not force:
        raise FileExistsError(f"{output} exists and is not empty; pass force=True")
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=f".{output.name}-r8-api-", dir=output.parent) as value:
        staging = Path(value) / "projection"
        paths = build_charm_r7_exact40_dataset(
            selection_file,
            staging,
            contract=CONTRACT,
            run_id=run_id,
        )
        _add_public_api_manifests(staging, frozen)
        if output.exists():
            shutil.rmtree(output)
        os.replace(staging, output)
    staging_root = paths["manifest"].parent
    return {key: output / path.relative_to(staging_root) for key, path in paths.items()}


def validate_corrected_exact40_dataset(output_dir: str | Path) -> dict[str, Any]:
    root = Path(output_dir).resolve()
    validation = validate_charm_r7_exact40_dataset(root, contract=CONTRACT)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    frozen = validate_corrected_selection(manifest["source"]["selection_path"])
    receipts = {
        str(item.get("task_id")): item
        for item in manifest.get("task_receipts", [])
        if isinstance(item, dict)
    }
    bindings: list[dict[str, str]] = []
    for selected in sorted(frozen["all_tasks"], key=lambda item: str(item["task_id"])):
        task_id = str(selected["task_id"])
        path = root / "shadow" / task_id / ".grader" / "public_api_manifest.json"
        if not path.is_file() or path.is_symlink():
            raise CharmGRPOProjectionError(f"R8 public API manifest is missing: {task_id}")
        api_manifest = json.loads(path.read_text(encoding="utf-8"))
        validated = validate_public_api_manifest(
            api_manifest,
            expected_task_id=task_id,
            expected_source_tree_sha256=str(selected["tree_sha256"]),
        )
        expected_contract_sha256 = _canonical_sha256(selected["public_api"])
        file_sha256 = sha256_file(path)
        receipt = receipts.get(task_id, {})
        if (
            validated["editable_files"] != selected["editable_files"]
            or validated["public_api_contract_sha256"] != expected_contract_sha256
            or receipt.get("public_api_manifest_sha256") != file_sha256
            or receipt.get("public_api_contract_sha256") != expected_contract_sha256
        ):
            raise CharmGRPOProjectionError(f"R8 public API binding drift: {task_id}")
        bindings.append(
            {
                "task_id": task_id,
                "public_api_manifest_sha256": file_sha256,
            }
        )
    contract = manifest.get("public_api_contract")
    expected_set_sha256 = _canonical_sha256(bindings)
    if contract != {
        "status": "PASS",
        "schema_version": "glm47-public-api-ast-manifest-v1",
        "compiler": "clang-18",
        "language_standard": "c++17",
        "task_count": len(bindings),
        "manifest_set_sha256": expected_set_sha256,
        "authoritative_for_k2": True,
        "reward_weights_changed": False,
    }:
        raise CharmGRPOProjectionError("R8 public API manifest-set contract drift")
    return {
        **validation,
        "public_api_manifest_count": len(bindings),
        "public_api_manifest_set_sha256": expected_set_sha256,
    }


def install_corrected_oracle_receipt(
    output_dir: str | Path,
    receipt_file: str | Path,
    *,
    force: bool = False,
) -> Path:
    """Validate and install the executable-oracle PASS into a portable runtime."""

    root = Path(output_dir).resolve()
    validation = validate_corrected_exact40_dataset(root)
    source = Path(receipt_file).resolve()
    if source.is_symlink() or not source.is_file():
        raise CharmGRPOProjectionError("R8 oracle receipt is missing or unsafe")
    receipt = _load_object(source)
    internal_sha256 = receipt.get("receipt_sha256")
    without_receipt = dict(receipt)
    without_receipt.pop("receipt_sha256", None)
    if (
        receipt.get("schema_version") != CONTRACT.oracle_receipt_schema
        or receipt.get("decision") != "PASS"
        or receipt.get("failure_count") != 0
        or receipt.get("task_count") != 51
        or receipt.get("dataset_manifest_sha256") != validation["manifest_sha256"]
        or receipt.get("selection_sha256") != validation["selection_sha256"]
        or internal_sha256 != _sha256_bytes(_canonical_bytes(without_receipt))
        or len(receipt.get("tasks", [])) != 51
        or any(item.get("reference_passed") is not True for item in receipt["tasks"])
        or any(
            item.get("starter_passed") is not item.get("starter_expected_pass")
            for item in receipt["tasks"]
        )
    ):
        raise CharmGRPOProjectionError("invalid corrected R8 executable-oracle receipt")
    destination = root / "oracle-verification-receipt.json"
    if destination.is_symlink() or (destination.exists() and not force):
        raise FileExistsError(f"refusing to overwrite oracle receipt: {destination}")
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    shutil.copyfile(source, temporary)
    os.replace(temporary, destination)
    return destination


def verify_corrected_exact40_oracles(
    output_dir: str | Path,
    *,
    image: str,
    workers: int = 4,
) -> dict[str, Any]:
    return verify_charm_r7_exact40_oracles(
        output_dir,
        contract=CONTRACT,
        image=image,
        workers=workers,
    )
