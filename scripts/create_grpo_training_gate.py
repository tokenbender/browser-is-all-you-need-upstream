"""Create a provenance gate for a completed Aider GRPO checkpoint set."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any


ITERATION_RE = re.compile(r"^iter_(\d+)$")
EXPECTED_ADAPTER_FILES = ("adapter_model.bin", "adapter_config.json")
EXPECTED_SOURCE_TENSORS = 9_741
EXPECTED_LAYER_47_TENSORS = 207


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_native_shard_names(
    expected_count: int,
    *,
    tensor_parallel_size: int | None = None,
    expert_parallel_size: int = 1,
    world_size: int | None = None,
) -> set[str]:
    if expected_count <= 0:
        raise ValueError("expected native shard count must be positive")
    tp_size = expected_count if tensor_parallel_size is None else tensor_parallel_size
    if tp_size <= 0 or expert_parallel_size <= 0 or (world_size is not None and world_size <= 0):
        raise ValueError("TP, EP, and world sizes must be positive")
    if expert_parallel_size == 1:
        if expected_count != tp_size:
            raise ValueError("legacy TP-only native shard count must equal TP size")
        return {f"adapter_megatron_tp{tp}_pp0.pt" for tp in range(tp_size)}
    owner_world_size = expected_count if world_size is None else world_size
    names = {
        f"adapter_megatron_tp{rank % tp_size}_pp0_ep{rank % expert_parallel_size}.pt"
        for rank in range(owner_world_size)
    }
    if len(names) != expected_count:
        raise ValueError(
            "EP-aware native shard count does not match the TP/EP owners implied by world size"
        )
    return names


def _checkpoint_record(
    iteration_dir: Path,
    *,
    expected_native_shards: int,
    expected_training_states: int,
    tensor_parallel_size: int | None = None,
    expert_parallel_size: int = 1,
    world_size: int | None = None,
) -> dict[str, Any]:
    import torch

    match = ITERATION_RE.fullmatch(iteration_dir.name)
    if match is None:
        raise ValueError(f"invalid checkpoint iteration name: {iteration_dir.name}")
    adapter = iteration_dir / "adapter"
    for name in EXPECTED_ADAPTER_FILES:
        if not (adapter / name).is_file():
            raise FileNotFoundError(f"incomplete GRPO adapter: {adapter / name}")
    native = sorted(adapter.glob("adapter_megatron_tp*_pp*.pt"))
    expected_names = expected_native_shard_names(
        expected_native_shards,
        tensor_parallel_size=tensor_parallel_size,
        expert_parallel_size=expert_parallel_size,
        world_size=world_size,
    )
    if {path.name for path in native} != expected_names:
        raise RuntimeError(f"GRPO native shard set is incomplete: {adapter}")
    training_state = sorted(adapter.glob("training_state_rank*.pt"))
    expected_training_names = {
        f"training_state_rank{index}.pt" for index in range(expected_training_states)
    }
    if {path.name for path in training_state} != expected_training_names:
        raise RuntimeError(f"GRPO training-state set is incomplete: {adapter}")
    state = torch.load(
        adapter / "adapter_model.bin", map_location="cpu", weights_only=True, mmap=True
    )
    layer_47 = [key for key in state if ".layers.47." in key]
    if len(state) != EXPECTED_SOURCE_TENSORS or len(layer_47) != EXPECTED_LAYER_47_TENSORS:
        raise RuntimeError(f"GRPO adapter tensor domain is invalid: {adapter}")
    return {
        "iteration": int(match.group(1)),
        "adapter_path": str(adapter),
        "adapter_model_sha256": sha256_path(adapter / "adapter_model.bin"),
        "adapter_config_sha256": sha256_path(adapter / "adapter_config.json"),
        "tensor_count": len(state),
        "layer_47_tensor_count": len(layer_47),
        "native_shards": {path.name: sha256_path(path) for path in native},
        "training_state_files": sorted(path.name for path in training_state),
    }


def create_gate(
    *,
    run_id: str,
    run_root: Path,
    save_dir: Path,
    data_manifest_path: Path,
    source_adapter_path: Path,
    expected_source_adapter_sha256: str,
    hybrid_manifest_path: Path,
    source_commit: str,
    phase: str,
    num_rollout: int,
    gpus_per_node: int,
    expected_native_shards: int,
    tensor_parallel_size: int | None = None,
    expert_parallel_size: int = 1,
    expected_native_reconstruction_manifest_sha256: str = "",
    expected_train_count: int = 253,
    output: Path,
) -> dict[str, Any]:
    data_manifest = json.loads(data_manifest_path.read_text(encoding="utf-8"))
    if data_manifest.get("kind") != "aider-cpp-rl-grpo":
        raise RuntimeError("training data is not the Aider C++ RL GRPO corpus")
    if data_manifest.get("counts", {}).get("train") != expected_train_count:
        raise RuntimeError(
            f"Aider GRPO gate requires {expected_train_count} train tasks, "
            f"manifest has {data_manifest.get('counts', {}).get('train')}"
        )
    source_sha256 = sha256_path(source_adapter_path / "adapter_model.bin")
    if source_sha256 != expected_source_adapter_sha256:
        raise RuntimeError("warm-start adapter bytes do not match the bound SHA-256")
    expected_native_names = expected_native_shard_names(
        expected_native_shards,
        tensor_parallel_size=tensor_parallel_size,
        expert_parallel_size=expert_parallel_size,
        world_size=gpus_per_node,
    )
    hybrid_manifest = json.loads(hybrid_manifest_path.read_text(encoding="utf-8"))
    hybrid_native_files = hybrid_manifest.get("native_files")
    if (
        hybrid_manifest.get("source_adapter_model_sha256") != source_sha256
        or hybrid_manifest.get("source") != str(source_adapter_path.resolve())
        or not isinstance(hybrid_native_files, Mapping)
        or set(hybrid_native_files) != expected_native_names
        or hybrid_manifest.get("training_state_files") != {}
    ):
        raise RuntimeError("hybrid adapter is not bound to the selected SFT warm start")
    hybrid_root = hybrid_manifest_path.parent
    for name in sorted(expected_native_names):
        expected_sha256 = hybrid_native_files[name]
        native_path = hybrid_root / name
        if (
            not isinstance(expected_sha256, str)
            or native_path.is_symlink()
            or not native_path.is_file()
            or sha256_path(native_path) != expected_sha256
        ):
            raise RuntimeError(
                f"hybrid native shard is absent or does not match its manifest: {native_path}"
            )

    reconstruction_record = hybrid_manifest.get("native_reconstruction_manifest")
    if expected_native_reconstruction_manifest_sha256:
        expected_reconstruction_sha256 = (
            expected_native_reconstruction_manifest_sha256.lower()
        )
        if not re.fullmatch(r"[0-9a-f]{64}", expected_reconstruction_sha256):
            raise RuntimeError("expected native reconstruction manifest SHA-256 is invalid")
        if (
            not isinstance(reconstruction_record, Mapping)
            or reconstruction_record.get("file")
            != "native_reconstruction_manifest.json"
            or reconstruction_record.get("sha256") != expected_reconstruction_sha256
            or reconstruction_record.get("status") != "passed"
            or reconstruction_record.get("source_hf_roundtrip_status") != "passed"
            or reconstruction_record.get("native_shard_count")
            != expected_native_shards
        ):
            raise RuntimeError("hybrid adapter lacks the bound native reconstruction proof")
        reconstruction_path = hybrid_root / "native_reconstruction_manifest.json"
        if (
            reconstruction_path.is_symlink()
            or not reconstruction_path.is_file()
            or sha256_path(reconstruction_path) != expected_reconstruction_sha256
        ):
            raise RuntimeError("hybrid native reconstruction manifest bytes are not bound")
        reconstruction = json.loads(reconstruction_path.read_text(encoding="utf-8"))
        if not isinstance(reconstruction, Mapping):
            raise RuntimeError("native reconstruction proof is not a JSON object")
        reconstruction_source = reconstruction.get("source")
        reconstruction_template = reconstruction.get("template")
        mapping = reconstruction.get("mapping")
        outputs = reconstruction.get("outputs")
        roundtrip = mapping.get("source_hf_roundtrip") if isinstance(mapping, Mapping) else None
        template_proof = (
            reconstruction_template.get("proof")
            if isinstance(reconstruction_template, Mapping)
            else None
        )
        output_shards = outputs.get("native_shards") if isinstance(outputs, Mapping) else None
        reconstruction_hashes = (
            {
                name: record.get("sha256")
                for name, record in output_shards.items()
                if isinstance(record, Mapping)
            }
            if isinstance(output_shards, Mapping)
            else {}
        )
        topology = mapping.get("rank_topology") if isinstance(mapping, Mapping) else None
        effective_tp_size = (
            expected_native_shards
            if tensor_parallel_size is None
            else tensor_parallel_size
        )
        experts_per_shard = (
            mapping.get("experts_per_shard") if isinstance(mapping, Mapping) else None
        )
        expected_topology = (
            {
                (
                    rank,
                    rank % effective_tp_size,
                    rank % expert_parallel_size,
                    (rank % expert_parallel_size) * experts_per_shard,
                    (rank % expert_parallel_size + 1) * experts_per_shard,
                    "adapter_megatron_tp"
                    f"{rank % effective_tp_size}_pp0_ep{rank % expert_parallel_size}.pt",
                )
                for rank in range(expected_native_shards)
            }
            if isinstance(experts_per_shard, int) and experts_per_shard > 0
            else set()
        )
        observed_topology = (
            {
                (
                    record.get("global_rank"),
                    record.get("tp_rank"),
                    record.get("ep_rank"),
                    record.get("expert_index_start"),
                    record.get("expert_index_stop"),
                    record.get("filename"),
                )
                for record in topology
                if isinstance(record, Mapping)
            }
            if isinstance(topology, list)
            else set()
        )
        if (
            reconstruction.get("schema_version") != 1
            or reconstruction.get("kind")
            != "glm47-hf-to-megatron-tp-native-reconstruction"
            or reconstruction.get("status") != "passed"
            or not isinstance(reconstruction_source, Mapping)
            or reconstruction_source.get("adapter_model_sha256") != source_sha256
            or not isinstance(mapping, Mapping)
            or mapping.get("tp_size") != effective_tp_size
            or mapping.get("expert_parallel_size") != expert_parallel_size
            or not isinstance(roundtrip, Mapping)
            or roundtrip.get("status") != "passed"
            or roundtrip.get("all_source_hf_tensor_bytes_exact") is not True
            or roundtrip.get("all_source_hf_tensors_value_exact") is not True
            or roundtrip.get("coverage_fraction") != 1.0
            or not isinstance(template_proof, Mapping)
            or template_proof.get("status") != "passed"
            or template_proof.get("all_template_native_tensor_bytes_exact")
            is not True
            or template_proof.get("all_template_native_tensors_value_exact")
            is not True
            or observed_topology != expected_topology
            or reconstruction_hashes != dict(hybrid_native_files)
        ):
            raise RuntimeError(
                "native reconstruction proof does not match the warm-start adapter topology"
            )
    elif reconstruction_record is not None:
        raise RuntimeError(
            "hybrid adapter carries a reconstruction proof without an expected manifest SHA-256"
        )

    iteration_dirs = sorted(
        (path for path in save_dir.glob("iter_*") if path.is_dir()),
        key=lambda path: int(ITERATION_RE.fullmatch(path.name).group(1))
        if ITERATION_RE.fullmatch(path.name)
        else -1,
    )
    checkpoints = [
        _checkpoint_record(
            path,
            expected_native_shards=expected_native_shards,
            expected_training_states=gpus_per_node,
            tensor_parallel_size=tensor_parallel_size,
            expert_parallel_size=expert_parallel_size,
            world_size=gpus_per_node,
        )
        for path in iteration_dirs
    ]
    if not checkpoints:
        raise RuntimeError(f"no complete GRPO checkpoints found beneath {save_dir}")
    if checkpoints[-1]["iteration"] + 1 < num_rollout:
        raise RuntimeError("checkpoint iterations do not cover the configured rollout count")

    gate = {
        "schema_version": 1,
        "kind": "glm47-aider-grpo-training-gate",
        "status": "passed",
        "phase": phase,
        "run_id": run_id,
        "run_root": str(run_root),
        "source_commit": source_commit,
        "gpus_per_node": gpus_per_node,
        "tensor_parallel_size": (
            expected_native_shards if tensor_parallel_size is None else tensor_parallel_size
        ),
        "expert_parallel_size": expert_parallel_size,
        "num_rollout": num_rollout,
        "data_manifest_path": str(data_manifest_path),
        "data_manifest_sha256": sha256_path(data_manifest_path),
        "data_source_tree_sha256": data_manifest["source_tree_sha256"],
        "training_task_count": data_manifest["counts"]["train"],
        "official_26_role": data_manifest["split_contract"]["official_26"],
        "source_adapter_path": str(source_adapter_path),
        "source_adapter_sha256": source_sha256,
        "hybrid_manifest_path": str(hybrid_manifest_path),
        "hybrid_manifest_sha256": sha256_path(hybrid_manifest_path),
        "native_reconstruction_manifest": reconstruction_record,
        "checkpoints": checkpoints,
        "latest_checkpoint": checkpoints[-1],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(gate, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(output)
    return gate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--save-dir", type=Path, required=True)
    parser.add_argument("--data-manifest", type=Path, required=True)
    parser.add_argument("--source-adapter", type=Path, required=True)
    parser.add_argument("--expected-source-adapter-sha256", required=True)
    parser.add_argument("--hybrid-manifest", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--phase", choices=("profile", "full"), required=True)
    parser.add_argument("--num-rollout", type=int, required=True)
    parser.add_argument("--gpus-per-node", type=int, required=True)
    parser.add_argument("--expected-native-shards", type=int, required=True)
    parser.add_argument("--tensor-parallel-size", type=int)
    parser.add_argument("--expert-parallel-size", type=int, default=1)
    parser.add_argument(
        "--expected-native-reconstruction-manifest-sha256",
        default="",
    )
    parser.add_argument("--expected-train-count", type=int, default=253)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    gate = create_gate(
        run_id=args.run_id,
        run_root=args.run_root,
        save_dir=args.save_dir,
        data_manifest_path=args.data_manifest,
        source_adapter_path=args.source_adapter,
        expected_source_adapter_sha256=args.expected_source_adapter_sha256,
        hybrid_manifest_path=args.hybrid_manifest,
        source_commit=args.source_commit,
        phase=args.phase,
        num_rollout=args.num_rollout,
        gpus_per_node=args.gpus_per_node,
        expected_native_shards=args.expected_native_shards,
        tensor_parallel_size=args.tensor_parallel_size,
        expert_parallel_size=args.expert_parallel_size,
        expected_native_reconstruction_manifest_sha256=(
            args.expected_native_reconstruction_manifest_sha256
        ),
        expected_train_count=args.expected_train_count,
        output=args.output,
    )
    print(json.dumps(gate, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
