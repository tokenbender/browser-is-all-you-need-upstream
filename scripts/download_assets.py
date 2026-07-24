#!/usr/bin/env python3
"""Download canonical datasets, evaluation evidence, and adapters from Hugging Face."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tarfile
from pathlib import Path, PurePosixPath

from huggingface_hub import HfApi, snapshot_download


ASSETS = {
    "model": {
        "repo_id": "zai-org/GLM-4.7-Flash",
        "repo_type": "model",
        "revision_env": "GLM47_MODEL_REVISION",
        "default_revision": "7dd20894a642a0aa287e9827cb1a1f7f91386b67",
        "destination": "GLM-4.7-Flash",
        "verify_checksums": False,
    },
    "data": {
        "repo_id": "TokenBender/glm47-pie-cpp-posttraining-data",
        "repo_type": "dataset",
        "revision_env": "GLM47_DATA_REVISION",
        "default_revision": "09bc0276a0ff8ab84a8db81880ca7f739057e654",
        "destination": "data",
        "verify_checksums": True,
    },
    "sft": {
        "repo_id": "TokenBender/glm47-flash-pie-cpp-lora-r16-sft-h100",
        "repo_type": "model",
        "revision_env": "GLM47_SFT_REVISION",
        "default_revision": "f1ac8df367080cc040f7cf769db219ee58f20f63",
        "destination": "adapters/sft",
        "verify_checksums": True,
    },
    "grpo": {
        "repo_id": "TokenBender/glm47-flash-pie-cpp-lora-r16-grpo-h100",
        "repo_type": "model",
        "revision_env": "GLM47_GRPO_REVISION",
        "default_revision": "1fbac6f6fd59829a64776937102351c6318a7fd4",
        "destination": "adapters/grpo",
        "verify_checksums": True,
    },
    "aider-rl-tasks": {
        "repo_id": "TokenBender/glm47-aider-cpp-rl-tasks",
        "repo_type": "dataset",
        "revision_env": "GLM47_AIDER_RL_TASKS_REVISION",
        "default_revision": "155587aa7200979fe8f35ea08f4ffcb6bce67201",
        "destination": "aider-rl-tasks",
        "verify_checksums": True,
    },
    "aider-data": {
        "repo_id": "TokenBender/glm47-aider-posttraining-data",
        "repo_type": "dataset",
        "revision_env": "GLM47_AIDER_DATA_REVISION",
        "default_revision": "27b7f1f43a123fe958104a5ba896f2ed3348ff43",
        "destination": "aider-data",
        "verify_checksums": False,
        "verify_upload_manifest": True,
    },
    "aider-responses": {
        "repo_id": "TokenBender/glm47-aider-fixed26-responses",
        "repo_type": "dataset",
        "revision_env": "GLM47_AIDER_RESPONSES_REVISION",
        "default_revision": "53a7e4f41b72bdbe7c67db4408bca6796d33ceb3",
        "destination": "aider-responses",
        "verify_checksums": False,
        "verify_upload_manifest": True,
    },
}

DEFAULT_ASSETS = ("data", "sft", "grpo")


def _verify_checksums(root: Path) -> None:
    checksum_file = root / "SHA256SUMS"
    if not checksum_file.is_file():
        raise FileNotFoundError(f"Missing checksum manifest: {checksum_file}")
    for line in checksum_file.read_text().splitlines():
        expected, relative_path = line.split(maxsplit=1)
        relative_path = relative_path.removeprefix("*").removeprefix("./")
        path = root / relative_path
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
        actual = digest.hexdigest()
        if actual != expected:
            raise RuntimeError(f"Checksum mismatch for {path}: {actual} != {expected}")


def _verify_upload_manifest(root: Path) -> None:
    manifest_path = root / "UPLOAD_MANIFEST.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Missing upload manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("kind") != "gated-hf-upload-manifest"
        or manifest.get("status") != "ready"
    ):
        raise RuntimeError(f"Unexpected upload manifest: {manifest_path}")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise RuntimeError(f"Upload manifest has no files: {manifest_path}")
    for relative_path, record in sorted(files.items()):
        relative = PurePosixPath(relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"Unsafe upload-manifest path: {relative_path}")
        path = root.joinpath(*relative.parts)
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError(f"Missing regular file: {path}")
        if path.stat().st_size != record.get("size_bytes"):
            raise RuntimeError(f"Size mismatch for {path}")
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
        actual = digest.hexdigest()
        if actual != record.get("sha256"):
            raise RuntimeError(f"Checksum mismatch for {path}")
    actual_paths = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if (path.is_file() or path.is_symlink())
        and path.relative_to(root).parts[0] != ".cache"
    }
    unexpected_paths = actual_paths - set(files) - {
        ".gitattributes",
        "UPLOAD_MANIFEST.json",
    }
    if unexpected_paths:
        raise RuntimeError(
            f"Files absent from upload manifest: {sorted(unexpected_paths)}"
        )


def _verify_aider_catalog(root: Path, name: str) -> None:
    catalog_path = root / "CATALOG.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    if name == "aider-data":
        datasets = catalog.get("datasets")
        if (
            catalog.get("kind") != "glm47-aider-posttraining-data-catalog"
            or not isinstance(datasets, list)
            or len(datasets) != 21
        ):
            raise RuntimeError("Aider data catalog does not bind exactly 21 entries")
        trainable = {
            entry["dataset_id"] for entry in datasets if entry.get("trainable") is True
        }
        if trainable != {
            "sft-v3-complement-530",
            "sft-v4-holistic-790",
            "sft-v5-experimental-1340",
            "rl-v2-169",
        }:
            raise RuntimeError(f"Unexpected trainable Aider datasets: {trainable}")
    elif name == "aider-responses":
        evaluations = catalog.get("evals")
        if (
            catalog.get("kind") != "glm47-aider-fixed26-response-catalog"
            or not isinstance(evaluations, list)
            or len(evaluations) != 16
            or catalog.get("policy", {}).get("training_use_prohibited") is not True
        ):
            raise RuntimeError("Aider response catalog policy or entry count mismatch")


def _extract_task_archive(root: Path) -> Path:
    archive = root / "tasks.tar.gz"
    destination = root / "tasks"
    if not archive.is_file():
        raise FileNotFoundError(f"Missing task archive: {archive}")

    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    destination_root = destination.resolve()

    with tarfile.open(archive, "r:gz") as handle:
        for member in handle.getmembers():
            if member.issym() or member.islnk():
                raise RuntimeError(f"Task archive contains a link: {member.name}")
            target = (destination / member.name).resolve()
            if target != destination_root and destination_root not in target.parents:
                raise RuntimeError(f"Task archive escapes destination: {member.name}")
        handle.extractall(destination, filter="data")

    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    expected = int(manifest["counts"]["copied_tasks"])
    actual = sum(1 for path in destination.rglob("*.json") if path.is_file())
    if actual != expected:
        raise RuntimeError(f"Extracted task count mismatch: {actual} != {expected}")
    return destination


def _extract_aider_rl_archive(root: Path) -> Path:
    artifact_manifest = json.loads(
        (root / "artifact_manifest.json").read_text(encoding="utf-8")
    )
    if artifact_manifest.get("kind") != "glm47-aider-cpp-rl-runtime-archive":
        raise RuntimeError("unexpected Aider C++ RL artifact kind")
    if artifact_manifest.get("counts", {}).get("tasks") != 253:
        raise RuntimeError("Aider C++ RL artifact does not bind exactly 253 tasks")
    archive_name = str(artifact_manifest.get("archive") or "")
    archive_root = str(artifact_manifest.get("archive_root") or "")
    if archive_name != "aider-cpp-rl-runtime.tar.gz":
        raise RuntimeError(f"unexpected Aider C++ RL archive name: {archive_name!r}")
    if archive_root != "aider_cpp_rl_tasks":
        raise RuntimeError(f"unexpected Aider C++ RL archive root: {archive_root!r}")

    archive = root / archive_name
    destination = root / "tasks"
    if not archive.is_file():
        raise FileNotFoundError(f"Missing Aider C++ RL archive: {archive}")
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    destination_root = destination.resolve()

    with tarfile.open(archive, "r:gz") as handle:
        for member in handle.getmembers():
            if not (member.isdir() or member.isfile()):
                raise RuntimeError(
                    f"Aider C++ RL archive contains an unsupported entry: {member.name}"
                )
            target = (destination / member.name).resolve()
            if target != destination_root and destination_root not in target.parents:
                raise RuntimeError(f"Aider C++ RL archive escapes destination: {member.name}")
        handle.extractall(destination, filter="data")

    extracted = destination / archive_root
    source_manifest = json.loads((extracted / "manifest.json").read_text(encoding="utf-8"))
    if source_manifest.get("kind") != "aider-cpp-rl-rubrics":
        raise RuntimeError("unexpected extracted Aider C++ RL manifest kind")
    if source_manifest.get("counts", {}).get("tasks") != 253:
        raise RuntimeError("extracted Aider C++ RL manifest does not bind 253 tasks")
    actual = sum(1 for path in extracted.rglob(".rubric.json") if path.is_file())
    if actual != 253:
        raise RuntimeError(f"Extracted Aider C++ RL task count mismatch: {actual} != 253")
    actual_files = sum(1 for path in extracted.rglob("*") if path.is_file())
    expected_files = artifact_manifest.get("counts", {}).get("files")
    if actual_files != expected_files:
        raise RuntimeError(
            f"Extracted Aider C++ RL file count mismatch: {actual_files} != {expected_files}"
        )
    extracted_manifest_sha256 = hashlib.sha256(
        (extracted / "manifest.json").read_bytes()
    ).hexdigest()
    if extracted_manifest_sha256 != artifact_manifest.get("source_manifest_sha256"):
        raise RuntimeError("extracted Aider C++ RL manifest checksum mismatch")
    return extracted


def _download(name: str, output_root: Path, verify: bool) -> Path:
    asset = ASSETS[name]
    destination = output_root / asset["destination"]
    revision = os.environ.get(asset["revision_env"], asset["default_revision"])
    if name in {"aider-rl-tasks", "aider-data", "aider-responses"}:
        resolved = HfApi().dataset_info(asset["repo_id"], revision=revision).sha
        if resolved != revision:
            raise RuntimeError(f"{name} revision mismatch: {resolved} != {revision}")
    snapshot_download(
        repo_id=asset["repo_id"],
        repo_type=asset["repo_type"],
        revision=revision,
        local_dir=destination,
    )
    if verify and asset["verify_checksums"]:
        _verify_checksums(destination)
    if verify and asset.get("verify_upload_manifest"):
        _verify_upload_manifest(destination)
    if name == "data":
        _extract_task_archive(destination)
    elif name == "aider-rl-tasks":
        _extract_aider_rl_archive(destination)
    elif name in {"aider-data", "aider-responses"}:
        _verify_aider_catalog(destination, name)
    print(f"{name}: {destination}")
    return destination


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("asset", choices=[*ASSETS, "all"], nargs="?", default="all")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(".glm47-posttraining/assets"),
    )
    parser.add_argument("--no-verify", action="store_true")
    args = parser.parse_args()

    names = list(DEFAULT_ASSETS) if args.asset == "all" else [args.asset]
    for name in names:
        _download(name, args.output_root, verify=not args.no_verify)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
