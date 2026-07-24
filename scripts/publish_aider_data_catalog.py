#!/usr/bin/env python3
"""Publish the complete Aider data/evaluation catalog to gated HF dataset repos.

The publisher deliberately separates three trust surfaces:

* answer-bearing training payloads and their lineage receipts;
* evaluator-only fixed-26 chat histories/results;
* hidden benchmark tests, runtime rubrics, reference answers, and executable
  grader oracles, which are never copied by this script. Internal review and
  verification receipts may be preserved and are labeled separately.

Every uploaded file is hashed locally and downloaded again from the committed
revision before the publication receipt is marked passed.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import hashlib
import io
import json
import os
import random
import shutil
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

from huggingface_hub import HfApi, hf_hub_download


DATA_REPO_DEFAULT = "TokenBender/glm47-aider-posttraining-data"
EVAL_REPO_DEFAULT = "TokenBender/glm47-aider-fixed26-responses"
MODAL_RESULTS_VOLUME = "w8-aider-polyglot-cpp-results"
MODAL_ASSETS_VOLUME = "glm47-assets"
BENCHMARK = {
    "name": "Aider Polyglot C++ fixed-26",
    "tasks": 26,
    "tries": 2,
    "aider_commit": "5dc9490bb35f9729ef2c95d00a19ccd30c26339c",
    "polyglot_commit": "7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f",
}


@dataclass(frozen=True)
class DatasetSpec:
    dataset_id: str
    role: str
    status: str
    rows: str
    lineage: str
    trainable: bool = False
    license_status: str = "unresolved-private-preservation-only"
    split_semantics: str = "not-applicable"
    oracle_visibility: str = (
        "internal review or verification receipts may be present; "
        "no hidden benchmark/runtime oracle"
    )
    fixed26_task_id_overlap: int | None = 0
    contamination_status: str = (
        "exact task-id clear for canonical train/validation/monitor payloads; "
        "semantic benchmark-family contamination is unresolved unless the "
        "entry audit says otherwise"
    )


@dataclass(frozen=True)
class EvalSpec:
    eval_id: str
    checkpoint: str
    pass_at_1: int | None
    multi_turn_with_error_feedback_at_2: int | None
    source_kind: str
    source: str
    receipt: str | None = None


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def require_file(path: Path, expected_sha256: str | None = None) -> Path:
    if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"missing nonempty regular file: {path}")
    if expected_sha256 and sha256_path(path) != expected_sha256:
        raise RuntimeError(f"SHA-256 mismatch: {path}")
    return path


def modal_file_bytes(
    volume_name: str, path: str, expected_sha256: str
) -> bytes:
    import modal

    payload = b"".join(modal.Volume.from_name(volume_name).read_file(path))
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise RuntimeError(
            f"Modal file SHA-256 mismatch: {volume_name}:/{path}"
        )
    return payload


def copy_file(source: Path, destination: Path) -> None:
    require_file(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def write_bytes(destination: Path, payload: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)


def deterministic_tar_gz(
    destination: Path, members: Mapping[str, bytes | Path]
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as raw:
        with gzip.GzipFile(
            filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0
        ) as zipped:
            with tarfile.open(fileobj=zipped, mode="w", format=tarfile.PAX_FORMAT) as tar:
                for name, value in sorted(members.items()):
                    payload = value.read_bytes() if isinstance(value, Path) else value
                    info = tarfile.TarInfo(PurePosixPath(name).as_posix())
                    info.size = len(payload)
                    info.mode = 0o644
                    info.mtime = 0
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    tar.addfile(info, io.BytesIO(payload))


def selected_evidence(root: Path, excluded_roots: Iterable[str] = ()) -> dict[str, Path]:
    excluded = set(excluded_roots)
    files: dict[str, Path] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink() or path.stat().st_size == 0:
            continue
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] in excluded:
            continue
        if relative.as_posix() in {
            "sft/train.jsonl",
            "validation/validation.jsonl",
            "grpo/train.jsonl",
            "eval/train_monitor.jsonl",
            "manifest.json",
        }:
            continue
        files[relative.as_posix()] = path
    return files


def add_dataset(
    stage: Path,
    spec: DatasetSpec,
    *,
    primary: Mapping[str, Path | bytes],
    evidence: Mapping[str, Path | bytes] | None = None,
    exclusions: Iterable[str] = (),
) -> dict[str, Any]:
    root = stage / "datasets" / spec.dataset_id
    file_records: dict[str, dict[str, Any]] = {}
    for relative, source in sorted(primary.items()):
        target = root / "data" / relative
        if isinstance(source, Path):
            copy_file(source, target)
        else:
            write_bytes(target, source)
        file_records[f"data/{relative}"] = {
            "sha256": sha256_path(target),
            "size_bytes": target.stat().st_size,
        }
    if evidence:
        archive = root / "evidence.tar.gz"
        deterministic_tar_gz(archive, evidence)
        file_records["evidence.tar.gz"] = {
            "sha256": sha256_path(archive),
            "size_bytes": archive.stat().st_size,
        }
    manifest = {
        "schema_version": 1,
        "kind": "glm47-aider-dataset-entry",
        "dataset_id": spec.dataset_id,
        "role": spec.role,
        "status": spec.status,
        "trainable": spec.trainable,
        "license_status": spec.license_status,
        "split_semantics": spec.split_semantics,
        "oracle_visibility": spec.oracle_visibility,
        "fixed26_task_id_overlap": spec.fixed26_task_id_overlap,
        "contamination_status": spec.contamination_status,
        "rows": spec.rows,
        "lineage": spec.lineage,
        "files": file_records,
        "excluded_from_hf": sorted(exclusions),
    }
    write_bytes(root / "manifest.json", json_bytes(manifest))
    card = (
        f"# {spec.dataset_id}\n\n"
        f"- Role: {spec.role}\n"
        f"- Status: {spec.status}\n"
        f"- Trainable: {str(spec.trainable).lower()}\n"
        f"- License status: {spec.license_status}\n"
        f"- Split semantics: {spec.split_semantics}\n"
        f"- Oracle visibility: {spec.oracle_visibility}\n"
        f"- Fixed-26 exact task-ID overlap: {spec.fixed26_task_id_overlap}\n"
        f"- Contamination status: {spec.contamination_status}\n"
        f"- Rows: {spec.rows}\n"
        f"- Lineage: {spec.lineage}\n\n"
        "This entry is access-gated. Hidden benchmark tests, runtime rubrics, "
        "reference answers, and executable grader oracles are outside the "
        "publication boundary. Any preserved internal review receipts are "
        "declared above.\n"
    )
    write_bytes(root / "README.md", card.encode())
    return manifest


def _zip_member(path: Path, member: str) -> bytes:
    require_file(path)
    with zipfile.ZipFile(path) as archive:
        return archive.read(member)


def _tar_member(path: Path, member: str) -> bytes:
    require_file(path)
    with tarfile.open(path) as archive:
        extracted = archive.extractfile(member)
        if extracted is None:
            raise RuntimeError(f"missing tar member {member} in {path}")
        return extracted.read()


def sft_v1_consumption_receipt(train_payload: bytes) -> bytes:
    rows = [
        json.loads(line)
        for line in train_payload.splitlines()
        if line.strip()
    ]
    if len(rows) != 321 or len({row["task_id"] for row in rows}) != 321:
        raise RuntimeError("SFT v1 active split must contain 321 unique task IDs")
    shuffled_indices = list(range(len(rows)))
    random.Random(42).shuffle(shuffled_indices)
    consumed_indices = shuffled_indices[:320]
    consumed_task_ids = [rows[index]["task_id"] for index in consumed_indices]
    index_sha256 = hashlib.sha256(
        ("".join(f"{index}\n" for index in consumed_indices)).encode()
    ).hexdigest()
    task_id_sha256 = hashlib.sha256(
        ("".join(f"{task_id}\n" for task_id in consumed_task_ids)).encode()
    ).hexdigest()
    if (
        index_sha256
        != "c0ca7af294eabb6ae81224fdf46b241fb48839fa0640db71e22119840966c8e0"
        or task_id_sha256
        != "4a644be44485af51eae3474b5f9294fcf83186d6ecddb9186b419e3a1e5eb815"
        or shuffled_indices[320] != 57
        or rows[57]["task_id"] != "dll-music-queue"
    ):
        raise RuntimeError("SFT v1 seed-42 consumption order does not match the run")
    return json_bytes(
        {
            "schema_version": 1,
            "kind": "glm47-aider-sft-v1-consumption-receipt",
            "train_rows": 321,
            "consumed_rows": 320,
            "batch_size": 32,
            "batches": 10,
            "shuffle": True,
            "rollout_seed": 42,
            "consumed_indices": consumed_indices,
            "consumed_index_sha256": index_sha256,
            "consumed_task_id_sha256": task_id_sha256,
            "omitted": {
                "index": 57,
                "task_id": "dll-music-queue",
            },
            "verification": (
                "Order matches the ten preserved 32-row SFT rollout dumps "
                "sft_0.pt through sft_9.pt."
            ),
        }
    )


def build_data_stage(workspace: Path, downloads: Path, stage: Path) -> list[dict[str, Any]]:
    artifacts = workspace / "artifacts"
    scratch = workspace / "scratch"
    entries: list[dict[str, Any]] = []

    v1_zip = require_file(
        downloads / "train-401-dsa.zip",
        "2efe714c454de7ba1c5fd523f5849b3c6c9af65e8e5ca5bf4cf438017fb1e03a",
    )
    v1_train = modal_file_bytes(
        MODAL_ASSETS_VOLUME,
        "aider-polyglot-cpp/sft/train.jsonl",
        "257f2aef6ccb1d3f02764eeb976c0ea233f2f36fb5b2dbd26ac8b1d4f22037a5",
    )
    v1_manifest = modal_file_bytes(
        MODAL_ASSETS_VOLUME,
        "aider-polyglot-cpp/manifest.json",
        "392d7e6656cd5da48d15a6a035fe42ed89cf09eae30ec25bbb7205b09b01e39c",
    )
    parsed_v1_manifest = json.loads(v1_manifest)
    if (
        parsed_v1_manifest.get("counts")
        != {"train": 321, "validation": 40, "test": 40}
        or parsed_v1_manifest.get("provenance", {}).get("train_sha256")
        != "257f2aef6ccb1d3f02764eeb976c0ea233f2f36fb5b2dbd26ac8b1d4f22037a5"
    ):
        raise RuntimeError("unexpected SFT v1 active-split manifest")
    entries.append(
        add_dataset(
            stage,
            DatasetSpec(
                "sft-v1-321",
                "Exact SFT v1 active split and its 401-row source lineage",
                "historical-trained",
                "401 source; 321 train; 320 consumed",
                "Deterministic 321/40/40 split of the original 401-row source",
                split_semantics=(
                    "321-row active train split; seed-42 shuffle consumed ten "
                    "complete 32-row batches and omitted active-split index 57"
                ),
                contamination_status=(
                    "fixed-26 exact task-ID overlap is zero; public benchmark-family "
                    "semantic overlap remains unresolved"
                ),
            ),
            primary={
                "source/train-401-dsa.zip": v1_zip,
                "sft/source-401.jsonl": _zip_member(v1_zip, "train.jsonl"),
                "manifest.json": v1_manifest,
                "sft/train.jsonl": v1_train,
                "consumption_receipt.json": sft_v1_consumption_receipt(v1_train),
            },
            exclusions=(
                "The unused 40-row validation and 40-row test projections and "
                "their split_manifest are not preserved.",
            ),
        )
    )

    v2_root = artifacts / "modal_pre_run_backup_20260719T190019Z" / "prepared"
    v2_train = require_file(
        v2_root / "sft/train.jsonl",
        "13219cae85551714d4280b60600bb7ef5336dffda54698340ba40f3405ccd51b",
    )
    entries.append(
        add_dataset(
            stage,
            DatasetSpec(
                "sft-v2-1211",
                "SFT training corpus",
                "historical-trained",
                "1,211 packaged; 1,184 consumed",
                "401 curated + 480 DSA + 330 puzzle rows",
            ),
            primary={
                "manifest.json": v2_root / "manifest.json",
                "sft/train.jsonl": v2_train,
            },
            evidence=selected_evidence(v2_root),
            exclusions=(
                "Raw Training_jsonl.zip sources are provenance-only and not republished.",
            ),
        )
    )

    simple_roots = (
        (
            DatasetSpec(
                "curated-heuristic-v1",
                "Candidate SFT selection",
                "review-only-not-train-ready",
                "32 rows",
                "Heuristic selection from SFT v2",
            ),
            artifacts / "aider-cpp-curated-heuristic-v1",
        ),
        (
            DatasetSpec(
                "curated-high-confidence-v1",
                "Candidate SFT selection",
                "review-only-not-train-ready",
                "14 rows",
                "High-confidence subset of curated-heuristic-v1",
            ),
            artifacts / "aider-cpp-curated-high-confidence-v1",
        ),
        (
            DatasetSpec(
                "sft-gold-v4",
                "Verified SFT candidate",
                "evaluated-candidate",
                "160 train + 22 validation",
                "75-source rows plus 85 verified signal-v3 rows",
            ),
            artifacts / "aider-cpp-sft-gold-v4",
        ),
        (
            DatasetSpec(
                "raw-concat-v1",
                "Literal concatenation SFT corpus",
                "trained-rejected",
                "875 rows; 868 unique task IDs",
                "160 Gold-v4 + 715 reverify rows; 7 duplicate task IDs",
            ),
            artifacts / "aider-cpp-raw-concat-v1",
        ),
        (
            DatasetSpec(
                "combined-v5-500",
                "Reviewed SFT candidate",
                "candidate-audit-limited",
                "500 rows",
                "182 verified anchors + 318 reviewed new rows",
            ),
            artifacts / "aider-cpp-combined-v5-500",
        ),
        (
            DatasetSpec(
                "sft-v3-complement-530",
                "SFT training corpus; strongest assisted fixed-26 parent",
                "historical-trained-promoted-parent",
                "530 packaged; 520 consumed",
                "401 original anchors + 129 verified complementary rows",
                trainable=True,
                split_semantics="train-only; fixed-26 remains external evaluation",
            ),
            artifacts / "aider-cpp-complement-530",
        ),
        (
            DatasetSpec(
                "pass1-skills-600",
                "Proposed direct-success SFT successor",
                "evaluated-candidate",
                "600 rows",
                "SFT v3 complement-530 + 70 synthetic skill rows",
            ),
            artifacts / "aider-cpp-pass1-skills-600",
        ),
    )
    promoted_train_sha256 = {
        "sft-v3-complement-530": (
            "805aa59bbc936ee20687a293ef47d2fb9bcaee12419c6539ecd6180dfab02089"
        ),
    }
    for spec, root in simple_roots:
        primary: dict[str, Path] = {}
        for relative in (
            "manifest.json",
            "sft/train.jsonl",
            "validation/validation.jsonl",
        ):
            path = root / relative
            if path.is_file():
                primary[relative] = require_file(
                    path,
                    promoted_train_sha256.get(spec.dataset_id)
                    if relative == "sft/train.jsonl"
                    else None,
                )
        entries.append(
            add_dataset(
                stage,
                spec,
                primary=primary,
                evidence=selected_evidence(root),
            )
        )

    for version, rows, role, status in (
        ("v2", "150 train + 4 validation", "Signal-focused SFT candidate", "candidate"),
        ("v3", "249 train + 6 validation", "Expanded signal-focused SFT corpus", "trained-evaluated"),
    ):
        root = artifacts / f"aider-cpp-signal-{version}"
        entries.append(
            add_dataset(
                stage,
                DatasetSpec(
                    f"signal-{version}",
                    role,
                    status,
                    rows,
                    "Answer-blind verified base tasks plus authored trajectories",
                ),
                primary={
                    "manifest.json": root / "manifest.json",
                    "sft/train.jsonl": root / "sft/train.jsonl",
                    "validation/validation.jsonl": root / "validation/validation.jsonl",
                },
                evidence=selected_evidence(root, excluded_roots=("private", "staging")),
                exclusions=(
                    "private/ reference rows",
                    "staging/ generated tests and fixtures",
                ),
            )
        )

    reverify_zip = require_file(
        downloads / "aider-tasks-reverify-sft.zip",
        "f90ff7c6c595b91f06b42c89e8d224f7f0d3786e5376ff17384aab59a13e9d38",
    )
    entries.append(
        add_dataset(
            stage,
            DatasetSpec(
                "reverify-715",
                "Audit projection and raw-concat source",
                "audit-only",
                "715 rows",
                "Reverified Aider task projection",
            ),
            primary={
                "source/aider-tasks-reverify-sft.zip": reverify_zip,
                "sft/train.jsonl": _zip_member(
                    reverify_zip, "aider-tasks-reverify-sft/sft/train.jsonl"
                ),
                "manifest.json": _zip_member(
                    reverify_zip, "aider-tasks-reverify-sft/manifest.json"
                ),
            },
        )
    )

    for audit_id, root in (
        ("reverify-audit", artifacts / "aider-tasks-reverify-audit-20260720"),
        ("regression-audit", artifacts / "aider-tasks-regression-audit-20260720"),
    ):
        evidence = {
            path.relative_to(root).as_posix(): path
            for path in sorted(root.iterdir())
            if path.is_file() and path.stat().st_size > 0
        }
        entries.append(
            add_dataset(
                stage,
                DatasetSpec(
                    audit_id,
                    "Dataset quality/audit ledger",
                    "audit-only",
                    "row-level catalog and decisions",
                    "Lineage evidence for reverify and SFT v2 remediation",
                    fixed26_task_id_overlap=None,
                    contamination_status=(
                        "not applicable to a canonical train/validation/monitor "
                        "payload; row-level audit decisions are preserved as evidence"
                    ),
                ),
                primary={},
                evidence=evidence,
                exclusions=("evidence/ benchmark trees and transcripts",),
            )
        )

    build_root = artifacts / "aider-cpp-combined-v5-build"
    entries.append(
        add_dataset(
            stage,
            DatasetSpec(
                "combined-v5-build-workbench",
                "Candidate-generation workbench",
                "lineage-only-not-a-training-dataset",
                "candidate pool and candidate variants",
                "Intermediate materialization behind combined-v5-500",
                fixed26_task_id_overlap=None,
                contamination_status=(
                    "unresolved candidate-generation workbench; not approved as "
                    "a canonical training payload"
                ),
            ),
            primary={
                "candidate_pool.jsonl": build_root / "candidate_pool.jsonl",
                "candidate_variants.jsonl": build_root / "candidate_variants.jsonl",
            },
            evidence={
                relative: build_root / relative
                for relative in (
                    "MIXTURE_DESIGN.md",
                    "MIXTURE_DESIGN_V2.md",
                    "candidate_variant_summary.json",
                    "mixture_summary.json",
                    "mixture_summary_v2.json",
                    "variant_token_summary.json",
                )
                if (build_root / relative).is_file()
            },
            exclusions=(
                "semantic_verifier/ blind packets and tests",
                "supplemental_blind_tests_v1/",
                "test_staging.jsonl",
                "semantic_judgments.jsonl",
                "executable_test_receipts.jsonl",
                "judge and mutation oracle outputs",
            ),
        )
    )

    replay = scratch / "aider-replay-data-patched"
    entries.append(
        add_dataset(
            stage,
            DatasetSpec(
                "rl-full-replay-253",
                "GRPO prompt and monitor projection",
                "prepared-not-promoted",
                "253 train + 32 monitor",
                "Projection of gated answer-free Aider C++ RL corpus",
            ),
            primary={
                "manifest.json": replay / "manifest.json",
                "grpo/train.jsonl": replay / "grpo/train.jsonl",
                "eval/train_monitor.jsonl": replay / "eval/train_monitor.jsonl",
            },
            exclusions=("rl_tasks/ task fixtures and grader tests",),
        )
    )

    rl2 = scratch / "lium-aider-2ep-fixed" / "prepared-aider-169"
    rl2_manifest = require_file(
        rl2 / "manifest.json",
        "a7e54c0245b97ae78f9b2fa57ff5278844585cf03004254137b6cfc8e91ef157",
    )
    rl2_train = require_file(
        rl2 / "grpo/train.jsonl",
        "b72394ab603b4b6faf22370ea70605446f112ab50c883eb61e308e2dd9ab4dd2",
    )
    difficulty = artifacts / "aider-rl-tasks-difficulty-20260722"
    entries.append(
        add_dataset(
            stage,
            DatasetSpec(
                "rl-difficulty-20260722",
                "Difficulty filter and selection audit",
                "audit-only-filter",
                "253 assessed; 169 kept; 84 dropped",
                "Selection audit that produced the repaired RL v2 subset",
                fixed26_task_id_overlap=None,
                contamination_status=(
                    "not applicable to a canonical training payload; this entry "
                    "contains only the difficulty-selection audit"
                ),
            ),
            primary={
                "difficulty_rows.json": difficulty / "difficulty_rows.json",
                "report.json": difficulty / "report.json",
            },
            evidence={"apply_filter.py": difficulty / "apply_filter.py"},
        )
    )

    entries.append(
        add_dataset(
            stage,
            DatasetSpec(
                "rl-v2-169",
                "Actual repaired two-epoch GRPO input",
                "historical-trained",
                "169 train + 22 monitor",
                "Difficulty-filtered subset of 253-task Aider C++ RL corpus",
                trainable=True,
                split_semantics=(
                    "monitor IDs overlap training tasks; monitor is non-gradient "
                    "training telemetry, not a held-out validation split"
                ),
            ),
            primary={
                "manifest.json": rl2_manifest,
                "grpo/train.jsonl": rl2_train,
                "eval/train_monitor.jsonl": rl2 / "eval/train_monitor.jsonl",
            },
            exclusions=("rl_tasks/ task fixtures and grader tests",),
        )
    )

    old_rl_tar = require_file(
        artifacts / "glm47-aider-grpo-20260721" / "glm47-aider-grpo-20260721.tar"
    )
    old_prefix = "glm47-aider-grpo-20260721/training/full/data"
    entries.append(
        add_dataset(
            stage,
            DatasetSpec(
                "rl-full-253-july21",
                "Earlier GRPO input preserved with the July 21 run",
                "historical-trained-not-promoted",
                "253 train + 32 monitor",
                "Pre-filter full Aider C++ RL projection",
                split_semantics=(
                    "monitor IDs overlap training tasks; monitor is non-gradient "
                    "training telemetry, not a held-out validation split"
                ),
            ),
            primary={
                "manifest.json": _tar_member(old_rl_tar, f"{old_prefix}/manifest.json"),
                "grpo/train.jsonl": _tar_member(
                    old_rl_tar, f"{old_prefix}/grpo/train.jsonl"
                ),
                "eval/train_monitor.jsonl": _tar_member(
                    old_rl_tar, f"{old_prefix}/eval/train_monitor.jsonl"
                ),
            },
            exclusions=("rl_tasks/ task fixtures and grader tests",),
        )
    )

    external = [
        {
            "dataset_id": "pie-cpp-posttraining",
            "status": "existing-gated",
            "repo": "TokenBender/glm47-pie-cpp-posttraining-data",
            "revision": "09bc0276a0ff8ab84a8db81880ca7f739057e654",
        },
        {
            "dataset_id": "aider-cpp-rl-runtime-v1",
            "status": "existing-gated-runtime-oracle-restricted",
            "repo": "TokenBender/glm47-aider-cpp-rl-tasks",
            "revision": "155587aa7200979fe8f35ea08f4ffcb6bce67201",
            "boundary": (
                "Contains rubrics and hidden executable tests; approve only RL "
                "runtime/service identities, not ordinary corpus consumers."
            ),
        },
        {
            "dataset_id": "rl8-validity-6-plus-2",
            "status": "existing-gated-framework-validity-only",
            "repo": "TokenBender/glm47-aider-rl8-validity-rollouts-20260723",
            "revision": "11451eeec5261eecdbca75e95ce190a632783654",
        },
        {
            "dataset_id": "rl-v3-failed-rollouts",
            "status": "existing-gated-failed-infrastructure",
            "repo": "TokenBender/glm47-aider-rl-v3-rollouts-20260722",
            "revision": "bcd3b747c3d5881921f269a8690def5986a56bed",
        },
    ]
    catalog = {
        "schema_version": 1,
        "kind": "glm47-aider-posttraining-data-catalog",
        "policy": {
            "repo_access": "private-manual-gated",
            "all_extant_project_payloads_mapped": True,
            "hidden_tests_oracles_republished": False,
            "gating_is_not_redistribution_authority": True,
        },
        "known_missing_payloads": [
            {
                "dataset_id": "sft-v1-321",
                "payloads": [
                    "40-row validation projection",
                    "40-row test projection",
                    "split_manifest.json",
                ],
                "impact": (
                    "These projections were not consumed by the recorded SFT run; "
                    "the exact 321-row train file and 320-row consumption order "
                    "are preserved."
                ),
            }
        ],
        "datasets": entries,
        "existing_gated_repositories": external,
    }
    write_bytes(stage / "CATALOG.json", json_bytes(catalog))
    write_bytes(
        stage / "README.md",
        (
            "# GLM-4.7 Aider post-training data\n\n"
            "Canonical private, manual-approval store for every project-tracked "
            "Aider training corpus and dataset lineage. `CATALOG.json` "
            "marks trained, candidate, rejected, audit-only, and failed artifacts "
            "without conflating them.\n\n"
            "Hidden benchmark tests, runtime rubrics, reference answers, and "
            "executable grader-oracle material are intentionally outside this "
            "repository. Internal review receipts are labeled per entry. Fixed-26 "
            f"model responses live in `{EVAL_REPO_DEFAULT}`.\n"
        ).encode(),
    )
    return entries


def _normalise_response_member(path: str) -> tuple[str, str] | None:
    parts = PurePosixPath(path).parts
    try:
        practice = parts.index("practice")
    except ValueError:
        return None
    if practice + 2 >= len(parts) or parts[practice - 2] != "cpp":
        return None
    task = parts[practice + 1]
    name = parts[-1]
    if name not in {".aider.chat.history.md", ".aider.results.json"}:
        return None
    return task, name


def local_directory_responses(roots: Iterable[Path]) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for root in roots:
        if not root.is_dir():
            raise RuntimeError(f"missing response root: {root}")
        for path in sorted(root.rglob(".aider.*")):
            normalised = _normalise_response_member(path.as_posix())
            if normalised:
                task, name = normalised
                key = f"responses/{task}/{name}"
                if key in result:
                    raise RuntimeError(f"duplicate response member: {key}")
                result[key] = path.read_bytes()
    return result


def archive_responses(path: Path, kind: str) -> tuple[dict[str, bytes], bytes | None]:
    response: dict[str, bytes] = {}
    receipt: bytes | None = None
    if kind == "zip":
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                normalised = _normalise_response_member(name)
                if normalised:
                    task, leaf = normalised
                    response[f"responses/{task}/{leaf}"] = archive.read(name)
                if name.endswith("/run_receipt.json") and "/eval/" in name:
                    receipt = archive.read(name)
    elif kind == "tar":
        with tarfile.open(path) as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                normalised = _normalise_response_member(member.name)
                extracted = archive.extractfile(member)
                if extracted is None:
                    continue
                if normalised:
                    task, leaf = normalised
                    response[f"responses/{task}/{leaf}"] = extracted.read()
                elif member.name.endswith("/evaluation/glm47-aider-cpp26-grpo-iter2-20260721/run_receipt.json"):
                    receipt = extracted.read()
    else:
        raise ValueError(kind)
    return response, receipt


def _read_modal_file(volume: Any, path: str) -> bytes:
    return b"".join(volume.read_file(path))


def modal_responses(run_id: str) -> tuple[dict[str, bytes], bytes]:
    import modal

    volume = modal.Volume.from_name(MODAL_RESULTS_VOLUME)
    run_root = f"runs/{run_id}"
    roots = list(volume.iterdir(run_root, recursive=False))
    full = [entry.path for entry in roots if entry.path.endswith("-full")]
    nested_full = [entry.path for entry in roots if entry.path.endswith("/full")]
    if not full and len(nested_full) == 1:
        full = [
            entry.path
            for entry in volume.iterdir(nested_full[0], recursive=False)
            if entry.path.endswith("-full")
        ]
    if not full:
        shard_roots = sorted(
            entry.path
            for entry in roots
            if entry.path.rsplit("/", 1)[-1].startswith("shard-")
        )
        for shard_root in shard_roots:
            candidates = [
                entry.path
                for entry in volume.iterdir(shard_root, recursive=False)
                if f"--{run_id}-shard-" in entry.path
            ]
            if len(candidates) != 1:
                raise RuntimeError(
                    f"expected one result directory in {shard_root}: {candidates}"
                )
            full.extend(candidates)
    if not full:
        raise RuntimeError(f"no result directories for {run_id}")
    task_paths: list[str] = []
    for result_root in full:
        task_root = f"{result_root}/cpp/exercises/practice"
        task_paths.extend(
            entry.path
            for entry in volume.iterdir(task_root, recursive=False)
        )
    task_paths.sort()
    if len(task_paths) != BENCHMARK["tasks"]:
        raise RuntimeError(f"{run_id}: expected 26 task directories, got {len(task_paths)}")
    remote_to_local: dict[str, str] = {}
    for task_path in task_paths:
        task = task_path.rsplit("/", 1)[-1]
        for leaf in (".aider.chat.history.md", ".aider.results.json"):
            local = f"responses/{task}/{leaf}"
            if local in remote_to_local.values():
                raise RuntimeError(f"{run_id}: duplicate response member {local}")
            remote_to_local[f"{task_path}/{leaf}"] = local
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        payloads = list(pool.map(lambda path: _read_modal_file(volume, path), remote_to_local))
    responses = {
        local: payload
        for local, payload in zip(remote_to_local.values(), payloads)
    }
    receipt = _read_modal_file(volume, f"{run_root}/run_receipt.json")
    return responses, receipt


def validate_response_set(eval_id: str, responses: Mapping[str, bytes]) -> None:
    histories = {name.split("/")[1] for name in responses if name.endswith("history.md")}
    results = {name.split("/")[1] for name in responses if name.endswith("results.json")}
    if histories != results or len(histories) != BENCHMARK["tasks"]:
        raise RuntimeError(
            f"{eval_id}: expected paired histories/results for 26 tasks; "
            f"histories={len(histories)} results={len(results)}"
        )
    for name, payload in responses.items():
        if not payload:
            raise RuntimeError(f"{eval_id}: empty response artifact: {name}")
        if name.endswith("results.json"):
            json.loads(payload)


def response_metrics(responses: Mapping[str, bytes]) -> tuple[int, int]:
    pass_at_1 = 0
    multi_turn_with_error_feedback_at_2 = 0
    for name, payload in responses.items():
        if not name.endswith("results.json"):
            continue
        outcomes = json.loads(payload).get("tests_outcomes")
        if (
            not isinstance(outcomes, list)
            or not outcomes
            or len(outcomes) > BENCHMARK["tries"]
            or any(type(outcome) is not bool for outcome in outcomes)
        ):
            raise RuntimeError(f"invalid tests_outcomes in {name}: {outcomes!r}")
        pass_at_1 += int(outcomes[0])
        multi_turn_with_error_feedback_at_2 += int(any(outcomes))
    return pass_at_1, multi_turn_with_error_feedback_at_2


def add_eval(
    stage: Path,
    spec: EvalSpec,
    responses: Mapping[str, bytes],
    receipt: bytes | None,
) -> dict[str, Any]:
    validate_response_set(spec.eval_id, responses)
    measured_pass_at_1, measured_multi_turn = response_metrics(responses)
    if (measured_pass_at_1, measured_multi_turn) != (
        spec.pass_at_1,
        spec.multi_turn_with_error_feedback_at_2,
    ):
        raise RuntimeError(
            f"{spec.eval_id}: declared pass@1/multi-turn-with-error-feedback@2 "
            f"{spec.pass_at_1}/{spec.multi_turn_with_error_feedback_at_2} "
            f"!= measured {measured_pass_at_1}/{measured_multi_turn}"
        )
    root = stage / "evals" / spec.eval_id
    archive = root / "responses.tar.gz"
    deterministic_tar_gz(archive, responses)
    files = {
        "responses.tar.gz": {
            "sha256": sha256_path(archive),
            "size_bytes": archive.stat().st_size,
        }
    }
    if receipt:
        write_bytes(root / "run_receipt.json", receipt)
        files["run_receipt.json"] = {
            "sha256": sha256_path(root / "run_receipt.json"),
            "size_bytes": (root / "run_receipt.json").stat().st_size,
        }
    manifest = {
        "schema_version": 2,
        "kind": "glm47-aider-fixed26-response-corpus",
        "eval_id": spec.eval_id,
        "checkpoint": spec.checkpoint,
        "pass_at_1": measured_pass_at_1,
        "multi_turn_with_error_feedback_at_2": measured_multi_turn,
        "task_count": BENCHMARK["tasks"],
        "history_files": BENCHMARK["tasks"],
        "result_files": BENCHMARK["tasks"],
        "benchmark": BENCHMARK,
        "source_kind": spec.source_kind,
        "source": spec.source,
        "files": files,
        "exclusions": [
            "benchmark source trees",
            "test fixtures",
            "hidden tests",
            "grader/oracle material",
        ],
    }
    write_bytes(root / "manifest.json", json_bytes(manifest))
    return manifest


def build_eval_stage(workspace: Path, stage: Path) -> list[dict[str, Any]]:
    artifacts = workspace / "artifacts"
    handover = workspace / "work" / "browser-is-all-you-need-pipe-handover"
    current = workspace / "work" / "browser-is-all-you-need-aider-upstream-pr"
    specs = (
        EvalSpec(
            "base-fixed26-20260711",
            "zai-org/GLM-4.7-Flash@7dd20894a642a0aa287e9827cb1a1f7f91386b67",
            0,
            4,
            "modal",
            "glm47-flash-aider-cpp-20260711192046",
        ),
        EvalSpec(
            "sft-v1-fixed26-20260718",
            "SFT v1 iter_0000009",
            1,
            5,
            "modal",
            "glm47-aider-v1-sft-eval-20260718",
        ),
        EvalSpec(
            "sft-v2-fixed26-20260719",
            "SFT v2 iter_0000036",
            1,
            6,
            "directory",
            str(
                artifacts
                / "aider-tasks-regression-audit-20260720"
                / "evidence/glm47-aider-1211-sft-eval-20260719"
                / "2026-07-18-19-47-05--glm47-aider-1211-sft-eval-20260719-full"
            ),
            str(
                artifacts
                / "aider-tasks-regression-audit-20260720"
                / "evidence/glm47-aider-1211-sft-eval-20260719/run_receipt.json"
            ),
        ),
        EvalSpec(
            "signal-v3-fixed26-20260719",
            "Signal v3 SFT",
            0,
            3,
            "modal",
            "glm47-aider-signal-v3-sft-eval-20260719",
        ),
        EvalSpec(
            "gold-v4-fixed26-20260720",
            "Gold v4 SFT",
            0,
            5,
            "directory",
            str(
                handover
                / "artifacts/aider-cpp-sft-gold-v4-run-20260720/eval-results"
                / "glm47-aider-gold-v4-sft-eval-20260720-r2"
                / "2026-07-19-22-14-12--glm47-aider-gold-v4-sft-eval-20260720-r2-full"
            ),
            str(
                handover
                / "artifacts/aider-cpp-sft-gold-v4-run-20260720/eval-results"
                / "glm47-aider-gold-v4-sft-eval-20260720-r2/run_receipt.json"
            ),
        ),
        EvalSpec(
            "raw-concat-v1-fixed26-20260720",
            "Raw concat v1 SFT",
            0,
            3,
            "directory",
            str(
                artifacts
                / "aider-cpp-raw-concat-v1-run-20260720/eval"
                / "glm47-aider-raw-concat-v1-sft-eval-20260720"
                / "2026-07-20-08-04-06--glm47-aider-raw-concat-v1-sft-eval-20260720-full"
            ),
            str(
                artifacts
                / "aider-cpp-raw-concat-v1-run-20260720/eval"
                / "glm47-aider-raw-concat-v1-sft-eval-20260720/run_receipt.json"
            ),
        ),
        EvalSpec(
            "combined-v5-fixed26-20260720",
            "Combined v5 fast-close SFT",
            0,
            2,
            "modal",
            "v5-fastclose-eval-20260720-2336",
        ),
        EvalSpec(
            "sft-v3-fixed26-20260721",
            "SFT v3 complement-530 iter_0000025",
            0,
            7,
            "zip",
            str(
                artifacts
                / "hf-glm47-aider-cpp-grpo-20260721/baselines"
                / "glm47-aider-complement-530-run-20260721.zip"
            ),
        ),
        EvalSpec(
            "pass1-skills-600-fixed26-20260722",
            "Pass1 skills 600 SFT",
            0,
            2,
            "modal",
            "glm47-aider-pass1-600-sft-eval-20260722",
        ),
        EvalSpec(
            "rl-july21-iter2-fixed26",
            "July 21 GRPO iter_0000002",
            0,
            2,
            "tar",
            str(
                artifacts
                / "glm47-aider-grpo-20260721/glm47-aider-grpo-20260721.tar"
            ),
        ),
        EvalSpec(
            "merged-sft-fixed26-20260722",
            "Equal-delta merged SFT v2+v3 rank-32",
            0,
            4,
            "directories",
            str(handover / "scratch/lium-merged-sft-eval/raw-benchmark"),
            str(handover / "scratch/lium-merged-sft-eval/remote-results/run_receipt.json"),
        ),
        EvalSpec(
            "rl-v2-iter0-fixed26-20260722",
            (
                "RL v2 iter_0000000@"
                "b03c280fa9e61a6b831b90a60d63979cd9666721eac316a08a90c20f8b338c1b"
            ),
            1,
            5,
            "modal",
            "glm47-aider-rl-iter0-fixed26-eval-20260722",
        ),
    )
    entries: list[dict[str, Any]] = []
    for spec in specs:
        if spec.source_kind == "modal":
            responses, receipt = modal_responses(spec.source)
        elif spec.source_kind == "directory":
            responses = local_directory_responses((Path(spec.source),))
            receipt = require_file(Path(spec.receipt)).read_bytes() if spec.receipt else None
        elif spec.source_kind == "directories":
            roots = sorted(Path(spec.source).glob("*shard-*"))
            responses = local_directory_responses(roots)
            receipt = require_file(Path(spec.receipt)).read_bytes() if spec.receipt else None
        elif spec.source_kind in {"zip", "tar"}:
            responses, receipt = archive_responses(
                require_file(Path(spec.source)), spec.source_kind
            )
        else:
            raise ValueError(spec.source_kind)
        entries.append(add_eval(stage, spec, responses, receipt))

    rl2_receipt = require_file(
        current / "docs/receipts/glm47-aider-rl-v2-fixed26-run-receipt.json",
        "0ec95a37a6957d681cf43762ac7b2dfaddaf7dbe8c3dd02ec437fb7289f48c42",
    )
    receipt_only = {
        "schema_version": 2,
        "kind": "glm47-aider-fixed26-receipt-only",
        "eval_id": "rl-v2-iter10-fixed26-20260722",
        "checkpoint": "RL v2 iter_0000010",
        "pass_at_1": 1,
        "multi_turn_with_error_feedback_at_2": 6,
        "task_count": 26,
        "benchmark": BENCHMARK,
        "status": "receipt-preserved-raw-transcripts-unrecoverable",
        "receipt_sha256": sha256_path(rl2_receipt),
    }
    receipt_root = stage / "evals" / receipt_only["eval_id"]
    copy_file(rl2_receipt, receipt_root / "run_receipt.json")
    write_bytes(receipt_root / "manifest.json", json_bytes(receipt_only))
    entries.append(receipt_only)

    catalog = {
        "schema_version": 2,
        "kind": "glm47-aider-fixed26-response-catalog",
        "access": "private-manual-gated-evaluator-only",
        "benchmark": BENCHMARK,
        "evals": entries,
        "policy": {
            "response_text_preserved": True,
            "benchmark_source_trees_preserved": False,
            "hidden_tests_oracles_republished": False,
            "training_use_prohibited": True,
        },
    }
    write_bytes(stage / "CATALOG.json", json_bytes(catalog))
    write_bytes(
        stage / "README.md",
        (
            "# GLM-4.7 Aider fixed-26 response evidence\n\n"
            "Evaluator-only, access-gated response corpora. Each complete entry "
            "contains 26 nonempty chat histories, 26 result JSON files, a "
            "manifest, and the run receipt when one survived. Benchmark source "
            "trees, tests, rubrics, and grader/oracle material are excluded.\n\n"
            "Do not use these fixed-26 responses as training data.\n"
        ).encode(),
    )
    return entries


def ensure_repo(api: HfApi, repo_id: str) -> None:
    api.create_repo(repo_id=repo_id, repo_type="dataset", private=True, exist_ok=True)
    api.update_repo_settings(
        repo_id=repo_id, repo_type="dataset", private=True, gated="manual"
    )
    info = api.dataset_info(repo_id)
    if info.private is not True or info.gated != "manual":
        raise RuntimeError(
            f"access policy mismatch for {repo_id}: "
            f"private={info.private!r} gated={info.gated!r}"
        )


def stage_manifest(stage: Path) -> dict[str, dict[str, Any]]:
    return {
        path.relative_to(stage).as_posix(): {
            "sha256": sha256_path(path),
            "size_bytes": path.stat().st_size,
        }
        for path in sorted(stage.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def upload_and_roundtrip(
    api: HfApi,
    *,
    repo_id: str,
    stage: Path,
    verify_root: Path,
    commit_message: str,
) -> dict[str, Any]:
    records = stage_manifest(stage)
    write_bytes(
        stage / "UPLOAD_MANIFEST.json",
        json_bytes(
            {
                "schema_version": 1,
                "kind": "gated-hf-upload-manifest",
                "status": "ready",
                "files": records,
            }
        ),
    )
    records = stage_manifest(stage)
    current_revision = api.dataset_info(repo_id).sha
    current_paths = set(
        api.list_repo_files(
            repo_id,
            repo_type="dataset",
            revision=current_revision,
        )
    )
    protected_generated_paths = {".gitattributes"}
    stale_paths = sorted(
        current_paths - set(records) - protected_generated_paths
    )
    commit = api.upload_folder(
        folder_path=str(stage),
        repo_id=repo_id,
        repo_type="dataset",
        commit_message=commit_message,
        delete_patterns=stale_paths or None,
        parent_commit=current_revision,
    )
    revision = str(commit.oid)
    for relative, record in sorted(records.items()):
        downloaded = Path(
            hf_hub_download(
                repo_id=repo_id,
                repo_type="dataset",
                filename=relative,
                revision=revision,
                local_dir=verify_root / repo_id.replace("/", "--"),
                force_download=True,
            )
        )
        if (
            downloaded.stat().st_size != record["size_bytes"]
            or sha256_path(downloaded) != record["sha256"]
        ):
            raise RuntimeError(f"remote round-trip mismatch: {repo_id}/{relative}")
    final_paths = set(
        api.list_repo_files(repo_id, repo_type="dataset", revision=revision)
    )
    missing_paths = set(records) - final_paths
    unexpected_paths = final_paths - set(records) - protected_generated_paths
    if missing_paths or unexpected_paths:
        raise RuntimeError(
            f"remote tree mismatch for {repo_id}: "
            f"missing={sorted(missing_paths)} unexpected={sorted(unexpected_paths)}"
        )
    info = api.dataset_info(repo_id, revision=revision)
    return {
        "repo": repo_id,
        "revision": revision,
        "private": info.private,
        "gated": info.gated,
        "files": len(records),
        "repository_files": len(final_paths),
        "bytes": sum(record["size_bytes"] for record in records.values()),
        "upload_manifest_sha256": records["UPLOAD_MANIFEST.json"]["sha256"],
        "pruned_paths": stale_paths,
        "roundtrip": "passed",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument(
        "--downloads-root", type=Path, default=Path.home() / "Downloads"
    )
    parser.add_argument("--data-repo", default=DATA_REPO_DEFAULT)
    parser.add_argument("--eval-repo", default=EVAL_REPO_DEFAULT)
    parser.add_argument("--verify-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    workspace = args.workspace_root.resolve()
    downloads = args.downloads_root.resolve()
    verify_root = args.verify_root.resolve()
    api = HfApi()
    ensure_repo(api, args.data_repo)
    ensure_repo(api, args.eval_repo)
    with tempfile.TemporaryDirectory(prefix="aider-data-catalog-") as temporary:
        root = Path(temporary)
        data_entries = build_data_stage(workspace, downloads, root / "data")
        eval_entries = build_eval_stage(workspace, root / "evals")
        data_receipt = upload_and_roundtrip(
            api,
            repo_id=args.data_repo,
            stage=root / "data",
            verify_root=verify_root,
            commit_message="Publish canonical Aider data catalog",
        )
        eval_receipt = upload_and_roundtrip(
            api,
            repo_id=args.eval_repo,
            stage=root / "evals",
            verify_root=verify_root,
            commit_message="Publish evaluator-only fixed-26 response catalog",
        )
    result = {
        "schema_version": 1,
        "kind": "glm47-aider-gated-data-publication-receipt",
        "status": "passed",
        "data": data_receipt,
        "data_entries": len(data_entries),
        "evaluations": eval_receipt,
        "evaluation_entries": len(eval_entries),
        "hidden_tests_oracles_republished": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    os.umask(0o077)
    main()
