#!/usr/bin/env python3
"""Publish the audited SFT v6 2000 package to the canonical gated HF catalog."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from huggingface_hub import CommitOperationAdd, HfApi, hf_hub_download


REPO_ROOT = Path(__file__).resolve().parent.parent
ARTIFACT = Path(
    os.environ.get(
        "AIDER_SFT_V6_ARTIFACT_ROOT",
        REPO_ROOT / "artifacts/aider-cpp-sft-v6-2000",
    )
).resolve()
PACKAGE = ARTIFACT / "package"
REPO_ID = "TokenBender/glm47-aider-posttraining-data"
DATASET_ID = "sft-v6-audited-2000"
TRAIN_SHA256 = "debe8081a7f780afa23942e7a0ab06358aeaaba6f6006557eb5cff93779d9995"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def main() -> None:
    if sha256(PACKAGE / "sft/train.jsonl") != TRAIN_SHA256:
        raise RuntimeError("local train hash mismatch")

    api = HfApi()
    before = api.dataset_info(REPO_ID)
    if before.private is not True or before.gated != "manual":
        raise RuntimeError("destination is not private and manual-gated")

    catalog = json.loads(
        Path(
            hf_hub_download(
                REPO_ID,
                "CATALOG.json",
                repo_type="dataset",
                revision=before.sha,
            )
        ).read_text()
    )
    upload_manifest = json.loads(
        Path(
            hf_hub_download(
                REPO_ID,
                "UPLOAD_MANIFEST.json",
                repo_type="dataset",
                revision=before.sha,
            )
        ).read_text()
    )
    existing_ids = [entry["dataset_id"] for entry in catalog["datasets"]]
    existing_index = (
        existing_ids.index(DATASET_ID) if DATASET_ID in existing_ids else None
    )

    with tempfile.TemporaryDirectory(prefix="aider-sft-v6-hf-") as raw:
        stage = Path(raw)
        entry_root = stage / "datasets" / DATASET_ID
        data_root = entry_root / "data"
        file_records: dict[str, dict[str, object]] = {}
        for source in sorted(PACKAGE.rglob("*")):
            if not source.is_file() or source.is_symlink():
                continue
            relative = source.relative_to(PACKAGE)
            destination = data_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())
            key = f"data/{relative.as_posix()}"
            file_records[key] = {
                "sha256": sha256(destination),
                "size_bytes": destination.stat().st_size,
            }

        entry = {
            "schema_version": 1,
            "kind": "glm47-aider-dataset-entry",
            "dataset_id": DATASET_ID,
            "role": (
                "SFT v6 corpus for single-turn C++17 repository editing in "
                "Aider whole-file format"
            ),
            "status": "row-level-train-ready-model-benefit-not-yet-evaluated",
            "trainable": True,
            "license_status": "private-research-corpus",
            "split_semantics": "train-only; fixed-26 remains external evaluation",
            "oracle_visibility": (
                "component execution receipts are included; no fixed-26 answer, "
                "test, rubric, or grader state is included"
            ),
            "fixed26_task_id_overlap": 0,
            "contamination_status": (
                "fixed-26 exact task-ID overlap is zero; exact normalized prompt, "
                "answer, task-ID, and message duplicates are zero"
            ),
            "rows": "2000 packaged and consumed per epoch at global batch 20",
            "lineage": (
                "949 quality-cleared target-distinct v5 rows, 70 executable pass1 "
                "rows, 3 unused mutation-adequate direct rows, and 978 current-replay "
                "cross-family multi-file compositions"
            ),
            "train_sha256": TRAIN_SHA256,
            "files": file_records,
        }
        (entry_root / "manifest.json").write_bytes(json_bytes(entry))
        (entry_root / "README.md").write_text(
            "# SFT v6 audited 2000\n\n"
            "Manual-gated, row-level train-ready C++17 Aider whole-file SFT corpus. "
            "The package contains its source manifest, row catalog, executable "
            "composition receipts, duplicate audit, fixed-26 contamination audit, "
            "exact tokenizer audit, rejection ledger, and checksums. Model-level "
            "promotion still requires held-out evaluation.\n",
            encoding="utf-8",
        )

        if existing_index is None:
            catalog["datasets"].insert(
                existing_ids.index("sft-v5-experimental-1340") + 1, entry
            )
        else:
            catalog["datasets"][existing_index] = entry
        catalog_path = stage / "CATALOG.json"
        catalog_path.write_bytes(json_bytes(catalog))

        records = dict(upload_manifest["files"])
        records["CATALOG.json"] = {
            "sha256": sha256(catalog_path),
            "size_bytes": catalog_path.stat().st_size,
        }
        entry_paths = [path for path in sorted(entry_root.rglob("*")) if path.is_file()]
        for path in entry_paths:
            remote = path.relative_to(stage).as_posix()
            records[remote] = {
                "sha256": sha256(path),
                "size_bytes": path.stat().st_size,
            }
        upload_path = stage / "UPLOAD_MANIFEST.json"
        upload_path.write_bytes(
            json_bytes(
                {
                    "schema_version": 1,
                    "kind": "gated-hf-upload-manifest",
                    "status": "ready",
                    "files": dict(sorted(records.items())),
                }
            )
        )

        operations = [
            CommitOperationAdd(path_in_repo="CATALOG.json", path_or_fileobj=str(catalog_path)),
            CommitOperationAdd(
                path_in_repo="UPLOAD_MANIFEST.json", path_or_fileobj=str(upload_path)
            ),
        ] + [
            CommitOperationAdd(
                path_in_repo=path.relative_to(stage).as_posix(),
                path_or_fileobj=str(path),
            )
            for path in entry_paths
        ]
        commit = api.create_commit(
            repo_id=REPO_ID,
            repo_type="dataset",
            operations=operations,
            commit_message="Add gated audited SFT v6 2000 corpus",
            parent_commit=before.sha,
        )

        after = api.dataset_info(REPO_ID)
        if after.sha != commit.oid or after.private is not True or after.gated != "manual":
            raise RuntimeError("remote revision or access gate verification failed")
        for remote, record in sorted(records.items()):
            downloaded = Path(
                hf_hub_download(
                    REPO_ID, remote, repo_type="dataset", revision=after.sha
                )
            )
            if (
                sha256(downloaded) != record["sha256"]
                or downloaded.stat().st_size != record["size_bytes"]
            ):
                raise RuntimeError(f"round-trip mismatch: {remote}")

    receipt = {
        "schema_version": 1,
        "kind": "aider-cpp-sft-v6-2000-hf-publication",
        "status": "passed",
        "repo_id": REPO_ID,
        "dataset_id": DATASET_ID,
        "before_revision": before.sha,
        "revision": after.sha,
        "private": after.private,
        "gated": after.gated,
        "train_sha256": TRAIN_SHA256,
        "entry_files": len(entry_paths),
        "roundtrip_files": len(records),
        "roundtrip": "passed",
        "url": (
            f"https://huggingface.co/datasets/{REPO_ID}/tree/"
            f"{after.sha}/datasets/{DATASET_ID}"
        ),
    }
    (ARTIFACT / "hf_publication_receipt.json").write_bytes(json_bytes(receipt))
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
