from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[1]
TASK = REPO / "grpo_h100_full_v5_charm_r8.yaml"
RUNNER = REPO / "scripts/gcp_full_v5_charm_r8_skypilot.sh"
SUBMITTER = REPO / "scripts/gcp_full_v5_charm_r8_skypilot_submit.sh"


def test_r8_candidate_task_is_managed_spot_and_autostops() -> None:
    task = yaml.safe_load(TASK.read_text(encoding="utf-8"))
    resources = task["resources"]

    assert resources["cloud"] == "gcp"
    assert resources["region"] == "us-central1"
    assert resources["instance_type"] == "a3-highgpu-8g"
    assert resources["accelerators"] == "H100:8"
    assert resources["use_spot"] is True
    assert resources["job_recovery"] == {
        "strategy": "FAILOVER",
        "max_restarts_on_errors": 0,
    }
    assert resources["autostop"] == {"idle_minutes": 10, "down": True}
    assert task["envs"]["GLM47_SKYPILOT_MODE"] == "candidate"
    assert "gcp_full_v5_charm_r8_skypilot.sh" in task["run"]
    assert "gcp-r8-candidate-hybrid45-exact40-r87-skypilot.json" in task["run"]


def test_r8_vm_runner_cannot_reach_training() -> None:
    text = RUNNER.read_text(encoding="utf-8")
    subprocess.run(["bash", "-n", str(RUNNER)], check=True)

    assert 'MODE="${GLM47_SKYPILOT_MODE:-candidate}"' in text
    assert 'if [[ "${MODE}" != "candidate" ]]' in text
    assert " CANDIDATE_NOT_ADMITTED" in text
    assert " host-check" not in text
    assert " prepare" not in text
    assert '"${DRIVER}" train' not in text
    assert "docker run" not in text.lower()
    assert "ray start" not in text.lower()
    assert "gcloud compute" not in text


def test_r8_local_submit_guard_blocks_before_sky_jobs_launch() -> None:
    text = SUBMITTER.read_text(encoding="utf-8")
    subprocess.run(["bash", "-n", str(SUBMITTER)], check=True)
    assert text.index('decision="$(') < text.index("exec sky jobs launch")
    assert text.index('admission_mode="$(') < text.index("exec sky jobs launch")

    env = {
        **os.environ,
        "PATH": "/usr/bin:/bin",
        "PYTHONPATH": f"{REPO / 'src'}:{REPO}",
    }
    completed = subprocess.run(
        [str(SUBMITTER), "charm-r8-r87-test-blocked"],
        cwd=REPO,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 2
    assert "Refusing SkyPilot provisioning" in completed.stderr
    assert "No GPU instance was requested" in completed.stderr
    assert "sky: command not found" not in completed.stderr
