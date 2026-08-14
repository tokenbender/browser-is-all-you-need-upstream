#!/usr/bin/env python3
"""Publish and byte-verify the frozen R8 image and private runtime.

This utility deliberately has no SkyPilot or compute-launch operation. Image
and private-runtime publication require separate exact authorization strings.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

from glm47_posttraining.aider_polyglot.charm_grpo import tree_sha256
from glm47_posttraining.aider_polyglot.effective_source import (
    validate_effective_source_manifest,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = (
    REPO_ROOT
    / "configs/full_v5_charm_grpo/gcp-r8-unadmitted-hybrid45-exact40-r87-skypilot.json"
)
RUNTIME_ROOT = (
    REPO_ROOT
    / "artifacts/charm-r8-candidate-hybrid45-exact40-r87-rewardable-20260813T044420Z"
)
PUBLICATION_RECEIPT = (
    REPO_ROOT
    / "artifacts/charm-r8-preflight-20260813/external-asset-publication.json"
)
LOCAL_CHECK_RECEIPT = (
    REPO_ROOT
    / "artifacts/charm-r8-preflight-20260813/external-asset-publication-local.json"
)

PROFILE_ID = "aider-charm-r8-experimental-unadmitted-hybrid45-exact40-r87-skypilot"
LOCAL_IMAGE = (
    "glm47-full-v5-unadmitted-grpo:"
    "gcp-r8-hybrid45-exact40-r87-asleepfix-20260814"
)
REGISTRY_TAG = (
    "us-central1-docker.pkg.dev/lifeandhalf-24122025/w8-biayn/"
    "glm47-full-v5-unadmitted-grpo:"
    "gcp-r8-hybrid45-exact40-r87-asleepfix-20260814"
)
IMAGE_DIGEST = "sha256:5df1c41efb6062a292ac68a49d68ad955d9f8209c182d3fc2f7e8c634ca076a2"
IMMUTABLE_IMAGE = (
    "us-central1-docker.pkg.dev/lifeandhalf-24122025/w8-biayn/"
    f"glm47-full-v5-unadmitted-grpo@{IMAGE_DIGEST}"
)
REGISTRY_HOST = "us-central1-docker.pkg.dev"
RUNTIME_GCS = (
    "gs://lifeandhalf-24122025-w8-biayn/glm47-full-v5/assets/runtime/"
    "charm-r8-candidate-hybrid45-exact40-r87-rewardable-20260813T044420Z"
)
RUNTIME_MANIFEST_SHA256 = "72296f7bae1b4690a613922f3f29b2011e4a8646d356a4e7663cfc5822e7bfd2"
RUNTIME_ORACLE_SHA256 = "f3878a58fe6fb7b4412d00a90eab732230c823ff0c73d0409669ebf18b878ce6"
RUNTIME_TREE_SHA256 = "b1fff05e66a4198dca8d74ae41e2837e0926b24b8acfb281822bd08583554075"
RUNTIME_FILE_COUNT = 244
LIBCLANG_RESOURCE_DIR = "/usr/local/lib/clang/18"

IMAGE_AUTH_ENV = "GLM47_R8_IMAGE_PUBLICATION_AUTHORIZATION"
IMAGE_AUTH_PHRASE = (
    "I_AUTHORIZE_R8_REPOSITORY_SOURCE_IMAGE_PUBLICATION_TO_US_CENTRAL1_ARTIFACT_REGISTRY"
)
RUNTIME_AUTH_ENV = "GLM47_R8_PRIVATE_RUNTIME_PUBLICATION_AUTHORIZATION"
RUNTIME_AUTH_PHRASE = (
    "I_AUTHORIZE_R8_PRIVATE_GRADER_ORACLE_RUNTIME_PUBLICATION_TO_FROZEN_GCS_PREFIX"
)


class PublicationError(RuntimeError):
    """An immutable asset identity or publication gate failed."""


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run(
    command: Sequence[str],
    *,
    input_text: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        list(command),
        cwd=REPO_ROOT,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "no diagnostic"
        raise PublicationError(f"command failed ({command[0]}): {detail}")
    return completed


def _require_authorization(environment: dict[str, str], name: str, phrase: str) -> None:
    if environment.get(name) != phrase:
        raise PublicationError(f"{name} does not contain the exact publication authorization")


def _load_profile(path: Path = PROFILE_PATH) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise PublicationError(f"R8 profile is missing or unsafe: {path}")
    profile = json.loads(path.read_text(encoding="utf-8"))
    if profile.get("profile_id") != PROFILE_ID:
        raise PublicationError("unexpected R8 profile identity")
    if profile.get("decision") != "EXPERIMENTAL_UNADMITTED":
        raise PublicationError("R8 profile is not explicitly experimental and unadmitted")
    execution = profile.get("execution", {})
    if execution.get("checkpoint_disposition") != "QUARANTINE_ONLY":
        raise PublicationError("R8 checkpoint disposition is not QUARANTINE_ONLY")
    if execution.get("charm_eligible") is not False:
        raise PublicationError("R8 profile unexpectedly permits CHARM eligibility")
    training = profile.get("training_image", {})
    if (
        training.get("local_name") != LOCAL_IMAGE
        or training.get("registry") != REGISTRY_TAG
        or training.get("registry_digest") != IMAGE_DIGEST
        or training.get("immutable_ref") != IMMUTABLE_IMAGE
    ):
        raise PublicationError("R8 training-image identity drifted")
    runtime = profile.get("full_v5_runtime", {})
    if (
        profile.get("gcp", {}).get("runtime_source") != RUNTIME_GCS
        or runtime.get("manifest_sha256") != RUNTIME_MANIFEST_SHA256
        or runtime.get("oracle_receipt_sha256") != RUNTIME_ORACLE_SHA256
        or runtime.get("tree_sha256") != RUNTIME_TREE_SHA256
    ):
        raise PublicationError("R8 private-runtime identity drifted")
    return profile


def runtime_inventory(root: Path) -> list[dict[str, Any]]:
    if root.is_symlink() or not root.is_dir():
        raise PublicationError(f"private runtime is missing or unsafe: {root}")
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path.is_symlink():
            raise PublicationError(f"private runtime contains a symlink: {path.relative_to(root)}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise PublicationError(f"private runtime contains a non-file: {path.relative_to(root)}")
        entries.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": _sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return entries


def _validate_runtime(profile: dict[str, Any]) -> dict[str, Any]:
    inventory = runtime_inventory(RUNTIME_ROOT)
    if len(inventory) != RUNTIME_FILE_COUNT:
        raise PublicationError(
            f"private-runtime file count mismatch: {len(inventory)} != {RUNTIME_FILE_COUNT}"
        )
    manifest_sha = _sha256_file(RUNTIME_ROOT / "manifest.json")
    oracle_sha = _sha256_file(RUNTIME_ROOT / "oracle-verification-receipt.json")
    observed_tree = tree_sha256(RUNTIME_ROOT)
    if manifest_sha != RUNTIME_MANIFEST_SHA256:
        raise PublicationError("private-runtime manifest digest mismatch")
    if oracle_sha != RUNTIME_ORACLE_SHA256:
        raise PublicationError("private-runtime oracle receipt digest mismatch")
    if observed_tree != RUNTIME_TREE_SHA256:
        raise PublicationError("private-runtime tree digest mismatch")
    manifest = json.loads((RUNTIME_ROOT / "manifest.json").read_text(encoding="utf-8"))
    oracle = json.loads(
        (RUNTIME_ROOT / "oracle-verification-receipt.json").read_text(encoding="utf-8")
    )
    if manifest.get("decision") != "PASS" or oracle.get("decision") != "PASS":
        raise PublicationError("private-runtime deterministic evidence is not PASS")
    if profile["full_v5_runtime"].get("reference_answers_packaged") is not False:
        raise PublicationError("profile unexpectedly permits packaged reference answers")
    return {
        "file_count": len(inventory),
        "inventory_sha256": hashlib.sha256(_canonical_bytes(inventory)).hexdigest(),
        "manifest_sha256": manifest_sha,
        "oracle_receipt_sha256": oracle_sha,
        "tree_sha256": observed_tree,
    }


def _validate_replay(profile: dict[str, Any]) -> dict[str, Any]:
    binding = profile.get("preflight_evidence", {}).get("hybrid45_corpus_replay", {})
    path = REPO_ROOT / str(binding.get("path", ""))
    if path.is_symlink() or not path.is_file():
        raise PublicationError("Hybrid45 zero-update replay is missing or unsafe")
    file_sha = _sha256_file(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if file_sha != binding.get("file_sha256"):
        raise PublicationError("Hybrid45 zero-update replay file digest mismatch")
    if payload.get("receipt_sha256") != binding.get("receipt_sha256"):
        raise PublicationError("Hybrid45 zero-update replay receipt digest mismatch")
    if (
        payload.get("decision") != "PASS"
        or payload.get("optimizer_updates") != 0
        or payload.get("functional_reference_pass_count") != 51
        or payload.get("gradient_full_positive_reward_count") != 40
    ):
        raise PublicationError("Hybrid45 zero-update replay no longer satisfies its frozen gates")
    return {
        "decision": "PASS",
        "file_sha256": file_sha,
        "receipt_sha256": payload["receipt_sha256"],
        "optimizer_updates": 0,
    }


def _validate_local_image() -> dict[str, Any]:
    records = json.loads(_run(["docker", "image", "inspect", LOCAL_IMAGE]).stdout)
    if len(records) != 1 or records[0].get("Id") != IMAGE_DIGEST:
        raise PublicationError("local R8 image ID does not match the frozen registry digest")
    env_pairs = records[0].get("Config", {}).get("Env", []) or []
    environment = dict(pair.split("=", 1) for pair in env_pairs if "=" in pair)
    if "CPLUS_INCLUDE_PATH" in environment:
        raise PublicationError("local R8 image globally exports CPLUS_INCLUDE_PATH")
    if environment.get("GLM47_LIBCLANG_RESOURCE_DIR") != LIBCLANG_RESOURCE_DIR:
        raise PublicationError("local R8 image has the wrong libclang resource directory")
    return {
        "image_id": records[0]["Id"],
        "cplus_include_path_absent": True,
        "libclang_resource_dir": environment["GLM47_LIBCLANG_RESOURCE_DIR"],
    }


def validate_local() -> dict[str, Any]:
    profile = _load_profile()
    source = profile.get("effective_source", {})
    source_validation = validate_effective_source_manifest(
        REPO_ROOT,
        REPO_ROOT / str(source.get("manifest_path", "")),
        expected_file_sha256=str(source.get("manifest_sha256", "")),
    )
    if (
        source_validation.get("source_set_sha256") != source.get("source_set_sha256")
        or source_validation.get("file_count") != source.get("file_count")
    ):
        raise PublicationError("effective R8 source binding mismatch")
    return {
        "decision": "PASS",
        "optimizer_updates": 0,
        "profile_id": profile["profile_id"],
        "effective_source": source_validation,
        "training_image": _validate_local_image(),
        "private_runtime": _validate_runtime(profile),
        "hybrid45_zero_update_replay": _validate_replay(profile),
    }


def _verify_remote_image() -> dict[str, Any]:
    completed = _run(
        ["gcloud", "artifacts", "docker", "images", "describe", IMMUTABLE_IMAGE,
         "--format=value(image_summary.digest)"]
    )
    observed = completed.stdout.strip()
    if observed != IMAGE_DIGEST:
        raise PublicationError(f"remote R8 image digest mismatch: {observed or '<empty>'}")
    return {"decision": "PASS", "immutable_ref": IMMUTABLE_IMAGE, "digest": observed}


def _remote_runtime_inventory() -> list[dict[str, Any]] | None:
    listing = _run(["gcloud", "storage", "ls", "--recursive", RUNTIME_GCS], check=False)
    if listing.returncode != 0:
        diagnostic = (listing.stderr + "\n" + listing.stdout).lower()
        if "not found" in diagnostic or "matched no objects" in diagnostic:
            return None
        raise PublicationError(
            "unable to determine private-runtime destination state: "
            + (listing.stderr.strip() or listing.stdout.strip() or "no diagnostic")
        )
    if not listing.stdout.strip():
        return None
    with tempfile.TemporaryDirectory(prefix="glm47-r8-runtime-verify-") as directory:
        destination = Path(directory) / "runtime"
        destination.mkdir()
        _run(["gcloud", "storage", "rsync", RUNTIME_GCS, str(destination),
              "--recursive", "--checksums-only"])
        return runtime_inventory(destination)


def _verify_remote_runtime(local_inventory: list[dict[str, Any]]) -> dict[str, Any]:
    observed = _remote_runtime_inventory()
    if observed is None:
        raise PublicationError("private-runtime destination is empty")
    if observed != local_inventory:
        raise PublicationError("remote private-runtime inventory differs from the frozen local bytes")
    return {
        "decision": "PASS",
        "gcs_prefix": RUNTIME_GCS,
        "file_count": len(observed),
        "inventory_sha256": hashlib.sha256(_canonical_bytes(observed)).hexdigest(),
    }


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def update_profile_status(field: str, path: Path = PROFILE_PATH) -> dict[str, Any]:
    if field not in {"training_image", "full_v5_runtime"}:
        raise PublicationError(f"unsupported profile asset field: {field}")
    profile = _load_profile(path)
    current = profile[field].get("gcp_asset_status")
    permitted = {
        "training_image": {"LOCAL_VALIDATED_UPLOAD_PENDING", "AVAILABLE"},
        "full_v5_runtime": {"LOCAL_MATERIALIZED_ORACLE_PASS_UPLOAD_PENDING", "AVAILABLE"},
    }
    if current not in permitted[field]:
        raise PublicationError(f"refusing unexpected {field} status: {current}")
    profile[field]["gcp_asset_status"] = "AVAILABLE"
    _atomic_write_json(path, profile)
    return profile


def _write_local_receipt(local: dict[str, Any]) -> dict[str, Any]:
    profile = _load_profile()
    payload = {
        "schema_version": "charm-r8-external-asset-local-check-v1",
        "decision": "LOCAL_PASS_REMOTE_PUBLICATION_NOT_VERIFIED",
        "scope": "local-asset-validation-only-no-upload-no-sky-no-gpu-compute",
        "optimizer_updates": 0,
        "profile_id": profile["profile_id"],
        "checkpoint_disposition": "QUARANTINE_ONLY",
        "local_validation": local,
        "training_image_gcp_asset_status": profile["training_image"].get("gcp_asset_status"),
        "private_runtime_gcp_asset_status": profile["full_v5_runtime"].get("gcp_asset_status"),
    }
    _atomic_write_json(LOCAL_CHECK_RECEIPT, payload)
    return payload


def _write_receipt(local: dict[str, Any], *, remote_image: dict[str, Any] | None = None,
                   remote_runtime: dict[str, Any] | None = None) -> dict[str, Any]:
    profile = _load_profile()
    image_available = profile["training_image"].get("gcp_asset_status") == "AVAILABLE"
    runtime_available = profile["full_v5_runtime"].get("gcp_asset_status") == "AVAILABLE"
    remote_pass = (
        isinstance(remote_image, dict)
        and remote_image.get("decision") == "PASS"
        and isinstance(remote_runtime, dict)
        and remote_runtime.get("decision") == "PASS"
    )
    payload = {
        "schema_version": "charm-r8-external-asset-publication-v1",
        "decision": "PASS" if image_available and runtime_available and remote_pass else "PARTIAL",
        "scope": "asset-publication-only-no-sky-or-gpu-compute",
        "optimizer_updates": 0,
        "profile_id": profile["profile_id"],
        "checkpoint_disposition": "QUARANTINE_ONLY",
        "local_validation": local,
        "training_image": {"gcp_asset_status": profile["training_image"].get("gcp_asset_status"),
                           "remote_verification": remote_image},
        "private_runtime": {"gcp_asset_status": profile["full_v5_runtime"].get("gcp_asset_status"),
                            "remote_verification": remote_runtime},
    }
    _atomic_write_json(PUBLICATION_RECEIPT, payload)
    return payload


def publish_image(environment: dict[str, str]) -> dict[str, Any]:
    _require_authorization(environment, IMAGE_AUTH_ENV, IMAGE_AUTH_PHRASE)
    local = validate_local()
    token = _run(["gcloud", "auth", "print-access-token"]).stdout
    if not token.strip():
        raise PublicationError("gcloud returned an empty registry access token")
    _run(["docker", "login", "--username", "oauth2accesstoken", "--password-stdin",
          f"https://{REGISTRY_HOST}"], input_text=token)
    _run(["docker", "tag", LOCAL_IMAGE, REGISTRY_TAG])
    _run(["docker", "push", REGISTRY_TAG])
    remote_image = _verify_remote_image()
    update_profile_status("training_image")
    profile = _load_profile()
    remote_runtime = None
    if profile["full_v5_runtime"].get("gcp_asset_status") == "AVAILABLE":
        remote_runtime = _verify_remote_runtime(runtime_inventory(RUNTIME_ROOT))
    return _write_receipt(local, remote_image=remote_image, remote_runtime=remote_runtime)


def publish_runtime(environment: dict[str, str]) -> dict[str, Any]:
    _require_authorization(environment, RUNTIME_AUTH_ENV, RUNTIME_AUTH_PHRASE)
    local = validate_local()
    expected = runtime_inventory(RUNTIME_ROOT)
    existing = _remote_runtime_inventory()
    if existing is not None and existing != expected:
        raise PublicationError("refusing to overwrite a nonempty, mismatching private-runtime prefix")
    if existing is None:
        _run(["gcloud", "storage", "rsync", str(RUNTIME_ROOT), RUNTIME_GCS,
              "--recursive", "--checksums-only"])
    remote_runtime = _verify_remote_runtime(expected)
    update_profile_status("full_v5_runtime")
    profile = _load_profile()
    remote_image = None
    if profile["training_image"].get("gcp_asset_status") == "AVAILABLE":
        remote_image = _verify_remote_image()
    return _write_receipt(local, remote_image=remote_image, remote_runtime=remote_runtime)


def verify_remote() -> dict[str, Any]:
    local = validate_local()
    remote_image = _verify_remote_image()
    remote_runtime = _verify_remote_runtime(runtime_inventory(RUNTIME_ROOT))
    update_profile_status("training_image")
    update_profile_status("full_v5_runtime")
    return _write_receipt(local, remote_image=remote_image, remote_runtime=remote_runtime)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("check-local", "publish-image", "publish-runtime", "verify-remote"),
    )
    args = parser.parse_args(argv)
    try:
        if args.action == "check-local":
            result = _write_local_receipt(validate_local())
        elif args.action == "publish-image":
            result = publish_image(dict(os.environ))
        elif args.action == "publish-runtime":
            result = publish_runtime(dict(os.environ))
        else:
            result = verify_remote()
    except (PublicationError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"R8 asset publication blocked: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
