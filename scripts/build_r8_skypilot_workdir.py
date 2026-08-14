#!/usr/bin/env python3
"""Build a minimal, digest-verified SkyPilot transport for the frozen R8 source."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tarfile
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from glm47_posttraining.aider_polyglot.effective_source import (  # noqa: E402
    validate_effective_source_manifest,
)


DEFAULT_PROFILE_REL = (
    "configs/full_v5_charm_grpo/"
    "gcp-r8-unadmitted-hybrid45-exact40-r87-skypilot.json"
)
ARCHIVE_NAME = "r8-frozen-workdir.tar.gz"
TASK_NAME = "r8-skypilot-transport.yaml"
RECEIPT_NAME = "r8-skypilot-transport-receipt.json"
IMMUTABLE_BOOT_IMAGE = (
    "projects/deeplearning-platform-release/global/images/"
    "common-cu129-ubuntu-2204-nvidia-580-v20260804"
)
IMMUTABLE_BOOT_IMAGE_ID = "2602194621800855867"
FROZEN_SOURCE_COMMIT = "19c68240991563e4ddbc0171485b1850101e7e2b"
HOST_VENV_REL = ".venvs/glm47-r8-host-pydantic-2.12.5"
HOST_PYTHON_PACKAGES = (
    "annotated-types==0.7.0",
    "pydantic-core==2.41.5",
    "typing-extensions==4.15.0",
    "typing-inspection==0.4.2",
    "pydantic==2.12.5",
)


class TransportError(ValueError):
    """The frozen R8 source cannot be represented by a safe transport."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bound_path(repo: Path, raw: str) -> Path:
    relative = Path(raw)
    if relative.is_absolute() or ".." in relative.parts:
        raise TransportError(f"unsafe repository-relative path: {raw}")
    path = repo / relative
    if path.is_symlink() or not path.is_file():
        raise TransportError(f"missing or unsafe transport input: {raw}")
    return path


def _tar_info(path: Path, arcname: str) -> tarfile.TarInfo:
    info = tarfile.TarInfo(arcname)
    info.size = path.stat().st_size
    info.mode = stat.S_IMODE(path.stat().st_mode)
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    return info


def _write_archive(archive: Path, members: list[tuple[str, Path]]) -> None:
    with archive.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(
                fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT
            ) as bundle:
                for arcname, path in members:
                    with path.open("rb") as stream:
                        bundle.addfile(_tar_info(path, arcname), stream)


def _transport_task(original: str, archive_sha256: str, source_commit: str) -> str:
    image_marker = "  instance_type: a3-highgpu-8g\n"
    if original.count(image_marker) != 1 or "  image_id:" in original:
        raise TransportError("R8 task has an unexpected worker-image declaration")
    original = original.replace(
        image_marker,
        image_marker + f"  image_id: {IMMUTABLE_BOOT_IMAGE}\n",
        1,
    )
    marker = "setup: |\n"
    if original.count(marker) != 1:
        raise TransportError("R8 task must contain exactly one literal setup block")
    bootstrap = (
        marker
        + "  set -euo pipefail\n"
        + f"  printf '%s  %s\\n' '{archive_sha256}' '{ARCHIVE_NAME}' | sha256sum -c -\n"
        + f"  tar --extract --gzip --file '{ARCHIVE_NAME}'\n"
    )
    transported = original.replace(marker, bootstrap, 1)

    run_marker = "run: |\n  set -euo pipefail\n"
    if transported.count(run_marker) != 1:
        raise TransportError("R8 task must contain one strict literal run block")
    package_args = " ".join(f"'{package}'" for package in HOST_PYTHON_PACKAGES)
    host_python_setup = (
        "\n"
        + f"  HOST_VENV=\"${{HOME}}/{HOST_VENV_REL}\"\n"
        + "  if ! python3 -m venv \"${HOST_VENV}\"; then\n"
        + "    sudo apt-get update\n"
        + "    sudo apt-get install -y --no-install-recommends python3-venv\n"
        + "    python3 -m venv --clear \"${HOST_VENV}\"\n"
        + "  fi\n"
        + "  \"${HOST_VENV}/bin/python\" -m pip install --disable-pip-version-check "
        + "--no-cache-dir --only-binary=:all: "
        + package_args
        + "\n"
        + "  \"${HOST_VENV}/bin/python\" -c "
        + "\"import pydantic; assert pydantic.__version__ == '2.12.5'\"\n"
    )
    transported = transported.replace("\nrun: |\n", host_python_setup + "\nrun: |\n", 1)
    run_bootstrap = (
        "run: |\n"
        + "  set -euo pipefail\n"
        + f"  export PATH=\"${{HOME}}/{HOST_VENV_REL}/bin:${{PATH}}\"\n"
        + f"  export GLM47_SOURCE_COMMIT='{source_commit}'\n"
        + "  python3 -c \"import pydantic; assert pydantic.__version__ == '2.12.5'\"\n"
    )
    return transported.replace(run_marker, run_bootstrap, 1)


def build_transport(repo: Path, profile_path: Path, output_root: Path) -> dict[str, Any]:
    repo = repo.resolve()
    profile_path = profile_path.resolve()
    output_root = output_root.resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise FileExistsError(f"transport output is not empty: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    workdir = output_root / "workdir"
    workdir.mkdir()

    if profile_path.is_symlink() or not profile_path.is_file():
        raise TransportError("R8 profile is missing or unsafe")
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    if profile.get("decision") != "EXPERIMENTAL_UNADMITTED":
        raise TransportError("transport only supports the unadmitted R8 profile")
    execution = profile.get("execution", {})
    if (
        execution.get("admission_mode") != "UNADMITTED_EXPERIMENT_ONLY"
        or execution.get("checkpoint_disposition") != "QUARANTINE_ONLY"
        or execution.get("charm_eligible") is not False
    ):
        raise TransportError("R8 quarantine contract is not intact")

    effective = profile.get("effective_source", {})
    manifest_path = _bound_path(repo, str(effective.get("manifest_path", "")))
    validation = validate_effective_source_manifest(
        repo,
        manifest_path,
        expected_file_sha256=str(effective.get("manifest_sha256", "")),
    )
    if (
        validation["source_set_sha256"] != effective.get("source_set_sha256")
        or validation["file_count"] != effective.get("file_count")
    ):
        raise TransportError("effective-source profile binding mismatch")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    member_paths: dict[str, Path] = {}
    for entry in manifest["files"]:
        relative = str(entry["path"])
        path = _bound_path(repo, relative)
        if path.stat().st_size != entry["size_bytes"] or _sha256(path) != entry["sha256"]:
            raise TransportError(f"effective-source file drifted: {relative}")
        member_paths[relative] = path

    for required in (manifest_path, profile_path):
        try:
            relative = required.relative_to(repo).as_posix()
        except ValueError as exc:
            raise TransportError("profile and manifest must be inside the repository") from exc
        member_paths[relative] = required

    members = sorted(member_paths.items())
    archive = workdir / ARCHIVE_NAME
    _write_archive(archive, members)
    archive_sha256 = _sha256(archive)

    task_relative = str(execution.get("task_yaml", ""))
    task_path = _bound_path(repo, task_relative)
    task_output = output_root / TASK_NAME
    task_output.write_text(
        _transport_task(
            task_path.read_text(encoding="utf-8"),
            archive_sha256,
            FROZEN_SOURCE_COMMIT,
        ),
        encoding="utf-8",
    )

    receipt = {
        "schema_version": "glm47-r8-skypilot-transport-v1",
        "decision": "PASS",
        "archive": {
            "name": ARCHIVE_NAME,
            "sha256": archive_sha256,
            "size_bytes": archive.stat().st_size,
            "member_count": len(members),
        },
        "effective_source": validation,
        "profile": {
            "path": profile_path.relative_to(repo).as_posix(),
            "sha256": _sha256(profile_path),
        },
        "task": {
            "source_path": task_relative,
            "source_sha256": _sha256(task_path),
            "transport_path": str(task_output),
        },
        "worker_boot_image": {
            "resource": IMMUTABLE_BOOT_IMAGE,
            "numeric_id": IMMUTABLE_BOOT_IMAGE_ID,
            "provenance": (
                "exact sourceImage/sourceImageId of the prior working "
                "glm47-full-v5-charm-h100-8 boot disk"
            ),
        },
        "source_commit": {
            "value": FROZEN_SOURCE_COMMIT,
            "transport": "GLM47_SOURCE_COMMIT",
            "purpose": "provenance for a digest-frozen workdir without .git",
        },
        "host_python": {
            "venv_relative_to_home": HOST_VENV_REL,
            "packages": list(HOST_PYTHON_PACKAGES),
            "purpose": "host-side frozen R8 driver imports before Docker launch",
        },
        "workdir": str(workdir),
    }
    receipt_path = output_root / RECEIPT_NAME
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {**receipt, "receipt_path": str(receipt_path)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo_root.resolve()
    profile = args.profile or (repo / DEFAULT_PROFILE_REL)
    print(json.dumps(build_transport(repo, profile, args.output_root), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
