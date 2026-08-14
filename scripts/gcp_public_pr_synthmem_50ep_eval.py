#!/usr/bin/env python3
"""Run the SynthMem 50-epoch public-PR diagnostic on a pinned GCP GPU profile."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from glm47_posttraining.public_pr_eval.runner import evaluate_suite_with_aider


SUITES = {
    "full": {
        "task_jsonl": Path(
            "/opt/public-pr-eval/configs/public_pr_eval/public-pr-repo-eval-v2-r5.jsonl"
        ),
        "task_jsonl_sha256": "316e293ecf3a183b1f14612007e47edfbbea3e2b72ee5349b95b12d0a779ec82",
        "prepared_root": Path("/opt/public-pr-prepared/full"),
        "oracle_receipt": Path("/opt/public-pr-oracles/full/oracle-replay.json"),
        "static_validation": Path(
            "/opt/public-pr-prepared/full/static-validation.json"
        ),
        "edit_format": "whole",
        "attempts": 2,
        "description": "three public-PR tasks",
    },
    "fmtlib-demo": {
        "task_jsonl": Path(
            "/opt/public-pr-eval/configs/public_pr_eval/public-pr-repo-eval-demo-fmtlib-v2.jsonl"
        ),
        "task_jsonl_sha256": "9db4bbc4df06aed1cb87dca1026456f2cafa3973f15024fba41b3c912d5b22a7",
        "prepared_root": Path("/opt/public-pr-prepared/demo-fmtlib"),
        "oracle_receipt": Path("/opt/public-pr-oracles/demo-fmtlib/oracle-replay.json"),
        "static_validation": Path(
            "/opt/public-pr-prepared/demo-fmtlib/static-validation.json"
        ),
        "edit_format": "diff",
        "attempts": 1,
        "description": "single-task fmtlib PR #3727 demo",
    },
    "fmtlib-compiler-repair": {
        "task_jsonl": Path(
            "/opt/public-pr-eval/configs/public_pr_eval/public-pr-repo-eval-demo-fmtlib-v3.jsonl"
        ),
        "task_jsonl_sha256": "01d2015df04766726b778948997be9d34aa48cba1e78c002d92429b582e0765c",
        "prepared_root": Path("/opt/public-pr-prepared/demo-fmtlib-v3"),
        "oracle_receipt": Path(
            "/opt/public-pr-oracles/demo-fmtlib-v3/oracle-replay.json"
        ),
        "static_validation": Path(
            "/opt/public-pr-prepared/demo-fmtlib-v3/static-validation.json"
        ),
        "edit_format": "diff",
        "attempts": 2,
        "initial_temperature": 0.7,
        "repair_temperature": 0.2,
        "description": "single-task baseline-preserving fmtlib compiler-repair demo",
    },
    "fmtlib-compact-repair-bestof4": {
        "task_jsonl": Path(
            "/opt/public-pr-eval/configs/public_pr_eval/public-pr-repo-eval-demo-fmtlib-v4.jsonl"
        ),
        "task_jsonl_sha256": "03ed4454a8953b80b09325392c0045e9ea0ba64b6c483ea886c3850ffbd7c7a3",
        "prepared_root": Path("/opt/public-pr-prepared/demo-fmtlib-v4"),
        "oracle_receipt": Path(
            "/opt/public-pr-oracles/demo-fmtlib-v4/oracle-replay.json"
        ),
        "static_validation": Path(
            "/opt/public-pr-prepared/demo-fmtlib-v4/static-validation.json"
        ),
        "edit_format": "diff",
        "attempts": 2,
        "candidate_seeds": [1701, 1702, 1703, 1704],
        "initial_temperature": 0.7,
        "repair_temperature": 0.2,
        "description": (
            "single-task compact fmtlib best-of-four compiler-repair demo"
        ),
    },
    "fmtlib-compact-repair-bestof4-thinking": {
        "task_jsonl": Path(
            "/opt/public-pr-eval/configs/public_pr_eval/public-pr-repo-eval-demo-fmtlib-v5.jsonl"
        ),
        "task_jsonl_sha256": "db8de1a51420ba5424f1799ea15e81adeaadaeb3dcd6331ce94412d98c223202",
        "prepared_root": Path("/opt/public-pr-prepared/demo-fmtlib-v5"),
        "oracle_receipt": Path(
            "/opt/public-pr-oracles/demo-fmtlib-v5/oracle-replay.json"
        ),
        "static_validation": Path(
            "/opt/public-pr-prepared/demo-fmtlib-v5/static-validation.json"
        ),
        "edit_format": "diff",
        "attempts": 2,
        "candidate_seeds": [1701, 1702, 1703, 1704],
        "initial_temperature": 0.7,
        "repair_temperature": 0.2,
        "thinking_enabled": True,
        "description": (
            "single-task thinking-on compact fmtlib best-of-four compiler-repair demo"
        ),
    },
    "fmtlib-verified-mechanisms-thinking": {
        "task_jsonl": Path(
            "/opt/public-pr-eval/configs/public_pr_eval/public-pr-repo-eval-demo-fmtlib-v6.jsonl"
        ),
        "task_jsonl_sha256": "a8c59421d38ea2dbdf0bca6168398c590d9497cdd0acdbced9d0377c8725746f",
        "prepared_root": Path("/opt/public-pr-prepared/demo-fmtlib-v6"),
        "oracle_receipt": Path(
            "/opt/public-pr-oracles/demo-fmtlib-v6/oracle-replay.json"
        ),
        "static_validation": Path(
            "/opt/public-pr-prepared/demo-fmtlib-v6/static-validation.json"
        ),
        "edit_format": "diff",
        "attempts": 2,
        "candidate_seeds": [1701, 1702, 1703, 1704],
        "initial_temperature": 0.7,
        "repair_temperature": 0.2,
        "thinking_enabled": True,
        "description": (
            "single-task thinking-on fmtlib best-of-four with compile-gated "
            "named mechanism verification"
        ),
    },
    "fmtlib-prioritized-verified-mechanisms-thinking": {
        "task_jsonl": Path(
            "/opt/public-pr-eval/configs/public_pr_eval/public-pr-repo-eval-demo-fmtlib-v7.jsonl"
        ),
        "task_jsonl_sha256": "cec16a8abd6b1d66e40d6d8fc9cff872229173b2614ae4e0f7754e5b61969a89",
        "prepared_root": Path("/opt/public-pr-prepared/demo-fmtlib-v7"),
        "oracle_receipt": Path(
            "/opt/public-pr-oracles/demo-fmtlib-v7/oracle-replay.json"
        ),
        "static_validation": Path(
            "/opt/public-pr-prepared/demo-fmtlib-v7/static-validation.json"
        ),
        "edit_format": "diff",
        "attempts": 2,
        "candidate_seeds": [1701, 1702, 1703, 1704],
        "initial_temperature": 0.7,
        "repair_temperature": 0.2,
        "thinking_enabled": True,
        "description": (
            "single-task thinking-on fmtlib best-of-four with compile-gated "
            "mechanisms and failure-prioritized intern guidance"
        ),
    },
    "fmtlib-final-cleanup-verified-mechanisms-thinking": {
        "task_jsonl": Path(
            "/opt/public-pr-eval/configs/public_pr_eval/public-pr-repo-eval-demo-fmtlib-v8.jsonl"
        ),
        "task_jsonl_sha256": "38f567a074a5a61e53ee1dad478833f10d9f7a40738d8d6c0baedfe1fe5294b6",
        "prepared_root": Path("/opt/public-pr-prepared/demo-fmtlib-v8"),
        "oracle_receipt": Path(
            "/opt/public-pr-oracles/demo-fmtlib-v8/oracle-replay.json"
        ),
        "static_validation": Path(
            "/opt/public-pr-prepared/demo-fmtlib-v8/static-validation.json"
        ),
        "edit_format": "diff",
        "attempts": 2,
        "candidate_seeds": [1701, 1702, 1703, 1704],
        "initial_temperature": 0.7,
        "repair_temperature": 0.2,
        "thinking_enabled": True,
        "description": (
            "single-task thinking-on fmtlib best-of-four with compile-gated "
            "mechanisms and a final mandatory legacy-helper cleanup gate"
        ),
    },
}
AIDER_FREEZE = Path("/opt/public-pr-prepared/aider-pip-freeze.txt")
BASE_MODEL_REVISION = "7dd20894a642a0aa287e9827cb1a1f7f91386b67"
CHECKPOINT_PROFILES: dict[str, dict[str, object]] = {
    "synthmem-v1-ep50": {
        "training_run_id": "glm47-synth-memorization-v1-100ep-20260731T071000Z",
        "checkpoint_path": "checkpoints/sft_lora_r16/iter_0000649",
        "epoch": 50,
        "optimizer_iteration": 649,
        "source_adapter_sha256": "4acb7f23c295f45380155c5d9ee6bc59422262f0cb51f0c02f7e550d405b575a",
        "serving_adapter_sha256": "6de1aeba533a5bfef26a73286fc32b47f403c022bd7467e2b3dc32cf18a35f48",
        "adapter_config_sha256": "0bd6d85f88fc42fefa52627b3c261f1ad58bb2c9519332ae8034dd5dffe2498e",
        "model_name": "glm47-synthmem-v1-ep50-public-pr",
        "source_tensor_count": 9_741,
        "layer_47_tensor_count": 207,
        "serving_tensor_count": 9_534,
        "lora_rank": 16,
        "lora_alpha": 32,
        "training_task_count": 260,
        "sequence_length": 4_096,
        "global_batch_size": 20,
        "training_gpu_topology": "8x NVIDIA H100",
        "optimizer_updates_per_epoch": 13,
        "step_649_metrics": {
            "loss": 0.000027910614625928666,
            "gradient_norm": 0.0021414729699963087,
            "learning_rate": 0.00011743214109250993,
            "step_time_seconds": 6.9253,
            "training_tflops": 26.7814,
            "effective_tokens_per_gpu_second": 960.2933,
        },
        "training_data_manifest_sha256": "afec0d05d5c1f9460ac9b2ed4e65aea69775b49639c7ae727f3660308ae1b8b8",
        "training_jsonl_sha256": "3472d76169e52bd0859c181d63de24a060c4c7f2d3d8a004ceb6090498f1ddc1",
        "training_source_commit": "6188070622895021d1c340ad31939e888c514396",
        "matched_fixed26_suite": "glm47-synthmem-v1-ep50-fixed26-v2-v4matched-eval4-20260804T084520Z",
    },
    "synthmem-v3-v1std-ep50": {
        "training_run_id": "glm47-synth-mem-v3-v1std-50ep-20260803T023833Z",
        "checkpoint_path": "checkpoints/sft_lora_r16/iter_0001299",
        "epoch": 50,
        "optimizer_iteration": 1_299,
        "source_adapter_sha256": "5ca6a0cbede843e8c042ebb1004a80e85d85686974063cb9bd0540e236aab6ca",
        "serving_adapter_sha256": None,
        "adapter_config_sha256": "0bd6d85f88fc42fefa52627b3c261f1ad58bb2c9519332ae8034dd5dffe2498e",
        "model_name": "glm47-synthmem-v3-v1std-50ep-public-pr",
        "source_tensor_count": 9_741,
        "layer_47_tensor_count": 207,
        "serving_tensor_count": 9_534,
        "lora_rank": 16,
        "lora_alpha": 32,
    },
}
DEFAULT_CHECKPOINT_PROFILE = "synthmem-v1-ep50"
API_KEY = "local-public-pr-eval"
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(message: str) -> None:
    print(f"[{utc_now()}] [gcp-public-pr-eval] {message}", flush=True)


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_sha256(value: str, label: str) -> str:
    normalized = value.strip().lower()
    if SHA256_RE.fullmatch(normalized) is None:
        raise ValueError(f"{label} must be an explicit lowercase SHA-256")
    return normalized


def validate_run_id(value: str) -> str:
    if RUN_ID_RE.fullmatch(value) is None:
        raise ValueError("run-id contains unsupported characters")
    return value


def read_exact_marker(path: Path, expected: str, label: str) -> None:
    if not path.is_file() or path.read_text(encoding="utf-8").strip() != expected:
        raise RuntimeError(f"{label} marker does not match {expected!r}")


def verify_model_manifest(
    model_path: Path, expected_manifest_sha256: str
) -> dict[str, object]:
    manifest = model_path / ".source-manifest.sha256"
    expected = validate_sha256(
        expected_manifest_sha256, "expected-model-manifest-sha256"
    )
    if not manifest.is_file() or sha256_path(manifest) != expected:
        raise RuntimeError("base-model manifest digest mismatch")
    log("verifying every base-model file against the caller-bound manifest")
    process = subprocess.Popen(
        ["sha256sum", "--check", "--quiet", "--strict", str(manifest)],
        cwd=model_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    started = time.monotonic()
    while process.poll() is None:
        elapsed = int(time.monotonic() - started)
        if elapsed >= 1800:
            process.kill()
            raise TimeoutError("base-model verification exceeded 1,800 seconds")
        if elapsed > 0 and elapsed % 30 == 0:
            log(f"base-model verification still running: elapsed={elapsed}s")
        time.sleep(1)
    output = process.communicate()[0]
    if process.returncode != 0:
        raise RuntimeError(f"base-model file verification failed:\n{output[-8000:]}")
    entries = sum(
        1 for line in manifest.read_text(encoding="utf-8").splitlines() if line
    )
    log(f"base-model manifest verified: {entries} files")
    return {"manifest_sha256": expected, "verified_file_count": entries}


def verify_network_isolation() -> None:
    interfaces = {path.name for path in Path("/sys/class/net").iterdir()}
    if interfaces != {"lo"}:
        raise RuntimeError(
            f"runtime network is not isolated; expected only loopback, found {sorted(interfaces)}"
        )


def gpu_inventory(
    expected_count: int = 4,
    expected_model: str = "A100",
    expected_memory_mib: int = 80_000,
) -> list[dict[str, object]]:
    output = subprocess.check_output(
        [
            "nvidia-smi",
            "--query-gpu=index,name,memory.total,driver_version,uuid",
            "--format=csv,noheader,nounits",
        ],
        text=True,
    )
    inventory = []
    for line in output.splitlines():
        index, name, memory, driver, uuid = [
            field.strip() for field in line.split(",", 4)
        ]
        inventory.append(
            {
                "index": int(index),
                "name": name,
                "memory_mib": int(memory),
                "driver_version": driver,
                "uuid": uuid,
            }
        )
    if len(inventory) != expected_count:
        raise RuntimeError(
            f"exactly {expected_count} GPUs are required, found {len(inventory)}"
        )
    for gpu in inventory:
        if expected_model not in str(gpu["name"]) or int(
            gpu["memory_mib"]
        ) < expected_memory_mib:
            raise RuntimeError(
                "expected "
                f"{expected_count} {expected_model} GPUs with at least "
                f"{expected_memory_mib} MiB each, found {gpu}"
            )
    return inventory


def model_parallelism_contract(
    model_path: Path, tensor_parallel_size: int
) -> dict[str, int]:
    config_path = model_path / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    num_attention_heads = config.get("num_attention_heads")
    if not isinstance(num_attention_heads, int) or num_attention_heads <= 0:
        raise RuntimeError("base-model config has no valid num_attention_heads")
    if num_attention_heads % tensor_parallel_size != 0:
        raise RuntimeError(
            "tensor parallel size "
            f"{tensor_parallel_size} does not divide the model's "
            f"{num_attention_heads} attention heads"
        )
    return {
        "num_attention_heads": num_attention_heads,
        "tensor_parallel_size": tensor_parallel_size,
        "attention_heads_per_tp_rank": (
            num_attention_heads // tensor_parallel_size
        ),
    }


def verify_evaluator_receipts(suite: dict[str, object]) -> dict[str, object]:
    task_jsonl = suite["task_jsonl"]
    task_jsonl_sha256 = str(suite["task_jsonl_sha256"])
    static_validation = suite["static_validation"]
    oracle_receipt = suite["oracle_receipt"]
    prepared_root = suite["prepared_root"]
    if not isinstance(task_jsonl, Path) or not isinstance(static_validation, Path):
        raise TypeError("suite paths are not Path objects")
    if not isinstance(oracle_receipt, Path) or not isinstance(prepared_root, Path):
        raise TypeError("suite paths are not Path objects")
    if sha256_path(task_jsonl) != task_jsonl_sha256:
        raise RuntimeError("task JSONL digest mismatch")
    static = json.loads(static_validation.read_text(encoding="utf-8"))
    oracle = json.loads(oracle_receipt.read_text(encoding="utf-8"))
    if (
        static.get("decision") != "PASS"
        or static.get("task_jsonl_sha256") != task_jsonl_sha256
    ):
        raise RuntimeError(
            "static format/prompt/code-quality validation is not bound PASS"
        )
    if (
        oracle.get("decision") != "PASS"
        or oracle.get("task_jsonl_sha256") != task_jsonl_sha256
    ):
        raise RuntimeError(
            "base/reference/plausible-wrong oracle replay is not bound PASS"
        )
    expected_thinking_mode = (
        "enabled" if bool(suite.get("thinking_enabled", False)) else "disabled"
    )
    contract_rows = [
        json.loads(line)
        for line in task_jsonl.read_text(encoding="utf-8").splitlines()
        if line
    ]
    if not contract_rows or any(
        row.get("run_policy", {}).get("thinking_mode") != expected_thinking_mode
        for row in contract_rows
    ):
        raise RuntimeError(
            "task contract thinking mode does not match the selected runtime suite"
        )
    return {
        "static_validation_sha256": sha256_path(static_validation),
        "oracle_replay_sha256": sha256_path(oracle_receipt),
        "prepared_suite_sha256": sha256_path(prepared_root / "prepared-suite.json"),
        "thinking_mode": expected_thinking_mode,
    }


def prepare_serving_adapter(
    adapter_path: Path,
    destination: Path,
    *,
    profile: dict[str, object],
) -> tuple[Path, dict[str, object]]:
    import torch

    expected_training_run_id = str(profile["training_run_id"])
    expected_source_sha256 = validate_sha256(
        str(profile["source_adapter_sha256"]), "profile source adapter"
    )
    expected_config_sha256 = validate_sha256(
        str(profile["adapter_config_sha256"]), "profile adapter config"
    )
    expected_serving_value = profile.get("serving_adapter_sha256")
    expected_serving_sha256 = (
        validate_sha256(str(expected_serving_value), "profile serving adapter")
        if expected_serving_value is not None
        else None
    )
    read_exact_marker(
        adapter_path / ".training-run-id", expected_training_run_id, "training run"
    )
    model_path = adapter_path / "adapter_model.bin"
    config_path = adapter_path / "adapter_config.json"
    if not model_path.is_file() or not config_path.is_file():
        raise FileNotFoundError("50-epoch adapter is incomplete")
    observed_model_sha = sha256_path(model_path)
    observed_config_sha = sha256_path(config_path)
    if (
        observed_model_sha != expected_source_sha256
        or observed_config_sha != expected_config_sha256
    ):
        raise RuntimeError(
            "adapter bytes do not match the immutable checkpoint profile"
        )

    log("loading and converting the trainer adapter for SGLang serving")
    state = torch.load(model_path, map_location="cpu", weights_only=True, mmap=True)
    layer_47 = [key for key in state if ".layers.47." in key]
    if (
        len(state) != int(profile["source_tensor_count"])
        or len(layer_47) != int(profile["layer_47_tensor_count"])
    ):
        raise RuntimeError(
            "adapter tensor structure does not match the immutable checkpoint profile"
        )
    filtered = {key: value for key, value in state.items() if ".layers.47." not in key}
    if len(filtered) != int(profile["serving_tensor_count"]):
        raise RuntimeError("serving tensor count mismatch")
    destination.mkdir(parents=True, exist_ok=False)
    serving_model_path = destination / "adapter_model.bin"
    torch.save(filtered, serving_model_path)
    shutil.copy2(config_path, destination / "adapter_config.json")
    serving_sha256 = sha256_path(serving_model_path)
    if (
        expected_serving_sha256 is not None
        and serving_sha256 != expected_serving_sha256
    ):
        raise RuntimeError("converted serving adapter digest mismatch")
    return destination, {
        "source_adapter_sha256": observed_model_sha,
        "source_adapter_config_sha256": observed_config_sha,
        "source_tensor_count": len(state),
        "removed_layer_47_tensor_count": len(layer_47),
        "serving_tensor_count": len(filtered),
        "serving_adapter_sha256": serving_sha256,
        "serving_adapter_config_sha256": sha256_path(
            destination / "adapter_config.json"
        ),
    }


def server_command(
    model_path: Path,
    port: int,
    lora_rank: int,
    model_name: str,
    tensor_parallel_size: int = 4,
    data_parallel_size: int = 1,
    preloaded_adapter: Path | None = None,
) -> list[str]:
    command = [
        "python3",
        "-m",
        "sglang.launch_server",
        "--model-path",
        str(model_path),
        "--tp-size",
        str(tensor_parallel_size),
        "--tool-call-parser",
        "glm47",
        "--reasoning-parser",
        "glm45",
        "--mem-fraction-static",
        "0.82",
        "--max-running-requests",
        "8",
        "--served-model-name",
        model_name,
        "--api-key",
        API_KEY,
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--enable-lora",
        "--max-lora-rank",
        str(lora_rank),
        "--lora-backend",
        "triton",
        "--lora-target-modules",
        "q_a_proj",
        "kv_a_proj_with_mqa",
        "o_proj",
        "gate_proj",
        "up_proj",
        "down_proj",
        "--experts-shared-outer-loras",
        "--lora-use-virtual-experts",
    ]
    if data_parallel_size > 1:
        command.extend(["--dp-size", str(data_parallel_size)])
    if preloaded_adapter is not None:
        command.extend(
            ["--lora-paths", f"{model_name}={preloaded_adapter}"]
        )
    return command


def wait_for_server(process: subprocess.Popen[str], log_path: Path, port: int) -> None:
    started = time.monotonic()
    deadline = started + 1800
    next_heartbeat = started
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                log_path.read_text(encoding="utf-8", errors="replace")[-12000:]
            )
        now = time.monotonic()
        if now >= next_heartbeat:
            size = log_path.stat().st_size if log_path.exists() else 0
            log(f"waiting for SGLang: elapsed={int(now - started)}s log_bytes={size}")
            next_heartbeat = now + 30
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/health", timeout=5
            ) as response:
                if response.status == 200:
                    log(f"SGLang healthy after {int(time.monotonic() - started)}s")
                    return
        except Exception:
            time.sleep(5)
    raise TimeoutError("SGLang did not become healthy within 1,800 seconds")


def load_adapter(adapter: Path, port: int, model_name: str) -> str:
    payload = json.dumps({"lora_name": model_name, "lora_path": str(adapter)}).encode()
    for endpoint in ("/load_lora_adapter", "/v1/load_lora_adapter"):
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}{endpoint}",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {API_KEY}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                if response.status == 200:
                    return response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
    raise RuntimeError("SGLang exposes no supported LoRA load endpoint")


def write_model_settings(
    path: Path,
    model_name: str,
    thinking_enabled: bool,
    edit_format: str,
    *,
    temperature: float = 0.7,
    seed: int = 1701,
) -> None:
    path.write_text(
        f"""- name: openai/{model_name}
  edit_format: {edit_format}
  use_repo_map: false
  use_temperature: true
  streaming: false
  extra_params:
    max_tokens: 32768
    temperature: {temperature}
    top_p: 1.0
    extra_body:
      chat_template_kwargs:
        enable_thinking: {str(thinking_enabled).lower()}
    seed: {seed}
""",
        encoding="utf-8",
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--model-path", type=Path, required=True)
    result.add_argument("--adapter-path", type=Path, required=True)
    result.add_argument("--expected-model-manifest-sha256", required=True)
    result.add_argument("--expected-adapter-config-sha256", required=True)
    result.add_argument(
        "--checkpoint-profile",
        choices=sorted(CHECKPOINT_PROFILES),
        default=DEFAULT_CHECKPOINT_PROFILE,
        help="immutable adapter/checkpoint identity profile",
    )
    result.add_argument(
        "--expected-adapter-model-sha256",
        help="optional assertion; must equal the selected profile",
    )
    result.add_argument(
        "--expected-training-run-id",
        help="optional assertion; must equal the selected profile",
    )
    result.add_argument("--output-root", type=Path, required=True)
    result.add_argument("--run-id", required=True)
    result.add_argument(
        "--suite",
        choices=sorted(SUITES),
        default="fmtlib-final-cleanup-verified-mechanisms-thinking",
    )
    result.add_argument("--port", type=int, default=8000)
    result.add_argument("--lora-rank", type=int, default=16)
    result.add_argument("--tensor-parallel-size", type=int, default=4)
    result.add_argument("--data-parallel-size", type=int, default=1)
    result.add_argument("--expected-gpu-count", type=int, default=4)
    result.add_argument("--expected-gpu-model", default="A100")
    result.add_argument("--expected-gpu-memory-mib", type=int, default=80_000)
    result.add_argument("--execution-profile", default="gcp-a100-tp4")
    result.add_argument("--provisioner", default="gcloud-shell")
    return result


def main() -> int:
    args = parser().parse_args()
    if args.tensor_parallel_size <= 0:
        raise ValueError("tensor parallel size must be positive")
    if args.data_parallel_size <= 0:
        raise ValueError("data parallel size must be positive")
    if args.expected_gpu_count <= 0:
        raise ValueError("expected GPU count must be positive")
    if args.expected_gpu_memory_mib <= 0:
        raise ValueError("expected GPU memory must be positive")
    if not args.expected_gpu_model.strip():
        raise ValueError("expected GPU model must not be empty")
    if not args.execution_profile.strip() or not args.provisioner.strip():
        raise ValueError("execution profile and provisioner must not be empty")
    if args.tensor_parallel_size * args.data_parallel_size != args.expected_gpu_count:
        raise ValueError(
            "tensor parallel size multiplied by data parallel size must equal "
            "the expected GPU count"
        )
    run_id = validate_run_id(args.run_id)
    suite_config = SUITES[args.suite]
    checkpoint_profile = dict(CHECKPOINT_PROFILES[args.checkpoint_profile])
    training_run_id = validate_run_id(str(checkpoint_profile["training_run_id"]))
    source_adapter_sha256 = validate_sha256(
        str(checkpoint_profile["source_adapter_sha256"]), "profile source adapter"
    )
    adapter_config_sha256 = validate_sha256(
        str(checkpoint_profile["adapter_config_sha256"]), "profile adapter config"
    )
    model_name = str(checkpoint_profile["model_name"])
    thinking_enabled = bool(suite_config.get("thinking_enabled", False))
    if (
        validate_sha256(
            args.expected_adapter_config_sha256,
            "expected-adapter-config-sha256",
        )
        != adapter_config_sha256
    ):
        raise RuntimeError(
            "caller adapter config digest does not match the checkpoint profile"
        )
    if (
        args.expected_adapter_model_sha256 is not None
        and validate_sha256(
            args.expected_adapter_model_sha256,
            "expected-adapter-model-sha256",
        )
        != source_adapter_sha256
    ):
        raise RuntimeError(
            "caller adapter model digest does not match the checkpoint profile"
        )
    if (
        args.expected_training_run_id is not None
        and validate_run_id(args.expected_training_run_id) != training_run_id
    ):
        raise RuntimeError(
            "caller training run ID does not match the checkpoint profile"
        )
    if args.lora_rank != int(checkpoint_profile["lora_rank"]):
        raise RuntimeError("LoRA rank does not match the checkpoint profile")
    task_jsonl = suite_config["task_jsonl"]
    prepared_root = suite_config["prepared_root"]
    if not isinstance(task_jsonl, Path) or not isinstance(prepared_root, Path):
        raise TypeError("suite paths are not Path objects")
    destination = args.output_root / "runs" / run_id
    if destination.exists():
        raise FileExistsError(f"refusing to reuse result directory: {destination}")
    destination.mkdir(parents=True)
    log(f"starting exact 50-epoch GCP evaluation: {run_id} suite={args.suite}")
    verify_network_isolation()
    inventory = gpu_inventory(
        args.expected_gpu_count,
        args.expected_gpu_model,
        args.expected_gpu_memory_mib,
    )
    log(
        f"verified {args.expected_gpu_count} {args.expected_gpu_model} GPUs; "
        f"tensor parallel size={args.tensor_parallel_size}; "
        f"data parallel size={args.data_parallel_size}"
    )
    read_exact_marker(
        args.model_path / ".source-revision", BASE_MODEL_REVISION, "base model"
    )
    parallelism = model_parallelism_contract(
        args.model_path, args.tensor_parallel_size
    )
    model_manifest = verify_model_manifest(
        args.model_path, args.expected_model_manifest_sha256
    )
    evaluator_receipts = verify_evaluator_receipts(suite_config)
    serving, conversion = prepare_serving_adapter(
        args.adapter_path,
        Path("/tmp") / f"{run_id}-serving-adapter",
        profile=checkpoint_profile,
    )
    candidate_seeds = [
        int(seed) for seed in suite_config.get("candidate_seeds", [1701])
    ]
    settings_by_seed: dict[int, Path] = {}
    repair_settings_by_seed: dict[int, Path] = {}
    settings_root = destination / "model-settings"
    settings_root.mkdir()
    for seed in candidate_seeds:
        candidate_settings = settings_root / f"candidate-{seed}.yml"
        candidate_repair_settings = settings_root / f"repair-{seed}.yml"
        write_model_settings(
            candidate_settings,
            model_name,
            thinking_enabled,
            str(suite_config["edit_format"]),
            temperature=float(suite_config.get("initial_temperature", 0.7)),
            seed=seed,
        )
        write_model_settings(
            candidate_repair_settings,
            model_name,
            thinking_enabled,
            str(suite_config["edit_format"]),
            temperature=float(suite_config.get("repair_temperature", 0.7)),
            seed=seed,
        )
        settings_by_seed[seed] = candidate_settings
        repair_settings_by_seed[seed] = candidate_repair_settings
    settings = settings_by_seed[candidate_seeds[0]]
    repair_settings = repair_settings_by_seed[candidate_seeds[0]]
    log_path = destination / "sglang.log"
    process: subprocess.Popen[str] | None = None
    load_receipt = ""
    preloaded_adapter = serving if args.data_parallel_size > 1 else None
    with log_path.open("w", encoding="utf-8") as log_handle:
        try:
            log(
                "launching SGLang with tensor parallelism "
                f"{args.tensor_parallel_size} and data parallelism "
                f"{args.data_parallel_size}"
            )
            process = subprocess.Popen(
                server_command(
                    args.model_path,
                    args.port,
                    args.lora_rank,
                    model_name,
                    args.tensor_parallel_size,
                    args.data_parallel_size,
                    preloaded_adapter,
                ),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
            )
            wait_for_server(process, log_path, args.port)
            if preloaded_adapter is not None:
                log("converted LoRA adapter loaded during SGLang startup")
                load_receipt = json.dumps(
                    {
                        "mode": "startup_preload",
                        "model": model_name,
                    },
                    sort_keys=True,
                )
            else:
                log("loading the converted LoRA adapter")
                load_receipt = load_adapter(serving, args.port, model_name)
            log(f"running {suite_config['description']} through Aider")
            suite = evaluate_suite_with_aider(
                task_jsonl,
                prepared_root,
                destination / "evaluation",
                aider_python="/opt/aider-venv/bin/python",
                model=model_name,
                model_settings=settings,
                api_base=f"http://127.0.0.1:{args.port}/v1",
                api_key=API_KEY,
                repair_model_settings=repair_settings,
                model_settings_by_seed=settings_by_seed,
                repair_model_settings_by_seed=repair_settings_by_seed,
            )
        finally:
            if process is not None:
                log("stopping SGLang")
                process.terminate()
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill()

    receipt = {
        "schema_version": "synthmem-50ep-public-pr-gcp-evaluation-v2",
        "status": "complete",
        "classification": "public_pr_regression_diagnostic_only",
        "run_id": run_id,
        "training_run_id": training_run_id,
        "execution_profile": args.execution_profile,
        "tensor_parallel_size": args.tensor_parallel_size,
        "data_parallel_size": args.data_parallel_size,
        "parallel_world_size": (
            args.tensor_parallel_size * args.data_parallel_size
        ),
        "model_parallelism": parallelism,
        "expected_gpu_count": args.expected_gpu_count,
        "expected_gpu_model": args.expected_gpu_model,
        "expected_gpu_memory_mib": args.expected_gpu_memory_mib,
        "provisioner": args.provisioner,
        "inference_request": {
            "thinking_enabled": thinking_enabled,
            "transport": "openai_chat_completions_extra_body",
            "field": "chat_template_kwargs.enable_thinking",
            "value": thinking_enabled,
            "configured_in": "aider_model_settings.extra_params.extra_body",
        },
        "checkpoint_profile": args.checkpoint_profile,
        "checkpoint_identity": checkpoint_profile,
        "base_model_revision": BASE_MODEL_REVISION,
        "base_model_file_manifest": model_manifest,
        "model": model_name,
        "gcp": {
            "project": os.environ["GCP_PROJECT"],
            "zone": os.environ["GCP_ZONE"],
            "instance": os.environ["GCP_INSTANCE"],
            "machine_type": os.environ["GCP_MACHINE_TYPE"],
            "resolved_dlvm_image": os.environ["GCP_DLVM_IMAGE"],
        },
        "evaluator_image_id": os.environ["EVAL_IMAGE_ID"],
        "gpu_inventory": inventory,
        "runtime_network": "docker_network_none_verified_loopback_only",
        "suite_mode": args.suite,
        "task_jsonl": str(task_jsonl),
        "task_jsonl_sha256": str(suite_config["task_jsonl_sha256"]),
        "evaluator_receipts": evaluator_receipts,
        "aider_environment_sha256": sha256_path(AIDER_FREEZE),
        "adapter_conversion": conversion,
        "adapter_load_response": load_receipt,
        "seed": candidate_seeds[0],
        "candidate_seeds": candidate_seeds,
        "temperature": float(suite_config.get("initial_temperature", 0.7)),
        "repair_temperature": float(suite_config.get("repair_temperature", 0.7)),
        "model_settings_sha256": sha256_path(settings),
        "repair_model_settings_sha256": sha256_path(repair_settings),
        "model_settings_directory": str(settings_root.relative_to(destination)),
        "model_settings_by_seed_sha256": {
            str(seed): sha256_path(path)
            for seed, path in sorted(settings_by_seed.items())
        },
        "repair_model_settings_by_seed_sha256": {
            str(seed): sha256_path(path)
            for seed, path in sorted(repair_settings_by_seed.items())
        },
        "top_p": 1.0,
        "max_completion_tokens": 32768,
        "attempts": int(suite_config["attempts"]),
        "suite": suite,
        "sglang_log_sha256": sha256_path(log_path),
        "completed_at_utc": utc_now(),
    }
    receipt_path = destination / "run-receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    log(
        f"complete; detailed report: {destination / 'evaluation' / 'diagnostic-report.md'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
