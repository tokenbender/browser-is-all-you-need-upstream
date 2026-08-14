from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import scripts.gcp_full_v5_charm_grpo as pipeline
from r8_runtime_fixture import build_schedule_runtime


REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "configs/full_v5_charm_grpo/gcp-r8-candidate-hybrid45-exact40-r87-skypilot.json"


def _load() -> dict[str, object]:
    previous = pipeline.CONFIG_PATH
    try:
        pipeline.CONFIG_PATH = CONFIG
        return pipeline.load_config()
    finally:
        pipeline.CONFIG_PATH = previous


def _render(phase: str) -> dict[str, object]:
    completed = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts/gcp_full_v5_charm_grpo.py"),
            "render",
            "--phase",
            phase,
            "--run-id",
            f"charm-r8-r87-{phase}-render",
        ],
        cwd=REPO,
        env={
            **os.environ,
            "PYTHONPATH": f"{REPO / 'src'}:{REPO}",
            "GLM47_FULL_V5_CONFIG_PATH": str(CONFIG),
        },
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout)


def test_corrected_profile_is_skypilot_only_and_fail_closed() -> None:
    config = _load()
    assert config["profile_id"] == ("aider-charm-r8-candidate-hybrid45-exact40-r87-skypilot")
    assert config["decision"] == "NOT_COMPLETED"
    assert config["execution"]["provisioner"] == "skypilot"
    assert config["execution"]["admission_mode"] == "PRETRAINING_GATES_NOT_COMPLETED"
    assert config["full_v5_runtime"]["oracle_receipt_sha256"] == (
        pipeline.PROFILE_CONTRACTS[config["profile_id"]]["oracle_receipt_sha256"]
    )
    assert config["full_v5_runtime"]["gcp_asset_status"] == (
        "LOCAL_MATERIALIZED_ORACLE_PASS_UPLOAD_PENDING"
    )
    assert config["preflight_evidence"]["scope"] == (
        "local-zero-update-evidence-not-training-admission"
    )
    assert config["preflight_evidence"]["all_local_zero_update_gates_passed"] is True
    assert config["preflight_evidence"]["training_admission_status"] == "NOT_COMPLETED"
    assert config["preflight_evidence"]["hybrid45_corpus_replay"][
        "gradient_full_positive_reward_count"
    ] == 40
    assert config["preflight_evidence"]["train_prompt_preflight"][
        "maximum_prompt_tokens"
    ] <= 2048
    assert config["admission"]["promotion_evaluation_split"]["sha256"] == (
        pipeline.PROFILE_CONTRACTS[config["profile_id"]]["promotion_split_sha256"]
    )
    assert config["admission"]["canary_task_manifest"] == {
        "decision": "FROZEN",
        "epochs": 5,
        "matched_trial_count": 4,
        "optimizer_updates": 5,
        "path": (
            "configs/full_v5_charm_grpo/"
            "r8-candidate-hybrid45-exact40-r87-canary.json"
        ),
        "sha256": pipeline.PROFILE_CONTRACTS[config["profile_id"]][
            "canary_manifest_sha256"
        ],
        "task_count": 20,
    }
    assert config["checkpoint_selection"]["expected_canary_checkpoint_count"] == 5
    assert config["checkpoint_selection"]["always_final"] is False
    assert config["checkpoint_selection"]["shadow_metrics_excluded"] is True
    assert config["full_v5_runtime"]["public_api_manifest_count"] == 51
    assert config["full_v5_runtime"]["public_api_manifest_schema"] == (
        "glm47-public-api-ast-manifest-v1"
    )
    assert config["full_v5_runtime"]["public_api_manifest_set_sha256"] == (
        "691eaa29592877385ff10b265a592c7e9884214f279eae0a8c31fe879535be64"
    )
    assert config["verifier_image"]["compile_compiler"] == "gcc-13.4.0"
    assert config["verifier_image"]["public_api_compiler"] == "clang-18.1.8"
    assert config["admission"]["pretraining_receipt"] == "NOT_COMPLETED"
    assert config["admission"]["canary_result"] == "NOT_COMPLETED"
    assert config["admission"]["full_training_authorized"] is False
    assert config["starting_adapter"]["adapter_model_sha256"] == (
        "4acb7f23c295f45380155c5d9ee6bc59422262f0cb51f0c02f7e550d405b575a"
    )


def test_corrected_render_binds_hybrid45_context_and_prompt_preflight() -> None:
    rendered = _render("canary")
    env = rendered["environment"]
    assert env["GLM47_PROVISIONER"] == "skypilot"
    assert env["GLM47_ADMISSION_STATUS"] == "NOT_COMPLETED"
    assert env["MILES_AIDER_REWARD_MODE"] == "hybrid_bipolar45"
    assert env["MILES_EXPECTED_DATASET_KIND"] == ("charm-r8-candidate-hybrid45-exact40")
    assert env["MILES_EXPECTED_PROMPT_ROWS"] == "100"
    assert env["MILES_ROLLOUT_MAX_PROMPT_LEN"] == "2048"
    assert env["GLM47_AIDER_REQUIRE_CONTEXT_ISOLATION"] == "1"
    assert env["GLM47_AIDER_REQUIRE_UNIQUE_TASK_GROUPS"] == "1"
    assert env["GLM47_AIDER_MIN_EXACT_FORMAT_RATE"] == "0.5"
    assert env["GLM47_AIDER_MIN_COMPILE_RATE"] == "0.2"
    assert env["GLM47_CPP_TSAN_PREFLIGHT_REQUIRED"] == "1"
    assert env["GLM47_CPP_TSAN_EXECUTION_ALLOWED"] == "1"
    assert env["GLM47_TOKENIZER_MANIFEST_SHA256"] == (
        "53bcc04c0e0acedb8b57abbb03f28c29519b79a245c78784c341554ad33ce1a2"
    )
    assert env["GLM47_CHAT_TEMPLATE_SHA256"] == (
        "d63ad536c3c81880043e22ec7fd08db42b4d8fb7c89c7138bc562bfa25281375"
    )
    assert env["MILES_GRPO_ADVANTAGE_POLICY"] == "miles-standard-grpo-group-std-v1"
    assert env["MILES_REWARDS_NORMALIZATION"] == "1"
    assert env["MILES_GRPO_STD_NORMALIZATION"] == "1"
    assert env["MILES_NORMALIZE_ADVANTAGES"] == "0"


def test_candidate_profile_refuses_any_optimizer_launch() -> None:
    previous = pipeline.CONFIG_PATH
    try:
        pipeline.CONFIG_PATH = CONFIG
        with pytest.raises(RuntimeError, match="optimizer launch is blocked"):
            pipeline.train(
                argparse.Namespace(
                    run_id="charm-r8-r87-blocked",
                    phase="canary",
                )
            )
    finally:
        pipeline.CONFIG_PATH = previous


def test_corrected_schedule_staging_preserves_hybrid45_policy(tmp_path: Path) -> None:
    canary_ids = json.loads(
        (
            REPO / "configs/full_v5_charm_grpo/r8-candidate-hybrid45-exact40-r87-selection.json"
        ).read_text(encoding="utf-8")
    )["canary_task_ids"]
    selection = json.loads(
        (
            REPO
            / "configs/full_v5_charm_grpo/r8-candidate-hybrid45-exact40-r87-selection.json"
        ).read_text(encoding="utf-8")
    )
    train_ids = [task_id for group in selection["groups"].values() for task_id in group]
    runtime = build_schedule_runtime(
        tmp_path / "runtime",
        train_ids=train_ids,
        canary_ids=canary_ids,
        reward_policy=selection["reward_policy"],
    )
    staged = pipeline.stage_r7_training_data(
        runtime,
        tmp_path / "data",
        phase="canary",
        canary_task_ids=canary_ids,
    )
    assert staged["rows"] == 100
    assert staged["reward_policy"] == "hybrid-bipolar45-v2"


def test_corrected_threshold_drift_is_rejected() -> None:
    config = _load()
    config["reward"]["signal_thresholds"]["minimum_exact_format_rate"] = 0.35
    contract = pipeline.PROFILE_CONTRACTS[config["profile_id"]]
    with pytest.raises(RuntimeError, match="signal_thresholds"):
        pipeline._validate_candidate_r8_config(config, contract)


def test_corrected_local_preflight_digest_drift_is_rejected() -> None:
    config = _load()
    config["preflight_evidence"]["hybrid45_corpus_replay"]["file_sha256"] = "0" * 64
    contract = pipeline.PROFILE_CONTRACTS[config["profile_id"]]
    with pytest.raises(RuntimeError, match="local_preflight_receipts"):
        pipeline._validate_candidate_r8_config(config, contract)


def test_corrected_checkpoint_selection_drift_is_rejected() -> None:
    config = _load()
    config["checkpoint_selection"]["always_final"] = True
    contract = pipeline.PROFILE_CONTRACTS[config["profile_id"]]
    with pytest.raises(RuntimeError, match="checkpoint_selection"):
        pipeline._validate_candidate_r8_config(config, contract)


def test_train_launcher_runs_prompt_preflight_before_ray() -> None:
    text = (REPO / "scripts/train_grpo.sh").read_text(encoding="utf-8")
    preflight = text.index("-m glm47_posttraining.aider_polyglot.prompt_preflight")
    ray = text.index("ray start --head")
    assert preflight < ray
    assert 'EXPECTED_PROMPT_ROWS="${MILES_EXPECTED_PROMPT_ROWS:-}"'.replace("\\", "") in text
    assert '--output "${PROMPT_PREFLIGHT_RECEIPT}"'.replace("\\", "") in text
    assert "context-isolated GRPO requires pinned prompt-local" in text
    assert "--disable-grpo-std-normalization" in text
    assert "--normalize-advantages" in text


def test_training_image_and_cpu_trainer_receipt_are_exactly_bound(tmp_path: Path) -> None:
    config = _load()
    image = config["training_image"]
    assert image["base"] == pipeline.R8_MILES_BASE_IMAGE
    assert image["miles_commit"] == pipeline.R8_MILES_COMMIT
    assert image["miles_source_files"] == pipeline.R8_MILES_SOURCE_FILES
    assert image["trainer_contract_preflight_required"] is True
    assert (
        config["optimizer_policy"]
        == pipeline.PROFILE_CONTRACTS[config["profile_id"]]["optimizer_policy"]
    )
    build_args = pipeline._training_build_args(config)
    rendered_args = " ".join(build_args)
    assert f"MILES_BASE_IMAGE={pipeline.R8_MILES_BASE_IMAGE}" in rendered_args
    for digest in pipeline.R8_MILES_SOURCE_FILES.values():
        assert digest in rendered_args
    contract_path = tmp_path / "miles-grpo-advantage-contract.json"
    command = pipeline._trainer_contract_command(config, "training:image", contract_path)
    assert "--gpus" not in command
    assert command[command.index("--network") + 1] == "none"
    image_index = command.index("training:image")
    assert command[image_index + 1 : image_index + 4] == [
        "env",
        "-u",
        "CPLUS_INCLUDE_PATH",
    ]
    assert str(contract_path) in command
    dockerfile = (REPO / "docker/full-v5-charm-grpo-gcp/Dockerfile").read_text()
    assert "ARG MILES_BASE_IMAGE=" in dockerfile
    assert "GLM47_ENFORCE_R8_TRAINER_CONTRACT" in dockerfile
    assert "-m glm47_posttraining.aider_polyglot.grpo_advantage_contract" in dockerfile
    assert "env -u CPLUS_INCLUDE_PATH" in dockerfile
    assert "GLM47_LIBCLANG_RESOURCE_DIR=/usr/local/lib/clang/18" in dockerfile
    assert "CPLUS_INCLUDE_PATH=/usr/local/lib/clang/18/include" not in dockerfile
    assert "GLM47_MILES_MODEL_ARGS_UTILS_SHA256" in dockerfile
    assert "GLM47_MILES_GLM47_FLASH_MODEL_ARGS_SHA256" in dockerfile
    assert "GLM47_MILES_CONVERTER_SHA256" in dockerfile
    assert "miles/utils/external_utils/model_args_utils.py=" in dockerfile
    assert "scripts/models/glm4.7-flash.py=" in dockerfile
    assert "tools/convert_hf_to_torch_dist.py=" in dockerfile
    dockerignore = (REPO / ".dockerignore").read_text(encoding="utf-8").splitlines()
    for private_path in (
        "artifacts",
        "dataset/jsonls",
        "dataset/registry",
        "dataset/reports",
        "dataset/tasks",
        "updated task",
    ):
        assert private_path in dockerignore
    assert "dataset/configs/*" in dockerignore
    assert "!dataset/configs/glm47-flash-tokenizer-manifest.json" in dockerignore
    assert "!dataset/configs/glm47-flash-chat-template.jinja" in dockerignore
    verifier = (REPO / "docker/full-v5-charm-grpo-gcp/Verifier.Dockerfile").read_text(
        encoding="utf-8"
    )
    assert "gcc:13@sha256:4f86732b7340848e" in verifier
    assert "silkeh/clang:18-bookworm@sha256:9388794775d1393c" in verifier
    assert "COPY --from=gcc13 /usr/local /usr/local" in verifier
    assert 'glm47.compile.compiler="gcc-13"' in verifier
    assert 'glm47.public-api.compiler="clang-18"' in verifier


def test_pinned_miles_python_model_args_have_a_read_only_shell_adapter(
    tmp_path: Path,
) -> None:
    miles_root = tmp_path / "miles"
    loader = miles_root / "miles/utils/external_utils/model_args_utils.py"
    loader.parent.mkdir(parents=True)
    loader.write_text(
        "import sys\n"
        "assert sys.argv[1] == 'glm4.7-flash'\n"
        "print('--num-layers 47 --hidden-size 2048')\n",
        encoding="utf-8",
    )
    adapter = REPO / "configs/miles/glm4.7-flash.sh"
    completed = subprocess.run(
        [
            "bash",
            "-c",
            (
                'set -euo pipefail; source "$1"; '
                'printf "%s\\n" "${MODEL_ARGS[@]}"'
            ),
            "bash",
            str(adapter),
        ],
        env={**os.environ, "MILES_ROOT": str(miles_root)},
        text=True,
        capture_output=True,
        check=True,
    )
    assert completed.stdout.splitlines() == [
        "--num-layers",
        "47",
        "--hidden-size",
        "2048",
    ]

    command = pipeline._docker_training_command(
        run_id="unadmitted-r8-r87-model-args-test",
        result_root=tmp_path,
        train_image="training:image",
        env_values={},
    )
    mount = (
        f"{pipeline.MILES_MODEL_ARGS_COMPAT_PATH}:"
        f"{pipeline.MILES_MODEL_ARGS_COMPAT_CONTAINER_PATH}:ro"
    )
    assert mount in command
    pipeline_text = (REPO / "scripts/gcp_full_v5_charm_grpo.py").read_text(
        encoding="utf-8"
    )
    assert pipeline_text.count("MILES_MODEL_ARGS_COMPAT_CONTAINER_PATH") >= 3


def test_prebuilt_images_require_and_verify_immutable_registry_refs(monkeypatch) -> None:
    digest_a = "sha256:" + "a" * 64
    digest_b = "sha256:" + "b" * 64
    runtime_id_a = "sha256:" + "c" * 64
    runtime_id_b = "sha256:" + "d" * 64
    train_ref = f"registry.example/training@{digest_a}"
    verifier_ref = f"registry.example/verifier@{digest_b}"
    config = {
        "training_image": {"immutable_ref": train_ref, "registry_digest": digest_a},
        "verifier_image": {"immutable_ref": verifier_ref, "registry_digest": digest_b},
    }
    pulled = []
    monkeypatch.setattr(pipeline, "docker_prefix", lambda: ["docker"])
    monkeypatch.setattr(pipeline, "run", lambda command, **_kwargs: pulled.append(command))
    monkeypatch.setattr(pipeline, "docker_repo_digests", lambda image: {image})
    monkeypatch.setattr(
        pipeline,
        "docker_image_id",
        lambda image: runtime_id_a if image == train_ref else runtime_id_b,
    )

    assert pipeline._pull_prebuilt_images(
        config,
        train_image=train_ref,
        verifier_image=verifier_ref,
    ) == {"training": runtime_id_a, "verifier": runtime_id_b}
    assert pulled == [["docker", "pull", train_ref], ["docker", "pull", verifier_ref]]

    with pytest.raises(RuntimeError, match="immutable registry reference"):
        pipeline._pull_prebuilt_images(
            config,
            train_image="registry.example/training:mutable",
            verifier_image=verifier_ref,
        )

    monkeypatch.setattr(
        pipeline,
        "docker_repo_digests",
        lambda _image: {"registry.example/unrelated@sha256:" + "e" * 64},
    )
    with pytest.raises(RuntimeError, match="registry digest mismatch"):
        pipeline._pull_prebuilt_images(
            config,
            train_image=train_ref,
            verifier_image=verifier_ref,
        )
