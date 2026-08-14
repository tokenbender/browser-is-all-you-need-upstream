"""Create the GLM-4.7 adapter layout used by SGLang and Miles.

The Miles trainer saves LoRA adapters that include the MTP head's tensors
(GLM-4.7-Flash layer 47). The serving adapter contains decoder layers 0-46.
Usage:

    python scripts/prepare_grpo_adapter.py <trainer_adapter_dir> <serve_dir>
    python scripts/prepare_grpo_adapter.py --include-native <trainer_adapter_dir> <hybrid_dir>
    python scripts/prepare_grpo_adapter.py --include-native --include-training-state \
        <same_stage_checkpoint_dir> <resume_dir>

``--include-native`` adds Megatron adapter shards for an SFT-to-GRPO transfer.
``--include-training-state`` additionally includes same-stage optimizer state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from collections.abc import Mapping
from tempfile import TemporaryDirectory
from pathlib import Path
from typing import Any


_LAYER_PATTERN = re.compile(r"\.layers\.(\d+)\.")
_GENERATED_PATTERNS = (
    "adapter_model.bin",
    "adapter_config.json",
    "mtp_strip_manifest.json",
    "native_reconstruction_manifest.json",
    "adapter_megatron_tp*_pp*.pt",
    "training_state_rank*.pt",
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def filter_served_layers(state_dict: dict[str, Any], *, num_layers: int) -> tuple[dict[str, Any], list[str]]:
    dropped = []
    kept = {}
    for key, value in state_dict.items():
        match = _LAYER_PATTERN.search(key)
        if match and int(match.group(1)) >= num_layers:
            dropped.append(key)
        else:
            kept[key] = value
    return kept, dropped


def clear_generated_outputs(dst: Path) -> list[Path]:
    removed = []
    for pattern in _GENERATED_PATTERNS:
        for target in sorted(dst.glob(pattern)):
            target.unlink()
            removed.append(target)
    return removed


def copy_native_state(
    src: Path,
    dst: Path,
    *,
    include_training_state: bool = False,
) -> tuple[list[Path], list[Path]]:
    native_files = []
    for source in sorted(src.glob("adapter_megatron_tp*_pp*.pt")):
        target = dst / source.name
        shutil.copy2(source, target)
        native_files.append(target)

    training_state_files = []
    if include_training_state:
        for source in sorted(src.glob("training_state_rank*.pt")):
            target = dst / source.name
            shutil.copy2(source, target)
            training_state_files.append(target)
    return native_files, training_state_files


def expected_native_shard_names(
    expected_count: int,
    *,
    tensor_parallel_size: int | None = None,
    expert_parallel_size: int = 1,
    world_size: int | None = None,
) -> set[str]:
    """Return the exact native shard topology expected by the trainer.

    Miles historically keyed native LoRA files by TP/PP only.  That is valid
    when EP=1.  With GLM-4.7's TP=4, EP=8 topology, each EP rank owns a
    different group of routed experts and must have its own file.  In this
    single-node PP=1 runner, global rank maps to ``rank % TP`` and ``rank % EP``.
    """
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


def validate_native_shards(
    paths: list[Path],
    expected_count: int | None,
    *,
    tensor_parallel_size: int | None = None,
    expert_parallel_size: int = 1,
    world_size: int | None = None,
) -> None:
    if not paths:
        raise ValueError("--include-native requires Megatron-native adapter shards")
    if expected_count is None:
        return
    names = {path.name for path in paths}
    expected = expected_native_shard_names(
        expected_count,
        tensor_parallel_size=tensor_parallel_size,
        expert_parallel_size=expert_parallel_size,
        world_size=world_size,
    )
    if names != expected:
        raise ValueError(f"native shard set mismatch: {sorted(names)} != {sorted(expected)}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_native_reconstruction_manifest(
    path: Path,
    *,
    expected_manifest_sha256: str,
    source_adapter_model_sha256: str,
    source_adapter_config_sha256: str,
    expected_native_names: set[str],
    tensor_parallel_size: int,
    expert_parallel_size: int,
) -> tuple[dict[str, str], dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"missing regular native reconstruction manifest: {path}")
    expected_manifest_sha256 = expected_manifest_sha256.lower()
    if not _SHA256_PATTERN.fullmatch(expected_manifest_sha256):
        raise ValueError("expected native reconstruction manifest SHA-256 is invalid")
    manifest_sha256 = _sha256(path)
    if manifest_sha256 != expected_manifest_sha256:
        raise ValueError(
            "native reconstruction manifest SHA-256 mismatch: "
            f"{manifest_sha256} != {expected_manifest_sha256}"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("native reconstruction manifest is not a JSON object")
    source = payload.get("source")
    template = payload.get("template")
    mapping = payload.get("mapping")
    outputs = payload.get("outputs")
    roundtrip = mapping.get("source_hf_roundtrip") if isinstance(mapping, Mapping) else None
    template_proof = template.get("proof") if isinstance(template, Mapping) else None
    if (
        payload.get("schema_version") != 1
        or payload.get("kind") != "glm47-hf-to-megatron-tp-native-reconstruction"
        or payload.get("status") != "passed"
        or not isinstance(source, Mapping)
        or source.get("adapter_model_sha256") != source_adapter_model_sha256
        or source.get("adapter_config_sha256") != source_adapter_config_sha256
        or not isinstance(mapping, Mapping)
        or mapping.get("mode") != "expert-parallel-aware"
        or mapping.get("tp_size") != tensor_parallel_size
        or mapping.get("expert_parallel_size") != expert_parallel_size
        or not isinstance(roundtrip, Mapping)
        or roundtrip.get("status") != "passed"
        or roundtrip.get("all_source_hf_tensor_bytes_exact") is not True
        or roundtrip.get("all_source_hf_tensors_value_exact") is not True
        or roundtrip.get("coverage_fraction") != 1.0
        or roundtrip.get("native_shard_count") != len(expected_native_names)
        or not isinstance(template_proof, Mapping)
        or template_proof.get("status") != "passed"
        or template_proof.get("all_template_native_tensor_bytes_exact") is not True
        or template_proof.get("all_template_native_tensors_value_exact") is not True
        or not isinstance(outputs, Mapping)
    ):
        raise ValueError("native reconstruction manifest proof contract is invalid")

    topology = mapping.get("rank_topology")
    experts_per_shard = mapping.get("experts_per_shard")
    if not isinstance(topology, list) or len(topology) != len(expected_native_names):
        raise ValueError("native reconstruction manifest topology is incomplete")
    topology_names = set()
    topology_global_ranks = set()
    topology_by_name = {}
    for record in topology:
        if not isinstance(record, Mapping):
            raise ValueError("native reconstruction manifest topology record is invalid")
        global_rank = record.get("global_rank")
        tp_rank = record.get("tp_rank")
        ep_rank = record.get("ep_rank")
        filename = record.get("filename")
        expert_index_start = record.get("expert_index_start")
        expert_index_stop = record.get("expert_index_stop")
        if (
            not isinstance(experts_per_shard, int)
            or experts_per_shard <= 0
            or not isinstance(global_rank, int)
            or not isinstance(tp_rank, int)
            or not isinstance(ep_rank, int)
            or tp_rank != global_rank % tensor_parallel_size
            or ep_rank != global_rank % expert_parallel_size
            or filename != f"adapter_megatron_tp{tp_rank}_pp0_ep{ep_rank}.pt"
            or expert_index_start != ep_rank * experts_per_shard
            or expert_index_stop != (ep_rank + 1) * experts_per_shard
        ):
            raise ValueError("native reconstruction manifest topology record is inconsistent")
        topology_names.add(filename)
        topology_global_ranks.add(global_rank)
        topology_by_name[filename] = record
    if (
        topology_names != expected_native_names
        or topology_global_ranks != set(range(len(expected_native_names)))
    ):
        raise ValueError("native reconstruction manifest topology filenames are incomplete")

    output_model = outputs.get("adapter_model.bin")
    output_config = outputs.get("adapter_config.json")
    output_shards = outputs.get("native_shards")
    if (
        not isinstance(output_model, Mapping)
        or output_model.get("sha256") != source_adapter_model_sha256
        or not isinstance(output_config, Mapping)
        or output_config.get("sha256") != source_adapter_config_sha256
        or not isinstance(output_shards, Mapping)
        or set(output_shards) != expected_native_names
    ):
        raise ValueError("native reconstruction manifest outputs are not bound to the adapter")
    native_hashes = {}
    for name in sorted(expected_native_names):
        record = output_shards[name]
        digest = record.get("sha256") if isinstance(record, Mapping) else None
        topology_record = topology_by_name[name]
        if (
            not isinstance(digest, str)
            or not _SHA256_PATTERN.fullmatch(digest)
            or record.get("size_bytes", 0) <= 0
            or record.get("tp_rank") != topology_record["tp_rank"]
            or record.get("ep_rank") != topology_record["ep_rank"]
            or record.get("expert_index_start") != topology_record["expert_index_start"]
            or record.get("expert_index_stop") != topology_record["expert_index_stop"]
        ):
            raise ValueError(f"native reconstruction manifest has an invalid shard hash: {name}")
        native_hashes[name] = digest
    return native_hashes, {
        "file": "native_reconstruction_manifest.json",
        "sha256": manifest_sha256,
        "kind": payload["kind"],
        "status": payload["status"],
        "source_hf_roundtrip_status": roundtrip["status"],
        "native_shard_count": len(native_hashes),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("src")
    parser.add_argument("dst")
    parser.add_argument("--num-layers", type=int, default=47)
    parser.add_argument("--include-native", action="store_true")
    parser.add_argument("--include-training-state", action="store_true")
    parser.add_argument("--expected-native-shards", type=int)
    parser.add_argument("--expected-tensor-parallel-size", type=int)
    parser.add_argument("--expected-expert-parallel-size", type=int, default=1)
    parser.add_argument("--expected-world-size", type=int)
    parser.add_argument("--native-reconstruction-manifest", type=Path)
    parser.add_argument("--expected-native-reconstruction-manifest-sha256")
    parser.add_argument("--expected-source-sha256")
    parser.add_argument("--expected-source-tensors", type=int)
    parser.add_argument("--expected-stripped-tensors", type=int)
    args = parser.parse_args(argv)
    if args.include_training_state and not args.include_native:
        parser.error("--include-training-state requires --include-native")
    reconstruction_manifest_requested = bool(args.native_reconstruction_manifest)
    reconstruction_manifest_sha_requested = bool(
        args.expected_native_reconstruction_manifest_sha256
    )
    if reconstruction_manifest_requested != reconstruction_manifest_sha_requested:
        parser.error(
            "--native-reconstruction-manifest and "
            "--expected-native-reconstruction-manifest-sha256 are required together"
        )
    if reconstruction_manifest_requested and (
        not args.include_native
        or args.expected_native_shards is None
        or args.expected_tensor_parallel_size is None
    ):
        parser.error(
            "native reconstruction proof requires --include-native, "
            "--expected-native-shards, and --expected-tensor-parallel-size"
        )

    import torch

    src = Path(args.src).resolve()
    dst = Path(args.dst).resolve()
    if src == dst:
        raise SystemExit("source and destination adapter directories must differ")
    source_model = src / "adapter_model.bin"
    source_config = src / "adapter_config.json"
    if not source_model.is_file() or not source_config.is_file():
        raise FileNotFoundError(f"source adapter is incomplete: {src}")
    source_sha256 = _sha256(source_model)
    source_config_sha256 = _sha256(source_config)
    if args.expected_source_sha256 and source_sha256 != args.expected_source_sha256.lower():
        raise ValueError(
            f"source adapter SHA-256 mismatch: {source_sha256} != "
            f"{args.expected_source_sha256.lower()}"
        )
    native_reconstruction_hashes: dict[str, str] = {}
    native_reconstruction_record: dict[str, Any] | None = None
    if args.native_reconstruction_manifest:
        expected_native_names = expected_native_shard_names(
            args.expected_native_shards,
            tensor_parallel_size=args.expected_tensor_parallel_size,
            expert_parallel_size=args.expected_expert_parallel_size,
            world_size=args.expected_world_size,
        )
        native_reconstruction_hashes, native_reconstruction_record = (
            validate_native_reconstruction_manifest(
                args.native_reconstruction_manifest.resolve(),
                expected_manifest_sha256=(
                    args.expected_native_reconstruction_manifest_sha256
                ),
                source_adapter_model_sha256=source_sha256,
                source_adapter_config_sha256=source_config_sha256,
                expected_native_names=expected_native_names,
                tensor_parallel_size=args.expected_tensor_parallel_size,
                expert_parallel_size=args.expected_expert_parallel_size,
            )
        )
    state_dict = torch.load(source_model, map_location="cpu", weights_only=True)
    kept, dropped = filter_served_layers(state_dict, num_layers=args.num_layers)
    if args.expected_source_tensors is not None and len(state_dict) != args.expected_source_tensors:
        raise ValueError(
            f"source tensor count mismatch: {len(state_dict)} != {args.expected_source_tensors}"
        )
    if (
        args.expected_stripped_tensors is not None
        and len(dropped) != args.expected_stripped_tensors
    ):
        raise ValueError(
            f"stripped tensor count mismatch: {len(dropped)} != "
            f"{args.expected_stripped_tensors}"
        )
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and any(dst.iterdir()):
        raise FileExistsError(f"refusing to replace nonempty adapter destination: {dst}")
    with TemporaryDirectory(prefix=f".{dst.name}-preparing-", dir=dst.parent) as temporary:
        staging = Path(temporary)
        output_model = staging / "adapter_model.bin"
        torch.save(kept, output_model)
        shutil.copy2(source_config, staging / "adapter_config.json")
        if args.include_native:
            native_files, training_state_files = copy_native_state(
                src,
                staging,
                include_training_state=args.include_training_state,
            )
            validate_native_shards(
                native_files,
                args.expected_native_shards,
                tensor_parallel_size=args.expected_tensor_parallel_size,
                expert_parallel_size=args.expected_expert_parallel_size,
                world_size=args.expected_world_size,
            )
            if native_reconstruction_hashes:
                actual_native_hashes = {
                    path.name: _sha256(path) for path in native_files
                }
                if actual_native_hashes != native_reconstruction_hashes:
                    raise ValueError(
                        "native adapter shard bytes do not match the bound reconstruction manifest"
                    )
                shutil.copy2(
                    args.native_reconstruction_manifest,
                    staging / "native_reconstruction_manifest.json",
                )
        else:
            native_files, training_state_files = [], []

        manifest = {
            "source": str(src),
            "num_layers": args.num_layers,
            "source_tensor_count": len(state_dict),
            "kept_tensor_count": len(kept),
            "stripped_tensor_count": len(dropped),
            "first_stripped_tensor": dropped[0] if dropped else None,
            "source_adapter_model_sha256": source_sha256,
            "source_adapter_config_sha256": source_config_sha256,
            "output_adapter_model_sha256": _sha256(output_model),
            "native_files": {path.name: _sha256(path) for path in native_files},
            "training_state_files": {
                path.name: _sha256(path) for path in training_state_files
            },
            "native_reconstruction_manifest": native_reconstruction_record,
            "replaced_files": [],
        }
        (staging / "mtp_strip_manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if dst.exists():
            dst.rmdir()
        os.replace(staging, dst)
    print(f"kept {len(kept)}/{len(state_dict)} tensors (stripped {len(dropped)} MTP tensors)")
    print("HYBRID_ADAPTER_READY" if args.include_native else "SERVE_COPY_READY", dst)


if __name__ == "__main__":
    main()
