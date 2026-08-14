from __future__ import annotations

import copy
import math
from pathlib import Path

import pytest

import glm47_posttraining.aider_polyglot.harness as harness_module
import glm47_posttraining.integrations.miles_aider_polyglot as integration_module
from glm47_posttraining.aider_polyglot.dataset import (
    _refuse_cross_policy_overwrite,
    _reward_contract_record,
    build_hybrid45_messages,
)
from glm47_posttraining.aider_polyglot.harness import run_shadow_hybrid45_tests
from glm47_posttraining.aider_polyglot.hybrid45 import (
    HYBRID45_TIER_WEIGHTS,
    build_repair_telemetry,
    derive_hybrid45_observation,
    evaluate_hybrid45_response_checks,
    score_hybrid45,
    validate_hybrid45_receipt,
)
from glm47_posttraining.aider_polyglot.parser import parse_whole_file_response
from glm47_posttraining.aider_polyglot.reward import compute_hybrid45_aider_reward
from glm47_posttraining.aider_polyglot.schema import (
    AiderPolyglotTask,
    AiderTestResult,
    HYBRID45_POLICY_VERSION,
    HYBRID45_STAGE_SCORES,
    WEIGHTED45_CHECK_IDS,
    WEIGHTED45_HARNESS_CHECK_IDS,
    WEIGHTED45_TIER_CHECKS,
)


def _task() -> AiderPolyglotTask:
    return AiderPolyglotTask(
        task_id="aider-shadow-cpp/example",
        exercise="example",
        split="train",
        harness_kind="shadow_cpp17",
        exercise_dir="shadow/example",
        editable_files=["example.h", "example.cpp"],
        prompt=[{"role": "user", "content": "implement answer"}],
        hidden_test_sha256="a" * 64,
        reward_contract=HYBRID45_POLICY_VERSION,
    )


def _response(*, value: int = 42, include_header: bool = True) -> str:
    header = "example.h\n\u0060\u0060\u0060cpp\n#pragma once\nint answer();\n\u0060\u0060\u0060\n"
    source = (
        "example.cpp\n\u0060\u0060\u0060cpp\n#include \"example.h\"\n"
        f"int answer() {{ return {value}; }}\n\u0060\u0060\u0060\n"
    )
    return (header if include_header else "") + source


def _maps(
    *,
    check_default: bool = False,
    observed_default: bool = True,
) -> tuple[dict[str, bool], dict[str, str], dict[str, bool], dict[str, bool]]:
    checks = {check_id: check_default for check_id in WEIGHTED45_CHECK_IDS}
    evidence = {check_id: "unit evidence" for check_id in WEIGHTED45_CHECK_IDS}
    observed = {check_id: observed_default for check_id in WEIGHTED45_CHECK_IDS}
    applicable = {check_id: True for check_id in WEIGHTED45_CHECK_IDS}
    return checks, evidence, observed, applicable


def _set(
    checks: dict[str, bool],
    observed: dict[str, bool],
    ids: tuple[str, ...] | list[str],
    value: bool,
    *,
    is_observed: bool = True,
) -> None:
    for check_id in ids:
        checks[check_id] = value
        observed[check_id] = is_observed


def _all_harness_pass() -> AiderTestResult:
    checks = {check_id: True for check_id in WEIGHTED45_HARNESS_CHECK_IDS}
    return AiderTestResult(
        status="passed",
        tests_passed=5,
        tests_total=5,
        candidate_returncode=0,
        weighted45_checks=checks,
        weighted45_evidence={check_id: "unit pass" for check_id in checks},
    )


def test_hybrid45_identity_weights_and_endpoints_are_exact() -> None:
    assert HYBRID45_POLICY_VERSION == "hybrid-bipolar45-v2"
    assert math.fsum(HYBRID45_TIER_WEIGHTS.values()) == pytest.approx(1.0)

    failed = score_hybrid45(*_maps(check_default=False))
    passed = score_hybrid45(*_maps(check_default=True))

    assert failed.binary_score == -1.0
    assert failed.optimizer_score == -1.0
    assert passed.binary_score == 1.0
    assert passed.reachability_stage == 8
    assert passed.optimizer_score == 1.0


@pytest.mark.parametrize(
    ("passed_count", "expected"),
    [(0, -1.0), (1, -0.6), (2, -0.2), (3, 0.2), (4, 0.6), (5, 1.0)],
)
def test_hybrid45_tier_uses_literal_bipolar_mean(
    passed_count: int, expected: float
) -> None:
    checks, evidence, observed, applicable = _maps(observed_default=False)
    tier = "compilation"
    tier_ids = WEIGHTED45_TIER_CHECKS[tier]
    _set(checks, observed, list(tier_ids), False)
    _set(checks, observed, list(tier_ids[:passed_count]), True)

    receipt = score_hybrid45(checks, evidence, observed, applicable)

    assert receipt.tier_observed_applicable_counts[tier] == 5
    assert receipt.tier_binary_scores[tier] == pytest.approx(expected)
    assert receipt.weighted_binary_contributions[tier] == pytest.approx(
        expected * HYBRID45_TIER_WEIGHTS[tier]
    )


def test_hybrid45_excludes_unobserved_and_non_applicable_kernels() -> None:
    checks, evidence, observed, applicable = _maps(check_default=True)
    for check_id in ("K1", "K5", "R1", "H1"):
        checks[check_id] = False
        observed[check_id] = False
        evidence[check_id] = "stage not reached"
    applicable["A4"] = False
    evidence["A4"] = "not applicable: no threading primitive"

    receipt = score_hybrid45(checks, evidence, observed, applicable)

    assert receipt.kernels["K1"] == -1
    assert receipt.observed["K1"] is False
    assert receipt.tier_observed_applicable_counts["compilation"] == 3
    assert receipt.tier_binary_scores["compilation"] == 1.0
    assert receipt.tier_observed_applicable_counts["full_pass"] == 4
    assert receipt.tier_binary_scores["full_pass"] == 1.0
    assert "K1" in receipt.not_reached_kernels


def test_hybrid45_noop_detection_is_v2_only(tmp_path: Path) -> None:
    (tmp_path / "example.h").write_text("#pragma once\nint answer();\n", encoding="utf-8")
    (tmp_path / "example.cpp").write_text(
        '#include "example.h"\nint answer() { return 42; }\n', encoding="utf-8"
    )
    response = _response()
    parsed = parse_whole_file_response(response, _task().editable_files)

    checks, evidence = evaluate_hybrid45_response_checks(
        _task(),
        tmp_path,
        response,
        parsed=parsed,
        parse_error=None,
    )

    assert checks["C2"] is True
    assert checks["C3"] is False
    assert evidence["C3"] == "no substantive production delta from starter"


def test_hybrid45_requires_complete_file_replacements_and_skips_runner(
    tmp_path: Path,
) -> None:
    called = False

    def runner(_path: Path, _files: dict[str, str]) -> AiderTestResult:
        nonlocal called
        called = True
        return _all_harness_pass()

    result = compute_hybrid45_aider_reward(
        _task(),
        tmp_path,
        _response(include_header=False),
        runner=runner,
    )

    assert called is False
    assert result.hybrid45 is not None
    assert result.hybrid45.checks["C2"] is False
    assert result.hybrid45.optimizer_score is not None
    assert result.hybrid45.optimizer_score <= -0.75
    assert result.hybrid45.optimizer_override == "no_usable_payload"


@pytest.mark.parametrize(
    ("hidden_passes", "expected"),
    [(0, -1.0), (1, -0.6), (2, -0.2), (3, 0.2), (4, 0.6), (5, 1.0)],
)
def test_hybrid45_continuous_semantics_matches_hidden_partitions(
    hidden_passes: int, expected: float
) -> None:
    checks, evidence, observed, applicable = _maps(check_default=True)
    for index, check_id in enumerate(("H1", "H2", "H3", "H4", "H5")):
        checks[check_id] = index < hidden_passes

    receipt = score_hybrid45(checks, evidence, observed, applicable)

    assert receipt.semantic_applicable is True
    assert receipt.hidden_partitions_passed == hidden_passes
    assert receipt.continuous_semantic_score == pytest.approx(expected)


def test_hybrid45_unreached_hidden_semantics_is_neutral_not_negative() -> None:
    checks, evidence, observed, applicable = _maps(check_default=True)
    for check_id in ("H1", "H2", "H3", "H4", "H5"):
        checks[check_id] = False
        observed[check_id] = False
        evidence[check_id] = "stage not reached"

    receipt = score_hybrid45(checks, evidence, observed, applicable)

    assert receipt.semantic_applicable is False
    assert receipt.continuous_semantic_score == 0.0
    assert receipt.tier_binary_scores["hidden_tests"] == 0.0


def test_hybrid45_compile_and_sanitizer_caps() -> None:
    compile_maps = _maps(check_default=True)
    compile_maps[0]["K2"] = False
    compile_receipt = score_hybrid45(*compile_maps)
    assert compile_receipt.optimizer_score is not None
    assert compile_receipt.optimizer_score <= 0.0
    assert compile_receipt.optimizer_override == "compile_or_link"

    sanitizer_maps = _maps(check_default=True)
    sanitizer_maps[0]["A2"] = False
    sanitizer_receipt = score_hybrid45(*sanitizer_maps)
    assert sanitizer_receipt.optimizer_score is not None
    assert sanitizer_receipt.optimizer_score <= -0.5
    assert sanitizer_receipt.optimizer_override == "runtime_or_sanitizer"


def test_hybrid45_primary_compiler_cause_and_consequences_are_ordered() -> None:
    checks, evidence, observed, applicable = _maps(check_default=True)
    checks.update({"K2": False, "K4": False, "K1": False, "K5": False})
    receipt = score_hybrid45(
        checks,
        evidence,
        observed,
        applicable,
        failure_mechanism="public_api_signature_mismatch",
    )

    assert receipt.primary_failure_kernel == "K2"
    assert receipt.failure_stage == "compilation"
    assert receipt.failure_mechanism == "public_api_signature_mismatch"
    assert receipt.consequence_kernels == ["K4", "K1", "K5"]


def test_hybrid45_reachability_stage_values_cover_declared_table() -> None:
    receipts = []

    stage0 = _maps(check_default=True)
    stage0[0]["C1"] = False
    receipts.append(score_hybrid45(*stage0))

    stage1 = _maps(check_default=True)
    for check_id in WEIGHTED45_HARNESS_CHECK_IDS:
        stage1[0][check_id] = False
        stage1[2][check_id] = False
        stage1[1][check_id] = "stage not reached"
    receipts.append(score_hybrid45(*stage1))

    stage2 = _maps(check_default=True)
    stage2[0]["K3"] = False
    stage2[0]["K4"] = False
    receipts.append(score_hybrid45(*stage2))

    stage3 = _maps(check_default=True)
    stage3[0]["K1"] = False
    stage3[0]["K5"] = False
    receipts.append(score_hybrid45(*stage3))

    stage4 = _maps(check_default=True)
    stage4[0]["R2"] = False
    receipts.append(score_hybrid45(*stage4))

    stage5 = _maps(check_default=True)
    for check_id in ("H1", "H2", "H3", "H4", "H5"):
        stage5[0][check_id] = False
    receipts.append(score_hybrid45(*stage5))

    stage6 = copy.deepcopy(stage5)
    stage6[0]["H1"] = True
    receipts.append(score_hybrid45(*stage6))

    stage7 = _maps(check_default=True)
    stage7[0]["A5"] = False
    receipts.append(score_hybrid45(*stage7))

    receipts.append(score_hybrid45(*_maps(check_default=True)))

    assert [receipt.reachability_stage for receipt in receipts] == list(range(9))
    assert [receipt.discrete_score for receipt in receipts] == [
        HYBRID45_STAGE_SCORES[index] for index in range(9)
    ]


def test_hybrid45_receipt_validation_rejects_arithmetic_tampering() -> None:
    receipt = score_hybrid45(*_maps(check_default=True))
    record = receipt.to_record()
    validate_hybrid45_receipt(record)

    record["binary_score"] = 0.9
    with pytest.raises(ValueError, match="deterministic recomputation"):
        validate_hybrid45_receipt(record)


@pytest.mark.parametrize("bad_kernel", [0, 0.5, True, "-1"])
def test_hybrid45_receipt_rejects_non_bipolar_integer_kernels(
    bad_kernel: object,
) -> None:
    record = score_hybrid45(*_maps(check_default=True)).to_record()
    record["kernels"]["A5"] = bad_kernel
    with pytest.raises(ValueError, match="kernels"):
        validate_hybrid45_receipt(record)


def test_hybrid45_receipt_rejects_missing_exact_entry() -> None:
    record = score_hybrid45(*_maps(check_default=True)).to_record()
    record["observed"].pop("A5")
    with pytest.raises(ValueError, match="observed contract mismatch"):
        validate_hybrid45_receipt(record)


def test_hybrid45_repair_telemetry_has_no_bonus() -> None:
    previous_maps = _maps(check_default=True)
    previous_maps[0]["K2"] = False
    previous = score_hybrid45(*previous_maps)
    current = score_hybrid45(*_maps(check_default=True))

    repair = build_repair_telemetry(previous, current)

    assert repair.optimizer_score == current.optimizer_score
    assert repair.reward_delta == pytest.approx(
        current.optimizer_score - previous.optimizer_score
    )
    assert "K2:-1->+1" in repair.kernel_flips


def test_hybrid45_infrastructure_failure_has_no_receipt_or_numeric_reward(
    tmp_path: Path,
) -> None:
    task = _task().model_copy(update={"reward_contract": "weighted45-v1"})
    result = compute_hybrid45_aider_reward(task, tmp_path, _response())

    assert result.infrastructure_error is True
    assert result.hybrid45 is None
    with pytest.raises(
        integration_module.AiderRewardInfrastructureError,
        match="infrastructure failure",
    ):
        integration_module.reward_record(
            type("Sample", (), {"response": _response()})(),
            task,
            result,
        )


def test_hybrid45_harness_redefines_a5_as_repeatability_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checks = {check_id: True for check_id in WEIGHTED45_HARNESS_CHECK_IDS}
    checks["A5"] = False
    evidence = {check_id: "unit pass" for check_id in checks}
    evidence["A5"] = "deterministic repeat changed hidden partition vector"
    repeated = AiderTestResult(
        status="tests_failed",
        tests_passed=5,
        tests_total=5,
        weighted45_checks=checks,
        weighted45_evidence=evidence,
    )
    calls: list[dict[str, object]] = []

    def fake(*_args, **kwargs):
        calls.append(kwargs)
        return repeated

    monkeypatch.setattr(
        harness_module,
        "run_shadow_weighted45_tests",
        fake,
    )

    result = run_shadow_hybrid45_tests(Path("."), {})

    assert result.weighted45_checks["A5"] is False
    assert result.status == "tests_failed"
    assert "deterministic repeat changed" in result.weighted45_evidence["A5"]
    assert len(calls) == 1
    assert calls[0]["determinism_repeat"] is True


def test_hybrid45_miles_record_and_optimizer_gate_require_exact_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "example.h").write_text("#pragma once\nint answer();\n", encoding="utf-8")
    (tmp_path / "example.cpp").write_text(
        '#include "example.h"\nint answer() { return 0; }\n', encoding="utf-8"
    )
    breakdown = compute_hybrid45_aider_reward(
        _task(),
        tmp_path,
        _response(),
        runner=lambda _path, _files: _all_harness_pass(),
    )
    monkeypatch.setenv("MILES_AIDER_REWARD_MODE", "hybrid_bipolar45")
    sample = type(
        "Sample",
        (),
        {"index": 0, "rollout_id": 0, "response": _response()},
    )()
    record = integration_module.reward_record(sample, _task(), breakdown)

    assert record["policy_version"] == HYBRID45_POLICY_VERSION
    assert set(record["hybrid45"]["kernels"]) == WEIGHTED45_CHECK_IDS
    monkeypatch.setenv("GLM47_AIDER_EXPECTED_TRAIN_GROUPS", "1")
    monkeypatch.setenv("GLM47_AIDER_EXPECTED_SAMPLES_PER_GROUP", "1")
    args = type("Args", (), {"rollout_batch_size": 1, "n_samples_per_prompt": 1})()
    rollout = type("Rollout", (), {"reward": record, "response": _response()})()
    integration_module.validate_aider_rollout_batch(args, [[rollout]])

    malformed = copy.deepcopy(record)
    malformed["hybrid45"]["kernels"].pop("A5")
    bad_rollout = type("Rollout", (), {"reward": malformed, "response": "bad"})()
    with pytest.raises(
        integration_module.AiderRewardInfrastructureError,
        match="invalid hybrid-bipolar45-v2 receipt",
    ):
        integration_module.validate_aider_rollout_batch(args, [[bad_rollout]])


def test_hybrid45_full_v5_aider_cpp17_uses_partitioned_v2_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exercise = tmp_path / "runtime" / "probe"
    exercise.mkdir(parents=True)
    (exercise / "example.h").write_text(
        "#pragma once\nint answer();\n", encoding="utf-8"
    )
    (exercise / "example.cpp").write_text(
        '#include "example.h"\nint answer() { return 0; }\n', encoding="utf-8"
    )
    task = _task().model_copy(
        update={
            "harness_kind": "aider_cpp17",
            "exercise_dir": "runtime/probe",
            "reward_contract": HYBRID45_POLICY_VERSION,
            "prompt_contract": "hybrid45-isolated-wholefile-v2",
        }
    )
    descriptor = task.write_json(tmp_path / "task.json")
    calls: list[dict[str, object]] = []

    def fake_runner(_path: Path, _files: dict[str, str], **kwargs) -> AiderTestResult:
        calls.append(kwargs)
        return _all_harness_pass()

    monkeypatch.setattr(integration_module, "run_shadow_hybrid45_tests", fake_runner)
    monkeypatch.setenv("MILES_AIDER_REWARD_MODE", "hybrid_bipolar45")
    record = integration_module._score_sample(
        {
            "metadata": {"task_path": str(descriptor), "task_id": task.task_id},
            "response": _response(),
        }
    )

    assert len(calls) == 1
    assert calls[0]["expected_test_sha256"] == task.hidden_test_sha256
    assert record["reward_mode"] == "hybrid_bipolar45"
    assert record["policy_version"] == HYBRID45_POLICY_VERSION


def test_hybrid45_official_cmake_fails_closed_before_scoring(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "runtime" / "official").mkdir(parents=True)
    task = _task().model_copy(
        update={
            "harness_kind": "official_cmake",
            "exercise_dir": "runtime/official",
            "reward_contract": HYBRID45_POLICY_VERSION,
            "prompt_contract": "hybrid45-isolated-wholefile-v2",
        }
    )
    descriptor = task.write_json(tmp_path / "official.json")
    monkeypatch.setenv("MILES_AIDER_REWARD_MODE", "hybrid_bipolar45")

    with pytest.raises(
        integration_module.AiderRewardInfrastructureError,
        match="five independently executable hidden partitions",
    ):
        integration_module._score_sample(
            {
                "metadata": {"task_path": str(descriptor), "task_id": task.task_id},
                "response": _response(),
            }
        )


def test_hybrid45_no_update_canary_writes_endpoint_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_runner(
        _path: Path,
        files: dict[str, str],
        **_kwargs,
    ) -> AiderTestResult:
        if "int answer( {" not in files["answer.cpp"]:
            return _all_harness_pass()
        checks = {check_id: False for check_id in WEIGHTED45_HARNESS_CHECK_IDS}
        evidence = {check_id: "stage not reached" for check_id in checks}
        evidence["K3"] = "candidate -fsyntax-only returncode=1"
        checks["K2"] = True
        evidence["K2"] = "hidden API/type-check returncode=0"
        evidence["K4"] = "strict warning flags rejected a candidate translation unit"
        return AiderTestResult(
            status="compile_failed",
            tests_total=5,
            candidate_returncode=1,
            weighted45_checks=checks,
            weighted45_evidence=evidence,
        )

    output = tmp_path / "no-update.json"
    monkeypatch.setattr(integration_module, "run_shadow_hybrid45_tests", fake_runner)
    monkeypatch.setenv(
        integration_module.HYBRID45_NO_UPDATE_RECEIPT_ENV,
        str(output),
    )

    receipt = integration_module.run_hybrid45_no_update_canary(image="sha256:unit")

    assert receipt["decision"] == "PASS"
    assert receipt["optimizer_updates"] == 0
    assert receipt["controls"]["reference"]["optimizer_score"] == 1.0
    assert receipt["controls"]["compile_failure"]["optimizer_score"] <= 0.0
    assert receipt["controls"]["safety_bypass"]["optimizer_score"] == -1.0
    assert output.is_file()


def test_dataset_reward_contracts_preserve_v1_and_version_v2() -> None:
    assert _reward_contract_record("weighted45-v1") == {
        "checks_per_tier": 5,
        "hidden_suite_partitions": 5,
        "normalization_weight": 6.54,
        "policy": "weighted45-v1",
        "raw_tier_formula": "0.3*N_passed-0.5",
        "tiers": 9,
        "total_checks": 45,
    }
    v2 = _reward_contract_record(HYBRID45_POLICY_VERSION)
    assert v2["policy"] == HYBRID45_POLICY_VERSION
    assert v2["activation_status"] == "NOT_ADMITTED"
    assert v2["projection"] == {
        "binary": 0.5,
        "discrete": 0.2,
        "continuous_semantic": 0.3,
    }


def test_dataset_refuses_cross_policy_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "prepared-v1"
    output.mkdir()
    (output / "manifest.json").write_text(
        '{"reward_contract":{"policy":"weighted45-v1"}}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="different reward policy"):
        _refuse_cross_policy_overwrite(output, HYBRID45_POLICY_VERSION)


def test_hybrid45_prompt_is_two_message_task_local_and_rubric_free(
    tmp_path: Path,
) -> None:
    (tmp_path / ".docs").mkdir()
    (tmp_path / ".docs" / "instructions.md").write_text(
        "Implement the public answer API.", encoding="utf-8"
    )
    (tmp_path / "example.h").write_text("#pragma once\nint answer();\n", encoding="utf-8")
    (tmp_path / "example.cpp").write_text(
        '#include "example.h"\nint answer() { return 0; }\n', encoding="utf-8"
    )

    messages = build_hybrid45_messages(
        tmp_path, ["example.h", "example.cpp"]
    )
    combined = "\n".join(message["content"] for message in messages).lower()

    assert [message["role"] for message in messages] == ["system", "user"]
    assert combined.count("you are solving one isolated") == 1
    assert "complete replacements for every declared editable file" in combined
    assert "weighted45" not in combined
    assert "hybrid45" not in combined
    assert "kernel" not in combined
    assert "reward" not in combined
    assert "verifier" not in combined


def test_hybrid45_observation_marks_not_reached_and_a4_applicability() -> None:
    checks, evidence, _observed, _applicable = _maps(check_default=False)
    evidence["K1"] = "stage not reached"
    checks["A4"] = True
    evidence["A4"] = "not applicable: no threading primitive"

    observed, applicable, compact = derive_hybrid45_observation(checks, evidence)

    assert observed["K1"] is False
    assert applicable["A4"] is False
    assert compact["A4"].startswith("not applicable:")
