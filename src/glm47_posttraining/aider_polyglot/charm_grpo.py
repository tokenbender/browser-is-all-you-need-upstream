"""Project independently certified CHARM tasks into an answer-free GRPO corpus.

The projector deliberately consumes an admitted or released CHARM manifest
instead of walking arbitrary task roots.  It copies only editable starter files and a
read-only hidden grader.  Reference implementations, test filenames, rubrics,
provenance, and audit internals never appear in model-facing prompt rows.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Iterable

from glm47_posttraining.aider_polyglot.dataset import build_aider_messages
from glm47_posttraining.aider_polyglot.harness import (
    DEFAULT_AIDER_DOCKER_IMAGE,
    run_shadow_tests,
)
from glm47_posttraining.aider_polyglot.schema import AiderPolyglotTask, AiderShadowRubric


DATASET_KIND = "charm-compiler-guided-cpp-grpo"
DATASET_SCHEMA = 1
SOURCE_MANIFEST_SCHEMA = "charm-topic-manifest-v1"
PROMPT_VARIANTS = ("short", "medium", "detailed")
REPAIR_VARIANT = "repair"
FORBIDDEN_RUNTIME_PATH_PARTS = {".reference", ".negative"}
PRIVATE_PROMPT_MARKERS = (
    ".reference/",
    ".grader/",
    ".rubric.json",
    "hidden_test",
    "oracle_proof",
    "negative_control",
    "expected output",
)

# The matrix is private curriculum metadata.  The task prompts do not contain
# these labels, and the mappings are analogies rather than copies of the held-out
# fmtlib implementation.  One distinct clean-room task is held out per cell.
MECHANISM_MONITOR_TASKS: tuple[tuple[str, str], ...] = (
    ("checked-conversion-helper", "charm-v1-wrapped-elapsed-counter"),
    ("arithmetic-category-dispatch", "charm-v1-stable-complex-quotient"),
    ("declaration-placement", "charm-v1-rotating-sensitivity-mask"),
    ("direct-time-conversion", "charm-v1-offset-civil-clock"),
    ("generic-overload-contract", "charm-v1-duplicate-side-traversal"),
    ("alternate-time-path", "charm-v1-weekly-window-intersection"),
    ("fractional-numeric-path", "charm-v1-complex-polynomial"),
    ("legacy-path-migration", "charm-v1-checkpointed-overdraft"),
    ("remainder-and-boundary-path", "charm-v1-configurable-dice-score"),
    ("internal-representation-conversion", "charm-v1-extension-canonicalizer"),
    ("root-state-transition", "charm-v1-generation-overwrite-ring"),
    ("mirrored-path-consistency", "charm-v1-stable-partition-repair"),
)

MEDIUM_ADDENDUM = """

Before responding, preserve every declared public API and edit only the supplied
files.  The result must compile as strict C++17 with -Wall -Wextra -Werror and
-pedantic.  Check normal, boundary, invalid-input, and state-transition behavior.
"""

DETAILED_ADDENDUM = """

Use this implementation audit before responding:
1. Inventory every editable file, public declaration, definition, and caller.
2. Preserve namespaces, visibility, signatures, types, qualifiers, and headers.
3. Place declarations after their dependencies and before every use.
4. Preserve balanced preprocessor branches, braces, overloads, and return paths.
5. Use only the standard library and C++17-compatible syntax.
6. Centralize repeated conversions or validation only when all callers migrate.
7. Check signedness, overflow, narrowing, fractional, and boundary arithmetic.
8. Keep equivalent primary and alternate code paths behaviorally consistent.
9. Return complete replacements for changed editable files and no other files.
10. Re-read the complete response for compile structure before finishing.
"""


class CharmGRPOProjectionError(ValueError):
    """A certified source or privacy invariant failed."""


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def tree_sha256(root: Path) -> str:
    files = {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
    receipt_bytes = (
        json.dumps(files, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    return _sha256_bytes(receipt_bytes)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_bytes(value))


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        for row in rows:
            handle.write(_canonical_bytes(row))


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CharmGRPOProjectionError(f"expected JSON object: {path}")
    return value


def _require_binding(binding: Any, label: str) -> Path:
    if not isinstance(binding, dict):
        raise CharmGRPOProjectionError(f"{label} binding is missing")
    path = Path(str(binding.get("path", ""))).resolve()
    if not path.is_file() or sha256_file(path) != binding.get("sha256"):
        raise CharmGRPOProjectionError(f"missing or stale {label} binding: {path}")
    return path


def _validate_source_manifest(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = _load_object(path)
    if (
        manifest.get("schema_version") != SOURCE_MANIFEST_SCHEMA
        or manifest.get("decision") != "PASS"
        or manifest.get("task_count") != 51
    ):
        raise CharmGRPOProjectionError(
            "projector requires the final PASS charm-topic-manifest-v1 with 51 tasks"
        )
    tasks = manifest.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 51 or not all(
        isinstance(item, dict) for item in tasks
    ):
        raise CharmGRPOProjectionError("certified manifest task collection is invalid")
    ids = [str(item.get("task_id")) for item in tasks]
    if len(set(ids)) != 51:
        raise CharmGRPOProjectionError("certified manifest has duplicate task IDs")

    admission_path = _require_binding(
        manifest.get("post_generation_admission"), "post-generation admission"
    )
    uniqueness_path = _require_binding(
        manifest.get("post_generation_uniqueness"), "post-generation uniqueness"
    )
    _require_binding(manifest.get("heldout_manifest"), "fixed heldout manifest")
    admission = _load_object(admission_path)
    uniqueness = _load_object(uniqueness_path)
    if admission.get("decision") != "PASS" or admission.get("stage") != "post-generation":
        raise CharmGRPOProjectionError("post-generation admission did not pass")
    if uniqueness.get("decision") != "PASS" or any(
        uniqueness.get(field) != 0
        for field in (
            "task_id_matches",
            "exact_matches",
            "near_matches",
            "structural_matches",
            "semantic_matches",
            "ambiguous_matches",
        )
    ):
        raise CharmGRPOProjectionError("post-generation uniqueness did not pass cleanly")
    return manifest, tasks


def _validate_task(selected: dict[str, Any]) -> tuple[Path, AiderShadowRubric]:
    task_id = str(selected.get("task_id"))
    root = Path(str(selected.get("root", ""))).resolve()
    if (
        not root.is_dir()
        or root.is_symlink()
        or root.name != task_id
        or not ({"incoming", "released"} & set(root.parts))
        or tree_sha256(root) != selected.get("tree_sha256")
    ):
        raise CharmGRPOProjectionError(f"admitted task tree drift: {task_id}")
    rubric = AiderShadowRubric.read_json(root / ".rubric.json")
    if rubric.task_id != task_id or rubric.verification_stage != "passed":
        raise CharmGRPOProjectionError(f"rubric identity or verification drift: {task_id}")
    hidden = root / rubric.hidden_test_file
    if not hidden.is_file() or hidden.is_symlink() or sha256_file(hidden) != rubric.hidden_test_sha256:
        raise CharmGRPOProjectionError(f"hidden grader drift: {task_id}")
    instructions = root / ".docs" / "instructions.md"
    if (
        not instructions.is_file()
        or instructions.is_symlink()
        or sha256_file(instructions) != rubric.source_prompt_sha256
    ):
        raise CharmGRPOProjectionError(f"public prompt drift: {task_id}")
    for name in rubric.editable_files:
        editable = root / name
        if not editable.is_file() or editable.is_symlink() or editable.parent != root:
            raise CharmGRPOProjectionError(f"editable source drift: {task_id}/{name}")
    return root, rubric


def _variant_messages(
    root: Path,
    rubric: AiderShadowRubric,
    variant: str,
    *,
    repair_proof: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    messages = build_aider_messages(root, rubric.editable_files)
    if variant == "medium":
        messages[-1]["content"] += MEDIUM_ADDENDUM
    elif variant == "detailed":
        messages[-1]["content"] += MEDIUM_ADDENDUM + DETAILED_ADDENDUM
    elif variant == REPAIR_VARIANT:
        if repair_proof is None:
            raise CharmGRPOProjectionError(f"repair variant lacks proof: {rubric.task_id}")
        proof_messages = repair_proof.get("messages")
        if (
            repair_proof.get("decision") != "PASS"
            or repair_proof.get("task_id") != rubric.task_id
            or repair_proof.get("message_roles") != ["user", "assistant", "user", "assistant"]
            or not isinstance(proof_messages, list)
            or len(proof_messages) != 4
        ):
            raise CharmGRPOProjectionError(f"invalid certified repair proof: {rubric.task_id}")
        failing_response = proof_messages[1].get("content")
        public_feedback = proof_messages[2].get("content")
        feedback_receipt = repair_proof.get("public_feedback")
        if (
            not isinstance(failing_response, str)
            or public_feedback
            != "Private tests failed. Private test names and output are intentionally withheld."
            or not isinstance(feedback_receipt, dict)
            or feedback_receipt.get("private_details_disclosed") is not False
        ):
            raise CharmGRPOProjectionError(f"unsafe certified repair feedback: {rubric.task_id}")
        messages.extend(
            [
                {"role": "assistant", "content": failing_response},
                {"role": "user", "content": public_feedback},
            ]
        )
    elif variant != "short":
        raise CharmGRPOProjectionError(f"unknown prompt variant: {variant}")
    _assert_model_facing_prompt(messages, rubric)
    return messages


def _assert_model_facing_prompt(messages: list[dict[str, str]], rubric: AiderShadowRubric) -> None:
    if not messages or messages[-1].get("role") != "user":
        raise CharmGRPOProjectionError(f"prompt does not end in a user turn: {rubric.task_id}")
    combined = "\n".join(str(item.get("content", "")) for item in messages).lower()
    found = [marker for marker in PRIVATE_PROMPT_MARKERS if marker.lower() in combined]
    if found:
        raise CharmGRPOProjectionError(
            f"private marker leaked into model prompt for {rubric.task_id}: {found}"
        )


def _repair_proof(selected: dict[str, Any]) -> dict[str, Any] | None:
    repair_types = selected.get("repair_types")
    if not isinstance(repair_types, list) or not repair_types:
        return None
    binding_path = selected.get("repair_trajectory_receipt_path")
    binding_sha = selected.get("repair_trajectory_receipt_sha256")
    path = Path(str(binding_path)).resolve()
    if not path.is_file() or sha256_file(path) != binding_sha:
        raise CharmGRPOProjectionError(
            f"missing or stale repair proof: {selected.get('task_id')}"
        )
    return _load_object(path)


def _materialize_exercise(root: Path, rubric: AiderShadowRubric, output: Path) -> Path:
    destination = output / "shadow" / rubric.task_id
    grader = destination / ".grader"
    grader.mkdir(parents=True)
    for name in rubric.editable_files:
        shutil.copy2(root / name, destination / name)
    hidden = grader / "test.cpp"
    shutil.copy2(root / rubric.hidden_test_file, hidden)
    hidden.chmod(0o400)
    actual = {
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file()
    }
    expected = {".grader/test.cpp", *rubric.editable_files}
    if actual != expected or any(
        part in FORBIDDEN_RUNTIME_PATH_PARTS
        for path in actual
        for part in Path(path).parts
    ):
        raise CharmGRPOProjectionError(f"unsafe runtime package layout: {rubric.task_id}")
    return destination


def _prompt_row(
    task: AiderPolyglotTask,
    descriptor: Path,
    staging: Path,
    *,
    base_task_id: str,
    variant: str,
    mechanism_id: str | None,
) -> dict[str, Any]:
    return {
        "prompt": [message.model_dump() for message in task.prompt],
        "label": task.task_id,
        "task_id": task.task_id,
        "problem_id": task.exercise,
        "split": task.split,
        "metadata": {
            "data_source": DATASET_KIND,
            "task_id": task.task_id,
            "base_task_id": base_task_id,
            "problem_id": task.exercise,
            "split": task.split,
            "prompt_variant": variant,
            "group_contract": "one-task-one-prompt-variant",
            "harness_kind": task.harness_kind,
            "task_path": descriptor.relative_to(staging).as_posix(),
            "editable_files": task.editable_files,
            "hidden_test_sha256": task.hidden_test_sha256,
            "source_prompt_sha256": task.source_prompt_sha256,
            "verification_gate": task.verification_gate,
            "family": task.family,
            "category": task.category,
            "tags": task.tags,
            "mechanism_monitor_id": mechanism_id,
        },
    }


def _variants_for(selected: dict[str, Any]) -> tuple[str, ...]:
    repair_types = selected.get("repair_types")
    return (*PROMPT_VARIANTS, REPAIR_VARIANT) if isinstance(repair_types, list) and repair_types else PROMPT_VARIANTS


def build_charm_grpo_dataset(
    selected_manifest: str | Path,
    output_dir: str | Path,
    *,
    profile: str = "charm-compiler-guided-3ep",
    run_id: str | None = None,
    force: bool = False,
    train_limit: int | None = None,
    eval_limit: int | None = None,
    sort_by_size: bool = False,
) -> dict[str, Path]:
    """Build a digest-bound GRPO corpus from the final certified CHARM release."""

    manifest_path = Path(selected_manifest).resolve()
    source_manifest, selected_tasks = _validate_source_manifest(manifest_path)
    output = Path(output_dir).resolve()
    if output == manifest_path.parent or output in manifest_path.parents:
        raise CharmGRPOProjectionError("output must be separate from source evidence")
    if output.exists() and any(output.iterdir()) and not force:
        raise FileExistsError(f"{output} exists and is not empty; pass force=True to replace it")

    monitor_by_task = {task_id: mechanism for mechanism, task_id in MECHANISM_MONITOR_TASKS}
    all_ids = {str(item["task_id"]) for item in selected_tasks}
    missing_monitor = sorted(set(monitor_by_task) - all_ids)
    if missing_monitor:
        raise CharmGRPOProjectionError(f"mechanism monitor tasks missing: {missing_monitor}")

    calibration_ids = {
        str(item["task_id"]) for item in selected_tasks if item.get("role") == "calibration"
    }
    train_selected = [
        item
        for item in selected_tasks
        if str(item["task_id"]) not in monitor_by_task
        and str(item["task_id"]) not in calibration_ids
    ]
    eval_selected = [item for item in selected_tasks if str(item["task_id"]) in monitor_by_task]
    train_selected.sort(key=lambda item: str(item["task_id"]))
    eval_selected.sort(key=lambda item: str(item["task_id"]))
    if train_limit is not None:
        if train_limit < 1:
            raise CharmGRPOProjectionError("train_limit must be positive")
        train_selected = train_selected[:train_limit]
    if eval_limit is not None:
        if eval_limit < 1:
            raise CharmGRPOProjectionError("eval_limit must be positive")
        eval_selected = eval_selected[:eval_limit]
    if not train_selected or not eval_selected:
        raise CharmGRPOProjectionError("projection requires non-empty train and monitor splits")

    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=f".{output.name}-preparing-", dir=output.parent) as temporary:
        staging = Path(temporary)
        train_rows: list[dict[str, Any]] = []
        eval_rows: list[dict[str, Any]] = []
        task_receipts: list[dict[str, Any]] = []

        for split, collection, destination_rows in (
            ("train", train_selected, train_rows),
            ("validation", eval_selected, eval_rows),
        ):
            for selected in collection:
                root, rubric = _validate_task(selected)
                _materialize_exercise(root, rubric, staging)
                proof = _repair_proof(selected)
                row_hashes: dict[str, str] = {}
                for variant in _variants_for(selected):
                    messages = _variant_messages(root, rubric, variant, repair_proof=proof)
                    prompt_sha = _sha256_bytes(_canonical_bytes(messages))
                    variant_task_id = f"charm-grpo/{rubric.task_id}/{variant}"
                    task = AiderPolyglotTask(
                        task_id=variant_task_id,
                        exercise=rubric.task_id,
                        split=split,
                        harness_kind="shadow_cpp17",
                        exercise_dir=f"shadow/{rubric.task_id}",
                        editable_files=rubric.editable_files,
                        prompt=messages,
                        source_revision=str(selected.get("tree_sha256")),
                        family=rubric.family,
                        category=rubric.category,
                        tags=[*rubric.tags, f"prompt-{variant}", "clean-room-charm"],
                        hidden_test_sha256=rubric.hidden_test_sha256,
                        source_prompt_sha256=prompt_sha,
                        verification_gate="charm-independent-audit-plus-hidden-grader-v1",
                    )
                    descriptor = task.write_json(
                        staging / "tasks" / split / rubric.task_id / f"{variant}.json"
                    )
                    row = _prompt_row(
                        task,
                        descriptor,
                        staging,
                        base_task_id=rubric.task_id,
                        variant=variant,
                        mechanism_id=monitor_by_task.get(rubric.task_id),
                    )
                    row_hashes[variant] = _sha256_bytes(_canonical_bytes(row["prompt"]))
                    destination_rows.append(row)
                task_receipts.append(
                    {
                        "task_id": rubric.task_id,
                        "split": split,
                        "source_tree_sha256": selected.get("tree_sha256"),
                        "hidden_test_sha256": rubric.hidden_test_sha256,
                        "prompt_variants": row_hashes,
                        "repair_proof_sha256": selected.get("repair_trajectory_receipt_sha256"),
                    }
                )

        if sort_by_size:
            train_rows.sort(
                key=lambda row: (
                    len(_canonical_bytes(row["prompt"])),
                    str(row["task_id"]),
                )
            )
        else:
            train_rows.sort(key=lambda row: str(row["task_id"]))
        eval_rows.sort(key=lambda row: str(row["task_id"]))

        _write_jsonl(staging / "grpo" / "train.jsonl", train_rows)
        _write_jsonl(staging / "eval" / "mechanism_monitor.jsonl", eval_rows)
        _write_jsonl(staging / "eval" / "train_monitor.jsonl", eval_rows)
        matrix = {
            "schema_version": "charm-cleanroom-mechanism-monitor-v1",
            "decision": "PASS",
            "interpretation": (
                "clean-room skill analogies only; the exact public-PR mechanisms remain held out"
            ),
            "cells": [
                {
                    "mechanism_id": mechanism,
                    "task_id": task_id,
                    "prompt_variants": list(
                        _variants_for(next(item for item in eval_selected if item["task_id"] == task_id))
                    ),
                }
                for mechanism, task_id in MECHANISM_MONITOR_TASKS
                if task_id in {str(item["task_id"]) for item in eval_selected}
            ],
        }
        _write_json(staging / "eval" / "mechanism_matrix.json", matrix)

        prompt_variant_counts = Counter(
            str(row["metadata"]["prompt_variant"]) for row in train_rows
        )
        manifest = {
            "kind": DATASET_KIND,
            "schema_version": DATASET_SCHEMA,
            "decision": "PASS",
            "profile": profile,
            "run_id": run_id,
            "source": {
                "selected_manifest_path": str(manifest_path),
                "selected_manifest_sha256": sha256_file(manifest_path),
                "generation_batch_id": source_manifest.get("generation_batch_id"),
                "post_generation_admission": source_manifest.get("post_generation_admission"),
                "post_generation_uniqueness": source_manifest.get("post_generation_uniqueness"),
                "fixed26_heldout_manifest": source_manifest.get("heldout_manifest"),
            },
            "split_contract": {
                "train": "certified clean-room tasks; three prompt lengths plus certified repair prompts",
                "monitor": "twelve task-disjoint clean-room mechanism analogies; no gradients",
                "excluded_calibration_task_ids": sorted(calibration_ids),
                "official_fixed26": "external evaluation only",
                "public_pr_r5": "external evaluation only; no prompt, patch, probe, or expected output copied",
                "train_monitor_task_overlap": [],
            },
            "group_contract": {
                "samples_within_group_share_exact_prompt": True,
                "task_and_prompt_variant_form_group_identity": True,
                "prompt_variants_are_never_mixed_within_group": True,
            },
            "reward_contract": {
                "executable_hidden_grader_required": True,
                "strict_cpp17_werror": True,
                "reference_answers_packaged": False,
                "candidate_network": "disabled by harness",
                "private_feedback": "redacted",
            },
            "counts": {
                "certified_source_tasks": len(selected_tasks),
                "gradient_tasks": len({row["metadata"]["base_task_id"] for row in train_rows}),
                "gradient_rows": len(train_rows),
                "monitor_tasks": len({row["metadata"]["base_task_id"] for row in eval_rows}),
                "monitor_rows": len(eval_rows),
                "excluded_calibration_tasks": len(calibration_ids),
            },
            "prompt_variant_counts": dict(sorted(prompt_variant_counts.items())),
            "files": {
                "grpo_train": "grpo/train.jsonl",
                "mechanism_monitor": "eval/mechanism_monitor.jsonl",
                "train_monitor": "eval/train_monitor.jsonl",
                "mechanism_matrix": "eval/mechanism_matrix.json",
            },
            "task_receipts": sorted(task_receipts, key=lambda item: item["task_id"]),
        }
        _write_json(staging / "manifest.json", manifest)

        if output.exists():
            if output.is_symlink():
                raise CharmGRPOProjectionError(f"refusing to replace symlink output: {output}")
            shutil.rmtree(output)
        os.replace(staging, output)

    return {
        "grpo_train": output / "grpo" / "train.jsonl",
        "eval": output / "eval" / "mechanism_monitor.jsonl",
        "train_monitor": output / "eval" / "train_monitor.jsonl",
        "mechanism_matrix": output / "eval" / "mechanism_matrix.json",
        "manifest": output / "manifest.json",
    }


def validate_projected_dataset(output_dir: str | Path) -> dict[str, Any]:
    """Revalidate a materialized corpus without trusting its manifest claims."""

    root = Path(output_dir).resolve()
    manifest_path = root / "manifest.json"
    manifest = _load_object(manifest_path)
    if manifest.get("kind") != DATASET_KIND or manifest.get("decision") != "PASS":
        raise CharmGRPOProjectionError("unexpected projected dataset manifest")
    row_paths = (root / "grpo" / "train.jsonl", root / "eval" / "mechanism_monitor.jsonl")
    rows: list[dict[str, Any]] = []
    for path in row_paths:
        for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise CharmGRPOProjectionError(f"non-object row: {path}:{line_number}")
            rows.append(value)
    task_ids = [str(row.get("task_id")) for row in rows]
    if len(task_ids) != len(set(task_ids)):
        raise CharmGRPOProjectionError("projected prompt-group IDs are not unique")
    for row in rows:
        metadata = row.get("metadata")
        prompt = row.get("prompt")
        if not isinstance(metadata, dict) or not isinstance(prompt, list):
            raise CharmGRPOProjectionError("projected row lacks prompt metadata")
        task_path = root / str(metadata.get("task_path", ""))
        task = AiderPolyglotTask.read_json(task_path)
        descriptor_prompt = [message.model_dump() for message in task.prompt]
        if task.task_id != row.get("task_id") or descriptor_prompt != prompt:
            raise CharmGRPOProjectionError(f"row/descriptor mismatch: {row.get('task_id')}")
        exercise = root / task.exercise_dir
        actual = {
            path.relative_to(exercise).as_posix()
            for path in exercise.rglob("*")
            if path.is_file()
        }
        if actual != {".grader/test.cpp", *task.editable_files}:
            raise CharmGRPOProjectionError(f"runtime exercise leakage: {task.task_id}")
        if sha256_file(exercise / ".grader" / "test.cpp") != task.hidden_test_sha256:
            raise CharmGRPOProjectionError(f"runtime hidden grader drift: {task.task_id}")
        combined = _canonical_bytes(prompt).lower()
        if any(marker.encode() in combined for marker in PRIVATE_PROMPT_MARKERS):
            raise CharmGRPOProjectionError(f"private prompt marker: {task.task_id}")
    train_bases = {
        str(row["metadata"]["base_task_id"])
        for row in rows
        if row.get("split") == "train"
    }
    monitor_bases = {
        str(row["metadata"]["base_task_id"])
        for row in rows
        if row.get("split") == "validation"
    }
    if train_bases & monitor_bases:
        raise CharmGRPOProjectionError("gradient and monitor task roots overlap")
    return {
        "decision": "PASS",
        "manifest_sha256": sha256_file(manifest_path),
        "row_count": len(rows),
        "train_task_count": len(train_bases),
        "monitor_task_count": len(monitor_bases),
        "private_marker_count": 0,
        "task_overlap_count": 0,
    }


def verify_projected_oracles(
    output_dir: str | Path,
    *,
    image: str = DEFAULT_AIDER_DOCKER_IMAGE,
    workers: int = 4,
) -> dict[str, Any]:
    """Execute each projected starter and certified reference against its hidden grader."""

    if workers < 1:
        raise ValueError("workers must be positive")
    root = Path(output_dir).resolve()
    validation = validate_projected_dataset(root)
    projected = _load_object(root / "manifest.json")
    source_path = Path(str(projected["source"]["selected_manifest_path"])).resolve()
    if sha256_file(source_path) != projected["source"]["selected_manifest_sha256"]:
        raise CharmGRPOProjectionError("projected source-manifest binding drift")
    _source, selected = _validate_source_manifest(source_path)
    selected_by_id = {str(item["task_id"]): item for item in selected}
    runtime_ids = sorted(
        path.name for path in (root / "shadow").iterdir() if path.is_dir()
    )

    def verify(task_id: str) -> dict[str, Any]:
        selected_task = selected_by_id[task_id]
        source_root, rubric = _validate_task(selected_task)
        exercise = root / "shadow" / task_id
        starter = {
            name: (exercise / name).read_text(encoding="utf-8")
            for name in rubric.editable_files
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
        return {
            "task_id": task_id,
            "starter_rejected": not starter_result.all_tests_pass,
            "starter_status": starter_result.status,
            "reference_passed": reference_result.all_tests_pass,
            "reference_status": reference_result.status,
            "reference_tests_passed": reference_result.tests_passed,
            "reference_tests_total": reference_result.tests_total,
            "hidden_test_sha256": rubric.hidden_test_sha256,
        }

    with ThreadPoolExecutor(max_workers=min(workers, len(runtime_ids))) as executor:
        task_results = list(executor.map(verify, runtime_ids))
    failures = [
        item
        for item in task_results
        if item["starter_rejected"] is not True or item["reference_passed"] is not True
    ]
    receipt = {
        "schema_version": "charm-grpo-executable-oracle-receipt-v1",
        "decision": "PASS" if not failures else "FAIL",
        "dataset_manifest_sha256": validation["manifest_sha256"],
        "sandbox_image": image,
        "task_count": len(task_results),
        "starter_rejected_count": sum(item["starter_rejected"] is True for item in task_results),
        "reference_passed_count": sum(item["reference_passed"] is True for item in task_results),
        "failure_task_ids": [str(item["task_id"]) for item in failures],
        "private_logs_disclosed": False,
        "tasks": sorted(task_results, key=lambda item: str(item["task_id"])),
    }
    if failures:
        raise CharmGRPOProjectionError(
            "projected executable reward separation failed: "
            + ", ".join(str(item["task_id"]) for item in failures)
        )
    return receipt
