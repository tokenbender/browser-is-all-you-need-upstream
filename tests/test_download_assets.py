from pathlib import Path

import pytest

from scripts import download_assets


@pytest.mark.parametrize(
    "name,repo,revision",
    [
        (
            "sft",
            "WootzappLab/glm47-flash-pie-cpp-lora-r16-sft-h100",
            "c877295dd577afb680d19bc9d9aea5ec99e7587c",
        ),
        (
            "grpo",
            "WootzappLab/glm47-flash-pie-cpp-lora-r16-grpo-h100",
            "6799626af220e128c88dab8539f1baeb8aadb572",
        ),
    ],
)
@pytest.mark.parametrize("override", [False, True])
def test_pie_adapter_download_binding(monkeypatch, tmp_path, name, repo, revision, override):
    calls = []
    verified = []
    revision_env = download_assets.ASSETS[name]["revision_env"]
    monkeypatch.delenv(revision_env, raising=False)
    if override:
        revision = "explicit-revision"
        monkeypatch.setenv(revision_env, revision)
    monkeypatch.setattr(download_assets, "snapshot_download", lambda **kw: calls.append(kw))
    monkeypatch.setattr(download_assets, "_verify_checksums", verified.append)

    destination = download_assets._download(name, tmp_path, verify=True)

    assert destination == tmp_path / "adapters" / name
    assert calls == [
        {"repo_id": repo, "repo_type": "model", "revision": revision, "local_dir": destination}
    ]
    assert verified == [Path(destination)]


@pytest.mark.parametrize("override", [False, True])
def test_pie_data_download_binding(monkeypatch, tmp_path, override):
    calls = []
    verified = []
    extracted = []
    revision = "35b4af63803b2ac906aa8a69178048c366394499"
    monkeypatch.delenv("GLM47_DATA_REVISION", raising=False)
    if override:
        revision = "explicit-revision"
        monkeypatch.setenv("GLM47_DATA_REVISION", revision)
    monkeypatch.setattr(download_assets, "snapshot_download", lambda **kw: calls.append(kw))
    monkeypatch.setattr(download_assets, "_verify_checksums", verified.append)
    monkeypatch.setattr(download_assets, "_extract_task_archive", extracted.append)

    destination = download_assets._download("data", tmp_path, verify=True)

    assert destination == tmp_path / "data"
    assert calls == [
        {
            "repo_id": "WootzappLab/glm47-pie-cpp-posttraining-data",
            "repo_type": "dataset",
            "revision": revision,
            "local_dir": destination,
        }
    ]
    assert verified == [destination]
    assert extracted == [destination]
