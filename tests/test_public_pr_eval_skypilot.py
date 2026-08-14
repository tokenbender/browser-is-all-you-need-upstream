from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PATH = REPO_ROOT / "scripts/gcp_public_pr_synthmem_50ep_eval.py"
LAUNCHER_PATH = REPO_ROOT / "scripts/gcp_public_pr_eval_run.sh"
HOST_SETUP_PATH = REPO_ROOT / "scripts/gcp_public_pr_eval_host_setup.sh"
DOCKERFILE_PATH = (
    REPO_ROOT / "docker/public-pr-synthmem-v1-ep50-gcp/Dockerfile"
)
RUNTIME_OVERLAY_DOCKERFILE_PATH = (
    REPO_ROOT / "docker/public-pr-synthmem-v1-ep50-gcp/Dockerfile.runtime-overlay"
)
SKYPILOT_PATH = REPO_ROOT / "eval_h100_v8.yaml"


def _load_runtime():
    spec = importlib.util.spec_from_file_location("gcp_eval_skypilot", RUNTIME_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _gpu_rows(count: int, model: str, memory_mib: int) -> str:
    return "".join(
        f"{index}, {model}, {memory_mib}, 580.65.06, GPU-{index}\n"
        for index in range(count)
    )


def test_runtime_preserves_a100_tp4_defaults() -> None:
    runtime = _load_runtime()
    parser = runtime.parser()

    assert parser.get_default("tensor_parallel_size") == 4
    assert parser.get_default("data_parallel_size") == 1
    assert parser.get_default("expected_gpu_count") == 4
    assert parser.get_default("expected_gpu_model") == "A100"
    assert parser.get_default("expected_gpu_memory_mib") == 80_000
    assert parser.get_default("execution_profile") == "gcp-a100-tp4"
    assert parser.get_default("provisioner") == "gcloud-shell"


def test_runtime_accepts_eight_h100s_and_rejects_topology_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _load_runtime()
    monkeypatch.setattr(
        runtime.subprocess,
        "check_output",
        lambda *_args, **_kwargs: _gpu_rows(8, "NVIDIA H100 80GB HBM3", 81_559),
    )

    inventory = runtime.gpu_inventory(8, "H100", 80_000)
    assert len(inventory) == 8
    assert all("H100" in str(gpu["name"]) for gpu in inventory)

    with pytest.raises(RuntimeError, match="exactly 4 GPUs are required"):
        runtime.gpu_inventory(4, "A100", 80_000)


def test_model_parallelism_contract_requires_attention_head_divisibility(
    tmp_path: Path,
) -> None:
    runtime = _load_runtime()
    (tmp_path / "config.json").write_text(
        '{"num_attention_heads": 20}\n', encoding="utf-8"
    )

    assert runtime.model_parallelism_contract(tmp_path, 4) == {
        "num_attention_heads": 20,
        "tensor_parallel_size": 4,
        "attention_heads_per_tp_rank": 5,
    }
    with pytest.raises(
        RuntimeError,
        match="tensor parallel size 8 does not divide.*20 attention heads",
    ):
        runtime.model_parallelism_contract(tmp_path, 8)


def test_sglang_tp4_dp2_preserves_glm_lora_flags() -> None:
    runtime = _load_runtime()
    command = runtime.server_command(
        Path("/models/GLM-4.7-Flash"),
        8000,
        16,
        "glm47-synthmem-v1-ep50",
        4,
        2,
        Path("/tmp/serving-adapter"),
    )

    assert command[command.index("--tp-size") + 1] == "4"
    assert command[command.index("--dp-size") + 1] == "2"
    assert command[command.index("--lora-paths") + 1] == (
        "glm47-synthmem-v1-ep50=/tmp/serving-adapter"
    )
    assert command[command.index("--tool-call-parser") + 1] == "glm47"
    assert command[command.index("--reasoning-parser") + 1] == "glm45"
    assert "--experts-shared-outer-loras" in command
    assert "--lora-use-virtual-experts" in command
    target_start = command.index("--lora-target-modules") + 1
    assert command[target_start : target_start + 6] == [
        "q_a_proj",
        "kv_a_proj_with_mqa",
        "o_proj",
        "gate_proj",
        "up_proj",
        "down_proj",
    ]


def test_shell_profiles_are_parameterized_and_syntax_valid() -> None:
    host_setup = HOST_SETUP_PATH.read_text(encoding="utf-8")
    launcher = LAUNCHER_PATH.read_text(encoding="utf-8")

    assert 'EXPECTED_GPU_COUNT="${EXPECTED_GPU_COUNT:-4}"' in host_setup
    assert 'EXPECTED_GPU_MODEL="${EXPECTED_GPU_MODEL:-A100}"' in host_setup
    assert "This script accepts no arguments" in host_setup
    assert "NVIDIA_SMI_BIN=" in host_setup
    assert "sudo -n" in host_setup
    assert host_setup.count("run_nvidia_smi --query-gpu=") == 2
    assert 'TENSOR_PARALLEL_SIZE="${TENSOR_PARALLEL_SIZE:-4}"' in launcher
    assert 'DATA_PARALLEL_SIZE="${DATA_PARALLEL_SIZE:-1}"' in launcher
    assert 'BUILD_IMAGE="${BUILD_IMAGE:-1}"' in launcher
    assert 'GCP_MACHINE_TYPE="$(basename "$(metadata_value instance/machine-type)")"' in launcher
    assert "GCP_MACHINE_TYPE=a2-ultragpu-4g" not in launcher
    for path in (HOST_SETUP_PATH, LAUNCHER_PATH):
        subprocess.run(["bash", "-n", str(path)], check=True)


def test_runtime_only_copy_does_not_invalidate_oracle_layer() -> None:
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")
    runtime_copy = (
        "COPY scripts/gcp_public_pr_synthmem_50ep_eval.py "
        "scripts/gcp_public_pr_synthmem_50ep_eval.py"
    )

    assert dockerfile.count(runtime_copy) == 1
    assert dockerfile.index(runtime_copy) > dockerfile.index("verify-oracles")
    assert dockerfile.index(runtime_copy) > dockerfile.index("pip freeze")


def test_runtime_overlay_preserves_the_verified_evaluator_parent() -> None:
    dockerfile = RUNTIME_OVERLAY_DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert (
        "sha256:a3567f523b8e8df09fd13848b510d48a4888dd1c06d8db1f765d7de3fe2e145a"
        in dockerfile
    )
    assert "FROM ${BASE_EVALUATOR_IMAGE}" in dockerfile
    assert dockerfile.count(
        "COPY scripts/gcp_public_pr_synthmem_50ep_eval.py "
        "scripts/gcp_public_pr_synthmem_50ep_eval.py"
    ) == 1
    assert "\nRUN " not in dockerfile


def test_skypilot_h100_task_binds_assets_results_and_runtime_profile() -> None:
    task = yaml.safe_load(SKYPILOT_PATH.read_text(encoding="utf-8"))
    resources = task["resources"]
    mounts = task["file_mounts"]
    run = task["run"]
    setup = task["setup"]

    assert resources["cloud"] == "gcp"
    assert resources["region"] == "us-central1"
    assert resources["accelerators"] == "H100:8"
    assert resources["network_tier"] == "best"
    assert resources["use_spot"] is False
    assert resources["autostop"] == {"idle_minutes": 10, "down": True}
    assert mounts["~/glm47-assets/model/GLM-4.7-Flash"]["mode"] == "COPY"
    assert mounts["~/glm47-assets/synthmem-v1-ep50/adapter"]["mode"] == "COPY"
    assert mounts["~/glm47-results-store"] == {
        "source": "gs://lifeandhalf-24122025-w8-biayn",
        "mode": "MOUNT",
    }
    assert (
        'export RESULT_DIR="${HOME}/glm47-results-store/'
        'glm47-public-pr-eval/results"' in run
    )
    assert "synthmem-v1-ep50-thinking-v8-h100-tp4-dp2-r2-20260811" in setup
    assert 'export BUILD_IMAGE=0' in run
    assert (
        "sha256:64cd3818b0a15cd9ff317095d5f09cafdad8a399fd346bf96f2557f31c7aa883" in setup
    )
    assert 'export TENSOR_PARALLEL_SIZE=4' in run
    assert 'export DATA_PARALLEL_SIZE=2' in run
    assert 'export EXPECTED_GPU_COUNT=8' in run
    assert 'export EXPECTED_GPU_MODEL=H100' in run
    assert 'export EXECUTION_PROFILE="gcp-skypilot-h100-tp4-dp2"' in run
    assert 'export PROVISIONER="skypilot"' in run
    assert 'export CHECKPOINT_PROFILE="synthmem-v1-ep50"' in run
    assert 'export SUITE="fmtlib-final-cleanup-verified-mechanisms-thinking"' in run
    assert run.count("gcp_public_pr_eval_run.sh") == 1
