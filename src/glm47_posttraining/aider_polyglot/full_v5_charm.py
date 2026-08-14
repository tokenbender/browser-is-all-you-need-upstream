"""Fail-closed full-v5 runtime validation and CHARM schedule construction."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .dataset import build_hybrid45_messages
from .schema import AiderPolyglotTask
from .schema import HYBRID45_POLICY_VERSION


SOURCE_PACKAGE_KIND = "aider-cpp-rl-full-v5-runtime"
SCHEDULE_KIND = "aider-cpp-rl-full-v5-charm-schedule"
EXPECTED_COUNTS = {
    "available_targets": 615,
    "train_environments": 551,
    "development_environments": 64,
    "train_prompt_variants": 661,
    "development_prompt_variants": 83,
}
FORBIDDEN_PARTS = {
    ".git",
    ".meta",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "solution",
    "solutions",
    "example",
    "examples",
}
FORBIDDEN_NAMES = {".env", ".DS_Store", "exemplar.cpp", "exemplar.h", "id_rsa", "id_ed25519"}


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.is_symlink():
            raise ValueError(f"full-v5 tree contains a symlink: {path}")
        relative = path.relative_to(root).as_posix().encode()
        data = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _tree_sha256(paths: Iterable[Path], root: Path) -> str:
    digest = hashlib.sha256()
    selected = sorted(paths)
    if not selected:
        raise ValueError(f"no oracle files found beneath {root}")
    for path in selected:
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"unsafe oracle file: {path}")
        relative = path.relative_to(root).as_posix().encode()
        data = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, 1):
            if not raw.strip():
                continue
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: JSONL row is not an object")
            rows.append(value)
    return rows


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _runtime_oracle_hash(package_dir: Path, task: AiderPolyglotTask) -> str:
    exercise = package_dir / task.exercise_dir
    if task.harness_kind == "aider_cpp17":
        return sha256_path(exercise / ".grader" / "test.cpp")
    candidates = [
        path
        for path in exercise.rglob("*")
        if path.is_file()
        and path.relative_to(exercise).as_posix() not in set(task.editable_files)
        and (
            path.name == "CMakeLists.txt"
            or path.name.endswith("_test.cpp")
            or "test" in path.parts
        )
    ]
    return _tree_sha256(candidates, exercise)


def _public_task_instructions(task: AiderPolyglotTask) -> str:
    """Extract only the current public task from the legacy Aider message stack."""

    current_user = task.prompt[-1].content
    marker = "\n####\n"
    if marker not in current_user:
        raise ValueError(f"{task.task_id}: public task/addendum boundary is missing")
    instructions, _legacy_addendum = current_user.split(marker, 1)
    instructions = instructions.strip()
    if not instructions.startswith("# "):
        raise ValueError(f"{task.task_id}: public task does not begin with a heading")
    return instructions


def validate_full_v5_package(
    package_dir: Path,
    *,
    expected_manifest_sha256: str | None = None,
    expected_tree_sha256: str | None = None,
) -> dict[str, Any]:
    """Validate the immutable answer-blind full-v5 runtime package."""

    package_dir = package_dir.resolve()
    manifest_path = package_dir / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise FileNotFoundError(f"missing regular full-v5 manifest: {manifest_path}")
    manifest_sha256 = sha256_path(manifest_path)
    if expected_manifest_sha256 and manifest_sha256 != expected_manifest_sha256:
        raise ValueError("full-v5 runtime manifest SHA-256 mismatch")
    observed_tree_sha256 = tree_sha256(package_dir)
    if expected_tree_sha256 and observed_tree_sha256 != expected_tree_sha256:
        raise ValueError("full-v5 runtime tree SHA-256 mismatch")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("kind") != SOURCE_PACKAGE_KIND:
        raise ValueError("unexpected full-v5 runtime manifest kind")
    counts = manifest.get("counts")
    if not isinstance(counts, dict):
        raise ValueError("full-v5 manifest counts are missing")
    for key, expected in EXPECTED_COUNTS.items():
        if counts.get(key) != expected:
            raise ValueError(f"full-v5 count mismatch for {key}: {counts.get(key)} != {expected}")
    contract = manifest.get("contract")
    if (
        not isinstance(contract, dict)
        or contract.get("reference_answers_packaged") is not False
        or contract.get("gold_assistant_messages_packaged") is not False
        or contract.get("fixed26_role") != "external-evaluation-only"
        or contract.get("fixed26_exact_task_id_hits") != 0
    ):
        raise ValueError("full-v5 privacy or fixed-26 contract mismatch")

    unsafe = [
        path
        for path in package_dir.rglob("*")
        if path.is_symlink()
        or path.name in FORBIDDEN_NAMES
        or any(part in FORBIDDEN_PARTS for part in path.relative_to(package_dir).parts)
    ]
    if unsafe:
        raise ValueError(f"unsafe or answer-bearing full-v5 entries: {unsafe[:5]}")

    descriptors = sorted((package_dir / "tasks").glob("*/*.json"))
    if len(descriptors) != EXPECTED_COUNTS["available_targets"]:
        raise ValueError("full-v5 descriptor count mismatch")
    tasks: dict[str, AiderPolyglotTask] = {}
    oracle_hashes: set[str] = set()
    split_counts: Counter[str] = Counter()
    for descriptor in descriptors:
        task = AiderPolyglotTask.read_json(descriptor)
        if task.task_id in tasks:
            raise ValueError(f"duplicate full-v5 task descriptor: {task.task_id}")
        expected_parent = "train" if task.split == "train" else "validation"
        if descriptor.parent.name != expected_parent:
            raise ValueError(f"{task.task_id}: descriptor split path mismatch")
        if task.harness_kind not in {"aider_cpp17", "official_cmake"}:
            raise ValueError(f"{task.task_id}: unsupported full-v5 harness")
        if not task.hidden_test_sha256:
            raise ValueError(f"{task.task_id}: missing executable-oracle digest")
        oracle_sha256 = _runtime_oracle_hash(package_dir, task)
        if oracle_sha256 != task.hidden_test_sha256:
            raise ValueError(f"{task.task_id}: executable-oracle digest mismatch")
        if oracle_sha256 in oracle_hashes:
            raise ValueError(f"{task.task_id}: executable oracle is reused")
        oracle_hashes.add(oracle_sha256)
        tasks[task.task_id] = task
        split_counts[task.split] += 1

    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ValueError("full-v5 manifest file mapping is missing")
    prompt_paths = {
        "train": package_dir / str(files.get("grpo_train", "")),
        "validation": package_dir / str(files.get("development", "")),
    }
    prompt_counts: Counter[str] = Counter()
    source_rows_by_split: dict[str, set[str]] = defaultdict(set)
    weights: dict[str, float] = defaultdict(float)
    variants: set[str] = set()
    for split, path in prompt_paths.items():
        for row in read_jsonl(path):
            metadata = row.get("metadata")
            if not isinstance(metadata, dict):
                raise ValueError("full-v5 prompt row lacks metadata")
            task_id = str(row.get("task_id", ""))
            task = tasks.get(task_id)
            if task is None or task.split != split:
                raise ValueError(f"{task_id}: prompt row split or target mismatch")
            variant_id = str(metadata.get("prompt_variant_id", ""))
            if not variant_id or variant_id in variants:
                raise ValueError(f"{task_id}: duplicate or absent prompt variant ID")
            variants.add(variant_id)
            source_row_ids = metadata.get("source_row_ids")
            if not isinstance(source_row_ids, list) or not source_row_ids:
                raise ValueError(f"{task_id}: prompt variant lacks source row IDs")
            source_rows_by_split[split].update(str(value) for value in source_row_ids)
            for name in ("prompt_contract", "response_contract", "reward_contract"):
                if metadata.get(name) != getattr(task, name):
                    raise ValueError(f"{task_id}: {name} metadata mismatch")
            weights[task_id] += float(metadata.get("sample_weight", 0.0))
            prompt_counts[split] += 1
    if source_rows_by_split["train"] & source_rows_by_split["validation"]:
        raise ValueError("full-v5 train and development source lineages overlap")
    invalid_weights = {
        task_id: value for task_id, value in weights.items() if abs(value - 1.0) > 1e-12
    }
    if invalid_weights or set(weights) != set(tasks):
        raise ValueError("full-v5 prompt-variant weights are invalid")
    expected_prompt_counts = {
        "train": EXPECTED_COUNTS["train_prompt_variants"],
        "validation": EXPECTED_COUNTS["development_prompt_variants"],
    }
    if dict(prompt_counts) != expected_prompt_counts:
        raise ValueError("full-v5 prompt counts differ from the frozen contract")
    return {
        "status": "passed",
        "manifest_sha256": manifest_sha256,
        "tree_sha256": observed_tree_sha256,
        "targets": len(tasks),
        "oracle_hashes": len(oracle_hashes),
        "prompt_variants": sum(prompt_counts.values()),
        "split_counts": dict(sorted(split_counts.items())),
        "prompt_counts": dict(sorted(prompt_counts.items())),
        "files": sum(1 for path in package_dir.rglob("*") if path.is_file()),
    }


def build_charm_schedule(
    package_dir: Path,
    output_dir: Path,
    *,
    epochs: int,
    rollout_batch_size: int,
    expected_manifest_sha256: str,
    expected_tree_sha256: str,
    selected_task_ids: Sequence[str] | None = None,
    reward_policy: str | None = None,
) -> dict[str, Any]:
    """Copy full-v5 and create a deterministic equal-exposure GRPO schedule."""

    if epochs <= 0 or rollout_batch_size <= 0:
        raise ValueError("epochs and rollout batch size must be positive")
    if reward_policy not in {None, HYBRID45_POLICY_VERSION}:
        raise ValueError(f"unsupported full-v5 schedule reward policy: {reward_policy}")
    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError(f"schedule destination already exists: {output_dir}")
    validation = validate_full_v5_package(
        package_dir,
        expected_manifest_sha256=expected_manifest_sha256,
        expected_tree_sha256=expected_tree_sha256,
    )
    source_manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))
    train_path = package_dir / str(source_manifest["files"]["grpo_train"])
    development_path = package_dir / str(source_manifest["files"]["development"])
    variants_by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in read_jsonl(train_path):
        metadata = row.get("metadata")
        if not isinstance(metadata, dict):
            raise ValueError("full-v5 schedule row lacks metadata")
        task_id = str(metadata.get("task_id") or row.get("task_id") or "")
        if not task_id:
            raise ValueError("full-v5 schedule row lacks task ID")
        variants_by_task[task_id].append(row)
    development_variants_by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in read_jsonl(development_path):
        metadata = row.get("metadata")
        if not isinstance(metadata, dict):
            raise ValueError("full-v5 development row lacks metadata")
        if reward_policy == HYBRID45_POLICY_VERSION and metadata.get("harness_kind") != "aider_cpp17":
            continue
        task_id = str(metadata.get("task_id") or row.get("task_id") or "")
        if not task_id:
            raise ValueError("full-v5 development row lacks task ID")
        development_variants_by_task[task_id].append(row)
    selected = sorted(set(selected_task_ids or variants_by_task))
    if selected_task_ids is not None and len(selected) != len(selected_task_ids):
        raise ValueError("selected canary task IDs contain duplicates")
    missing = sorted(set(selected) - set(variants_by_task))
    if missing:
        raise ValueError(f"selected full-v5 tasks are absent: {missing[:5]}")
    if len(selected) % rollout_batch_size:
        raise ValueError("rollout batch size must divide the selected task count")

    projected_tasks: dict[str, AiderPolyglotTask] = {}
    projected_prompts: dict[str, list[dict[str, str]]] = {}
    projected_prompt_sha256: dict[str, str] = {}
    projection_rows_by_task: dict[str, list[dict[str, Any]]] = {
        task_id: variants_by_task[task_id] for task_id in selected
    }
    if reward_policy == HYBRID45_POLICY_VERSION:
        projection_rows_by_task.update(development_variants_by_task)
    if reward_policy == HYBRID45_POLICY_VERSION:
        package_root = package_dir.resolve()
        for task_id, variants in sorted(projection_rows_by_task.items()):
            task_paths = {
                str(row["metadata"].get("task_path", "")) for row in variants
            }
            if len(task_paths) != 1 or not next(iter(task_paths)):
                raise ValueError(f"{task_id}: prompt variants do not bind one task path")
            relative_task_path = Path(next(iter(task_paths)))
            descriptor = (package_root / relative_task_path).resolve()
            if package_root not in descriptor.parents:
                raise ValueError(f"{task_id}: task descriptor escapes the runtime package")
            task = AiderPolyglotTask.read_json(descriptor)
            if task.task_id != task_id:
                raise ValueError(f"{task_id}: task descriptor identity mismatch")
            if task.harness_kind not in {"shadow_cpp17", "aider_cpp17"}:
                raise ValueError(
                    f"{task_id}: {HYBRID45_POLICY_VERSION} requires a five-part "
                    "aider_cpp17 executable oracle"
                )
            prompt = build_hybrid45_messages(
                package_root / task.exercise_dir,
                task.editable_files,
                public_instructions=_public_task_instructions(task),
            )
            projected = AiderPolyglotTask.model_validate(
                {
                    **task.model_dump(),
                    "prompt": prompt,
                    "prompt_contract": "hybrid45-isolated-wholefile-v2",
                    "reward_contract": HYBRID45_POLICY_VERSION,
                }
            )
            prompt_record = [message.model_dump() for message in projected.prompt]
            prompt_sha256 = hashlib.sha256(
                json.dumps(
                    prompt_record,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
            ).hexdigest()
            projected_tasks[task_id] = projected
            projected_prompts[task_id] = prompt_record
            projected_prompt_sha256[task_id] = prompt_sha256

    schedule: list[dict[str, Any]] = []
    selected_variants: set[str] = set()
    for epoch in range(1, epochs + 1):
        for task_id in selected:
            variants = sorted(
                variants_by_task[task_id],
                key=lambda row: str(row["metadata"]["prompt_variant_id"]),
            )
            row = json.loads(json.dumps(variants[(epoch - 1) % len(variants)]))
            if reward_policy == HYBRID45_POLICY_VERSION:
                metadata = row["metadata"]
                source_variant_id = str(metadata["prompt_variant_id"])
                metadata["source_prompt_variant_id"] = source_variant_id
                metadata["source_prompt_contract"] = metadata["prompt_contract"]
                metadata["source_reward_contract"] = metadata["reward_contract"]
                metadata["prompt_variant_id"] = (
                    "hybrid45-v2-" + hashlib.sha256(task_id.encode()).hexdigest()[:20]
                )
                metadata["prompt_contract"] = "hybrid45-isolated-wholefile-v2"
                metadata["reward_contract"] = HYBRID45_POLICY_VERSION
                metadata["projected_prompt_sha256"] = projected_prompt_sha256[task_id]
                row["prompt"] = projected_prompts[task_id]
            row["metadata"]["schedule_epoch"] = epoch
            row["metadata"]["schedule_target_exposure"] = epoch
            schedule.append(row)
            selected_variants.add(str(row["metadata"]["prompt_variant_id"]))

    shutil.copytree(package_dir, output_dir)
    for task_id, task in projected_tasks.items():
        task_path = str(projection_rows_by_task[task_id][0]["metadata"]["task_path"])
        task.write_json(output_dir / task_path)
    scheduled_path = output_dir / str(source_manifest["files"]["grpo_train"])
    _write_jsonl(scheduled_path, schedule)
    projected_development: list[dict[str, Any]] | None = None
    projected_development_path = output_dir / str(source_manifest["files"]["development"])
    if reward_policy == HYBRID45_POLICY_VERSION:
        projected_development = []
        for task_id, variants in sorted(development_variants_by_task.items()):
            row = json.loads(
                json.dumps(
                    min(variants, key=lambda item: str(item["metadata"]["prompt_variant_id"]))
                )
            )
            metadata = row["metadata"]
            metadata["source_prompt_variant_id"] = str(metadata["prompt_variant_id"])
            metadata["source_prompt_contract"] = metadata["prompt_contract"]
            metadata["source_reward_contract"] = metadata["reward_contract"]
            metadata["prompt_variant_id"] = (
                "hybrid45-v2-eval-" + hashlib.sha256(task_id.encode()).hexdigest()[:20]
            )
            metadata["prompt_contract"] = "hybrid45-isolated-wholefile-v2"
            metadata["reward_contract"] = HYBRID45_POLICY_VERSION
            metadata["projected_prompt_sha256"] = projected_prompt_sha256[task_id]
            row["prompt"] = projected_prompts[task_id]
            projected_development.append(row)
        _write_jsonl(projected_development_path, projected_development)
    manifest = json.loads(json.dumps(source_manifest))
    manifest["kind"] = SCHEDULE_KIND
    manifest["source_manifest_sha256"] = expected_manifest_sha256
    manifest["source_tree_sha256"] = expected_tree_sha256
    manifest["schedule"] = {
        "selection": "sorted task IDs; prompt variants round-robin by epoch",
        "epochs": epochs,
        "target_count": len(selected),
        "rows": len(schedule),
        "rollout_batch_size": rollout_batch_size,
        "num_rollout": len(schedule) // rollout_batch_size,
        "covered_prompt_variant_count": len(selected_variants),
        "row_sha256": sha256_path(scheduled_path),
        "selected_task_ids_sha256": hashlib.sha256(
            ("\n".join(selected) + "\n").encode()
        ).hexdigest(),
        "reward_policy": reward_policy or "source-contract",
    }
    if reward_policy == HYBRID45_POLICY_VERSION:
        manifest["projection"] = {
            "policy_version": HYBRID45_POLICY_VERSION,
            "prompt_contract": "hybrid45-isolated-wholefile-v2",
            "prompt_shape": "one isolated system turn plus one current-task user turn",
            "complete_editable_file_replacements_required": True,
            "source_rows_preserved_as_lineage_only": True,
            "activation_status": "EXPERIMENTAL_UNADMITTED",
            "selected_task_count": len(selected),
            "development_task_count": len(projected_development or []),
            "selected_prompt_digest_sha256": hashlib.sha256(
                ("\n".join(projected_prompt_sha256[task_id] for task_id in selected) + "\n").encode()
            ).hexdigest(),
            "development_prompt_digest_sha256": hashlib.sha256(
                (
                    "\n".join(
                        projected_prompt_sha256[task_id]
                        for task_id in sorted(development_variants_by_task)
                    )
                    + "\n"
                ).encode()
            ).hexdigest(),
        }
    manifest["counts"]["train"] = len(selected)
    manifest["counts"]["validation"] = (
        len(projected_development)
        if projected_development is not None
        else EXPECTED_COUNTS["development_environments"]
    )
    manifest["counts"]["schedule_epochs"] = epochs
    manifest["counts"]["schedule_rows"] = len(schedule)
    output_manifest = output_dir / "manifest.json"
    output_manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {
        "status": "passed",
        "kind": SCHEDULE_KIND,
        "source_validation": validation,
        "manifest_sha256": sha256_path(output_manifest),
        "train_sha256": sha256_path(scheduled_path),
        "target_count": len(selected),
        "epochs": epochs,
        "rollout_batch_size": rollout_batch_size,
        "num_rollout": len(schedule) // rollout_batch_size,
        "rows": len(schedule),
        "development_rows": (
            len(projected_development)
            if projected_development is not None
            else EXPECTED_COUNTS["development_prompt_variants"]
        ),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--package-dir", type=Path, required=True)
    validate.add_argument("--expected-manifest-sha256", required=True)
    validate.add_argument("--expected-tree-sha256", required=True)
    build = subparsers.add_parser("build-schedule")
    build.add_argument("--package-dir", type=Path, required=True)
    build.add_argument("--output-dir", type=Path, required=True)
    build.add_argument("--epochs", type=int, required=True)
    build.add_argument("--rollout-batch-size", type=int, required=True)
    build.add_argument("--expected-manifest-sha256", required=True)
    build.add_argument("--expected-tree-sha256", required=True)
    build.add_argument("--selected-task-ids", type=Path)
    build.add_argument(
        "--reward-policy",
        choices=(HYBRID45_POLICY_VERSION,),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "validate":
        result = validate_full_v5_package(
            args.package_dir,
            expected_manifest_sha256=args.expected_manifest_sha256,
            expected_tree_sha256=args.expected_tree_sha256,
        )
    else:
        selected = None
        if args.selected_task_ids:
            payload = json.loads(args.selected_task_ids.read_text(encoding="utf-8"))
            selected = payload.get("task_ids") if isinstance(payload, dict) else None
            if not isinstance(selected, list) or not all(isinstance(item, str) for item in selected):
                raise ValueError("selected-task-ids must contain a task_ids string array")
        result = build_charm_schedule(
            args.package_dir,
            args.output_dir,
            epochs=args.epochs,
            rollout_batch_size=args.rollout_batch_size,
            expected_manifest_sha256=args.expected_manifest_sha256,
            expected_tree_sha256=args.expected_tree_sha256,
            selected_task_ids=selected,
            reward_policy=args.reward_policy,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
