from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from glm47_posttraining.aider_polyglot.rollout_receipts import (
    RolloutReceiptError,
    build_context_identity,
    build_hidden_partition_accounting,
    validate_context_identity,
    validate_hidden_partition_accounting,
)
from glm47_posttraining.aider_polyglot.schema import AiderPolyglotTask, AiderTestResult
from glm47_posttraining.integrations import miles_aider_polyglot as integration_module


def _bound_task(tmp_path: Path) -> tuple[AiderPolyglotTask, Path, Path]:
    exercise = tmp_path / "shadow" / "example"
    (exercise / ".grader").mkdir(parents=True)
    (exercise / "example.cpp").write_text("int answer() { return 0; }\n", encoding="utf-8")
    grader = b"int main() { return 0; }\n"
    (exercise / ".grader" / "test.cpp").write_bytes(grader)
    task = AiderPolyglotTask(
        task_id="charm-r8/example/short",
        exercise="charm-example",
        split="train",
        harness_kind="shadow_cpp17",
        exercise_dir="shadow/example",
        editable_files=["example.cpp"],
        prompt=[
            {"role": "system", "content": "Return whole files."},
            {"role": "user", "content": "Implement answer()."},
        ],
        source_revision="a" * 64,
        tags=["clean-room-charm-r8"],
        hidden_test_sha256=hashlib.sha256(grader).hexdigest(),
        source_prompt_sha256="b" * 64,
        prompt_contract="hybrid45-isolated-wholefile-v2",
        reward_contract="hybrid-bipolar45-v2",
    )
    task_path = task.write_json(tmp_path / "tasks" / "train" / "example.json")
    return task, task_path, exercise


def _sample(index: int) -> SimpleNamespace:
    return SimpleNamespace(
        index=index,
        rollout_id=7,
        prompt="<system>Return whole files.</system><user>Implement answer().</user>",
        response="example.cpp\n```cpp\nint answer() { return 42; }\n```\n",
        tokens=list(range(12)),
        response_length=4,
        status="finished",
        metadata={
            "base_task_id": "charm-example",
            "prompt_variant": "short",
        },
    )


def _context(tmp_path: Path, monkeypatch, index: int) -> dict[str, object]:
    monkeypatch.setenv("GLM47_TOKENIZER_REVISION", "glm47-tokenizer-pinned")
    monkeypatch.setenv("GLM47_TOKENIZER_MANIFEST_SHA256", "c" * 64)
    monkeypatch.setenv("GLM47_CHAT_TEMPLATE_SHA256", "d" * 64)
    monkeypatch.setenv("GLM47_CPP_SANDBOX_IMAGE", "sha256:" + "e" * 64)
    task, task_path, exercise = _bound_task(tmp_path)
    sample = _sample(index)
    return build_context_identity(
        sample=sample,
        task=task,
        task_path=task_path,
        exercise_dir=exercise,
        raw_response=sample.response,
        scored_response=sample.response,
        harness=AiderTestResult(
            status="passed",
            tests_passed=5,
            tests_total=5,
            verification_workspace_id=f"workspace-{index}",
        ),
    )


def _signal_record(context: dict[str, object]) -> dict[str, object]:
    return {
        "score": 0.1,
        "reward": 0.1,
        "reason": "tests_failed",
        "task_id": "charm-r8/example/short",
        "logical_task_id": "charm-example",
        "problem_id": "charm-example",
        "infrastructure_error": False,
        "tests_passed": 1,
        "tests_total": 5,
        "format_valid": True,
        "modified_files": ["example.cpp"],
        "compile_error": False,
        "context_identity": context,
    }


def test_context_receipt_binds_prompt_workspace_tokens_and_private_gates(
    tmp_path: Path, monkeypatch
) -> None:
    context = _context(tmp_path, monkeypatch, 0)
    validate_context_identity(context, maximum_prompt_tokens=8)
    assert context["logical_task_id"] == "charm-example"
    assert context["prompt_token_count"] == 8
    assert context["response_token_count"] == 4
    assert context["verification_workspace_id"] == "workspace-0"
    assert context["fixed26_exclusion_passed"] is True
    assert context["private_marker_scan_passed"] is True
    assert len(context["editable_file_manifest"]) == 1
    assert len(context["protected_file_manifest"]) == 1

    with pytest.raises(RolloutReceiptError, match="invalid token counts"):
        validate_context_identity(context, maximum_prompt_tokens=7)


def test_context_receipt_binds_isolated_workspace_when_verifier_is_not_executed(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("GLM47_TOKENIZER_REVISION", "glm47-tokenizer-pinned")
    monkeypatch.setenv("GLM47_TOKENIZER_MANIFEST_SHA256", "c" * 64)
    monkeypatch.setenv("GLM47_CHAT_TEMPLATE_SHA256", "d" * 64)
    monkeypatch.setenv("GLM47_CPP_SANDBOX_IMAGE", "sha256:" + "e" * 64)
    task, task_path, exercise = _bound_task(tmp_path)
    sample = _sample(0)
    context = build_context_identity(
        sample=sample,
        task=task,
        task_path=task_path,
        exercise_dir=exercise,
        raw_response=sample.response,
        scored_response=sample.response,
        harness=None,
        receipt_workspace_id="receipt-workspace-0",
    )

    validate_context_identity(context, maximum_prompt_tokens=8)
    assert context["verification_executed"] is False
    assert context["verification_workspace_binding"] == "isolated_receipt"
    assert context["verification_workspace_id"] == "receipt-workspace-0"


def test_hidden_partition_accounting_is_exact_distinct_and_digest_bound(
    tmp_path: Path, monkeypatch
) -> None:
    context = _context(tmp_path, monkeypatch, 0)
    hybrid = {
        "checks": {f"H{index}": index != 3 for index in range(1, 6)},
        "observed": {f"H{index}": True for index in range(1, 6)},
        "applicable": {f"H{index}": True for index in range(1, 6)},
        "continuous_semantic_score": 0.6,
    }
    accounting = build_hidden_partition_accounting(context, hybrid)
    validate_hidden_partition_accounting(accounting)
    assert accounting["partition_count"] == 5
    assert [item["partition_id"] for item in accounting["partitions"]] == [
        "H1",
        "H2",
        "H3",
        "H4",
        "H5",
    ]
    assert len({item["partition_sha256"] for item in accounting["partitions"]}) == 5


def test_strict_batch_context_gate_rejects_workspace_reuse(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GLM47_AIDER_EXPECTED_TRAIN_GROUPS", "1")
    monkeypatch.setenv("GLM47_AIDER_EXPECTED_SAMPLES_PER_GROUP", "2")
    monkeypatch.setenv("GLM47_AIDER_REQUIRE_CONTEXT_ISOLATION", "1")
    monkeypatch.setenv("MILES_GRPO_ADVANTAGE_POLICY", "miles-standard-grpo-group-std-v1")
    monkeypatch.setenv("GLM47_AIDER_MAX_PROMPT_TOKENS", "8")
    first = _context(tmp_path / "first", monkeypatch, 0)
    second = _context(tmp_path / "second", monkeypatch, 1)
    second["verification_workspace_id"] = first["verification_workspace_id"]
    data = [
        [
            SimpleNamespace(index=0, response="a", reward=_signal_record(first)),
            SimpleNamespace(index=1, response="b", reward=_signal_record(second)),
        ]
    ]
    with pytest.raises(
        integration_module.AiderRewardInfrastructureError,
        match="reuses a verifier workspace",
    ):
        integration_module.validate_aider_rollout_batch(
            SimpleNamespace(rollout_batch_size=1, n_samples_per_prompt=2), data
        )
