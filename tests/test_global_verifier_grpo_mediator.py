from __future__ import annotations

import asyncio
import copy
import json
import shutil
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from Reward_GRPO import global_verifier_grpo_mediator as mediator

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "Reward_GRPO/global_verifiers_set2/task_bundle_example"


def registry() -> mediator.TaskBundleRegistry:
    return mediator.TaskBundleRegistry(
        ROOT / "Reward_GRPO/global_verifier_task_registry.json"
    )


def valid_response(expression: str = "left + right") -> str:
    return (
        "adder.h\n```cpp\n#pragma once\n"
        f"inline int add(int left, int right) {{ return {expression}; }}\n```\n"
    )


def prepared_row() -> dict:
    return mediator.prepare_dataset_row(
        {"sample_id": "adder-1", "task_bundle_id": "portable-adder"}, registry()
    )


def test_registry_authenticates_identity_and_digests() -> None:
    binding = registry().resolve("portable-adder")
    assert binding.path == EXAMPLE.resolve()
    assert binding.manifest["task_id"] == "portable-adder"
    assert len(binding.bundle_sha256) == len(binding.manifest_sha256) == 64


def test_prompt_is_public_only_and_bound_to_bundle() -> None:
    row = prepared_row()
    prompt = row["prompt"]
    metadata = row["metadata"]
    assert len(prompt) == 8
    rendered = json.dumps(prompt, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert "Portable Adder" in rendered
    assert "adder.h" in rendered
    assert "official_tests.cpp" not in rendered
    assert "protected_asset_hashes.json" not in rendered
    assert "tests_passed" not in rendered
    assert metadata["task_bundle_id"] == "portable-adder"
    assert metadata["prompt_sha256"] == mediator._sha256_bytes(rendered.encode())


def test_registry_rejects_bundle_tampering(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    shutil.copytree(EXAMPLE, bundle)
    payload = {
        "schema_version": 1,
        "bundles": {
            "portable-adder": {
                "path": "bundle",
                "bundle_sha256": "0" * 64,
            }
        },
    }
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(mediator.MediatorError) as raised:
        mediator.TaskBundleRegistry(path).resolve("portable-adder")
    assert raised.value.reason == "BUNDLE_HASH_MISMATCH"


def test_host_evaluation_passes_and_preserves_reward_components() -> None:
    binding = registry().resolve("portable-adder")
    receipt = mediator.evaluate_response(
        binding, valid_response(), executor="host", invalid_retries=0
    )
    reward = mediator.receipt_to_reward(receipt)
    assert receipt["status"] == "PASS"
    assert receipt["mediator_attempts"] == 1
    assert reward == {
        "valid": True,
        "retry": False,
        "reward": 1.0,
        "include_in_normalization": True,
        "include_in_loss": True,
        "projection_kind": "binary-correctness-v1",
        "stage": "binary",
        "correctness": 1.0,
        "format": 1.0,
        "build": 1.0,
        "api": 1.0,
        "tests": 1.0,
    }


def test_logic_failure_is_model_fail_not_infrastructure_invalid() -> None:
    binding = registry().resolve("portable-adder")
    receipt = mediator.evaluate_response(
        binding, valid_response("left - right"), executor="host", invalid_retries=0
    )
    reward = mediator.receipt_to_reward(receipt)
    assert receipt["status"] == "FAIL"
    assert reward["valid"] is True
    assert reward["build"] == reward["api"] == 1.0
    assert reward["correctness"] == 0.0
    assert reward["tests"] == pytest.approx(1 / 3)


def test_truncation_is_distinct_format_failure() -> None:
    binding = registry().resolve("portable-adder")
    receipt = mediator.evaluate_response(
        binding, "adder.h\n```cpp\nunfinished", finish_reason="length",
        executor="host", invalid_retries=0,
    )
    assert receipt["status"] == "FAIL"
    assert receipt["reason"] == "TRUNCATED"
    assert receipt["format_valid"] is False


def test_reward_hook_requires_exact_prompt_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    row = prepared_row()
    sample = {"metadata": row["metadata"], "prompt": row["prompt"],
              "response": valid_response()}
    monkeypatch.setenv(mediator.EXECUTOR_ENV, "host")
    monkeypatch.setenv(mediator.RETRIES_ENV, "0")
    monkeypatch.setenv(mediator.REQUIRE_BATCH_ENV, "0")
    result = asyncio.run(mediator.reward_func(None, sample))
    assert result["reward"] == 1.0
    assert result["infrastructure_error"] is False

    sample["metadata"] = {**sample["metadata"], "prompt_sha256": "0" * 64}
    result = asyncio.run(mediator.reward_func(None, sample))
    assert result["reward"] == 0.0
    assert result["infrastructure_error"] is True
    assert result["reason"] == "PROMPT_BINDING_MISMATCH"


def test_reward_hook_rejects_stale_prompt_even_with_current_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = prepared_row()
    stale = [dict(message) for message in row["prompt"]]
    stale[-1] = {**stale[-1], "content": stale[-1]["content"] + "stale"}
    sample = {"metadata": row["metadata"], "prompt": stale, "response": valid_response()}
    monkeypatch.setenv(mediator.EXECUTOR_ENV, "host")
    monkeypatch.setenv(mediator.RETRIES_ENV, "0")
    monkeypatch.setenv(mediator.REQUIRE_BATCH_ENV, "0")
    result = asyncio.run(mediator.reward_func(None, sample))
    assert result["infrastructure_error"] is True
    assert result["reason"] == "PROMPT_BINDING_MISMATCH"

def test_rendered_miles_prompt_is_bound_byte_for_byte(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = prepared_row()
    runtime_args = SimpleNamespace(apply_chat_template=True)
    monkeypatch.setattr(
        mediator, "_render_messages_for_miles",
        lambda args, messages: "authenticated-rendered-prompt",
    )
    sample = {"prompt": "authenticated-rendered-prompt"}
    assert mediator._sample_prompt_sha256(
        sample, expected_messages=row["prompt"], runtime_args=runtime_args,
    ) == row["metadata"]["prompt_sha256"]
    sample["prompt"] += "-stale"
    with pytest.raises(mediator.MediatorError) as raised:
        mediator._sample_prompt_sha256(
            sample, expected_messages=row["prompt"], runtime_args=runtime_args,
        )
    assert raised.value.reason == "PROMPT_BINDING_MISMATCH"


def test_miles_truncated_status_maps_to_length_finish_reason() -> None:
    sample = SimpleNamespace(status=SimpleNamespace(value="truncated"))
    assert mediator._sample_finish_reason(sample) == "length"


def test_reward_post_process_excludes_invalid_from_statistics_and_loss() -> None:
    def reward(score: float, *, valid: bool) -> dict:
        return {
            "score": score,
            "valid": valid,
            "infrastructure_error": not valid,
            "include_in_normalization": valid,
            "include_in_loss": valid,
        }

    samples = [
        SimpleNamespace(group_index=7, reward=reward(1.0, valid=True), remove_sample=False),
        SimpleNamespace(group_index=7, reward=reward(-1.0, valid=True), remove_sample=False),
        SimpleNamespace(group_index=7, reward=reward(-1.0, valid=True), remove_sample=False),
        SimpleNamespace(group_index=7, reward=reward(0.0, valid=False), remove_sample=False),
    ]
    args = SimpleNamespace(
        group_rm=True,
        n_samples_per_prompt=4,
        rollout_batch_size=1,
        rewards_normalization=True,
        advantage_estimator="grpo",
        grpo_std_normalization=True,
    )
    raw, normalized = mediator.reward_post_process(args, samples)
    assert raw == [1.0, -1.0, -1.0, 0.0]
    assert normalized[:3] == pytest.approx([
        1.154699538, -0.577349769, -0.577349769,
    ])
    assert normalized[3] == 0.0
    assert [sample.remove_sample for sample in samples] == [False, False, False, True]
    assert samples[3].reward["post_process"]["included"] is False


def test_reward_worker_limit_is_global_across_concurrent_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock = threading.Lock()
    active = 0
    maximum = 0

    def fake_score(*_args, **_kwargs):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.03)
        with lock:
            active -= 1
        return {
            "score": 1.0,
            "reward": 1.0,
            "valid": True,
            "infrastructure_error": False,
            "include_in_normalization": True,
            "include_in_loss": True,
            "retry": False,
            "retry_requested": False,
            "retry_exhausted": False,
            "retry_token": "token",
            "retry_attempt": 0,
            "worker_identity": "worker",
            "reason": "pass",
            "rollout_id": "r",
            "problem_id": "p",
        }

    async def run_groups() -> None:
        await asyncio.gather(
            mediator._score_queued(
                [{}, {}, {}, {}], object(), executor="host", retries=0,
            ),
            mediator._score_queued(
                [{}, {}, {}, {}], object(), executor="host", retries=0,
            ),
        )

    monkeypatch.setenv(mediator.WORKERS_ENV, "2")
    monkeypatch.setattr(mediator, "score_sample", fake_score)
    asyncio.run(run_groups())
    assert maximum == 2


def test_outer_envelope_authenticates_candidate_and_immutable_runner_receipt() -> None:
    receipt = mediator.evaluate_response(
        registry().resolve("portable-adder"),
        valid_response(),
        executor="host",
        invalid_retries=0,
    )
    verified = mediator.verify_mediator_receipt(receipt)
    inner = verified["attempts"][-1]["runner_receipt"]
    assert verified["candidate_sha256"] == inner["candidate_sha256"]
    assert verified["mediator_receipt_sha256"] == mediator.mediator_receipt_sha256(verified)

    tampered = copy.deepcopy(verified)
    tampered["candidate_sha256"] = "0" * 64
    tampered = mediator.sign_mediator_receipt(tampered)
    with pytest.raises(mediator.MediatorError, match="candidate_sha256"):
        mediator.verify_mediator_receipt(tampered)


def test_live_scoring_requires_actual_prompt_and_returns_explicit_mask_contract() -> None:
    row = prepared_row()
    result = mediator.score_sample(
        {"metadata": row["metadata"], "response": valid_response()},
        registry(),
        executor="host",
        invalid_retries=0,
    )
    assert result["reason"] == "MISSING_ROLLOUT_PROMPT"
    assert result["valid"] is False
    assert result["include_in_normalization"] is False
    assert result["include_in_loss"] is False
    assert result["retry"] is False
    assert result["retry_requested"] is False


def test_production_reward_hook_rejects_single_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(mediator.REQUIRE_BATCH_ENV, "1")
    with pytest.raises(mediator.MediatorError) as raised:
        asyncio.run(mediator.reward_func(None, {}))
    assert raised.value.reason == "BATCH_SCORING_REQUIRED"


def test_invalid_retry_is_rescheduled_in_a_later_queue_round(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, str | None]] = []

    def fake_score(
        item, registry_value, *, executor, invalid_retries, retry_token=None,
        retry_attempt=0, retry_limit=None, runtime_args=None,
    ):
        calls.append((retry_attempt, retry_token))
        token = retry_token or "stable-token"
        if retry_attempt == 0:
            return {
                "score": 0.0,
                "reward": 0.0,
                "valid": False,
                "infrastructure_error": True,
                "include_in_normalization": False,
                "include_in_loss": False,
                "retry": True,
                "retry_requested": True,
                "retry_exhausted": False,
                "retry_token": token,
                "retry_attempt": retry_attempt,
                "worker_identity": "worker-first",
                "reason": "verifier_invalid",
                "rollout_id": "r",
                "problem_id": "p",
            }
        return {
            "score": 1.0,
            "reward": 1.0,
            "valid": True,
            "infrastructure_error": False,
            "include_in_normalization": True,
            "include_in_loss": True,
            "retry": False,
            "retry_requested": False,
            "retry_exhausted": False,
            "retry_token": token,
            "retry_attempt": retry_attempt,
            "worker_identity": "worker-retry",
            "reason": "pass",
            "rollout_id": "r",
            "problem_id": "p",
        }

    monkeypatch.setattr(mediator, "_settings", lambda: (object(), "host", 1))
    monkeypatch.setattr(mediator, "score_sample", fake_score)
    values = asyncio.run(mediator.reward_func(None, [{}]))
    assert calls == [(0, None), (1, "stable-token")]
    assert values[0]["retry_recovered"] is True
    assert values[0]["retry_queue_rounds"] == 2
    assert [item["worker_identity"] for item in values[0]["retry_history"]] == [
        "worker-first", "worker-retry",
    ]


def test_authenticated_staged_projection_preserves_bipolar_partial_score() -> None:
    receipt = {
        "status": "FAIL",
        "format_valid": True,
        "reward_projection": {
            "kind": "staged-g04-bipolar-v1",
            "pass": 1.0,
            "format_fail": -1.0,
            "g01_fail": -0.875,
            "g02_fail": -0.75,
            "g03_fail": -0.5,
            "g04_scale": 2.0,
            "g04_offset": -1.0,
        },
        "policies": [
            {"policy": "G01", "status": "PASS"},
            {"policy": "G02", "status": "PASS"},
            {"policy": "G03", "status": "PASS"},
            {"policy": "G04", "status": "FAIL", "facts": {"score": 0.25}},
        ],
    }
    projection = mediator.receipt_to_reward(receipt)
    assert projection["reward"] == pytest.approx(-0.5)
    assert projection["stage"] == "functional"
    assert projection["tests"] == pytest.approx(0.25)


def test_validate_dataset_checks_serialized_prompt_binding(tmp_path: Path) -> None:
    row = prepared_row()
    path = tmp_path / "train.jsonl"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    report = mediator.validate_dataset(path, registry())
    assert report["row_count"] == 1
    row["prompt"][-1]["content"] += "stale"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(mediator.MediatorError) as raised:
        mediator.validate_dataset(path, registry())
    assert raised.value.reason == "PROMPT_BINDING_MISMATCH"


def test_hard_preflight_checks_data_and_coverage_before_controls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class RegistryStub:
        bundle_ids = ["bundle-a", "bundle-b"]

    monkeypatch.delenv(mediator.TRAIN_DATA_ENV, raising=False)
    monkeypatch.setattr(
        mediator, "TaskBundleRegistry", lambda _: RegistryStub(),
    )

    def fake_validate(*_args: object) -> dict:
        events.append("dataset")
        return {"task_bundle_ids": ["bundle-a"]}

    monkeypatch.setattr(mediator, "validate_dataset", fake_validate)

    def fake_controls(*_args: object, **_kwargs: object) -> dict:
        events.append("controls")
        return {"ready": True}

    monkeypatch.setattr(mediator, "_preflight_report", fake_controls)

    with pytest.raises(mediator.MediatorError) as missing:
        mediator._hard_preflight_report(tmp_path / "registry.json")
    assert missing.value.reason == "MISSING_PREFLIGHT_DATASET"
    assert events == []

    with pytest.raises(mediator.MediatorError) as mismatch:
        mediator._hard_preflight_report(
            tmp_path / "registry.json", data_path=tmp_path / "train.jsonl"
        )
    assert mismatch.value.reason == "PREFLIGHT_DATASET_COVERAGE_MISMATCH"
    assert events == ["dataset"]


def test_cli_accepts_exact_positional_preflight_invocation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        mediator,
        "_hard_preflight_report",
        lambda registry_path, data_path=None: {"ready": True},
    )
    monkeypatch.setattr(sys, "argv", ["global_verifier_grpo_mediator", "preflight"])
    assert mediator.main() == 0
    assert json.loads(capsys.readouterr().out)["ready"] is True
