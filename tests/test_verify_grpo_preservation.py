from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.verify_grpo_preservation import (
    expected_native_shard_names,
    verify_preservation,
)


@pytest.fixture(autouse=True)
def _fake_torch(monkeypatch: pytest.MonkeyPatch) -> None:
    def load(path: Path, **_: object) -> object:
        return json.loads(Path(path).read_text(encoding="utf-8"))

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(load=load))


def _write_rollout(path: Path, sample_count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "samples": [
                    {
                        "index": index,
                        "response": f"response-{index}",
                        "reward": {
                            "score": 0.25,
                            "reward": 0.25,
                            "reason": "tests_failed",
                            "task_id": f"aider-cpp-rl/task-{index % 8}",
                            "infrastructure_error": False,
                        },
                    }
                    for index in range(sample_count)
                ]
            }
        ),
        encoding="utf-8",
    )


def _build_run(tmp_path: Path) -> Path:
    run_root = tmp_path / "run"
    gate_checkpoints = []
    for index in range(11):
        _write_rollout(run_root / "rollout_dumps" / f"grpo_{index}.pt", 256)
        _write_rollout(run_root / "rollout_dumps" / f"grpo_eval_{index}.pt", 22)

        adapter = run_root / "checkpoints" / "grpo_lora_r16" / f"iter_{index:07d}" / "adapter"
        adapter.mkdir(parents=True)
        (adapter / "adapter_model.bin").write_bytes(f"adapter-{index}".encode())
        (adapter / "adapter_config.json").write_text(
            json.dumps({"r": 32, "lora_alpha": 32}) + "\n", encoding="utf-8"
        )
        for shard in range(4):
            (adapter / f"adapter_megatron_tp{shard}_pp0.pt").write_bytes(
                f"native-{index}-{shard}".encode()
            )
        for rank in range(8):
            (adapter / f"training_state_rank{rank}.pt").write_bytes(
                f"state-{index}-{rank}".encode()
            )
        gate_checkpoints.append(
            {
                "iteration": index,
                "adapter_path": str(adapter),
                "adapter_model_sha256": hashlib.sha256(
                    (adapter / "adapter_model.bin").read_bytes()
                ).hexdigest(),
                "adapter_config_sha256": hashlib.sha256(
                    (adapter / "adapter_config.json").read_bytes()
                ).hexdigest(),
                "native_shards": {
                    path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in sorted(adapter.glob("adapter_megatron_*.pt"))
                },
                "training_state_files": [f"training_state_rank{rank}.pt" for rank in range(8)],
            }
        )

    stage = run_root / "grpo_lora_r16"
    stage.mkdir(parents=True)
    (stage / "run.log").write_text("training complete\n", encoding="utf-8")
    (stage / "grpo_training_gate.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "glm47-aider-grpo-training-gate",
                "status": "passed",
                "run_id": "run",
                "run_root": str(run_root),
                "gpus_per_node": 8,
                "tensor_parallel_size": 4,
                "expert_parallel_size": 1,
                "num_rollout": 11,
                "checkpoints": gate_checkpoints,
                "latest_checkpoint": gate_checkpoints[-1],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (stage / "run_receipt.txt").write_text(
        "\n".join(
            (
                "status=success",
                "training_gate_status=passed",
                "run_id=run",
                f"run_root={run_root}",
                "num_rollout=11",
                "gpus_per_node=8",
                "tensor_model_parallel_size=4",
                "expert_model_parallel_size=1",
                f"training_gate={stage / 'grpo_training_gate.json'}",
                "",
            )
        ),
        encoding="utf-8",
    )
    (stage / "vram_usage.csv").write_text("timestamp,index,memory.used\n", encoding="utf-8")
    wandb = run_root / "wandb" / "wandb" / "run-test" / "logs"
    wandb.mkdir(parents=True)
    (wandb / "debug.log").write_text("wandb history flushed\n", encoding="utf-8")
    sync = run_root / "sync_metrics" / "rollout-10"
    sync.mkdir(parents=True)
    (sync / "rank-0.json").write_text('{"status":"passed"}\n', encoding="utf-8")
    return run_root


def _source_regular_paths(root: Path) -> list[str]:
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    )


def _refresh_gate_native_inventory(
    run_root: Path, *, tensor_parallel_size: int, expert_parallel_size: int
) -> None:
    gate_path = run_root / "grpo_lora_r16" / "grpo_training_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    gate["tensor_parallel_size"] = tensor_parallel_size
    gate["expert_parallel_size"] = expert_parallel_size
    for record in gate["checkpoints"]:
        adapter = (
            run_root
            / "checkpoints"
            / "grpo_lora_r16"
            / f"iter_{record['iteration']:07d}"
            / "adapter"
        )
        record["native_shards"] = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(adapter.glob("adapter_megatron_*.pt"))
        }
    gate["latest_checkpoint"] = gate["checkpoints"][-1]
    gate_path.write_text(json.dumps(gate) + "\n", encoding="utf-8")

    receipt_path = run_root / "grpo_lora_r16" / "run_receipt.txt"
    receipt = receipt_path.read_text(encoding="utf-8")
    receipt = receipt.replace(
        "tensor_model_parallel_size=4",
        f"tensor_model_parallel_size={tensor_parallel_size}",
    ).replace(
        "expert_model_parallel_size=1",
        f"expert_model_parallel_size={expert_parallel_size}",
    )
    receipt_path.write_text(receipt, encoding="utf-8")


def test_preservation_requires_exact_tp4_ep8_native_topology() -> None:
    assert expected_native_shard_names(8, tensor_parallel_size=4, expert_parallel_size=8) == {
        f"adapter_megatron_tp{ep_rank % 4}_pp0_ep{ep_rank}.pt" for ep_rank in range(8)
    }
    assert expected_native_shard_names(
        4, tensor_parallel_size=4, expert_parallel_size=2, world_size=8
    ) == {
        "adapter_megatron_tp0_pp0_ep0.pt",
        "adapter_megatron_tp1_pp0_ep1.pt",
        "adapter_megatron_tp2_pp0_ep0.pt",
        "adapter_megatron_tp3_pp0_ep1.pt",
    }
    with pytest.raises(ValueError, match="positive"):
        expected_native_shard_names(8, tensor_parallel_size=0, expert_parallel_size=8, world_size=8)


def test_preservation_manifest_is_complete_and_deterministic(tmp_path: Path) -> None:
    run_root = _build_run(tmp_path)
    output_a = tmp_path / "preserved-a"
    output_b = tmp_path / "preserved-b"

    manifest = verify_preservation(run_root, output_a)
    verify_preservation(run_root, output_b)

    assert manifest["status"] == "passed"
    assert manifest["rollout_evidence"]["train_sample_total"] == 2_816
    assert manifest["rollout_evidence"]["eval_sample_total"] == 242
    assert len(manifest["checkpoints"]) == 11
    assert len(manifest["operational_evidence"]["wandb"]["files"]) == 1
    assert len(manifest["operational_evidence"]["sync"]["files"]) == 1
    assert (output_a / "preservation_manifest.json").read_bytes() == (
        output_b / "preservation_manifest.json"
    ).read_bytes()
    assert (output_a / "SHA256SUMS").read_bytes() == (output_b / "SHA256SUMS").read_bytes()

    sums = (output_a / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    summed_paths = [line.split("  ", 1)[1] for line in sums]
    assert summed_paths == _source_regular_paths(run_root)
    assert summed_paths == sorted(summed_paths)
    assert manifest["retained_file_count"] == len(summed_paths)
    assert (
        hashlib.sha256((output_a / "SHA256SUMS").read_bytes()).hexdigest()
        == manifest["sha256sums_sha256"]
    )


def test_preservation_accepts_complete_tp4_ep8_native_sets(tmp_path: Path) -> None:
    run_root = _build_run(tmp_path)
    names = expected_native_shard_names(8, tensor_parallel_size=4, expert_parallel_size=8)
    for adapter in (run_root / "checkpoints" / "grpo_lora_r16").glob("iter_*/adapter"):
        for path in adapter.glob("adapter_megatron_*.pt"):
            path.unlink()
        for name in names:
            (adapter / name).write_bytes(f"native-{adapter.parent.name}-{name}".encode())
    _refresh_gate_native_inventory(run_root, tensor_parallel_size=4, expert_parallel_size=8)
    gate_path = run_root / "grpo_lora_r16" / "grpo_training_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    gate["native_reconstruction_manifest"] = {
        "sha256": "a" * 64,
        "status": "passed",
        "source_hf_roundtrip_status": "passed",
        "native_shard_count": 8,
    }
    gate_path.write_text(json.dumps(gate) + "\n", encoding="utf-8")
    receipt_path = run_root / "grpo_lora_r16" / "run_receipt.txt"
    with receipt_path.open("a", encoding="utf-8") as handle:
        handle.write("expected_native_reconstruction_manifest_sha256=" + "a" * 64 + "\n")

    manifest = verify_preservation(
        run_root,
        tmp_path / "preserved-ep8",
        expected_native_shards=8,
        tensor_parallel_size=4,
        expert_parallel_size=8,
    )
    assert manifest["contract"]["native_shards_per_checkpoint"] == 8
    assert manifest["contract"]["tensor_parallel_size"] == 4
    assert manifest["contract"]["expert_parallel_size"] == 8


@pytest.mark.parametrize("extra", [False, True])
def test_preservation_rejects_missing_or_extra_rollout_slot(tmp_path: Path, extra: bool) -> None:
    run_root = _build_run(tmp_path)
    if extra:
        _write_rollout(run_root / "rollout_dumps" / "grpo_11.pt", 256)
    else:
        (run_root / "rollout_dumps" / "grpo_10.pt").unlink()

    with pytest.raises(RuntimeError, match="rollout dump slots"):
        verify_preservation(run_root, tmp_path / "preserved")


def test_preservation_rejects_wrong_rollout_sample_count(tmp_path: Path) -> None:
    run_root = _build_run(tmp_path)
    _write_rollout(run_root / "rollout_dumps" / "grpo_eval_4.pt", 21)

    with pytest.raises(RuntimeError, match="sample count mismatch"):
        verify_preservation(run_root, tmp_path / "preserved")


@pytest.mark.parametrize(
    ("record", "message"),
    [
        (0.0, "non-mapping reward"),
        (
            {
                "score": float("nan"),
                "reward": float("nan"),
                "reason": "tests_failed",
                "task_id": "aider-cpp-rl/task",
                "infrastructure_error": False,
            },
            "invalid numeric reward",
        ),
        (
            {
                "score": 0.0,
                "reward": 0.0,
                "reason": "reward_exception",
                "task_id": "aider-cpp-rl/task",
                "infrastructure_error": True,
            },
            "infrastructure reward record",
        ),
    ],
)
def test_preservation_rejects_untrainable_reward_records(
    tmp_path: Path, record: object, message: str
) -> None:
    run_root = _build_run(tmp_path)
    path = run_root / "rollout_dumps" / "grpo_0.pt"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["samples"][3]["reward"] = record
    path.write_text(json.dumps(payload, allow_nan=True), encoding="utf-8")

    with pytest.raises(RuntimeError, match=message):
        verify_preservation(run_root, tmp_path / "preserved")


@pytest.mark.parametrize("extra", [False, True])
def test_preservation_rejects_missing_or_extra_checkpoint_slot(tmp_path: Path, extra: bool) -> None:
    run_root = _build_run(tmp_path)
    checkpoint_root = run_root / "checkpoints" / "grpo_lora_r16"
    if extra:
        (checkpoint_root / "iter_0000011").mkdir()
    else:
        checkpoint = checkpoint_root / "iter_0000010"
        for path in sorted(checkpoint.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            else:
                path.rmdir()
        checkpoint.rmdir()

    with pytest.raises(RuntimeError, match="checkpoint slots"):
        verify_preservation(run_root, tmp_path / "preserved")


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("adapter_megatron_tp3_pp0.pt", "native shard slots"),
        ("training_state_rank7.pt", "training-state slots"),
    ],
)
def test_preservation_rejects_incomplete_checkpoint_file_sets(
    tmp_path: Path, name: str, message: str
) -> None:
    run_root = _build_run(tmp_path)
    adapter = run_root / "checkpoints" / "grpo_lora_r16" / "iter_0000005" / "adapter"
    (adapter / name).unlink()

    with pytest.raises(RuntimeError, match=message):
        verify_preservation(run_root, tmp_path / "preserved")


def test_preservation_requires_operational_evidence(tmp_path: Path) -> None:
    run_root = _build_run(tmp_path)
    (run_root / "wandb" / "wandb" / "run-test" / "logs" / "debug.log").unlink()

    with pytest.raises(RuntimeError, match="W&B evidence"):
        verify_preservation(run_root, tmp_path / "preserved")


def test_preservation_rejects_foreign_training_gate(tmp_path: Path) -> None:
    run_root = _build_run(tmp_path)
    gate_path = run_root / "grpo_lora_r16" / "grpo_training_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    gate["run_id"] = "another-run"
    gate_path.write_text(json.dumps(gate) + "\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="not bound"):
        verify_preservation(run_root, tmp_path / "preserved")


def test_preservation_rejects_stale_checkpoint_hash_in_gate(tmp_path: Path) -> None:
    run_root = _build_run(tmp_path)
    gate_path = run_root / "grpo_lora_r16" / "grpo_training_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    gate["checkpoints"][3]["adapter_model_sha256"] = "0" * 64
    gate_path.write_text(json.dumps(gate) + "\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="does not match retained"):
        verify_preservation(run_root, tmp_path / "preserved")


def test_preservation_rejects_continuation_without_reconstruction_proof(
    tmp_path: Path,
) -> None:
    run_root = _build_run(tmp_path)
    receipt_path = run_root / "grpo_lora_r16" / "run_receipt.txt"
    with receipt_path.open("a", encoding="utf-8") as handle:
        handle.write("grpo_continuation_mode=weights_only_fresh_optimizer\n")
        handle.write("expected_native_reconstruction_manifest_sha256=" + "0" * 64 + "\n")

    with pytest.raises(RuntimeError, match="native reconstruction proof"):
        verify_preservation(run_root, tmp_path / "preserved")


def test_preservation_rejects_fresh_ep_run_without_reconstruction_proof(
    tmp_path: Path,
) -> None:
    run_root = _build_run(tmp_path)
    names = expected_native_shard_names(8, tensor_parallel_size=4, expert_parallel_size=8)
    for adapter in (run_root / "checkpoints" / "grpo_lora_r16").glob("iter_*/adapter"):
        for path in adapter.glob("adapter_megatron_*.pt"):
            path.unlink()
        for name in names:
            (adapter / name).write_bytes(f"native-{adapter.parent.name}-{name}".encode())
    _refresh_gate_native_inventory(run_root, tensor_parallel_size=4, expert_parallel_size=8)

    with pytest.raises(RuntimeError, match="native reconstruction proof"):
        verify_preservation(
            run_root,
            tmp_path / "preserved",
            expected_native_shards=8,
            tensor_parallel_size=4,
            expert_parallel_size=8,
        )
