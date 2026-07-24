from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.create_grpo_training_gate import create_gate, expected_native_shard_names
from scripts.prepare_grpo_adapter import validate_native_reconstruction_manifest


def _write_adapter(path: Path) -> None:
    path.mkdir(parents=True)
    (path / "adapter_model.bin").write_bytes(b"adapter")
    (path / "adapter_config.json").write_text('{"r": 16}\n', encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> dict[str, Path | str]:
    run_root = tmp_path / "runs" / "run"
    source = tmp_path / "runs" / "sft" / "adapter"
    _write_adapter(source)
    data_manifest = run_root / "data" / "manifest.json"
    data_manifest.parent.mkdir(parents=True)
    data_manifest.write_text(
        json.dumps(
            {
                "kind": "aider-cpp-rl-grpo",
                "counts": {"train": 253},
                "source_tree_sha256": "a" * 64,
                "split_contract": {"official_26": "external fixed evaluation only"},
            }
        ),
        encoding="utf-8",
    )
    hybrid = run_root / "adapter_hybrid"
    hybrid.mkdir(parents=True)
    native_files = {}
    for index in range(4):
        native = hybrid / f"adapter_megatron_tp{index}_pp0.pt"
        native.write_bytes(b"native")
        native_files[native.name] = _sha256(native)
    hybrid_manifest = hybrid / "mtp_strip_manifest.json"
    hybrid_manifest.write_text(
        json.dumps(
            {
                "source": str(source.resolve()),
                "source_adapter_model_sha256": _sha256(source / "adapter_model.bin"),
                "native_files": native_files,
                "training_state_files": {},
            }
        ),
        encoding="utf-8",
    )
    checkpoint = run_root / "checkpoints" / "grpo_lora_r16" / "iter_0000000" / "adapter"
    _write_adapter(checkpoint)
    for index in range(4):
        (checkpoint / f"adapter_megatron_tp{index}_pp0.pt").write_bytes(b"native")
    for index in range(8):
        (checkpoint / f"training_state_rank{index}.pt").write_bytes(b"state")
    return {
        "run_root": run_root,
        "source": source,
        "source_sha": _sha256(source / "adapter_model.bin"),
        "data_manifest": data_manifest,
        "hybrid_manifest": hybrid_manifest,
        "save_dir": run_root / "checkpoints" / "grpo_lora_r16",
        "checkpoint": checkpoint,
    }


def _fake_torch(monkeypatch) -> None:
    state = {
        **{f"model.layers.47.tensor_{index}": object() for index in range(207)},
        **{f"model.layers.0.tensor_{index}": object() for index in range(9534)},
    }
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(load=lambda *args, **kwargs: state))


def _write_native_reconstruction_manifest(
    hybrid: Path,
    source: Path,
    names: set[str],
) -> tuple[Path, str]:
    topology = []
    output_shards = {}
    for ep_rank in range(8):
        tp_rank = ep_rank % 4
        name = f"adapter_megatron_tp{tp_rank}_pp0_ep{ep_rank}.pt"
        assert name in names
        topology.append(
            {
                "global_rank": ep_rank,
                "tp_rank": tp_rank,
                "ep_rank": ep_rank,
                "expert_index_start": ep_rank * 8,
                "expert_index_stop": (ep_rank + 1) * 8,
                "filename": name,
            }
        )
        output_shards[name] = {
            "sha256": _sha256(hybrid / name),
            "size_bytes": (hybrid / name).stat().st_size,
            "tp_rank": tp_rank,
            "ep_rank": ep_rank,
            "expert_index_start": ep_rank * 8,
            "expert_index_stop": (ep_rank + 1) * 8,
        }
    payload = {
        "schema_version": 1,
        "kind": "glm47-hf-to-megatron-tp-native-reconstruction",
        "status": "passed",
        "source": {
            "adapter_model_sha256": _sha256(source / "adapter_model.bin"),
            "adapter_config_sha256": _sha256(source / "adapter_config.json"),
        },
        "template": {
            "proof": {
                "status": "passed",
                "all_template_native_tensor_bytes_exact": True,
                "all_template_native_tensors_value_exact": True,
            }
        },
        "mapping": {
            "mode": "expert-parallel-aware",
            "tp_size": 4,
            "expert_parallel_size": 8,
            "experts_per_shard": 8,
            "rank_topology": topology,
            "source_hf_roundtrip": {
                "status": "passed",
                "all_source_hf_tensor_bytes_exact": True,
                "all_source_hf_tensors_value_exact": True,
                "coverage_fraction": 1.0,
                "native_shard_count": 8,
            },
        },
        "outputs": {
            "adapter_model.bin": {
                "sha256": _sha256(source / "adapter_model.bin")
            },
            "adapter_config.json": {
                "sha256": _sha256(source / "adapter_config.json")
            },
            "native_shards": output_shards,
        },
    }
    path = hybrid / "native_reconstruction_manifest.json"
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return path, _sha256(path)


def test_gate_requires_exact_tp4_ep8_native_topology() -> None:
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


def test_create_gate_binds_data_warm_start_and_checkpoint(tmp_path: Path, monkeypatch) -> None:
    _fake_torch(monkeypatch)
    fixture = _fixture(tmp_path)
    output = fixture["run_root"] / "grpo_lora_r16" / "grpo_training_gate.json"
    gate = create_gate(
        run_id="run",
        run_root=fixture["run_root"],
        save_dir=fixture["save_dir"],
        data_manifest_path=fixture["data_manifest"],
        source_adapter_path=fixture["source"],
        expected_source_adapter_sha256=fixture["source_sha"],
        hybrid_manifest_path=fixture["hybrid_manifest"],
        source_commit="deadbeef",
        phase="profile",
        num_rollout=1,
        gpus_per_node=8,
        expected_native_shards=4,
        output=output,
    )
    assert gate["status"] == "passed"
    assert gate["training_task_count"] == 253
    assert gate["latest_checkpoint"]["adapter_path"] == str(fixture["checkpoint"])
    assert gate["latest_checkpoint"]["tensor_count"] == 9741
    assert output.is_file()


def test_create_gate_accepts_complete_tp4_ep8_native_set(tmp_path: Path, monkeypatch) -> None:
    _fake_torch(monkeypatch)
    fixture = _fixture(tmp_path)
    names = expected_native_shard_names(8, tensor_parallel_size=4, expert_parallel_size=8)
    for root in (fixture["hybrid_manifest"].parent, fixture["checkpoint"]):
        for path in root.glob("adapter_megatron_*.pt"):
            path.unlink()
        for name in names:
            (root / name).write_bytes(b"native")
    hybrid = json.loads(fixture["hybrid_manifest"].read_text(encoding="utf-8"))
    hybrid["native_files"] = {
        name: _sha256(fixture["hybrid_manifest"].parent / name) for name in names
    }
    reconstruction_path, reconstruction_sha256 = _write_native_reconstruction_manifest(
        fixture["hybrid_manifest"].parent,
        fixture["source"],
        names,
    )
    _, reconstruction_record = validate_native_reconstruction_manifest(
        reconstruction_path,
        expected_manifest_sha256=reconstruction_sha256,
        source_adapter_model_sha256=fixture["source_sha"],
        source_adapter_config_sha256=_sha256(
            fixture["source"] / "adapter_config.json"
        ),
        expected_native_names=names,
        tensor_parallel_size=4,
        expert_parallel_size=8,
    )
    hybrid["native_reconstruction_manifest"] = reconstruction_record
    fixture["hybrid_manifest"].write_text(json.dumps(hybrid), encoding="utf-8")

    gate = create_gate(
        run_id="run",
        run_root=fixture["run_root"],
        save_dir=fixture["save_dir"],
        data_manifest_path=fixture["data_manifest"],
        source_adapter_path=fixture["source"],
        expected_source_adapter_sha256=fixture["source_sha"],
        hybrid_manifest_path=fixture["hybrid_manifest"],
        source_commit="deadbeef",
        phase="full",
        num_rollout=1,
        gpus_per_node=8,
        expected_native_shards=8,
        tensor_parallel_size=4,
        expert_parallel_size=8,
        expected_native_reconstruction_manifest_sha256=reconstruction_sha256,
        output=fixture["run_root"] / "gate.json",
    )
    assert gate["tensor_parallel_size"] == 4
    assert gate["expert_parallel_size"] == 8
    assert gate["native_reconstruction_manifest"]["sha256"] == reconstruction_sha256
    assert set(gate["latest_checkpoint"]["native_shards"]) == names


def test_create_gate_rejects_hybrid_native_bytes_not_bound_by_manifest(
    tmp_path: Path, monkeypatch
) -> None:
    _fake_torch(monkeypatch)
    fixture = _fixture(tmp_path)
    (fixture["hybrid_manifest"].parent / "adapter_megatron_tp2_pp0.pt").write_bytes(b"changed")

    with pytest.raises(RuntimeError, match="does not match its manifest"):
        create_gate(
            run_id="run",
            run_root=fixture["run_root"],
            save_dir=fixture["save_dir"],
            data_manifest_path=fixture["data_manifest"],
            source_adapter_path=fixture["source"],
            expected_source_adapter_sha256=fixture["source_sha"],
            hybrid_manifest_path=fixture["hybrid_manifest"],
            source_commit="deadbeef",
            phase="profile",
            num_rollout=1,
            gpus_per_node=8,
            expected_native_shards=4,
            output=fixture["run_root"] / "gate.json",
        )


def test_prepare_rejects_native_reconstruction_manifest_without_exact_proof(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    names = expected_native_shard_names(
        8, tensor_parallel_size=4, expert_parallel_size=8, world_size=8
    )
    hybrid_root = fixture["hybrid_manifest"].parent
    for path in hybrid_root.glob("adapter_megatron_*.pt"):
        path.unlink()
    for name in names:
        (hybrid_root / name).write_bytes(b"native")
    reconstruction_path, _ = _write_native_reconstruction_manifest(
        hybrid_root,
        fixture["source"],
        names,
    )
    payload = json.loads(reconstruction_path.read_text(encoding="utf-8"))
    payload["mapping"]["source_hf_roundtrip"][
        "all_source_hf_tensor_bytes_exact"
    ] = False
    reconstruction_path.write_text(
        json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="proof contract"):
        validate_native_reconstruction_manifest(
            reconstruction_path,
            expected_manifest_sha256=_sha256(reconstruction_path),
            source_adapter_model_sha256=fixture["source_sha"],
            source_adapter_config_sha256=_sha256(
                fixture["source"] / "adapter_config.json"
            ),
            expected_native_names=names,
            tensor_parallel_size=4,
            expert_parallel_size=8,
        )


def test_create_gate_rejects_incomplete_training_state(tmp_path: Path, monkeypatch) -> None:
    _fake_torch(monkeypatch)
    fixture = _fixture(tmp_path)
    (fixture["checkpoint"] / "training_state_rank7.pt").unlink()
    with pytest.raises(RuntimeError, match="training-state"):
        create_gate(
            run_id="run",
            run_root=fixture["run_root"],
            save_dir=fixture["save_dir"],
            data_manifest_path=fixture["data_manifest"],
            source_adapter_path=fixture["source"],
            expected_source_adapter_sha256=fixture["source_sha"],
            hybrid_manifest_path=fixture["hybrid_manifest"],
            source_commit="deadbeef",
            phase="profile",
            num_rollout=1,
            gpus_per_node=8,
            expected_native_shards=4,
            output=fixture["run_root"] / "gate.json",
        )
