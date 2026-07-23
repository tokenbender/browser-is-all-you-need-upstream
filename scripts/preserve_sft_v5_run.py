#!/usr/bin/env python3
"""Preserve the SFT-v5 checkpoint and fixed-26 responses on gated HF repos.

The response publication boundary is deliberately narrow: chat histories,
result JSON, run/shard receipts, and server logs are preserved; benchmark
source trees, fixtures, tests, rubrics, and grader/oracle material are not.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from huggingface_hub import (
    CommitOperationAdd,
    HfApi,
    hf_hub_download,
)


EVAL_REPO = "TokenBender/glm47-aider-fixed26-responses"
MODEL_REPO = "TokenBender/glm47-aider-sft-v5-1340-modal-3ep"
EVAL_ID = "sft-v5-experimental-1340-3ep-fixed26-20260723"
TRAIN_RUN_ID = "glm47-aider-sft-v5-1340-modal-3ep-20260723T210506Z"
EVAL_RUN_ID = "glm47-aider-sft-v5-1340-modal-3ep-fixed26-20260723T221500Z"
TRAIN_SOURCE_COMMIT = "0bb26d2d0b281ad0be623d650c21f9a83667ca32"
RECORDED_GATE_SOURCE_COMMIT = "7a81e7112c8f550d7173ee1d35ee2aac9e01d9b1"
ADAPTER_SHA256 = "bdd808bf98d26b467af7fec1a20d7ed6502bac0ffd50eae9cb6a1e702613daaa"
CONFIG_SHA256 = "0bd6d85f88fc42fefa52627b3c261f1ad58bb2c9519332ae8034dd5dffe2498e"
DATA_MANIFEST_SHA256 = "0906e1abcec775ca52362679fe39d83af9ac1744c984faf1125f4de0c7b2e130"
TRAIN_JSONL_SHA256 = "a01a07c9d4e2706683814a3d5afc2bcd47172ff92b08f15e2c673729f185bd66"
BENCHMARK = {
    "name": "Aider Polyglot C++ fixed-26",
    "tasks": 26,
    "tries": 2,
    "aider_commit": "5dc9490bb35f9729ef2c95d00a19ccd30c26339c",
    "polyglot_commit": "7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f",
}


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {"sha256": sha256_path(path), "size_bytes": path.stat().st_size}


def deterministic_tar_gz(members: dict[str, Path], destination: Path) -> None:
    with destination.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode="w", format=tarfile.PAX_FORMAT) as tar:
                for name, path in sorted(members.items()):
                    payload = path.read_bytes()
                    info = tarfile.TarInfo(PurePosixPath(name).as_posix())
                    info.size = len(payload)
                    info.mode = 0o644
                    info.mtime = 0
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    tar.addfile(info, io.BytesIO(payload))


def collect_responses(results_root: Path) -> tuple[dict[str, Path], list[dict[str, Any]]]:
    members: dict[str, Path] = {}
    outcomes: list[dict[str, Any]] = []
    for result in sorted(results_root.rglob(".aider.results.json")):
        payload = json.loads(result.read_text())
        task = payload["testcase"]
        history = result.with_name(".aider.chat.history.md")
        if not history.is_file() or not history.stat().st_size:
            raise RuntimeError(f"missing history for {task}")
        tests = payload.get("tests_outcomes")
        if not isinstance(tests, list) or not tests or len(tests) > 2:
            raise RuntimeError(f"invalid outcomes for {task}: {tests!r}")
        members[f"tasks/{task}/.aider.results.json"] = result
        members[f"tasks/{task}/.aider.chat.history.md"] = history
        outcomes.append({"task": task, "tests_outcomes": tests})
    if len(outcomes) != 26 or len(members) != 52:
        raise RuntimeError(f"expected 26 complete response pairs, got {len(outcomes)}")
    for name in ("run_receipt.json",):
        members[f"receipts/{name}"] = results_root / name
    for shard in range(2):
        for name in ("shard_receipt.json", "sglang.log"):
            path = results_root / f"shard-{shard}" / name
            if not path.is_file() or not path.stat().st_size:
                raise RuntimeError(f"missing {path}")
            members[f"receipts/shard-{shard}/{name}"] = path
    return members, outcomes


def correction_receipt() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "glm47-aider-source-provenance-correction",
        "status": "corrected-with-original-retained",
        "run_id": TRAIN_RUN_ID,
        "field": "source_commit",
        "recorded_value": RECORDED_GATE_SOURCE_COMMIT,
        "correct_value": TRAIN_SOURCE_COMMIT,
        "evidence": [
            "Training was launched from work/modal-sft-v5-7a81e71.",
            "Commit 0bb26d2 was created at 2026-07-23T21:04:46Z.",
            "The detached Modal launch began at 2026-07-23T21:05Z.",
            "The sft_training_gate.json was manually authored after training.",
        ],
        "integrity_note": (
            "The original gate and completed evaluation receipt are retained "
            "unchanged. Adapter and data hashes remain the evaluation binding."
        ),
    }


def preserve_eval(api: HfApi, results_root: Path, temporary: Path) -> dict[str, Any]:
    info = api.dataset_info(EVAL_REPO)
    if info.private is not True or info.gated != "manual":
        raise RuntimeError(f"{EVAL_REPO} must remain private and manually gated")
    catalog_path = Path(
        hf_hub_download(
            repo_id=EVAL_REPO,
            repo_type="dataset",
            filename="CATALOG.json",
            revision=info.sha,
        )
    )
    upload_manifest_path = Path(
        hf_hub_download(
            repo_id=EVAL_REPO,
            repo_type="dataset",
            filename="UPLOAD_MANIFEST.json",
            revision=info.sha,
        )
    )
    catalog = json.loads(catalog_path.read_text())
    upload_manifest = json.loads(upload_manifest_path.read_text())
    existing = next(
        (entry for entry in catalog["evals"] if entry["eval_id"] == EVAL_ID),
        None,
    )
    if existing is not None:
        for name, record in existing["files"].items():
            downloaded = Path(
                hf_hub_download(
                    repo_id=EVAL_REPO,
                    repo_type="dataset",
                    filename=f"evals/{EVAL_ID}/{name}",
                    revision=info.sha,
                )
            )
            if file_record(downloaded) != record:
                raise RuntimeError(f"existing response round-trip mismatch: {name}")
        return {
            "repo": EVAL_REPO,
            "revision": info.sha,
            "status": "passed-already-present",
            "eval_id": EVAL_ID,
            "archive_sha256": existing["files"]["responses.tar.gz"]["sha256"],
            "history_files": existing["history_files"],
            "result_files": existing["result_files"],
            "hidden_tests_oracles_republished": False,
            "roundtrip": "passed",
        }

    members, outcomes = collect_responses(results_root)
    correction = temporary / "provenance_correction.json"
    correction.write_bytes(json_bytes(correction_receipt()))
    members["receipts/provenance_correction.json"] = correction
    archive = temporary / "responses.tar.gz"
    deterministic_tar_gz(members, archive)
    run_receipt = results_root / "run_receipt.json"
    measured_p1 = sum(row["tests_outcomes"][0] for row in outcomes)
    measured_p2 = sum(any(row["tests_outcomes"]) for row in outcomes)
    if (measured_p1, measured_p2) != (2, 5):
        raise RuntimeError(f"unexpected measured result: {(measured_p1, measured_p2)}")

    entry = {
        "schema_version": 1,
        "kind": "glm47-aider-fixed26-response-corpus",
        "eval_id": EVAL_ID,
        "checkpoint": f"{TRAIN_RUN_ID}/iter_0000200@{ADAPTER_SHA256}",
        "pass_at_1": measured_p1,
        "pass_at_2": measured_p2,
        "task_count": 26,
        "history_files": 26,
        "result_files": 26,
        "benchmark": BENCHMARK,
        "source_kind": "modal",
        "source": EVAL_RUN_ID,
        "training_data_manifest_sha256": DATA_MANIFEST_SHA256,
        "files": {},
        "exclusions": [
            "benchmark source trees",
            "test fixtures",
            "hidden tests",
            "grader/oracle material",
        ],
    }
    eval_root = temporary / "eval"
    eval_root.mkdir()
    eval_files = {
        "responses.tar.gz": archive,
        "run_receipt.json": run_receipt,
        "provenance_correction.json": correction,
    }
    entry["files"] = {name: file_record(path) for name, path in eval_files.items()}
    manifest = eval_root / "manifest.json"
    manifest.write_bytes(json_bytes(entry))
    eval_files["manifest.json"] = manifest
    catalog["evals"].append(entry)
    catalog["evals"].sort(key=lambda row: row["eval_id"])
    new_catalog = temporary / "CATALOG.json"
    new_catalog.write_bytes(json_bytes(catalog))

    remote_files = {
        f"evals/{EVAL_ID}/{name}": path for name, path in eval_files.items()
    }
    remote_files["CATALOG.json"] = new_catalog
    for name, path in remote_files.items():
        upload_manifest["files"][name] = file_record(path)
    new_upload_manifest = temporary / "UPLOAD_MANIFEST.json"
    new_upload_manifest.write_bytes(json_bytes(upload_manifest))
    remote_files["UPLOAD_MANIFEST.json"] = new_upload_manifest

    commit = api.create_commit(
        repo_id=EVAL_REPO,
        repo_type="dataset",
        parent_commit=info.sha,
        commit_message="Preserve SFT v5 fixed-26 response evidence",
        operations=[
            CommitOperationAdd(path_in_repo=name, path_or_fileobj=str(path))
            for name, path in sorted(remote_files.items())
        ],
    )
    for name, path in remote_files.items():
        downloaded = Path(
            hf_hub_download(
                repo_id=EVAL_REPO,
                repo_type="dataset",
                filename=name,
                revision=commit.oid,
                force_download=True,
            )
        )
        if file_record(downloaded) != file_record(path):
            raise RuntimeError(f"round-trip mismatch: {name}")
    final = api.dataset_info(EVAL_REPO, revision=commit.oid)
    if final.private is not True or final.gated != "manual":
        raise RuntimeError("response repository access policy changed")
    return {
        "repo": EVAL_REPO,
        "revision": commit.oid,
        "status": "passed",
        "eval_id": EVAL_ID,
        "archive_sha256": sha256_path(archive),
        "history_files": 26,
        "result_files": 26,
        "hidden_tests_oracles_republished": False,
    }


def preserve_model(
    api: HfApi, checkpoint_root: Path, training_root: Path, temporary: Path
) -> dict[str, Any]:
    adapter = checkpoint_root / "adapter_model.bin"
    config = checkpoint_root / "adapter_config.json"
    if sha256_path(adapter) != ADAPTER_SHA256 or sha256_path(config) != CONFIG_SHA256:
        raise RuntimeError("checkpoint identity mismatch")
    api.create_repo(MODEL_REPO, private=True, exist_ok=True)
    api.update_repo_settings(MODEL_REPO, private=True, gated="manual")
    info = api.model_info(MODEL_REPO)
    if info.private is not True or info.gated != "manual":
        raise RuntimeError(f"{MODEL_REPO} must be private and manually gated")

    files: dict[str, Path] = {}
    for path in sorted(checkpoint_root.iterdir()):
        if path.is_file() and path.stat().st_size:
            files[f"checkpoint/{path.name}"] = path
    for path in sorted(training_root.iterdir()):
        if path.is_file() and path.stat().st_size:
            files[f"training-evidence/{path.name}"] = path
    correction = temporary / "model_provenance_correction.json"
    correction.write_bytes(json_bytes(correction_receipt()))
    files["training-evidence/provenance_correction.json"] = correction
    manifest_value = {
        "schema_version": 1,
        "kind": "glm47-aider-sft-checkpoint-manifest",
        "run_id": TRAIN_RUN_ID,
        "training_source_commit": TRAIN_SOURCE_COMMIT,
        "data_manifest_sha256": DATA_MANIFEST_SHA256,
        "train_jsonl_sha256": TRAIN_JSONL_SHA256,
        "adapter_sha256": ADAPTER_SHA256,
        "files": {name: file_record(path) for name, path in files.items()},
    }
    manifest = temporary / "model_manifest.json"
    manifest.write_bytes(json_bytes(manifest_value))
    files["MANIFEST.json"] = manifest
    readme = temporary / "model_README.md"
    readme.write_text(
        "---\nlicense: other\ngated_fields:\n- email\n---\n\n"
        "# GLM-4.7-Flash Aider C++ SFT v5\n\n"
        "Private, manually gated preservation of the final three-epoch LoRA "
        "checkpoint and training evidence for the 1,340-row SFT v5 run. "
        "See `MANIFEST.json` for immutable identities and "
        "`training-evidence/provenance_correction.json` for the retained "
        "post-hoc gate correction.\n"
    )
    files["README.md"] = readme
    if "MANIFEST.json" in api.list_repo_files(MODEL_REPO, revision=info.sha):
        remote_manifest = Path(
            hf_hub_download(
                repo_id=MODEL_REPO,
                filename="MANIFEST.json",
                revision=info.sha,
            )
        )
        if json.loads(remote_manifest.read_text()) == manifest_value:
            for name in (
                "MANIFEST.json",
                "checkpoint/adapter_config.json",
                "checkpoint/adapter_model.bin",
            ):
                downloaded = Path(
                    hf_hub_download(
                        repo_id=MODEL_REPO,
                        filename=name,
                        revision=info.sha,
                    )
                )
                if file_record(downloaded) != file_record(files[name]):
                    raise RuntimeError(f"existing model round-trip mismatch: {name}")
            return {
                "repo": MODEL_REPO,
                "revision": info.sha,
                "status": "passed-already-present",
                "files": len(files),
                "adapter_sha256": ADAPTER_SHA256,
                "roundtrip_verified": [
                    "MANIFEST.json",
                    "checkpoint/adapter_config.json",
                    "checkpoint/adapter_model.bin",
                ],
            }
    existing = set(api.list_repo_files(MODEL_REPO, revision=info.sha))
    target = set(files) | {".gitattributes"}
    delete_operations = []
    if existing - target:
        from huggingface_hub import CommitOperationDelete

        delete_operations = [
            CommitOperationDelete(path_in_repo=name) for name in sorted(existing - target)
        ]
    commit = api.create_commit(
        repo_id=MODEL_REPO,
        parent_commit=info.sha,
        commit_message="Preserve SFT v5 final checkpoint and evidence",
        operations=delete_operations
        + [
            CommitOperationAdd(path_in_repo=name, path_or_fileobj=str(path))
            for name, path in sorted(files.items())
        ],
    )
    for name in ("MANIFEST.json", "checkpoint/adapter_config.json", "checkpoint/adapter_model.bin"):
        downloaded = Path(
            hf_hub_download(
                repo_id=MODEL_REPO,
                filename=name,
                revision=commit.oid,
                force_download=True,
            )
        )
        if file_record(downloaded) != file_record(files[name]):
            raise RuntimeError(f"model round-trip mismatch: {name}")
    final = api.model_info(MODEL_REPO, revision=commit.oid)
    if final.private is not True or final.gated != "manual":
        raise RuntimeError("checkpoint repository access policy changed")
    return {
        "repo": MODEL_REPO,
        "revision": commit.oid,
        "status": "passed",
        "files": len(files),
        "adapter_sha256": ADAPTER_SHA256,
        "roundtrip_verified": [
            "MANIFEST.json",
            "checkpoint/adapter_config.json",
            "checkpoint/adapter_model.bin",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--checkpoint-root", type=Path, required=True)
    parser.add_argument("--training-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Validate local identities and outcomes without changing HF repositories.",
    )
    args = parser.parse_args()
    if args.verify_only:
        _, outcomes = collect_responses(args.results_root.resolve())
        measured = {
            "pass_at_1": sum(row["tests_outcomes"][0] for row in outcomes),
            "pass_at_2": sum(any(row["tests_outcomes"]) for row in outcomes),
        }
        if measured != {"pass_at_1": 2, "pass_at_2": 5}:
            raise RuntimeError(f"unexpected measured result: {measured}")
        checkpoint_root = args.checkpoint_root.resolve()
        if (
            sha256_path(checkpoint_root / "adapter_model.bin") != ADAPTER_SHA256
            or sha256_path(checkpoint_root / "adapter_config.json") != CONFIG_SHA256
        ):
            raise RuntimeError("checkpoint identity mismatch")
        result = {
            "schema_version": 1,
            "kind": "glm47-aider-sft-v5-local-verification",
            "status": "passed",
            "tasks": len(outcomes),
            **measured,
            "adapter_sha256": ADAPTER_SHA256,
            "hidden_tests_oracles_selected": False,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(json_bytes(result))
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    api = HfApi()
    with tempfile.TemporaryDirectory(prefix="preserve-sft-v5-") as directory:
        temporary = Path(directory)
        eval_receipt = preserve_eval(api, args.results_root.resolve(), temporary)
        model_receipt = preserve_model(
            api,
            args.checkpoint_root.resolve(),
            args.training_root.resolve(),
            temporary,
        )
    receipt = {
        "schema_version": 1,
        "kind": "glm47-aider-sft-v5-preservation-receipt",
        "status": "passed",
        "training_source_commit": TRAIN_SOURCE_COMMIT,
        "provenance_correction": correction_receipt(),
        "responses": eval_receipt,
        "checkpoint": model_receipt,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(json_bytes(receipt))
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    os.umask(0o077)
    main()
