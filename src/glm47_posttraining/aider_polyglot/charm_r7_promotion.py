"""Build immutable R7 checkpoint-development and unseen-shadow evidence.

The public bundle contains only the answer-free rows already present in the
admitted R7 runtime.  The private bundle contains target responses for the six
checkpoint-development tasks only; it is never copied into the runtime or a
model-facing/release payload.  The five unseen-shadow tasks are excluded from
checkpoint selection and have no target-response projection.
"""

from __future__ import annotations

import json
import os
import shutil
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from glm47_posttraining.aider_polyglot.charm_grpo import (
    CharmGRPOProjectionError,
    _canonical_bytes,
    _load_object,
    _sha256_bytes,
    _write_json,
    _write_jsonl,
    sha256_file,
    tree_sha256,
)


SPLIT_SCHEMA = "charm-r7-promotion-evaluation-split-v1"
R8_SPLIT_SCHEMA = "charm-r8-promotion-evaluation-split-v1"
PUBLIC_BUNDLE_SCHEMA = "charm-r7-public-evaluation-bundle-v1"
R8_PUBLIC_BUNDLE_SCHEMA = "charm-r8-public-evaluation-bundle-v1"
PRIVATE_TARGET_SCHEMA = "charm-r7-private-validation-target-bundle-v1"
R8_PRIVATE_TARGET_SCHEMA = "charm-r8-private-validation-target-bundle-v1"
SUPPORTED_SPLIT_SCHEMAS = {SPLIT_SCHEMA, R8_SPLIT_SCHEMA}
PUBLIC_SCHEMA_BY_SPLIT = {
    SPLIT_SCHEMA: PUBLIC_BUNDLE_SCHEMA,
    R8_SPLIT_SCHEMA: R8_PUBLIC_BUNDLE_SCHEMA,
}
PRIVATE_SCHEMA_BY_SPLIT = {
    SPLIT_SCHEMA: PRIVATE_TARGET_SCHEMA,
    R8_SPLIT_SCHEMA: R8_PRIVATE_TARGET_SCHEMA,
}
DEVELOPMENT_TASK_COUNT = 6
UNSEEN_SHADOW_TASK_COUNT = 5
EXPECTED_HEADER_MODES = {"editable", "extended", "frozen", "reconstructed", "repaired"}


def _repo_root(path: Path) -> Path:
    for parent in (path.parent, *path.parents):
        if (parent / "README.md").is_file() and (parent / "src").is_dir():
            return parent
    raise CharmGRPOProjectionError(f"cannot resolve repository root from {path}")


def _bound_file(repo: Path, source: dict[str, Any], stem: str) -> Path:
    raw = source.get(f"{stem}_path")
    expected = source.get(f"{stem}_sha256")
    if not isinstance(raw, str) or not isinstance(expected, str):
        raise CharmGRPOProjectionError(f"missing R7 promotion binding: {stem}")
    path = Path(raw)
    path = path.resolve() if path.is_absolute() else (repo / path).resolve()
    if path.is_symlink() or not path.is_file() or sha256_file(path) != expected:
        raise CharmGRPOProjectionError(f"missing or stale R7 promotion binding: {stem}")
    return path


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CharmGRPOProjectionError(f"invalid JSONL: {path}:{line_number}") from exc
        if not isinstance(value, dict):
            raise CharmGRPOProjectionError(f"non-object JSONL row: {path}:{line_number}")
        rows.append(value)
    return rows


def validate_r7_promotion_split(split_file: str | Path) -> dict[str, Any]:
    """Validate the exact 6/5 partition and all immutable source bindings."""

    split_path = Path(split_file).resolve()
    split = _load_object(split_path)
    split_schema = split.get("schema_version")
    if split_schema not in SUPPORTED_SPLIT_SCHEMAS or split.get("decision") != "FROZEN":
        raise CharmGRPOProjectionError("promotion split is not a supported frozen v1")
    repo = _repo_root(split_path)
    source = split.get("source")
    if not isinstance(source, dict):
        raise CharmGRPOProjectionError("R7 promotion source bindings are missing")

    runtime_raw = source.get("runtime_path")
    if not isinstance(runtime_raw, str):
        raise CharmGRPOProjectionError("R7 promotion runtime path is missing")
    runtime = Path(runtime_raw)
    runtime = runtime.resolve() if runtime.is_absolute() else (repo / runtime).resolve()
    if runtime.is_symlink() or not runtime.is_dir():
        raise CharmGRPOProjectionError("R7 promotion runtime is missing or unsafe")
    runtime_manifest = runtime / "manifest.json"
    if (
        not runtime_manifest.is_file()
        or sha256_file(runtime_manifest) != source.get("runtime_manifest_sha256")
        or tree_sha256(runtime) != source.get("runtime_tree_sha256")
    ):
        raise CharmGRPOProjectionError("R7 promotion runtime binding drift")
    manifest = _load_object(runtime_manifest)
    if manifest.get("source", {}).get("selection_sha256") != source.get("selection_sha256"):
        raise CharmGRPOProjectionError("R7 promotion selection binding drift")

    projection_manifest_path = _bound_file(repo, source, "projection_manifest")
    private_projection_path = _bound_file(repo, source, "private_projection")
    projection_manifest = _load_object(projection_manifest_path)
    if (
        projection_manifest.get("decision") != "PASS"
        or projection_manifest.get("task_count") != 51
        or projection_manifest.get("train_jsonl", {}).get("sha256")
        != source.get("private_projection_sha256")
        or projection_manifest.get("selected_manifest", {}).get("sha256")
        != source.get("selected_manifest_sha256")
        or projection_manifest.get("chat_template", {}).get("sha256")
        != source.get("chat_template_sha256")
    ):
        raise CharmGRPOProjectionError("R7 promotion private projection binding drift")

    development_ids = split.get("checkpoint_development_task_ids")
    shadow_ids = split.get("unseen_shadow_task_ids")
    if (
        not isinstance(development_ids, list)
        or not isinstance(shadow_ids, list)
        or len(development_ids) != DEVELOPMENT_TASK_COUNT
        or len(shadow_ids) != UNSEEN_SHADOW_TASK_COUNT
        or len(set(development_ids)) != DEVELOPMENT_TASK_COUNT
        or len(set(shadow_ids)) != UNSEEN_SHADOW_TASK_COUNT
        or set(development_ids) & set(shadow_ids)
        or not all(isinstance(item, str) for item in development_ids + shadow_ids)
    ):
        raise CharmGRPOProjectionError("R7 promotion split is not an exact disjoint 6/5")

    monitor_path = runtime / str(manifest.get("files", {}).get("task_disjoint_monitor", ""))
    monitor_rows = _read_jsonl(monitor_path)
    monitor_by_id = {str(row.get("metadata", {}).get("base_task_id")): row for row in monitor_rows}
    if set(monitor_by_id) != set(development_ids) | set(shadow_ids):
        raise CharmGRPOProjectionError("R7 promotion split does not partition all 11 monitors")
    train_rows = _read_jsonl(runtime / str(manifest.get("files", {}).get("grpo_train", "")))
    train_ids = {str(row.get("metadata", {}).get("base_task_id")) for row in train_rows}
    if train_ids & set(monitor_by_id):
        raise CharmGRPOProjectionError("R7 promotion evaluation overlaps gradient tasks")

    shadow_rows = [monitor_by_id[task_id] for task_id in shadow_ids]
    header_modes: Counter[str] = Counter()
    repair_count = 0
    calibration_count = 0
    receipts = {str(item.get("task_id")): item for item in manifest.get("task_receipts", [])}
    subset = _load_object(runtime / str(manifest.get("files", {}).get("subset_manifest", "")))
    source_tasks = {str(item.get("task_id")): item for item in subset.get("monitor_tasks", [])}
    for row in shadow_rows:
        task_id = str(row["metadata"]["base_task_id"])
        selected = source_tasks.get(task_id)
        receipt = receipts.get(task_id)
        if not isinstance(selected, dict) or not isinstance(receipt, dict):
            raise CharmGRPOProjectionError(f"missing shadow metadata: {task_id}")
        header_modes[str(selected.get("header_mode"))] += 1
        repair_count += selected.get("role") == "repair_trajectory"
        calibration_count += selected.get("role") == "calibration"
    shadow_contract = split.get("unseen_shadow_contract")
    if (
        not isinstance(shadow_contract, dict)
        or shadow_contract.get("access") != "post-selection-only"
        or shadow_contract.get("optimizer_exposure_count") != 0
        or shadow_contract.get("checkpoint_selection_exposure_count") != 0
        or set(header_modes) != EXPECTED_HEADER_MODES
        or any(value != 1 for value in header_modes.values())
        or dict(sorted(header_modes.items()))
        != dict(sorted(shadow_contract.get("header_mode_counts", {}).items()))
        or repair_count != shadow_contract.get("repair_task_count")
        or (
            split_schema == R8_SPLIT_SCHEMA
            and (
                calibration_count != 3
                or calibration_count != shadow_contract.get("calibration_task_count")
            )
        )
    ):
        raise CharmGRPOProjectionError("R7 unseen-shadow balance/access contract drift")

    private_rows = _read_jsonl(private_projection_path)
    private_by_id = {str(row.get("metadata", {}).get("task_id")): row for row in private_rows}
    if set(development_ids + shadow_ids) - set(private_by_id):
        raise CharmGRPOProjectionError("R7 promotion tasks are absent from private projection")

    return {
        "decision": "PASS",
        "split": split,
        "split_path": split_path,
        "split_sha256": sha256_file(split_path),
        "runtime": runtime,
        "runtime_manifest": manifest,
        "runtime_manifest_sha256": sha256_file(runtime_manifest),
        "development_ids": development_ids,
        "shadow_ids": shadow_ids,
        "monitor_by_id": monitor_by_id,
        "private_projection_path": private_projection_path,
        "private_by_id": private_by_id,
        "projection_manifest_path": projection_manifest_path,
        "header_mode_counts": dict(sorted(header_modes.items())),
    }


def _replace_directory(staging: Path, output: Path, *, force: bool) -> None:
    if output.exists() and any(output.iterdir()) and not force:
        raise FileExistsError(f"{output} exists and is not empty; pass force=True")
    if output.exists():
        if output.is_symlink():
            raise CharmGRPOProjectionError(f"refusing to replace symlink: {output}")
        shutil.rmtree(output)
    os.replace(staging, output)


def build_r7_public_evaluation_bundle(
    split_file: str | Path,
    output_dir: str | Path,
    *,
    force: bool = False,
) -> dict[str, Path]:
    """Build answer-free development and post-selection-only shadow rows."""

    frozen = validate_r7_promotion_split(split_file)
    output = Path(output_dir).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=f".{output.name}-preparing-", dir=output.parent) as value:
        staging = Path(value)
        development = [frozen["monitor_by_id"][task_id] for task_id in frozen["development_ids"]]
        shadow = [frozen["monitor_by_id"][task_id] for task_id in frozen["shadow_ids"]]
        development_path = staging / "checkpoint-development.jsonl"
        shadow_path = staging / "unseen-shadow-post-selection-only.jsonl"
        _write_jsonl(development_path, development)
        _write_jsonl(shadow_path, shadow)
        manifest = {
            "schema_version": PUBLIC_SCHEMA_BY_SPLIT[
                frozen["split"]["schema_version"]
            ],
            "decision": "PASS",
            "split_sha256": frozen["split_sha256"],
            "runtime_manifest_sha256": frozen["runtime_manifest_sha256"],
            "selection_sha256": frozen["split"]["source"]["selection_sha256"],
            "answer_free": True,
            "checkpoint_development_task_ids": frozen["development_ids"],
            "unseen_shadow_task_ids": frozen["shadow_ids"],
            "unseen_shadow_access": "post-selection-only",
            "checkpoint_selection_excludes_shadow": True,
            "files": {
                "checkpoint_development": development_path.name,
                "unseen_shadow": shadow_path.name,
            },
            "file_sha256": {
                "checkpoint_development": sha256_file(development_path),
                "unseen_shadow": sha256_file(shadow_path),
            },
        }
        _write_json(staging / "manifest.json", manifest)
        _replace_directory(staging, output, force=force)
    return {
        "manifest": output / "manifest.json",
        "checkpoint_development": output / "checkpoint-development.jsonl",
        "unseen_shadow": output / "unseen-shadow-post-selection-only.jsonl",
    }


def build_r7_private_validation_targets(
    split_file: str | Path,
    output_dir: str | Path,
    *,
    force: bool = False,
) -> dict[str, Path]:
    """Build a private, development-only target-response loss bundle."""

    frozen = validate_r7_promotion_split(split_file)
    output = Path(output_dir).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=f".{output.name}-preparing-", dir=output.parent) as value:
        staging = Path(value)
        target_rows: list[dict[str, Any]] = []
        for task_id in frozen["development_ids"]:
            public_row = frozen["monitor_by_id"][task_id]
            private_row = frozen["private_by_id"][task_id]
            private_messages = private_row.get("messages")
            public_prompt = public_row.get("prompt")
            if (
                not isinstance(private_messages, list)
                or len(private_messages) != 2
                or private_messages[0].get("role") != "user"
                or private_messages[1].get("role") != "assistant"
                or not isinstance(private_messages[1].get("content"), str)
                or not private_messages[1]["content"]
                or not isinstance(public_prompt, list)
                or not public_prompt
                or public_prompt[-1].get("role") != "user"
                or public_row.get("metadata", {}).get("base_task_id") != task_id
                or private_row.get("metadata", {}).get("task_id") != task_id
            ):
                raise CharmGRPOProjectionError(
                    f"R7 development target topology/prompt drift: {task_id}"
                )
            # Score the verified answer under the exact GRPO/Aider prompt. The
            # private SFT projection intentionally uses a different one-turn
            # renderer, so its user message is provenance rather than the
            # checkpoint-loss prompt.
            messages = [*public_prompt, private_messages[1]]
            target_rows.append(
                {
                    "task_id": task_id,
                    "messages": messages,
                    "metadata": {
                        "split": "checkpoint-development-private-loss-only",
                        "source_final_row_sha256": _sha256_bytes(_canonical_bytes(private_row)),
                        "public_prompt_sha256": public_row["metadata"]["source_prompt_sha256"],
                        "rendered_public_prompt_sha256": _sha256_bytes(
                            _canonical_bytes(public_prompt)
                        ),
                        "target_response_sha256": _sha256_bytes(
                            private_messages[1]["content"].encode("utf-8")
                        ),
                        "shadow": False,
                    },
                }
            )
        targets_path = staging / "private-validation-targets.jsonl"
        _write_jsonl(targets_path, target_rows)
        manifest = {
            "schema_version": PRIVATE_SCHEMA_BY_SPLIT[
                frozen["split"]["schema_version"]
            ],
            "decision": "PASS",
            "private": True,
            "release_authorized": False,
            "model_facing": False,
            "split_sha256": frozen["split_sha256"],
            "runtime_manifest_sha256": frozen["runtime_manifest_sha256"],
            "projection_manifest_sha256": sha256_file(frozen["projection_manifest_path"]),
            "private_projection_sha256": sha256_file(frozen["private_projection_path"]),
            "task_count": len(target_rows),
            "task_ids": frozen["development_ids"],
            "unseen_shadow_task_ids_present": [],
            "file": targets_path.name,
            "file_sha256": sha256_file(targets_path),
        }
        _write_json(staging / "manifest.json", manifest)
        _replace_directory(staging, output, force=force)
    os.chmod(output, 0o700)
    for path in output.iterdir():
        os.chmod(path, 0o600)
    return {
        "manifest": output / "manifest.json",
        "targets": output / "private-validation-targets.jsonl",
    }


def validate_r7_public_evaluation_bundle(
    split_file: str | Path, bundle_dir: str | Path
) -> dict[str, Any]:
    frozen = validate_r7_promotion_split(split_file)
    root = Path(bundle_dir).resolve()
    manifest = _load_object(root / "manifest.json")
    if (
        manifest.get("schema_version")
        != PUBLIC_SCHEMA_BY_SPLIT[frozen["split"]["schema_version"]]
        or manifest.get("decision") != "PASS"
        or manifest.get("split_sha256") != frozen["split_sha256"]
        or manifest.get("runtime_manifest_sha256") != frozen["runtime_manifest_sha256"]
        or manifest.get("answer_free") is not True
        or manifest.get("checkpoint_selection_excludes_shadow") is not True
    ):
        raise CharmGRPOProjectionError("invalid R7 public evaluation bundle manifest")
    expected = {
        "checkpoint_development": frozen["development_ids"],
        "unseen_shadow": frozen["shadow_ids"],
    }
    for label, task_ids in expected.items():
        path = root / str(manifest.get("files", {}).get(label, ""))
        if sha256_file(path) != manifest.get("file_sha256", {}).get(label):
            raise CharmGRPOProjectionError(f"R7 public bundle digest drift: {label}")
        rows = _read_jsonl(path)
        observed = [str(row.get("metadata", {}).get("base_task_id")) for row in rows]
        if observed != task_ids or any(
            row.get("prompt", [{}])[-1].get("role") != "user" for row in rows
        ):
            raise CharmGRPOProjectionError(f"R7 public bundle row drift: {label}")
        if rows != [frozen["monitor_by_id"][task_id] for task_id in task_ids]:
            raise CharmGRPOProjectionError(
                f"R7 public bundle is not a byte-exact row projection: {label}"
            )
    return {
        "decision": "PASS",
        "manifest_sha256": sha256_file(root / "manifest.json"),
        "development_task_count": DEVELOPMENT_TASK_COUNT,
        "unseen_shadow_task_count": UNSEEN_SHADOW_TASK_COUNT,
        "shadow_header_mode_counts": frozen["header_mode_counts"],
    }


def validate_r7_private_validation_targets(
    split_file: str | Path, bundle_dir: str | Path
) -> dict[str, Any]:
    frozen = validate_r7_promotion_split(split_file)
    root = Path(bundle_dir).resolve()
    manifest = _load_object(root / "manifest.json")
    targets_path = root / str(manifest.get("file", ""))
    if (
        manifest.get("schema_version")
        != PRIVATE_SCHEMA_BY_SPLIT[frozen["split"]["schema_version"]]
        or manifest.get("decision") != "PASS"
        or manifest.get("private") is not True
        or manifest.get("release_authorized") is not False
        or manifest.get("model_facing") is not False
        or manifest.get("split_sha256") != frozen["split_sha256"]
        or manifest.get("task_ids") != frozen["development_ids"]
        or manifest.get("unseen_shadow_task_ids_present") != []
        or sha256_file(targets_path) != manifest.get("file_sha256")
    ):
        raise CharmGRPOProjectionError("invalid R7 private validation-target bundle")
    rows = _read_jsonl(targets_path)
    if [row.get("task_id") for row in rows] != frozen["development_ids"]:
        raise CharmGRPOProjectionError("R7 private validation-target row order drift")
    if set(frozen["shadow_ids"]) & {str(row.get("task_id")) for row in rows}:
        raise CharmGRPOProjectionError("R7 unseen-shadow target leaked into private loss bundle")
    return {
        "decision": "PASS",
        "manifest_sha256": sha256_file(root / "manifest.json"),
        "target_task_count": len(rows),
        "shadow_target_count": 0,
    }
