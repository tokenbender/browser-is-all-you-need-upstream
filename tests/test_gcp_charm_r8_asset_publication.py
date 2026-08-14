from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts/gcp_full_v5_charm_r8_publish_assets.py"
SPEC = importlib.util.spec_from_file_location("r8_asset_publication", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
PUBLISHER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PUBLISHER)


def test_publication_targets_are_frozen_and_have_no_compute_operation() -> None:
    assert PUBLISHER.IMAGE_DIGEST == (
        "sha256:5df1c41efb6062a292ac68a49d68ad955d9f8209c182d3fc2f7e8c634ca076a2"
    )
    assert PUBLISHER.IMMUTABLE_IMAGE.endswith("@" + PUBLISHER.IMAGE_DIGEST)
    assert PUBLISHER.RUNTIME_GCS == (
        "gs://lifeandhalf-24122025-w8-biayn/glm47-full-v5/assets/runtime/"
        "charm-r8-candidate-hybrid45-exact40-r87-rewardable-20260813T044420Z"
    )
    text = SCRIPT.read_text(encoding="utf-8")
    assert "sky jobs launch" not in text
    assert "gcloud compute" not in text
    assert "publish-image" in text
    assert "publish-runtime" in text


def test_private_runtime_inventory_rejects_symlinks(tmp_path: Path) -> None:
    (tmp_path / "data.txt").write_text("safe\n", encoding="utf-8")
    (tmp_path / "link.txt").symlink_to(tmp_path / "data.txt")
    with pytest.raises(PUBLISHER.PublicationError, match="symlink"):
        PUBLISHER.runtime_inventory(tmp_path)


def test_publication_authorizations_fail_before_any_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def forbidden(*args: object, **kwargs: object) -> None:
        nonlocal called
        called = True
        raise AssertionError("subprocess must not run before authorization")

    monkeypatch.setattr(PUBLISHER, "_run", forbidden)
    with pytest.raises(PUBLISHER.PublicationError, match=PUBLISHER.IMAGE_AUTH_ENV):
        PUBLISHER.publish_image({})
    with pytest.raises(PUBLISHER.PublicationError, match=PUBLISHER.RUNTIME_AUTH_ENV):
        PUBLISHER.publish_runtime({})
    assert called is False


def test_profile_status_update_is_atomic_and_narrow(tmp_path: Path) -> None:
    source = json.loads(PUBLISHER.PROFILE_PATH.read_text(encoding="utf-8"))
    source["training_image"]["gcp_asset_status"] = "LOCAL_VALIDATED_UPLOAD_PENDING"
    source["full_v5_runtime"]["gcp_asset_status"] = (
        "LOCAL_MATERIALIZED_ORACLE_PASS_UPLOAD_PENDING"
    )
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    before = json.loads(path.read_text(encoding="utf-8"))
    after = PUBLISHER.update_profile_status("training_image", path)
    assert after["training_image"]["gcp_asset_status"] == "AVAILABLE"
    assert after["full_v5_runtime"] == before["full_v5_runtime"]
    after["training_image"]["gcp_asset_status"] = before["training_image"]["gcp_asset_status"]
    assert after == before
    assert not list(tmp_path.glob("*.tmp.*"))


def test_remote_runtime_mismatch_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = [{"path": "a", "sha256": "0" * 64, "size_bytes": 1}]
    observed = [{"path": "a", "sha256": "1" * 64, "size_bytes": 1}]
    monkeypatch.setattr(PUBLISHER, "_remote_runtime_inventory", lambda: observed)
    with pytest.raises(PUBLISHER.PublicationError, match="differs"):
        PUBLISHER._verify_remote_runtime(expected)




def test_publication_pass_requires_both_remote_proofs(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = json.loads(PUBLISHER.PROFILE_PATH.read_text(encoding="utf-8"))
    profile["training_image"]["gcp_asset_status"] = "AVAILABLE"
    profile["full_v5_runtime"]["gcp_asset_status"] = "AVAILABLE"
    written: list[dict[str, object]] = []
    monkeypatch.setattr(PUBLISHER, "_load_profile", lambda: profile)
    monkeypatch.setattr(PUBLISHER, "_atomic_write_json", lambda path, payload: written.append(payload))
    partial = PUBLISHER._write_receipt({"decision": "PASS"})
    assert partial["decision"] == "PARTIAL"
    passed = PUBLISHER._write_receipt(
        {"decision": "PASS"},
        remote_image={"decision": "PASS"},
        remote_runtime={"decision": "PASS"},
    )
    assert passed["decision"] == "PASS"
    assert len(written) == 2


def test_cli_missing_publication_authorization_is_non_mutating() -> None:
    environment = {
        **os.environ,
        "PYTHONPATH": f"{REPO / 'src'}:{REPO}",
        "PATH": "/usr/bin:/bin",
    }
    environment.pop(PUBLISHER.IMAGE_AUTH_ENV, None)
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "publish-image"],
        cwd=REPO,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 2
    assert PUBLISHER.IMAGE_AUTH_ENV in completed.stderr
    assert "docker: command not found" not in completed.stderr
    assert "gcloud: command not found" not in completed.stderr
