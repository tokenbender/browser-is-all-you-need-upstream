from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
RUNNER = ROOT / "Reward_GRPO/global_cpp_verifier_runner.py"
PACK = ROOT / "Reward_GRPO/Generalized Cpp Verifiers"
FIXTURES = ROOT / "generalized_verifier_docs/validation/fixtures"
SELF_CHECK = ROOT / "generalized_verifier_docs/validation/self_check.py"


def _manifest(tmp_path: Path, response_text: str | None = None) -> tuple[Path, str]:
    if response_text is None:
        response_text = (FIXTURES / "responses/complete.txt").read_text()
    payload = {
        "schema_version": 1,
        "task_id": "portable-arithmetic",
        "source": "pytest-hermetic-fixture",
        "candidate_files": ["arithmetic.cpp", "arithmetic.h"],
        "protected_files": {},
        "fixture_dir": str(FIXTURES / "arithmetic"),
        "policies": {f"G{number:02d}": [] for number in range(2, 8)},
        "response_text": response_text,
    }
    path = tmp_path / "manifest.json"
    data = (json.dumps(payload, indent=2) + "\n").encode()
    path.write_bytes(data)
    return path, hashlib.sha256(data).hexdigest()


def _run_runner(
    tmp_path: Path, candidate: Path, *, profile: str = "live"
) -> tuple[subprocess.CompletedProcess[str], dict]:
    manifest, digest = _manifest(tmp_path)
    output = tmp_path / "runner-output"
    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--candidate-dir",
            str(candidate),
            "--manifest",
            str(manifest),
            "--expected-manifest-sha256",
            digest,
            "--output-dir",
            str(output),
            "--reward-root",
            str(ROOT / "Reward_GRPO"),
            "--profile",
            profile,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    receipt = json.loads(
        (output / "global_cpp_verification_receipt.json").read_text()
    )
    return completed, receipt


def test_clean_checkout_self_check_is_hermetic(tmp_path: Path) -> None:
    json_out = tmp_path / "results.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(SELF_CHECK),
            "--receipt-dir",
            str(tmp_path / "receipts"),
            "--gen-dir",
            str(tmp_path / "generated"),
            "--report",
            str(tmp_path / "report.md"),
            "--json-out",
            str(json_out),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    results = json.loads(json_out.read_text())
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert results["all_ok"] is True
    assert len(results["cases"]) == 21
    assert all(case["ok"] for case in results["cases"])


def test_full_runner_executes_all_seven_policies(tmp_path: Path) -> None:
    completed, receipt = _run_runner(
        tmp_path, FIXTURES / "arithmetic", profile="full"
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert receipt["status"] == "pass"
    assert receipt["semantic_status"] == "pass"
    assert receipt["diagnostic_status"] == "pass"
    assert receipt["executed_policies"] == [
        "G01",
        "G02",
        "G03",
        "G04",
        "G05",
        "G06",
        "G07",
    ]
    assert receipt["candidate_source_unchanged"] is True
    assert all(item["status"] == "pass" for item in receipt["policy_results"])


def test_semantic_failure_is_model_fail_not_infrastructure_invalid(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    source = FIXTURES / "candidates/semantic-fail"
    shutil.copy2(source / "arithmetic.h", candidate / "arithmetic.h")
    shutil.copy2(source / "arithmetic.cpp", candidate / "arithmetic.cpp")
    completed, receipt = _run_runner(tmp_path, candidate)
    policies = {item["policy_id"]: item for item in receipt["policy_results"]}
    assert completed.returncode == 1
    assert receipt["status"] == "fail"
    assert receipt["semantic_status"] == "fail"
    assert policies["G03"]["status"] == "fail"
    assert receipt["candidate_source_unchanged"] is True


def test_manifest_validator_rejects_duplicates_and_unknown_policy() -> None:
    validator_path = PACK / "verifiers/_manifest_validation.py"
    spec = importlib.util.spec_from_file_location("manifest_validation", validator_path)
    assert spec is not None and spec.loader is not None
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    base = {
        "task_id": "portable-arithmetic",
        "candidate_files": ["arithmetic.h", "arithmetic.cpp"],
        "policies": {"G02": []},
    }
    duplicate = {**base, "candidate_files": ["arithmetic.h", "arithmetic.h"]}
    with pytest.raises(validator.ManifestValidationError, match="duplicates"):
        validator.validate_manifest(duplicate)
    unknown = {**base, "policies": {"G99": []}}
    with pytest.raises(validator.ManifestValidationError, match="unsupported"):
        validator.validate_manifest(unknown)


# --- verifier-v2: the reward adapter lives next to the pack and needs src/
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
from Reward_GRPO import generalized_cpp_grpo  # noqa: E402


def _policy(policy_id: str, values: list) -> dict:
    return {
        "policy_id": policy_id,
        "kernels": [
            {"kernel_id": f"{policy_id}-{index}", "kernel": value}
            for index, value in enumerate(values, start=1)
        ],
    }


def test_build_fail_candidate_g03_kernel_is_not_run(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    source = FIXTURES / "candidates/link-fail"
    shutil.copy2(source / "arithmetic.h", candidate / "arithmetic.h")
    shutil.copy2(source / "arithmetic.cpp", candidate / "arithmetic.cpp")
    completed, receipt = _run_runner(tmp_path, candidate)
    policies = {item["policy_id"]: item for item in receipt["policy_results"]}
    assert completed.returncode == 1
    assert receipt["status"] == "fail"  # via G02
    assert policies["G02"]["status"] == "fail"
    g03 = policies["G03"]
    assert "receipt_errors" not in g03
    kernels = {kernel["kernel_id"]: kernel for kernel in g03["kernels"]}
    assert kernels["G03-1"]["kernel"] == 1  # reference control unchanged
    candidate_kernel = kernels["G03-2"]
    assert candidate_kernel["kernel"] is None
    assert candidate_kernel["status"] == "not_run"
    assert candidate_kernel["facts"]["candidate"]["status"] == "BUILD_FAIL"
    assert candidate_kernel["facts"]["candidate"]["build"]["status"] == "LE"
    assert g03["kernel_sum"] == 1 and g03["kernel_total"] == 1


def test_receipt_to_reward_is_flat_kernel_mean() -> None:
    ce1 = {  # stage-1 compile failure, G03-2 deduplicated (not_run)
        "status": "fail",
        "policy_results": [
            _policy("G01", [1]), _policy("G02", [-1]), _policy("G03", [1, None]),
            _policy("G04", [1]), _policy("G05", [1]),
        ],
    }
    # flat mean over the five remaining +/-1 kernels: (1-1+1+1+1)/5
    assert generalized_cpp_grpo.receipt_to_reward(ce1)[0] == pytest.approx(0.6)
    ce2 = {  # stage-2 / link failure
        "status": "fail",
        "policy_results": [
            _policy("G01", [1]), _policy("G02", [1, -1]), _policy("G03", [1, None]),
            _policy("G04", [1]), _policy("G05", [1]),
        ],
    }
    assert generalized_cpp_grpo.receipt_to_reward(ce2)[0] == pytest.approx(4 / 6)
    semantic = {  # builds and runs, differential fails: G03-2 stays -1
        "status": "fail",
        "policy_results": [
            _policy("G01", [1]), _policy("G02", [1, 1]), _policy("G03", [1, -1]),
            _policy("G04", [1]), _policy("G05", [1]),
        ],
    }
    assert generalized_cpp_grpo.receipt_to_reward(semantic)[0] == pytest.approx(5 / 7)
    g01_fail = {  # API gate failure stays the harshest verifier outcome
        "status": "fail",
        "policy_results": [
            _policy("G01", [-1]), _policy("G02", []), _policy("G03", []),
            _policy("G04", []), _policy("G05", []),
        ],
    }
    assert generalized_cpp_grpo.receipt_to_reward(g01_fail)[0] == -1.0
    full_pass = {
        "status": "pass",
        "policy_results": [
            _policy("G01", [1]), _policy("G02", [1, 1]), _policy("G03", [1, 1]),
            _policy("G04", [1]), _policy("G05", [1]),
        ],
    }
    assert generalized_cpp_grpo.receipt_to_reward(full_pass)[0] == 1.0
    invalid = {"status": "invalid", "policy_results": []}
    assert generalized_cpp_grpo.receipt_to_reward(invalid) == (0.0, True, "verifier_invalid")


def test_parser_failures_are_routed_through_g04() -> None:
    truncated = (
        "Let me work through this.\narithmetic.cpp\n```cpp\n"
        "int add(int a, int b) { return a + b; }\n"  # fence never closed
    )
    record = generalized_cpp_grpo._model_failure(
        {"response": truncated, "response_length": 8192, "metadata": {}},
        "portable-arithmetic", "invalid_format", "no complete editable files",
    )
    assert record["score"] == record["reward"] == -0.8
    assert record["integrity_verdict"] == "TRUNCATED"
    assert record["integrity_facts"]["unclosed_fence"] is True

    loop = (FIXTURES / "responses/loop.txt").read_text()
    record = generalized_cpp_grpo._model_failure(
        {"response": loop, "response_length": 8192, "metadata": {}},
        "portable-arithmetic", "invalid_format", "no complete editable files",
    )
    assert record["score"] == record["reward"] == -1.0
    assert record["integrity_verdict"] == "LOOP"

    forbidden = generalized_cpp_grpo._model_failure(
        {"response": truncated, "metadata": {}},
        "portable-arithmetic", "forbidden_file", "non-editable file",
    )
    assert forbidden["score"] == -1.0
    assert "integrity_verdict" not in forbidden


def test_empty_response_is_empty_verdict_not_flat_penalty() -> None:
    for empty in ("", "   \n\t  "):
        record = generalized_cpp_grpo._model_failure(
            {"response": empty, "metadata": {}},
            "portable-arithmetic", "invalid_format", "no complete editable files",
        )
        assert record["score"] == record["reward"] == -1.0
        assert record["integrity_verdict"] == "EMPTY"
