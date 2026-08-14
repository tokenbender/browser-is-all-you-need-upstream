"""Fail-closed completion gate for the compiler-guided CHARM GRPO pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .charm_grpo import DATASET_KIND, validate_projected_dataset


ITERATION_RE = re.compile(r"^iter_(\d+)$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_SOURCE_TENSORS = 9_741
EXPECTED_LAYER_47_TENSORS = 207


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_regular(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
        raise FileNotFoundError(f"missing nonempty regular {label}: {path}")


def _parse_key_value(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            result[key] = value
    return result


def _expected_native_names() -> set[str]:
    return {
        f"adapter_megatron_tp{rank % 4}_pp0_ep{rank % 8}.pt"
        for rank in range(8)
    }


def _checkpoint_record(path: Path) -> dict[str, Any]:
    import torch

    match = ITERATION_RE.fullmatch(path.name)
    if match is None:
        raise ValueError(f"invalid checkpoint iteration: {path}")
    adapter = path / "adapter"
    model = adapter / "adapter_model.bin"
    config = adapter / "adapter_config.json"
    _require_regular(model, "checkpoint adapter model")
    _require_regular(config, "checkpoint adapter config")
    native = sorted(adapter.glob("adapter_megatron_tp*_pp*.pt"))
    if {item.name for item in native} != _expected_native_names():
        raise RuntimeError(f"checkpoint native shard topology is incomplete: {adapter}")
    training = sorted(adapter.glob("training_state_rank*.pt"))
    if {item.name for item in training} != {
        f"training_state_rank{rank}.pt" for rank in range(8)
    }:
        raise RuntimeError(f"checkpoint training-state topology is incomplete: {adapter}")
    state = torch.load(model, map_location="cpu", weights_only=True, mmap=True)
    if not isinstance(state, Mapping):
        raise TypeError("checkpoint adapter state is not a mapping")
    layer_47 = [name for name in state if ".layers.47." in str(name)]
    if len(state) != EXPECTED_SOURCE_TENSORS or len(layer_47) != EXPECTED_LAYER_47_TENSORS:
        raise RuntimeError("checkpoint adapter tensor domain differs from the bound GLM-4.7 LoRA")
    return {
        "iteration": int(match.group(1)),
        "adapter_path": str(adapter),
        "adapter_model_sha256": sha256_path(model),
        "adapter_config_sha256": sha256_path(config),
        "tensor_count": len(state),
        "layer_47_tensor_count": len(layer_47),
        "native_shards": {item.name: sha256_path(item) for item in native},
        "training_state_files": [item.name for item in training],
    }


def _rollout_record(path: Path, *, expected_samples: int) -> dict[str, Any]:
    import torch

    try:
        payload = torch.load(path, map_location="cpu", weights_only=False)
    except TypeError:  # pragma: no cover - older training torch
        payload = torch.load(path, map_location="cpu")
    if not isinstance(payload, Mapping) or not isinstance(payload.get("samples"), list):
        raise TypeError(f"rollout dump has no sample list: {path}")
    samples = payload["samples"]
    if len(samples) != expected_samples:
        raise RuntimeError(
            f"rollout sample count mismatch in {path.name}: {len(samples)} != {expected_samples}"
        )
    reasons: dict[str, int] = {}
    task_ids: set[str] = set()
    positive = 0
    for index, sample in enumerate(samples):
        if not isinstance(sample, Mapping) or not isinstance(sample.get("reward"), Mapping):
            raise RuntimeError(f"missing reward record in {path.name} sample {index}")
        reward = sample["reward"]
        score = reward.get("score")
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(float(score))
            or reward.get("infrastructure_error") is not False
        ):
            raise RuntimeError(f"invalid executable reward in {path.name} sample {index}")
        reason = reward.get("reason")
        task_id = reward.get("task_id")
        if not isinstance(reason, str) or reason in {
            "reward_exception",
            "infrastructure_error",
            "missing_task_path",
        }:
            raise RuntimeError(f"invalid reward reason in {path.name} sample {index}")
        if not isinstance(task_id, str) or not task_id:
            raise RuntimeError(f"missing reward task ID in {path.name} sample {index}")
        reasons[reason] = reasons.get(reason, 0) + 1
        task_ids.add(task_id)
        positive += int(float(score) > 0.0)
    return {
        "file": path.name,
        "sha256": sha256_path(path),
        "sample_count": len(samples),
        "positive_sample_count": positive,
        "task_count": len(task_ids),
        "reward_reason_counts": dict(sorted(reasons.items())),
    }


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite receipt: {path}")
    temporary = path.with_suffix(path.suffix + f".tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def verify_and_stage(
    *,
    run_id: str,
    run_root: Path,
    data_dir: Path,
    expected_data_manifest_sha256: str,
    source_adapter: Path,
    expected_source_adapter_sha256: str,
    expected_reconstruction_manifest_sha256: str,
    num_rollouts: int,
    rollout_sample_count: int,
    output_receipt: Path,
    eval_adapter: Path,
) -> dict[str, Any]:
    for value, label in (
        (expected_data_manifest_sha256, "data manifest"),
        (expected_source_adapter_sha256, "source adapter"),
        (expected_reconstruction_manifest_sha256, "reconstruction manifest"),
    ):
        if SHA256_RE.fullmatch(value) is None:
            raise ValueError(f"invalid expected {label} SHA-256")
    validation = validate_projected_dataset(data_dir)
    manifest = data_dir / "manifest.json"
    if sha256_path(manifest) != expected_data_manifest_sha256:
        raise RuntimeError("runtime data manifest digest mismatch")
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    if (
        manifest_payload.get("kind") != DATASET_KIND
        or manifest_payload.get("counts", {}).get("gradient_rows") != 114
        or manifest_payload.get("counts", {}).get("monitor_tasks") != 12
        or manifest_payload.get("split_contract", {}).get("train_monitor_task_overlap") != []
    ):
        raise RuntimeError("runtime data split contract is invalid")

    source_model = source_adapter / "adapter_model.bin"
    reconstruction = source_adapter / "native_reconstruction_manifest.json"
    _require_regular(source_model, "source adapter")
    _require_regular(reconstruction, "native reconstruction proof")
    if sha256_path(source_model) != expected_source_adapter_sha256:
        raise RuntimeError("source adapter digest mismatch")
    if sha256_path(reconstruction) != expected_reconstruction_manifest_sha256:
        raise RuntimeError("native reconstruction proof digest mismatch")

    runner_receipt = run_root / "grpo_lora_r16" / "run_receipt.txt"
    _require_regular(runner_receipt, "Miles run receipt")
    runner = _parse_key_value(runner_receipt)
    if runner.get("status") != "success" or runner.get("ray_status") != "0":
        raise RuntimeError("Miles did not complete successfully")

    save_dir = run_root / "checkpoints" / "grpo_lora_r16"
    checkpoints = sorted(
        (path for path in save_dir.glob("iter_*") if ITERATION_RE.fullmatch(path.name)),
        key=lambda path: int(ITERATION_RE.fullmatch(path.name).group(1)),  # type: ignore[union-attr]
    )
    if not checkpoints:
        raise RuntimeError("no GRPO checkpoint was produced")
    latest = _checkpoint_record(checkpoints[-1])
    if int(latest["iteration"]) + 1 < num_rollouts:
        raise RuntimeError("latest checkpoint does not cover all configured rollout updates")

    dump_paths = sorted((run_root / "rollout_dumps").glob("grpo_*.pt"))
    if len(dump_paths) != num_rollouts:
        raise RuntimeError(f"rollout dump count mismatch: {len(dump_paths)} != {num_rollouts}")
    rollouts = [
        _rollout_record(path, expected_samples=rollout_sample_count)
        for path in dump_paths
    ]
    if not any(record["positive_sample_count"] for record in rollouts):
        raise RuntimeError("all rollout rewards are zero; no trainable signal was demonstrated")

    if eval_adapter.exists() or eval_adapter.is_symlink():
        raise FileExistsError(f"refusing to overwrite staged eval adapter: {eval_adapter}")
    eval_adapter.parent.mkdir(parents=True, exist_ok=True)
    staging = eval_adapter.parent / f".{eval_adapter.name}.tmp-{os.getpid()}"
    staging.mkdir()
    latest_path = Path(str(latest["adapter_path"]))
    shutil.copy2(latest_path / "adapter_model.bin", staging / "adapter_model.bin")
    shutil.copy2(latest_path / "adapter_config.json", staging / "adapter_config.json")
    (staging / ".training-run-id").write_text(run_id + "\n", encoding="utf-8")
    os.replace(staging, eval_adapter)

    receipt = {
        "schema_version": "charm-compiler-grpo-completion-v1",
        "decision": "PASS",
        "run_id": run_id,
        "dataset": validation,
        "data_manifest_sha256": expected_data_manifest_sha256,
        "source_adapter_sha256": expected_source_adapter_sha256,
        "native_reconstruction_manifest_sha256": expected_reconstruction_manifest_sha256,
        "runner_receipt_sha256": sha256_path(runner_receipt),
        "rollout_count": len(rollouts),
        "rollout_sample_count": sum(int(item["sample_count"]) for item in rollouts),
        "rollouts": rollouts,
        "latest_checkpoint": latest,
        "eval_adapter": {
            "path": str(eval_adapter),
            "training_run_id": run_id,
            "adapter_model_sha256": sha256_path(eval_adapter / "adapter_model.bin"),
            "adapter_config_sha256": sha256_path(eval_adapter / "adapter_config.json"),
        },
    }
    _atomic_json(output_receipt, receipt)
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--expected-data-manifest-sha256", required=True)
    parser.add_argument("--source-adapter", type=Path, required=True)
    parser.add_argument("--expected-source-adapter-sha256", required=True)
    parser.add_argument("--expected-reconstruction-manifest-sha256", required=True)
    parser.add_argument("--num-rollouts", type=int, default=18)
    parser.add_argument("--rollout-sample-count", type=int, default=152)
    parser.add_argument("--output-receipt", type=Path, required=True)
    parser.add_argument("--eval-adapter", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    receipt = verify_and_stage(
        run_id=args.run_id,
        run_root=args.run_root.resolve(),
        data_dir=args.data_dir.resolve(),
        expected_data_manifest_sha256=args.expected_data_manifest_sha256,
        source_adapter=args.source_adapter.resolve(),
        expected_source_adapter_sha256=args.expected_source_adapter_sha256,
        expected_reconstruction_manifest_sha256=(
            args.expected_reconstruction_manifest_sha256
        ),
        num_rollouts=args.num_rollouts,
        rollout_sample_count=args.rollout_sample_count,
        output_receipt=args.output_receipt.resolve(),
        eval_adapter=args.eval_adapter.resolve(),
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
