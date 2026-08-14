from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts/gcp_full_v5_runtime_build_stage.sh"


def test_source_first_runtime_builder_is_pinned_and_model_host_free() -> None:
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    subprocess.run(["bash", "-n", str(SCRIPT_PATH)], check=True)

    assert "0efce27cd2c333f769afc74c9f9b852823256322" in text
    assert "a01a07c9d4e2706683814a3d5afc2bcd47172ff92b08f15e2c673729f185bd66" in text
    assert "93d671faa44abcc6deca21c6a49e247d76436835bfa2905ee33968a478fb532a" in text
    assert "0a3df3ce40eed45814651c933277bfc5ca17359a2b3e6f0a7027b184e3569c7e" in text
    assert "d2a4c413f8944dc2d560b3ca156b5543455f4dbeb24cbfa8e1f7770d356861f5" in text
    assert "5490c109fd2ed746f5680f0e996e847112872940b8e5eb466cd6af86bc6579e2" in text

    lowered = text.lower()
    assert "huggingface" not in lowered
    assert "hf_token" not in lowered
    assert "hf auth" not in lowered
    assert "hf download" not in lowered


def test_runtime_stage_is_separate_and_roundtrip_verified() -> None:
    text = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "build-stage)" in text
    assert "GCS destination is not empty; refusing to overwrite" in text
    assert text.count("gcloud storage rsync --recursive") == 2
    assert 'verify_bundle_identities "${BUILD_ROOT}/gcs-roundtrip-bundle"' in text
    assert "sky launch" not in text
    assert "sky jobs launch" not in text


def test_preflight_fails_closed_without_private_input_root() -> None:
    completed = subprocess.run(
        ["bash", str(SCRIPT_PATH), "preflight"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )

    assert completed.returncode == 2
    assert "FULL_V5_PRODUCER_DIR is required" in completed.stderr
