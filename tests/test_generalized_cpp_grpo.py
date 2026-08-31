from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest

from Reward_GRPO import generalized_cpp_grpo as adapter


ROOT = Path(__file__).parents[1]
CANARY = ROOT / "Reward_GRPO/generalized_cpp_grpo_canary"


def response(expression: str = "a + b") -> str:
    return (
        "arithmetic.h\n```cpp\n#pragma once\n"
        "namespace demo { int add(int, int); int multiply(int, int); }\n```\n\n"
        "arithmetic.cpp\n```cpp\n#include \"arithmetic.h\"\n"
        "namespace demo { int add(int a, int b) { return "
        f"{expression}; }} int multiply(int a, int b) {{ return a * b; }} }}\n```\n"
    )


def sample(text: str, *, digest: str | None = None) -> dict:
    metadata = {
        "task_id": "generalized-cpp/portable-arithmetic",
        "problem_id": "portable-arithmetic",
        "split": "train",
    }
    if digest is not None:
        metadata["generalized_verifier_manifest_sha256"] = digest
    return {
        "metadata": metadata,
        "response": text,
        "rollout_id": "rollout-1",
        "index": 0,
    }


def test_valid_response_runs_end_to_end() -> None:
    binding = adapter.TaskRegistry(adapter.DEFAULT_REGISTRY).resolve(
        "portable-arithmetic"
    )
    record = adapter.score_sample(sample(response(), digest=binding.manifest_sha256))
    assert record["infrastructure_error"] is False
    assert record["score"] == 1.0
    assert record["reason"] == "pass"
    assert record["format_valid"] is True
    assert record["candidate_source_unchanged"] is True
    assert record["policy_results"]
    assert record["kernel_results"]


def test_semantic_failure_is_model_failure_not_infrastructure() -> None:
    record = adapter.score_sample(sample(response("a - b")))
    assert record["infrastructure_error"] is False
    assert -1.0 <= record["score"] < 1.0
    assert record["reason"] == "fail"
    policies = {item["policy_id"]: item for item in record["policy_results"]}
    assert policies["G03"]["status"] == "fail"


def test_invalid_response_is_a_format_reward_not_worker_failure() -> None:
    record = adapter.score_sample(sample("unfinished response"))
    assert record["infrastructure_error"] is False
    assert record["score"] == pytest.approx(-1.0)
    assert record["reason"] == "invalid_format"
    assert record["integrity_verdict"] == "EMPTY"
    assert record["policy_results"] == []


def test_metadata_binding_mismatch_is_infrastructure_invalid() -> None:
    record = adapter.score_sample(sample(response(), digest="0" * 64))
    assert record["infrastructure_error"] is True
    assert record["score"] == 0.0
    assert record["reason"] == "metadata_binding_mismatch"


def test_registry_rejects_protected_fixture_tampering(tmp_path: Path) -> None:
    copied = tmp_path / "canary"
    shutil.copytree(CANARY, copied)
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tasks": {
                    "portable-arithmetic": {
                        "manifest": "canary/manifest.json",
                        "manifest_sha256": adapter._sha256(copied / "manifest.json"),
                        "fixture_dir": "canary/fixture",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (copied / "fixture/arithmetic_test.cpp").write_text(
        "// tampered\n", encoding="utf-8"
    )
    with pytest.raises(adapter.BindingError) as raised:
        adapter.TaskRegistry(registry_path).resolve("portable-arithmetic")
    assert raised.value.reason == "protected_file_mismatch"


def test_batch_neutralizes_infrastructure_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    binding = adapter.TaskRegistry(adapter.DEFAULT_REGISTRY).resolve(
        "portable-arithmetic"
    )
    valid = sample(response(), digest=binding.manifest_sha256)
    invalid = sample(response(), digest="0" * 64)
    invalid["index"] = 1
    monkeypatch.setenv(adapter.WORKERS_ENV, "2")
    records = asyncio.run(adapter.reward_func(None, [valid, invalid]))
    assert isinstance(records, list)
    assert records[0]["score"] == 1.0
    assert records[1]["infrastructure_error"] is True
    assert records[1]["score"] == 1.0
    assert records[1]["score_neutralized"] is True


def test_preflight_runs_registered_canary(capsys: pytest.CaptureFixture[str]) -> None:
    adapter.preflight()
    assert "GENERALIZED_CPP_GRPO_READY" in capsys.readouterr().out
