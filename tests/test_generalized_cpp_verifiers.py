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
    work = tmp_path / "self-check"
    completed = subprocess.run(
        [sys.executable, str(SELF_CHECK), "--work-dir", str(work)],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "controls passed" in completed.stdout
    receipts = list((work / "receipts").glob("*/*_kernel_receipt.json"))
    assert len(receipts) == 16  # Fourteen original controls plus two ported regressions.
    assert all(json.loads(p.read_text())["verifier_source_sha256"] for p in receipts)


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


def test_structural_gate_does_not_treat_imported_types_as_namespaces() -> None:
    engine_path = ROOT / "generalized_verifier_docs/01_structural_api_gate.py"
    spec = importlib.util.spec_from_file_location("structural_api_gate", engine_path)
    assert spec is not None and spec.loader is not None
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)
    required = engine.required_symbols_from_test(
        """
        using cyclic_schedule::weekly_time;
        using Balance = factor_balance::balance;
        enum class local_result { good };
        void check() {
            weekly_time::at(1, 2, 3);
            (void) Balance::equal;
            (void) local_result::good;
            (void) factor_balance::proper_factor_sum(6);
        }
        """
    )
    symbols = {item.key() for item in required}
    assert symbols == {
        ("cyclic_schedule", "weekly_time"),
        ("factor_balance", "balance"),
        ("factor_balance", "proper_factor_sum"),
    }


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


def test_receipt_to_reward_is_candidate_owned_and_correctness_weighted() -> None:
    ce1 = {  # stage-1 compile failure, G03-2 deduplicated (not_run)
        "status": "fail",
        "policy_results": [
            _policy("G01", [1]), _policy("G02", [-1]), _policy("G03", [1, None]),
            _policy("G04", [1]), _policy("G05", [1]),
        ],
    }
    assert generalized_cpp_grpo.receipt_to_reward(ce1)[0] == pytest.approx(-0.85)
    ce2 = {  # stage-2 / link failure
        "status": "fail",
        "policy_results": [
            _policy("G01", [1]), _policy("G02", [1, -1]), _policy("G03", [1, None]),
            _policy("G04", [1]), _policy("G05", [1]),
        ],
    }
    assert generalized_cpp_grpo.receipt_to_reward(ce2)[0] == pytest.approx(-0.65)
    semantic = {  # builds and runs, differential fails: G03-2 stays -1
        "status": "fail",
        "policy_results": [
            _policy("G01", [1]), _policy("G02", [1, 1]), _policy("G03", [1, -1]),
            _policy("G04", [1]), _policy("G05", [1]),
        ],
    }
    assert generalized_cpp_grpo.receipt_to_reward(semantic)[0] == pytest.approx(-0.45)
    reference_control_fail = {
        **semantic,
        "policy_results": [
            _policy("G01", [1]), _policy("G02", [1, 1]), _policy("G03", [-1, -1]),
            _policy("G04", [1]), _policy("G05", [1]),
        ],
    }
    assert generalized_cpp_grpo.receipt_to_reward(reference_control_fail)[0] == pytest.approx(
        -0.45
    )
    no_format_or_boundary_credit = {
        **semantic,
        "policy_results": [
            _policy("G01", [1]), _policy("G02", [1, 1]), _policy("G03", [1, -1]),
            _policy("G04", [-1]), _policy("G05", [-1]),
        ],
    }
    assert generalized_cpp_grpo.receipt_to_reward(no_format_or_boundary_credit)[
        0
    ] == pytest.approx(-0.5)
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
    # Aggregate labels alone never authenticate success.
    assert generalized_cpp_grpo.receipt_to_reward(full_pass)[1] is True
    run = {"verified_pass": True, "execution_completed": True,
           "returncode": 0, "harness_returncode": 0, "crashed": False,
           "timed_out": False, "infrastructure_error": False}
    for policy in full_pass["policy_results"]:
        policy["status"] = "pass"
        for kernel in policy["kernels"]:
            kernel["status"] = "pass"
    full_pass["policy_results"][2]["kernels"][1]["facts"] = {
        "engine_exit_code": 0,
        "reference": {"status": "OK", "run": dict(run)},
        "candidate": {"status": "RAN", "run": dict(run)},
    }
    assert generalized_cpp_grpo.receipt_to_reward(full_pass)[0] == 1.0
    all_candidate_gates_pass_but_status_fails = {**full_pass, "status": "fail"}
    assert generalized_cpp_grpo.receipt_to_reward(
        all_candidate_gates_pass_but_status_fails
    )[0] == pytest.approx(0.0)
    invalid = {"status": "invalid", "policy_results": []}
    assert generalized_cpp_grpo.receipt_to_reward(invalid) == (0.0, True, "verifier_invalid")


def _semantic_receipt(passed: int, total: int, reported: object | None = None) -> dict:
    score = passed / total if reported is None else reported
    return {
        "status": "fail",
        "policy_results": [
            _policy("G01", [1]),
            _policy("G02", [1, 1]),
            {
                "policy_id": "G03",
                "kernels": [
                    {"kernel_id": "G03-1", "kernel": 1, "status": "pass", "facts": {}},
                    {
                        "kernel_id": "G03-2",
                        "kernel": -1,
                        "status": "fail",
                        "facts": {
                            "reference": {"status": "OK"},
                            "candidate": {
                                "status": "RAN",
                                "run": {
                                    "passed_assertions": passed,
                                    "total_assertions": total,
                                    "score": score,
                                    "crashed": False,
                                    "execution_completed": True,
                                    "infrastructure_error": False,
                                    "timed_out": False,
                                },
                            },
                        },
                    },
                ],
            },
            _policy("G04", [1]),
            _policy("G05", [1]),
        ],
    }


def test_semantic_fraction_is_validated_monotonic_and_failure_bounded() -> None:
    zero = _semantic_receipt(0, 69)
    middle = _semantic_receipt(34, 69)
    near = _semantic_receipt(68, 69)

    rewards = [
        generalized_cpp_grpo.receipt_to_reward(receipt)[0]
        for receipt in (zero, middle, near)
    ]
    assert rewards[0] == pytest.approx(-0.45)
    assert rewards == sorted(rewards)
    assert rewards[-1] == pytest.approx(-0.45 + 0.45 * (68 / 69))
    assert all(-1.0 <= reward <= 0.0 for reward in rewards)
    assert rewards[-1] > generalized_cpp_grpo.receipt_to_reward(
        {
            "status": "fail",
            "policy_results": [
                _policy("G01", [1]), _policy("G02", [1, -1]),
                _policy("G03", [1, None]), _policy("G04", [1]),
                _policy("G05", [1]),
            ],
        }
    )[0]


@pytest.mark.parametrize("reported", [1.0, float("nan"), True])
def test_malformed_semantic_fraction_cannot_create_reward(reported: object) -> None:
    receipt = _semantic_receipt(68, 69, reported)
    assert generalized_cpp_grpo._candidate_semantic_fraction(receipt) is None
    assert generalized_cpp_grpo.receipt_to_reward(receipt)[0] == pytest.approx(-0.45)


def test_semantic_fraction_requires_ran_candidate_and_healthy_reference() -> None:
    for field, value in (("reference", "TASK_PACKAGE_BROKEN"), ("candidate", "BUILD_FAIL")):
        receipt = _semantic_receipt(68, 69)
        facts = receipt["policy_results"][2]["kernels"][1]["facts"]
        facts[field]["status"] = value
        assert generalized_cpp_grpo._candidate_semantic_fraction(receipt) is None
        assert generalized_cpp_grpo.receipt_to_reward(receipt)[0] == pytest.approx(-0.45)


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


def test_shared_parser_keeps_strict_boundary_default() -> None:
    parser = generalized_cpp_grpo.parse_whole_file_response
    valid = "answer.cpp\n```cpp\nint answer() { return 42; }\n```\n"
    forbidden = "CMakeLists.txt\n```cmake\nproject(no)\n```\n" + valid
    duplicate = valid + valid

    with pytest.raises(generalized_cpp_grpo.AiderResponseError) as caught:
        parser(forbidden, ["answer.cpp"])
    assert caught.value.reason == "forbidden_file"
    with pytest.raises(generalized_cpp_grpo.AiderResponseError) as caught:
        parser(duplicate, ["answer.cpp"])
    assert caught.value.reason == "duplicate_file"

    recovered = parser(
        forbidden, ["answer.cpp"], recover_boundary_errors=True
    )
    assert recovered.files == {"answer.cpp": "int answer() { return 42; }\n"}
    assert recovered.format_valid is False
