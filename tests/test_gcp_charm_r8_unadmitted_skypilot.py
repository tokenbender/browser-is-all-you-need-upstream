from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

import scripts.gcp_full_v5_charm_grpo as pipeline
from r8_runtime_fixture import build_schedule_runtime


REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "configs/full_v5_charm_grpo/gcp-r8-unadmitted-hybrid45-exact40-r87-skypilot.json"
TASK = REPO / "grpo_h100_full_v5_charm_r8_unadmitted.yaml"
RUNNER = REPO / "scripts/gcp_full_v5_charm_r8_unadmitted_skypilot.sh"
SUBMITTER = REPO / "scripts/gcp_full_v5_charm_r8_unadmitted_skypilot_submit.sh"
DRIVER = REPO / "scripts/gcp_full_v5_charm_grpo.py"
TRANSPORT_BUILDER = REPO / "scripts/build_r8_skypilot_workdir.py"
AUTH_ENV = "GLM47_CHARM_R8_UNADMITTED_FULL_AUTHORIZATION"
AUTH_PHRASE = "I_AUTHORIZE_UNADMITTED_R8_HYBRID45_EXACT40_6_UPDATE_EXPERIMENT_AND_GCP_COSTS"


def _env() -> dict[str, str]:
    return {
        **os.environ,
        "PYTHONPATH": f"{REPO / 'src'}:{REPO}",
        "GLM47_FULL_V5_CONFIG_PATH": str(CONFIG),
    }


def test_r8_direct_full_profile_is_quarantined_and_exact40() -> None:
    profile = json.loads(CONFIG.read_text(encoding="utf-8"))
    assert profile["decision"] == "EXPERIMENTAL_UNADMITTED"
    assert profile["execution"]["provisioner"] == "skypilot"
    assert profile["execution"]["admission_mode"] == "UNADMITTED_EXPERIMENT_ONLY"
    assert profile["execution"]["checkpoint_disposition"] == "QUARANTINE_ONLY"
    assert profile["execution"]["charm_eligible"] is False
    assert profile["full_training"]["train_targets"] == 40
    assert profile["full_training"]["epochs"] == 3
    assert profile["full_training"]["rollout_updates"] == 6
    assert profile["full_training"]["requires_canary_promotion_pass"] is False
    assert profile["reward"]["policy_version"] == "hybrid-bipolar45-v2"
    assert profile["experimental_contract"]["eligible_for_charm_promotion"] is False
    assert profile["experimental_contract"]["canary_skipped_by_operator"] is True
    assert profile["training_image"]["gcp_asset_status"] in {
        "LOCAL_VALIDATED_UPLOAD_PENDING",
        "AVAILABLE",
    }
    assert profile["full_v5_runtime"]["gcp_asset_status"] in {
        "LOCAL_MATERIALIZED_ORACLE_PASS_UPLOAD_PENDING",
        "AVAILABLE",
    }


def test_r8_direct_full_render_preserves_corrected_contract() -> None:
    completed = subprocess.run(
        [sys.executable, str(DRIVER), "render", "--phase", "experimental", "--run-id", "unadmitted-r8-r87-attempt-test"],
        cwd=REPO,
        env=_env(),
        text=True,
        capture_output=True,
        check=True,
    )
    env = json.loads(completed.stdout)["environment"]
    assert env["MILES_NUM_ROLLOUT"] == "6"
    assert env["MILES_EXPECTED_PROMPT_ROWS"] == "120"
    assert env["MILES_GRPO_ROLLOUT_SHUFFLE"] == "0"
    assert env["GLM47_AIDER_REQUIRE_CONTEXT_ISOLATION"] == "1"
    assert env["GLM47_AIDER_REQUIRE_UNIQUE_TASK_GROUPS"] == "1"
    assert env["GLM47_CPP_TSAN_EXECUTION_ALLOWED"] == "1"
    assert env["GLM47_CHARM_ELIGIBLE"] == "0"
    assert env["GLM47_CHECKPOINT_DISPOSITION"] == "QUARANTINE_ONLY"
    assert "MILES_EXTRA_ARGS" not in env
    assert env["MILES_SGLANG_MEM_FRACTION_STATIC"] == "0.60"


def test_r8_one_update_smoke_preserves_full_batch_and_topology() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(DRIVER),
            "render",
            "--phase",
            "experimental",
            "--run-id",
            "unadmitted-r8-r87-one-update-test",
            "--one-update-smoke",
        ],
        cwd=REPO,
        env=_env(),
        text=True,
        capture_output=True,
        check=True,
    )
    env = json.loads(completed.stdout)["environment"]
    assert env["MILES_NUM_ROLLOUT"] == "1"
    assert env["MILES_EXPECTED_PROMPT_ROWS"] == "20"
    assert env["MILES_ROLLOUT_BATCH_SIZE"] == "20"
    assert env["MILES_N_SAMPLES_PER_PROMPT"] == "8"
    assert env["MILES_GLOBAL_BATCH_SIZE"] == "160"
    assert env["MILES_TENSOR_MODEL_PARALLEL_SIZE"] == "4"
    assert env["MILES_EXPERT_MODEL_PARALLEL_SIZE"] == "8"
    assert "MILES_EXTRA_ARGS" not in env
    assert env["MILES_SGLANG_MEM_FRACTION_STATIC"] == "0.60"
    assert env["GLM47_CHECKPOINT_DISPOSITION"] == "QUARANTINE_ONLY"


def test_r8_experimental_phase_stages_the_frozen_full_schedule(tmp_path: Path) -> None:
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
        canary_ids=selection["canary_task_ids"],
        reward_policy=selection["reward_policy"],
    )
    staged = pipeline.stage_r7_training_data(
        runtime,
        tmp_path / "data",
        phase="experimental",
    )

    assert staged["phase"] == "experimental"
    assert staged["epochs"] == 3
    assert staged["unique_tasks"] == 40
    assert staged["rows"] == 120
    assert staged["prompt_data"] == "grpo/full-3ep-train.jsonl"
    rows = pipeline.read_jsonl(tmp_path / "data" / staged["prompt_data"])
    assert {row["metadata"]["schedule_phase"] for row in rows} == {"experimental"}


def test_r8_direct_full_task_is_spot_recoverable_and_attempt_isolated() -> None:
    task = yaml.safe_load(TASK.read_text(encoding="utf-8"))
    resources = task["resources"]
    assert resources["use_spot"] is True
    assert resources["job_recovery"] == {"strategy": "FAILOVER", "max_restarts_on_errors": 0}
    assert resources["autostop"] == {"idle_minutes": 10, "down": True}
    assert "gcp_full_v5_charm_r8_unadmitted_skypilot.sh" in task["run"]
    assert "gcloud auth print-access-token" in task["setup"]
    assert "sudo docker login" in task["setup"]
    assert "us-central1-docker.pkg.dev" in task["setup"]
    assert task["envs"]["GLM47_R8_ONE_UPDATE_SMOKE"] == "0"

    text = RUNNER.read_text(encoding="utf-8")
    subprocess.run(["bash", "-n", str(RUNNER)], check=True)
    assert 'ATTEMPT_RUN_ID="${BASE_RUN_ID}-attempt-${ATTEMPT_STAMP}-${ATTEMPT_NONCE}"' in text
    assert "secrets.token_hex(4)" in text
    assert 'write_attempt_record "started"' in text
    assert 'write_attempt_record "failed"' in text
    assert 'write_attempt_record "passed"' in text
    assert 'ATTEMPT_EVIDENCE_ROOT="${ATTEMPT_INDEX_ROOT}/${ATTEMPT_RUN_ID}"' in text
    assert '"last_stage":"%s"' in text
    assert "write_stage_record()" in text
    assert "persist_control_artifacts()" in text
    assert "run_logged_stage prepare" in text
    assert "run_logged_stage train" in text
    assert '>"${CONTROL_ROOT}/prepare.log" 2>&1' not in text
    assert "--prebuilt-images" in text
    assert "--phase experimental" in text
    assert "--one-update-smoke" in text
    assert "GLM47_R8_ONE_UPDATE_SMOKE" in text
    assert "--phase canary" not in text
    assert "--phase full" not in text
    assert "tmux" not in text


def test_r8_runner_streams_and_persists_prepare_failure(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python3"
    fake_python.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "-c" ]]; then
  if [[ "${2:-}" == *"token_hex"* ]]; then
    printf 'feedface\\n'
  else
    printf 'registry.example/training@sha256:%064d\\n' 0
    printf 'registry.example/verifier@sha256:%064d\\n' 1
  fi
  exit 0
fi
case "${2:-}" in
  inspect|render)
    printf '{"status":"ok"}\\n'
    ;;
  host-check)
    printf 'HOST_CHECK_OK\\n'
    ;;
  prepare)
    printf 'PREPARE_FAILURE_MARKER\\n' >&2
    exit 2
    ;;
  *)
    printf 'unexpected fake-python invocation: %s\\n' "$*" >&2
    exit 99
    ;;
esac
""",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    base_run_id = "unadmitted-r8-r87-durable-failure-test"
    local_root = tmp_path / "local"
    durable_root = tmp_path / "durable"
    environment = {
        **_env(),
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "RUN_ID": base_run_id,
        AUTH_ENV: AUTH_PHRASE,
        "GLM47_FULL_V5_RESULT_ROOT": str(local_root),
        "GLM47_FULL_V5_DURABLE_RESULT_ROOT": str(durable_root),
    }

    completed = subprocess.run(
        ["bash", str(RUNNER)],
        cwd=REPO,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "PREPARE_FAILURE_MARKER" in completed.stdout
    attempt_index = durable_root / "attempt-index" / base_run_id
    failed_records = list(attempt_index.glob("*.failed.json"))
    assert len(failed_records) == 1
    failed = json.loads(failed_records[0].read_text(encoding="utf-8"))
    assert failed["exit_code"] == 2
    assert failed["last_stage"] == "prepare"
    attempt_id = failed_records[0].name.removesuffix(".failed.json")
    evidence_root = attempt_index / attempt_id
    assert "PREPARE_FAILURE_MARKER" in (
        evidence_root / "control/prepare.log"
    ).read_text(encoding="utf-8")
    assert (evidence_root / "stages/prepare.started.json").is_file()
    assert (evidence_root / "stages/prepare.failed.json").is_file()
    assert (evidence_root / "stages/prepare.terminal-failure.json").is_file()


def test_r8_frozen_transport_binds_source_commit(tmp_path: Path) -> None:
    output_root = tmp_path / "transport"
    completed = subprocess.run(
        [
            sys.executable,
            str(TRANSPORT_BUILDER),
            "--repo-root",
            str(REPO),
            "--profile",
            str(CONFIG),
            "--output-root",
            str(output_root),
        ],
        cwd=REPO,
        env=_env(),
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(completed.stdout)
    receipt = json.loads(
        (output_root / "r8-skypilot-transport-receipt.json").read_text(
            encoding="utf-8"
        )
    )
    task = yaml.safe_load(
        (output_root / "r8-skypilot-transport.yaml").read_text(encoding="utf-8")
    )
    source_commit = receipt["source_commit"]["value"]

    assert len(source_commit) == 40
    assert set(source_commit) <= set("0123456789abcdef")
    assert receipt["source_commit"]["transport"] == "GLM47_SOURCE_COMMIT"
    assert payload["source_commit"] == receipt["source_commit"]
    assert f"export GLM47_SOURCE_COMMIT='{source_commit}'" in task["run"]


def test_r8_submitter_requires_cost_authorization_before_sky() -> None:
    text = SUBMITTER.read_text(encoding="utf-8")
    subprocess.run(["bash", "-n", str(SUBMITTER)], check=True)
    assert text.index('if [[ "${!AUTH_ENV:-}"') < text.index("exec sky jobs launch")
    assert "--detach-run" in text
    assert "--yes" in text
    assert "build_r8_skypilot_workdir.py" in text
    assert 'mktemp -d "/tmp/glm47-r8-${RUN_ID}.XXXXXXXX"' in text
    assert ".w8-biayn/r8-skypilot-transports" not in text
    assert 'TRANSPORT_TASK="../r8-skypilot-transport.yaml"' in text
    assert "GLM47_R8_ONE_UPDATE_SMOKE" in text
    assert "--one-update-smoke" in text
    environment = _env()
    environment.pop(AUTH_ENV, None)
    environment["PATH"] = "/usr/bin:/bin"
    completed = subprocess.run(
        [str(SUBMITTER), "unadmitted-r8-r87-test"],
        cwd=REPO,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 2
    assert "No GPU was requested" in completed.stderr
    assert "sky: command not found" not in completed.stderr


def test_r8_submitter_blocks_authorized_cost_before_sky_when_assets_are_pending() -> None:
    environment = _env()
    environment[AUTH_ENV] = AUTH_PHRASE
    environment["PATH"] = "/usr/bin:/bin"
    completed = subprocess.run(
        [str(SUBMITTER), "unadmitted-r8-r87-test-pending-assets"],
        cwd=REPO,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "sky: command not found" not in completed.stderr
