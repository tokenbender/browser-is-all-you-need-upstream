"""Build the admitted CHARM R7 exact-40 and exact-20 canary corpus.

The source of truth is the independently audited 51-task CHARM V1 release.
This module selects forty byte-bound task trees for gradients, keeps the other
eleven task-disjoint roots as a no-gradient monitor, and emits one immutable
prompt row per selected task.  Certified repair tasks use the existing
failure -> sanitized feedback -> repair trajectory; no R6 task or response is
ever projected into model-facing data.
"""

from __future__ import annotations

import json
import os
import shutil
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Iterable

from glm47_posttraining.aider_polyglot.charm_grpo import (
    PRIVATE_PROMPT_MARKERS,
    CharmGRPOProjectionError,
    _canonical_bytes,
    _load_object,
    _materialize_exercise,
    _repair_proof,
    _sha256_bytes,
    _validate_source_manifest,
    _validate_task,
    _variant_messages,
    _write_json,
    _write_jsonl,
    sha256_file,
)
from glm47_posttraining.aider_polyglot.harness import (
    DEFAULT_AIDER_DOCKER_IMAGE,
    run_shadow_tests,
)
from glm47_posttraining.aider_polyglot.schema import (
    AiderPolyglotTask,
    HYBRID45_MEF_POLICY_VERSION,
    HYBRID45_POLICY_VERSION,
)


DATASET_KIND = "charm-r7-admitted-mef-exact40"
DATASET_SCHEMA = "charm-grpo-exact40-runtime-v1"
SELECTION_SCHEMA = "charm-grpo-exact40-selection-v1"


@dataclass(frozen=True)
class Exact40ProjectionContract:
    dataset_kind: str
    dataset_schema: str
    selection_schema: str
    reward_policy: str
    descriptor_prefix: str
    task_tag: str
    verification_gate: str
    oracle_receipt_schema: str
    require_public_api_manifest: bool = False


R7_PROJECTION_CONTRACT = Exact40ProjectionContract(
    dataset_kind=DATASET_KIND,
    dataset_schema=DATASET_SCHEMA,
    selection_schema=SELECTION_SCHEMA,
    reward_policy=HYBRID45_MEF_POLICY_VERSION,
    descriptor_prefix="charm-r7",
    task_tag="clean-room-charm-r7",
    verification_gate="charm-r7-exact40-independent-audit-hidden-grader-v1",
    oracle_receipt_schema="charm-r7-executable-oracle-receipt-v1",
)
R8_HYBRID45_PROJECTION_CONTRACT = Exact40ProjectionContract(
    dataset_kind="charm-r8-candidate-hybrid45-exact40",
    dataset_schema="charm-grpo-exact40-runtime-v2",
    selection_schema="charm-grpo-exact40-selection-v2",
    reward_policy=HYBRID45_POLICY_VERSION,
    descriptor_prefix="charm-r8",
    task_tag="clean-room-charm-r8",
    verification_gate="charm-r8-exact40-independent-audit-hidden-grader-v2",
    oracle_receipt_schema="charm-r8-executable-oracle-receipt-v1",
    require_public_api_manifest=True,
)

SUBSET_SCHEMA = "charm-grpo-subset-manifest-v1"
FULL_TASK_COUNT = 40
CANARY_TASK_COUNT = 20
SOURCE_TASK_COUNT = 51
REPAIR_FEEDBACK = "Private tests failed. Private test names and output are intentionally withheld."
GROUP_NAMES = (
    "constraint_contracts",
    "numeric_aggregation",
    "spatial_transforms",
    "temporal_state",
)


def _repo_root(path: Path) -> Path:
    for parent in (path.parent, *path.parents):
        if (parent / "README.md").is_file() and (parent / "src").is_dir():
            return parent
    raise CharmGRPOProjectionError(f"cannot resolve repository root from {path}")


def _bound_path(repo: Path, source: dict[str, Any], stem: str) -> Path:
    raw = source.get(f"{stem}_path")
    expected = source.get(f"{stem}_sha256")
    path = Path(str(raw))
    path = path.resolve() if path.is_absolute() else (repo / path).resolve()
    if not path.is_file() or sha256_file(path) != expected:
        raise CharmGRPOProjectionError(f"missing or stale R7 source binding: {stem}")
    return path


def _require_counter(
    label: str,
    observed: Counter[str],
    expected: Any,
) -> None:
    if not isinstance(expected, dict):
        raise CharmGRPOProjectionError(f"R7 expected {label} is not an object")
    normalized = {str(key): int(value) for key, value in expected.items()}
    if dict(sorted(observed.items())) != dict(sorted(normalized.items())):
        raise CharmGRPOProjectionError(
            f"R7 {label} drift: observed={dict(sorted(observed.items()))} "
            f"expected={dict(sorted(normalized.items()))}"
        )


def _role_lane(selected: dict[str, Any]) -> str:
    role = selected.get("role")
    if role == "repair_trajectory":
        return "repair"
    if role == "calibration":
        return "calibration"
    if role in {"direct_verified_success", "boundary_case"}:
        return "ordinary"
    raise CharmGRPOProjectionError(f"unsupported CHARM role for {selected.get('task_id')}: {role}")


def _composition(tasks: Iterable[dict[str, Any]]) -> dict[str, Any]:
    collection = list(tasks)
    return {
        "task_count": len(collection),
        "role_counts": Counter(str(item.get("role")) for item in collection),
        "starter_counts": Counter(str(item.get("starter_type")) for item in collection),
        "layout_counts": Counter(str(item.get("editable_layout")) for item in collection),
        "header_mode_counts": Counter(str(item.get("header_mode")) for item in collection),
        "repair_type_counts": Counter(
            str(repair_type) for item in collection for repair_type in item.get("repair_types", [])
        ),
        "api_capability_counts": Counter(
            str(capability)
            for item in collection
            for capability in item.get("api_capabilities", [])
        ),
        "multi_file_gt2": sum(item.get("multi_file_gt2") is True for item in collection),
    }


def validate_r7_selection(
    selection_file: str | Path,
    *,
    contract: Exact40ProjectionContract = R7_PROJECTION_CONTRACT,
) -> dict[str, Any]:
    """Validate every source digest and exact full/canary composition gate."""

    selection_path = Path(selection_file).resolve()
    selection = _load_object(selection_path)
    if (
        selection.get("schema_version") != contract.selection_schema
        or selection.get("decision") != "FROZEN"
        or selection.get("reward_policy") != contract.reward_policy
    ):
        raise CharmGRPOProjectionError("R7 frozen selection contract is invalid")
    repo = _repo_root(selection_path)
    source = selection.get("source")
    if not isinstance(source, dict):
        raise CharmGRPOProjectionError("R7 source bindings are missing")
    source_manifest_path = _bound_path(repo, source, "selected_manifest")
    generation_plan_path = _bound_path(repo, source, "canonical_generation_plan")
    sft_ready_path = _bound_path(repo, source, "sft_ready_manifest")
    pretraining_admission_path = _bound_path(repo, source, "pretraining_admission")
    task_id_registry_path = _bound_path(repo, source, "task_id_registry")
    source_manifest, all_tasks = _validate_source_manifest(source_manifest_path)
    if len(all_tasks) != SOURCE_TASK_COUNT:
        raise CharmGRPOProjectionError("R7 source manifest no longer has 51 tasks")
    sft_ready = _load_object(sft_ready_path)
    if (
        sft_ready.get("decision") != "PASS"
        or sft_ready.get("status") != "consumer_verified_sft_ready"
        or sft_ready.get("task_count") != SOURCE_TASK_COUNT
    ):
        raise CharmGRPOProjectionError("R7 SFT-ready source binding is not terminal PASS")
    ready_selected = sft_ready.get("selected_manifest")
    if not isinstance(ready_selected, dict) or ready_selected.get("sha256") != sha256_file(
        source_manifest_path
    ):
        raise CharmGRPOProjectionError("R7 SFT-ready manifest binds a different selection")
    pretraining_admission = _load_object(pretraining_admission_path)
    if (
        pretraining_admission.get("decision") != "PASS"
        or pretraining_admission.get("stage") != "pre-training"
    ):
        raise CharmGRPOProjectionError("R7 pre-training admission did not pass")
    if not _load_object(generation_plan_path):
        raise CharmGRPOProjectionError("R7 canonical generation plan is empty")

    registry = _load_object(task_id_registry_path)
    entries = registry.get("entries")
    source_ids = {str(item.get("task_id")) for item in all_tasks}
    if (
        registry.get("schema_version") != "charm-task-id-reservation-registry-v1"
        or not isinstance(entries, dict)
        or len(source_ids) != SOURCE_TASK_COUNT
    ):
        raise CharmGRPOProjectionError("R7 task-ID registry is invalid")
    batch_id = source_manifest.get("generation_batch_id")
    session_id = source_manifest.get("generation_session_id")
    invalid_registry_ids = sorted(
        task_id
        for task_id in source_ids
        if not isinstance(entries.get(task_id), dict)
        or entries[task_id].get("state") not in {"admitted", "released"}
        or entries[task_id].get("generation_batch_id") != batch_id
        or entries[task_id].get("generation_session_id") != session_id
    )
    if invalid_registry_ids:
        raise CharmGRPOProjectionError(
            f"R7 source tasks are not admitted by the bound registry: {invalid_registry_ids}"
        )

    groups = selection.get("groups")
    if not isinstance(groups, dict) or set(groups) != set(GROUP_NAMES):
        raise CharmGRPOProjectionError("R7 must contain the exact four frozen groups")
    ordered_ids: list[str] = []
    group_by_id: dict[str, str] = {}
    for group in GROUP_NAMES:
        values = groups.get(group)
        if (
            not isinstance(values, list)
            or len(values) != 10
            or not all(isinstance(value, str) for value in values)
        ):
            raise CharmGRPOProjectionError(f"R7 group is not an exact ten: {group}")
        for task_id in values:
            if task_id in group_by_id:
                raise CharmGRPOProjectionError(f"R7 duplicate selected task: {task_id}")
            group_by_id[task_id] = group
            ordered_ids.append(task_id)
    if len(ordered_ids) != FULL_TASK_COUNT:
        raise CharmGRPOProjectionError("R7 selection is not exactly forty tasks")

    by_id = {str(item.get("task_id")): item for item in all_tasks}
    missing = sorted(set(ordered_ids) - set(by_id))
    if missing:
        raise CharmGRPOProjectionError(f"R7 selected tasks absent from source: {missing}")
    selected_tasks = [by_id[task_id] for task_id in ordered_ids]
    monitor_tasks = [by_id[task_id] for task_id in sorted(set(by_id) - set(ordered_ids))]
    if len(monitor_tasks) != SOURCE_TASK_COUNT - FULL_TASK_COUNT:
        raise CharmGRPOProjectionError("R7 monitor complement is not exactly eleven tasks")

    expected_full = selection.get("expected_full_composition")
    if not isinstance(expected_full, dict) or expected_full.get("task_count") != FULL_TASK_COUNT:
        raise CharmGRPOProjectionError("R7 full composition contract is missing")
    observed_full = _composition(selected_tasks)
    for field in (
        "role_counts",
        "starter_counts",
        "layout_counts",
        "header_mode_counts",
        "repair_type_counts",
        "api_capability_counts",
    ):
        _require_counter(field, observed_full[field], expected_full.get(field))
    if observed_full["multi_file_gt2"] != expected_full.get("multi_file_gt2"):
        raise CharmGRPOProjectionError("R7 full multi-file composition drift")
    _require_counter(
        "group_counts",
        Counter(group_by_id.values()),
        expected_full.get("group_counts"),
    )
    if observed_full["role_counts"]["repair_trajectory"] != 10:
        raise CharmGRPOProjectionError("R7 must bind exactly 25% certified repair tasks")

    canary_ids = selection.get("canary_task_ids")
    if (
        not isinstance(canary_ids, list)
        or len(canary_ids) != CANARY_TASK_COUNT
        or len(set(canary_ids)) != CANARY_TASK_COUNT
        or not all(isinstance(value, str) for value in canary_ids)
        or not set(canary_ids) <= set(ordered_ids)
    ):
        raise CharmGRPOProjectionError("R7 canary is not an exact twenty-task subset")
    canary_tasks = [by_id[task_id] for task_id in canary_ids]
    expected_canary = selection.get("expected_canary_composition")
    if (
        not isinstance(expected_canary, dict)
        or expected_canary.get("task_count") != CANARY_TASK_COUNT
    ):
        raise CharmGRPOProjectionError("R7 canary composition contract is missing")
    observed_canary = _composition(canary_tasks)
    for field in ("role_counts", "starter_counts", "layout_counts"):
        _require_counter(field, observed_canary[field], expected_canary.get(field))
    group_counts = Counter(group_by_id[task_id] for task_id in canary_ids)
    if group_counts != Counter(
        {group: expected_canary.get("group_count_each") for group in GROUP_NAMES}
    ):
        raise CharmGRPOProjectionError("R7 canary does not contain five tasks per group")
    header_each = int(expected_canary.get("header_mode_count_each", -1))
    if observed_canary["header_mode_counts"] != Counter(
        {
            mode: header_each
            for mode in ("editable", "extended", "frozen", "reconstructed", "repaired")
        }
    ):
        raise CharmGRPOProjectionError("R7 canary header modes are not exactly balanced")
    if set(observed_canary["repair_type_counts"]) != set(
        expected_canary.get("repair_types_present", [])
    ):
        raise CharmGRPOProjectionError("R7 canary repair mechanism coverage drift")
    if observed_canary["multi_file_gt2"] != expected_canary.get("multi_file_gt2"):
        raise CharmGRPOProjectionError("R7 canary multi-file composition drift")
    if observed_canary["role_counts"]["repair_trajectory"] != 5:
        raise CharmGRPOProjectionError("R7 canary must bind exactly 25% repair tasks")

    schedule = selection.get("schedule")
    if (
        not isinstance(schedule, dict)
        or schedule.get("full_epochs") != 3
        or schedule.get("canary_epochs") != 5
        or schedule.get("ordinary_fraction") != 0.75
        or schedule.get("repair_fraction") != 0.25
        or schedule.get("one_gradient_row_per_task") is not True
    ):
        raise CharmGRPOProjectionError("R7 schedule contract drift")

    for item in selected_tasks:
        _validate_task(item)
        lane = _role_lane(item)
        proof = _repair_proof(item)
        if (lane == "repair") != (proof is not None):
            raise CharmGRPOProjectionError(f"R7 repair-proof/lane mismatch: {item.get('task_id')}")

    return {
        "decision": "PASS",
        "selection_path": selection_path,
        "selection_sha256": sha256_file(selection_path),
        "selection": selection,
        "source_manifest": source_manifest,
        "source_manifest_path": source_manifest_path,
        "all_tasks": all_tasks,
        "selected_tasks": selected_tasks,
        "monitor_tasks": monitor_tasks,
        "ordered_ids": ordered_ids,
        "canary_ids": canary_ids,
        "group_by_id": group_by_id,
    }


def _row(
    task: AiderPolyglotTask,
    descriptor: Path,
    staging: Path,
    *,
    contract: Exact40ProjectionContract,
    base_task_id: str,
    source_role: str,
    lane: str,
    group: str | None,
    variant: str,
) -> dict[str, Any]:
    return {
        "prompt": [message.model_dump() for message in task.prompt],
        "label": task.task_id,
        "task_id": task.task_id,
        "problem_id": task.exercise,
        "split": task.split,
        "metadata": {
            "data_source": contract.dataset_kind,
            "task_id": task.task_id,
            "base_task_id": base_task_id,
            "problem_id": task.exercise,
            "split": task.split,
            "prompt_variant": variant,
            "curriculum_role": lane,
            "source_role": source_role,
            "curriculum_group": group,
            "gradient_bearing": task.split == "train",
            "group_contract": "one-task-one-frozen-prompt",
            "harness_kind": task.harness_kind,
            "task_path": descriptor.relative_to(staging).as_posix(),
            "editable_files": task.editable_files,
            "hidden_test_sha256": task.hidden_test_sha256,
            "source_prompt_sha256": task.source_prompt_sha256,
            "verification_gate": task.verification_gate,
            "family": task.family,
            "category": task.category,
            "tags": task.tags,
            "reward_policy": contract.reward_policy,
            "repair_feedback": "sanitized-and-private" if lane == "repair" else None,
        },
    }


def _schedule(rows: list[dict[str, Any]], epochs: int, phase: str) -> list[dict[str, Any]]:
    schedule: list[dict[str, Any]] = []
    for epoch in range(1, epochs + 1):
        shift = (epoch - 1) % len(rows)
        ordered = rows[shift:] + rows[:shift]
        for position, row in enumerate(ordered, 1):
            metadata = row["metadata"]
            schedule.append(
                {
                    "phase": phase,
                    "epoch": epoch,
                    "position": position,
                    "task_id": row["task_id"],
                    "base_task_id": metadata["base_task_id"],
                    "curriculum_role": metadata["curriculum_role"],
                    "curriculum_group": metadata["curriculum_group"],
                }
            )
    return schedule


def build_charm_r7_exact40_dataset(
    selection_file: str | Path,
    output_dir: str | Path,
    *,
    contract: Exact40ProjectionContract = R7_PROJECTION_CONTRACT,
    run_id: str | None = None,
    force: bool = False,
) -> dict[str, Path]:
    """Materialize the answer-free exact-40 corpus and exact-20 canary."""

    frozen = validate_r7_selection(selection_file, contract=contract)
    output = Path(output_dir).resolve()
    selection_path = frozen["selection_path"]
    if output == selection_path.parent or output in selection_path.parents:
        raise CharmGRPOProjectionError("R7 output must be separate from source evidence")
    if output.exists() and any(output.iterdir()) and not force:
        raise FileExistsError(f"{output} exists and is not empty; pass force=True")
    output.parent.mkdir(parents=True, exist_ok=True)

    selected_ids = set(frozen["ordered_ids"])
    by_id = {str(item["task_id"]): item for item in frozen["all_tasks"]}
    with TemporaryDirectory(prefix=f".{output.name}-preparing-", dir=output.parent) as value:
        staging = Path(value)
        train_by_base: dict[str, dict[str, Any]] = {}
        monitor_rows: list[dict[str, Any]] = []
        task_receipts: list[dict[str, Any]] = []
        for task_id in [*frozen["ordered_ids"], *sorted(set(by_id) - selected_ids)]:
            selected = by_id[task_id]
            source_root, rubric = _validate_task(selected)
            _materialize_exercise(source_root, rubric, staging)
            gradient = task_id in selected_ids
            lane = _role_lane(selected) if gradient else "monitor"
            variant = "repair" if lane == "repair" else "short"
            proof = _repair_proof(selected) if variant == "repair" else None
            messages = _variant_messages(source_root, rubric, variant, repair_proof=proof)
            if variant == "repair" and [item["role"] for item in messages[-2:]] != [
                "assistant",
                "user",
            ]:
                raise CharmGRPOProjectionError(f"R7 repair turn topology drift: {task_id}")
            if variant == "repair" and messages[-1]["content"] != REPAIR_FEEDBACK:
                raise CharmGRPOProjectionError(f"R7 repair feedback drift: {task_id}")
            prompt_sha = _sha256_bytes(_canonical_bytes(messages))
            descriptor_id = f"{contract.descriptor_prefix}/{task_id}/{variant}"
            task = AiderPolyglotTask(
                task_id=descriptor_id,
                exercise=task_id,
                split="train" if gradient else "validation",
                harness_kind="shadow_cpp17",
                exercise_dir=f"shadow/{task_id}",
                editable_files=rubric.editable_files,
                prompt=messages,
                source_revision=str(selected.get("tree_sha256")),
                family=rubric.family,
                category=rubric.category,
                tags=[
                    *rubric.tags,
                    f"prompt-{variant}",
                    f"curriculum-role-{lane}",
                    contract.task_tag,
                ],
                hidden_test_sha256=rubric.hidden_test_sha256,
                source_prompt_sha256=prompt_sha,
                verification_gate=contract.verification_gate,
                prompt_contract="hybrid45-isolated-wholefile-v2",
                reward_contract=contract.reward_policy,
            )
            descriptor = task.write_json(
                staging / "tasks" / task.split / task_id / f"{variant}.json"
            )
            row = _row(
                task,
                descriptor,
                staging,
                contract=contract,
                base_task_id=task_id,
                source_role=str(selected["role"]),
                lane=lane,
                group=frozen["group_by_id"].get(task_id),
                variant=variant,
            )
            if gradient:
                train_by_base[task_id] = row
            else:
                monitor_rows.append(row)
            task_receipts.append(
                {
                    "task_id": task_id,
                    "split": task.split,
                    "source_tree_sha256": selected.get("tree_sha256"),
                    "hidden_test_sha256": rubric.hidden_test_sha256,
                    "prompt_sha256": prompt_sha,
                    "curriculum_role": lane,
                    "repair_proof_sha256": selected.get("repair_trajectory_receipt_sha256"),
                }
            )

        train_rows = [train_by_base[task_id] for task_id in frozen["ordered_ids"]]
        canary_rows = [train_by_base[task_id] for task_id in frozen["canary_ids"]]
        monitor_rows.sort(key=lambda row: str(row["metadata"]["base_task_id"]))
        full_schedule = _schedule(
            train_rows, int(frozen["selection"]["schedule"]["full_epochs"]), "full"
        )
        canary_schedule = _schedule(
            canary_rows, int(frozen["selection"]["schedule"]["canary_epochs"]), "canary"
        )
        _write_jsonl(staging / "grpo" / "train.jsonl", train_rows)
        _write_jsonl(staging / "grpo" / "canary.jsonl", canary_rows)
        _write_jsonl(staging / "eval" / "task_disjoint_monitor.jsonl", monitor_rows)
        _write_jsonl(staging / "schedules" / "full-3ep.jsonl", full_schedule)
        _write_jsonl(staging / "schedules" / "canary-5ep.jsonl", canary_schedule)

        subset_manifest = {
            "schema_version": SUBSET_SCHEMA,
            "decision": "PASS",
            "selection_sha256": frozen["selection_sha256"],
            "source_manifest_sha256": sha256_file(frozen["source_manifest_path"]),
            "gradient_task_count": len(train_rows),
            "monitor_task_count": len(monitor_rows),
            "canary_task_count": len(canary_rows),
            "gradient_tasks": frozen["selected_tasks"],
            "monitor_tasks": frozen["monitor_tasks"],
            "canary_task_ids": frozen["canary_ids"],
        }
        _write_json(staging / "subset-manifest.json", subset_manifest)
        file_paths = {
            "grpo_train": "grpo/train.jsonl",
            "grpo_canary": "grpo/canary.jsonl",
            "task_disjoint_monitor": "eval/task_disjoint_monitor.jsonl",
            "full_schedule": "schedules/full-3ep.jsonl",
            "canary_schedule": "schedules/canary-5ep.jsonl",
            "subset_manifest": "subset-manifest.json",
        }
        manifest = {
            "kind": contract.dataset_kind,
            "schema_version": contract.dataset_schema,
            "decision": "PASS",
            "run_id": run_id,
            "source": {
                "selection_path": str(selection_path),
                "selection_sha256": frozen["selection_sha256"],
                "selected_manifest_path": str(frozen["source_manifest_path"]),
                "selected_manifest_sha256": sha256_file(frozen["source_manifest_path"]),
                "post_generation_admission": frozen["source_manifest"].get(
                    "post_generation_admission"
                ),
                "post_generation_uniqueness": frozen["source_manifest"].get(
                    "post_generation_uniqueness"
                ),
                "fixed26_heldout_manifest": frozen["source_manifest"].get("heldout_manifest"),
            },
            "heldout_contract": frozen["selection"]["heldout_contract"],
            "reward_contract": {
                "policy": contract.reward_policy,
                "repair_bonus": False,
                "strong_negative_syntax_api_link": True,
                "private_feedback": "sanitized",
                "official_fixed26": "unchanged external evaluation only",
            },
            "counts": {
                "certified_source_tasks": SOURCE_TASK_COUNT,
                "gradient_tasks": len(train_rows),
                "ordinary_gradient_tasks": sum(
                    row["metadata"]["curriculum_role"] != "repair" for row in train_rows
                ),
                "repair_gradient_tasks": sum(
                    row["metadata"]["curriculum_role"] == "repair" for row in train_rows
                ),
                "monitor_tasks": len(monitor_rows),
                "canary_tasks": len(canary_rows),
                "full_schedule_exposures": len(full_schedule),
                "canary_schedule_exposures": len(canary_schedule),
            },
            "files": file_paths,
            "file_sha256": {
                label: sha256_file(staging / relative) for label, relative in file_paths.items()
            },
            "task_receipts": sorted(task_receipts, key=lambda item: item["task_id"]),
        }
        _write_json(staging / "manifest.json", manifest)
        if output.exists():
            if output.is_symlink():
                raise CharmGRPOProjectionError(f"refusing to replace symlink: {output}")
            shutil.rmtree(output)
        os.replace(staging, output)

    return {
        "grpo_train": output / "grpo" / "train.jsonl",
        "grpo_canary": output / "grpo" / "canary.jsonl",
        "monitor": output / "eval" / "task_disjoint_monitor.jsonl",
        "full_schedule": output / "schedules" / "full-3ep.jsonl",
        "canary_schedule": output / "schedules" / "canary-5ep.jsonl",
        "subset_manifest": output / "subset-manifest.json",
        "manifest": output / "manifest.json",
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise CharmGRPOProjectionError(f"non-object row: {path}:{line_number}")
        rows.append(value)
    return rows


def validate_charm_r7_exact40_dataset(
    output_dir: str | Path,
    *,
    contract: Exact40ProjectionContract = R7_PROJECTION_CONTRACT,
) -> dict[str, Any]:
    """Revalidate rows, schedules, descriptors, privacy, and all digest bindings."""

    root = Path(output_dir).resolve()
    manifest_path = root / "manifest.json"
    manifest = _load_object(manifest_path)
    if (
        manifest.get("kind") != contract.dataset_kind
        or manifest.get("schema_version") != contract.dataset_schema
        or manifest.get("decision") != "PASS"
    ):
        raise CharmGRPOProjectionError("unexpected R7 dataset manifest")
    source = manifest.get("source")
    if not isinstance(source, dict):
        raise CharmGRPOProjectionError("R7 projected source binding is missing")
    selection_path = Path(str(source.get("selection_path", ""))).resolve()
    if sha256_file(selection_path) != source.get("selection_sha256"):
        raise CharmGRPOProjectionError("R7 projected selection binding drift")
    frozen = validate_r7_selection(selection_path, contract=contract)
    if sha256_file(frozen["source_manifest_path"]) != source.get("selected_manifest_sha256"):
        raise CharmGRPOProjectionError("R7 projected source-manifest binding drift")
    files = manifest.get("files")
    file_hashes = manifest.get("file_sha256")
    if not isinstance(files, dict) or not isinstance(file_hashes, dict):
        raise CharmGRPOProjectionError("R7 projected file bindings are missing")
    for label, relative in files.items():
        path = root / str(relative)
        if not path.is_file() or sha256_file(path) != file_hashes.get(label):
            raise CharmGRPOProjectionError(f"R7 projected file drift: {label}")

    train_rows = _read_jsonl(root / str(files["grpo_train"]))
    canary_rows = _read_jsonl(root / str(files["grpo_canary"]))
    monitor_rows = _read_jsonl(root / str(files["task_disjoint_monitor"]))
    expected_train = list(frozen["ordered_ids"])
    expected_canary = list(frozen["canary_ids"])
    expected_monitor = sorted(str(item["task_id"]) for item in frozen["monitor_tasks"])
    for label, rows, expected in (
        ("train", train_rows, expected_train),
        ("canary", canary_rows, expected_canary),
        ("monitor", monitor_rows, expected_monitor),
    ):
        observed = [str(row.get("metadata", {}).get("base_task_id")) for row in rows]
        if observed != expected:
            raise CharmGRPOProjectionError(f"R7 {label} row identity/order drift")
    if set(expected_train) & set(expected_monitor):
        raise CharmGRPOProjectionError("R7 gradient/monitor task overlap")

    all_rows = train_rows + monitor_rows
    if len({str(row.get("task_id")) for row in all_rows}) != len(all_rows):
        raise CharmGRPOProjectionError("R7 descriptor task IDs are not unique")
    for row in all_rows:
        metadata = row.get("metadata")
        prompt = row.get("prompt")
        if not isinstance(metadata, dict) or not isinstance(prompt, list):
            raise CharmGRPOProjectionError("R7 row lacks prompt metadata")
        descriptor = root / str(metadata.get("task_path", ""))
        task = AiderPolyglotTask.read_json(descriptor)
        if (
            task.task_id != row.get("task_id")
            or [message.model_dump() for message in task.prompt] != prompt
            or task.reward_contract != contract.reward_policy
        ):
            raise CharmGRPOProjectionError(f"R7 row/descriptor mismatch: {row.get('task_id')}")
        exercise = root / task.exercise_dir
        actual = {
            path.relative_to(exercise).as_posix() for path in exercise.rglob("*") if path.is_file()
        }
        expected_runtime_files = {".grader/test.cpp", *task.editable_files}
        if contract.require_public_api_manifest:
            expected_runtime_files.add(".grader/public_api_manifest.json")
        if actual != expected_runtime_files:
            raise CharmGRPOProjectionError(f"R7 runtime leakage: {task.task_id}")
        if sha256_file(exercise / ".grader" / "test.cpp") != task.hidden_test_sha256:
            raise CharmGRPOProjectionError(f"R7 hidden grader drift: {task.task_id}")
        combined = _canonical_bytes(prompt).lower()
        if any(marker.encode() in combined for marker in PRIVATE_PROMPT_MARKERS):
            raise CharmGRPOProjectionError(f"R7 private prompt marker: {task.task_id}")
        role = str(metadata.get("curriculum_role"))
        roles = [str(message.get("role")) for message in prompt]
        if role == "repair":
            if roles[-2:] != ["assistant", "user"] or prompt[-1].get("content") != REPAIR_FEEDBACK:
                raise CharmGRPOProjectionError(f"R7 unsafe repair topology: {task.task_id}")
        elif role in {"ordinary", "calibration", "monitor"}:
            if roles[-1:] != ["user"]:
                raise CharmGRPOProjectionError(f"R7 prompt must end in user: {task.task_id}")
        else:
            raise CharmGRPOProjectionError(f"R7 unknown curriculum role: {task.task_id}")

    for phase, path, rows, epochs in (
        ("full", root / str(files["full_schedule"]), train_rows, 3),
        ("canary", root / str(files["canary_schedule"]), canary_rows, 5),
    ):
        schedule = _read_jsonl(path)
        if len(schedule) != len(rows) * epochs:
            raise CharmGRPOProjectionError(f"R7 {phase} exposure count drift")
        expected_ids = {str(row["metadata"]["base_task_id"]) for row in rows}
        for epoch in range(1, epochs + 1):
            epoch_rows = [item for item in schedule if item.get("epoch") == epoch]
            if (
                len(epoch_rows) != len(rows)
                or {str(item.get("base_task_id")) for item in epoch_rows} != expected_ids
            ):
                raise CharmGRPOProjectionError(f"R7 {phase} epoch coverage drift: {epoch}")
            repair = sum(item.get("curriculum_role") == "repair" for item in epoch_rows)
            if repair * 4 != len(epoch_rows):
                raise CharmGRPOProjectionError(f"R7 {phase} epoch is not exact 25% repair")

    counts = manifest.get("counts")
    if not isinstance(counts, dict) or counts != {
        "certified_source_tasks": 51,
        "gradient_tasks": 40,
        "ordinary_gradient_tasks": 30,
        "repair_gradient_tasks": 10,
        "monitor_tasks": 11,
        "canary_tasks": 20,
        "full_schedule_exposures": 120,
        "canary_schedule_exposures": 100,
    }:
        raise CharmGRPOProjectionError("R7 manifest count contract drift")
    return {
        "decision": "PASS",
        "manifest_sha256": sha256_file(manifest_path),
        "selection_sha256": frozen["selection_sha256"],
        "gradient_task_count": len(train_rows),
        "repair_task_count": 10,
        "monitor_task_count": len(monitor_rows),
        "canary_task_count": len(canary_rows),
        "private_marker_count": 0,
        "task_overlap_count": 0,
    }


def verify_charm_r7_exact40_oracles(
    output_dir: str | Path,
    *,
    contract: Exact40ProjectionContract = R7_PROJECTION_CONTRACT,
    image: str = DEFAULT_AIDER_DOCKER_IMAGE,
    workers: int = 4,
) -> dict[str, Any]:
    """Verify all 51 packaged starters and references against private graders."""

    if workers < 1:
        raise ValueError("workers must be positive")
    root = Path(output_dir).resolve()
    validation = validate_charm_r7_exact40_dataset(root, contract=contract)
    manifest = _load_object(root / "manifest.json")
    frozen = validate_r7_selection(manifest["source"]["selection_path"], contract=contract)
    by_id = {str(item["task_id"]): item for item in frozen["all_tasks"]}

    def verify(task_id: str) -> dict[str, Any]:
        selected = by_id[task_id]
        source_root, rubric = _validate_task(selected)
        exercise = root / "shadow" / task_id
        starter = {
            name: (exercise / name).read_text(encoding="utf-8") for name in rubric.editable_files
        }
        reference = {
            name: (source_root / ".reference" / name).read_text(encoding="utf-8")
            for name in rubric.editable_files
        }
        starter_result = run_shadow_tests(
            exercise,
            starter,
            image=image,
            expected_test_sha256=rubric.hidden_test_sha256,
        )
        reference_result = run_shadow_tests(
            exercise,
            reference,
            image=image,
            expected_test_sha256=rubric.hidden_test_sha256,
        )
        starter_should_pass = selected.get("role") == "calibration"
        return {
            "task_id": task_id,
            "source_role": selected.get("role"),
            "starter_expected_pass": starter_should_pass,
            "starter_passed": starter_result.all_tests_pass,
            "starter_status": starter_result.status,
            "reference_passed": reference_result.all_tests_pass,
            "reference_status": reference_result.status,
            "reference_tests_passed": reference_result.tests_passed,
            "reference_tests_total": reference_result.tests_total,
            "hidden_test_sha256": rubric.hidden_test_sha256,
        }

    task_ids = sorted(by_id)
    with ThreadPoolExecutor(max_workers=min(workers, len(task_ids))) as executor:
        task_results = list(executor.map(verify, task_ids))
    failures = [
        item
        for item in task_results
        if item["reference_passed"] is not True
        or item["starter_passed"] is not item["starter_expected_pass"]
    ]
    receipt = {
        "schema_version": contract.oracle_receipt_schema,
        "decision": "PASS" if not failures else "FAIL",
        "dataset_manifest_sha256": validation["manifest_sha256"],
        "selection_sha256": validation["selection_sha256"],
        "sandbox_image": image,
        "candidate_network": "disabled-by-harness",
        "task_count": len(task_results),
        "failure_count": len(failures),
        "tasks": task_results,
    }
    receipt["receipt_sha256"] = _sha256_bytes(_canonical_bytes(receipt))
    if failures:
        raise CharmGRPOProjectionError(
            "R7 executable-oracle verification failed: "
            + ", ".join(str(item["task_id"]) for item in failures)
        )
    return receipt
