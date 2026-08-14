from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess

import pytest
from pydantic import ValidationError

import glm47_posttraining.aider_polyglot.harness as harness_module
import glm47_posttraining.integrations.miles_aider_polyglot as integration_module
from glm47_posttraining.aider_polyglot.harness import (
    _instrument_weighted45_grader,
    run_shadow_weighted45_tests,
)
from glm47_posttraining.aider_polyglot.policy45 import (
    WEIGHTED45_TOTAL_WEIGHT,
    score_weighted45,
)
from glm47_posttraining.aider_polyglot.reward import compute_weighted45_aider_reward
from glm47_posttraining.aider_polyglot.schema import (
    AiderPolyglotTask,
    AiderTestResult,
    WEIGHTED45_CHECK_IDS,
    WEIGHTED45_HARNESS_CHECK_IDS,
)


def _task() -> AiderPolyglotTask:
    return AiderPolyglotTask(
        task_id="aider-shadow-cpp/example",
        exercise="example",
        split="train",
        harness_kind="shadow_cpp17",
        exercise_dir="shadow/example",
        editable_files=["example.cpp", "example.h"],
        prompt=[{"role": "user", "content": "implement answer"}],
        hidden_test_sha256="a" * 64,
    )


def _complete_response() -> str:
    return (
        "example.h\n```cpp\n#pragma once\nint answer();\n```\n"
        'example.cpp\n```cpp\n#include "example.h"\nint answer() { return 42; }\n```\n'
    )


def test_weighted45_formula_endpoints_and_total_weight() -> None:
    all_failed = score_weighted45({check_id: False for check_id in WEIGHTED45_CHECK_IDS})
    all_passed = score_weighted45({check_id: True for check_id in WEIGHTED45_CHECK_IDS})

    assert all_failed.normalized_reward == -0.5
    assert all_failed.normalized_percentage == -50.0
    assert all_passed.normalized_reward == 1.0
    assert all_passed.normalized_percentage == 100.0
    assert all_passed.total_weight == WEIGHTED45_TOTAL_WEIGHT == 6.54
    assert set(all_passed.tier_pass_counts.values()) == {5}


def test_weighted45_formula_uses_exact_linear_milestones() -> None:
    checks = {check_id: False for check_id in WEIGHTED45_CHECK_IDS}
    checks.update({f"F{index}": True for index in range(1, 4)})
    score = score_weighted45(checks)

    assert score.tier_pass_counts["forbidden_file_bypass"] == 3
    assert score.raw_tier_rewards["forbidden_file_bypass"] == pytest.approx(0.4)
    assert score.weighted_tier_rewards["forbidden_file_bypass"] == pytest.approx(0.4)


def test_weighted45_schema_rejects_partial_harness_receipt() -> None:
    with pytest.raises(ValidationError, match="contract mismatch"):
        AiderTestResult(
            status="tests_failed",
            weighted45_checks={"H1": True},
        )


@pytest.mark.parametrize(
    "message",
    [
        "LeakSanitizer does not work under ptrace",
        "FATAL: ThreadSanitizer: unexpected memory mapping 0x123-0x456",
    ],
)
def test_weighted45_sanitizer_platform_failures_are_infrastructure(message: str) -> None:
    assert harness_module._is_infrastructure_error(message)


@pytest.mark.parametrize(
    "grader",
    [
        """
        int main() {
          if (one()) return 1;
          if (two() || three()) return 2;
          if (four()) return 3;
          if (five()) return 4;
          return 0;
        }
        """,
        """
        #include <cassert>
        int main() {
          assert(one()); assert(two()); assert(three());
          assert(four()); assert(five());
          return 0;
        }
        """,
        """
        #define CHECK(...) do { if (!(__VA_ARGS__)) return __LINE__; } while (false)
        int main() {
          CHECK(one()); CHECK(two()); CHECK(three()); CHECK(four()); CHECK(five());
          return 0;
        }
        """,
    ],
)
def test_weighted45_instruments_every_supported_hidden_grader_idiom(grader: str) -> None:
    instrumented, count = _instrument_weighted45_grader(grader)

    assert count >= 5
    assert "GLM47_AIDER_SUITE" in instrumented
    assert "glm47_weighted45_detail::failed" in instrumented


def test_weighted45_hidden_harness_returns_all_twenty_observed_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exercise = tmp_path / "example"
    (exercise / ".grader").mkdir(parents=True)
    (exercise / "example.h").write_text("#pragma once\nint answer();\n", encoding="utf-8")
    (exercise / "example.cpp").write_text(
        '#include "example.h"\nint answer(){return 0;}\n', encoding="utf-8"
    )
    hidden = (
        '#include "example.h"\n'
        "int main(){\n"
        " if(answer()!=42) return 1;\n"
        " if(answer()<0) return 2;\n"
        " if(answer()>100) return 3;\n"
        " if(answer()%2!=0) return 4;\n"
        " if(answer()!=answer()) return 5;\n"
        " return 0;\n}\n"
    )
    grader_path = exercise / ".grader" / "test.cpp"
    grader_path.write_text(hidden, encoding="utf-8")
    grader_path.chmod(0o400)
    marker = "GLM47_AIDER_WEIGHTED45_fixed"
    monkeypatch.setattr(harness_module.secrets, "token_hex", lambda _size: "fixed")

    def fake_stage(
        _scratch: Path, script: str, *, image: str, timeout_s: int
    ) -> subprocess.CompletedProcess[str]:
        del image, timeout_s
        output = f"{marker}:0\n" if "GLM47_AIDER_SUITE=" in script else ""
        return subprocess.CompletedProcess(["fake"], 0, stdout=output, stderr="")

    monkeypatch.setattr(harness_module, "_run_stage", fake_stage)
    result = run_shadow_weighted45_tests(
        exercise,
        {
            "example.h": "#pragma once\nint answer();\n",
            "example.cpp": '#include "example.h"\nint answer(){return 42;}\n',
        },
        expected_test_sha256=hashlib.sha256(hidden.encode()).hexdigest(),
    )

    assert result.status == "passed"
    assert (result.tests_passed, result.tests_total) == (5, 5)
    assert set(result.weighted45_checks) == WEIGHTED45_HARNESS_CHECK_IDS
    assert all(result.weighted45_checks.values())
    assert set(result.weighted45_evidence) == WEIGHTED45_HARNESS_CHECK_IDS
    assert grader_path.stat().st_mode & 0o777 == 0o400


def test_weighted45_k2_requires_bound_public_api_ast_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exercise = tmp_path / "api-bound"
    (exercise / ".grader").mkdir(parents=True)
    source = "namespace charm::api_bound { int answer(){return 42;} }\n"
    (exercise / "answer.cpp").write_text(source, encoding="utf-8")
    hidden = (
        '#include "answer.cpp"\n'
        "int main(){\n"
        " if(charm::api_bound::answer()!=42) return 1;\n"
        " if(charm::api_bound::answer()<0) return 2;\n"
        " if(charm::api_bound::answer()>100) return 3;\n"
        " if(charm::api_bound::answer()%2!=0) return 4;\n"
        " if(charm::api_bound::answer()!=charm::api_bound::answer()) return 5;\n"
        " return 0;\n}\n"
    )
    (exercise / ".grader" / "test.cpp").write_text(hidden, encoding="utf-8")
    (exercise / ".grader" / "public_api_manifest.json").write_text("{}\n", encoding="utf-8")
    gate_calls: list[list[str]] = []

    def fake_api_gate(
        _scratch: Path,
        files: dict[str, str],
        *,
        image: str,
        timeout_s: int,
    ) -> tuple[bool, str, str]:
        del image, timeout_s
        gate_calls.append(list(files))
        return False, "clang18_ast decision=FAIL", "private receipt"

    def fake_stage(
        _scratch: Path, script: str, *, image: str, timeout_s: int
    ) -> subprocess.CompletedProcess[str]:
        del script, image, timeout_s
        return subprocess.CompletedProcess(["fake"], 0, stdout="", stderr="")

    monkeypatch.setattr(harness_module, "_run_public_api_gate", fake_api_gate)
    monkeypatch.setattr(harness_module, "_run_stage", fake_stage)
    result = run_shadow_weighted45_tests(
        exercise,
        {"answer.cpp": source},
        expected_test_sha256=hashlib.sha256(hidden.encode()).hexdigest(),
    )

    assert gate_calls == [["answer.cpp"]]
    assert result.status == "compile_failed"
    assert result.weighted45_checks["K3"] is True
    assert result.weighted45_checks["K2"] is False
    assert "clang18_ast decision=FAIL" in result.weighted45_evidence["K2"]


def test_weighted45_hidden_harness_does_not_link_an_included_cpp_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exercise = tmp_path / "included-cpp"
    (exercise / ".grader").mkdir(parents=True)
    source = "int answer(){return 42;}\n"
    (exercise / "answer.cpp").write_text(source, encoding="utf-8")
    hidden = (
        '#include "answer.cpp"\n'
        "int main(){\n"
        " if(answer()!=42) return 1;\n"
        " if(answer()<0) return 2;\n"
        " if(answer()>100) return 3;\n"
        " if(answer()%2!=0) return 4;\n"
        " if(answer()!=answer()) return 5;\n"
        " return 0;\n}\n"
    )
    (exercise / ".grader" / "test.cpp").write_text(hidden, encoding="utf-8")
    scripts: list[str] = []

    def fake_stage(
        _scratch: Path, script: str, *, image: str, timeout_s: int
    ) -> subprocess.CompletedProcess[str]:
        del image, timeout_s
        scripts.append(script)
        output = "GLM47_AIDER_WEIGHTED45_fixed:0\n" if "GLM47_AIDER_SUITE=" in script else ""
        return subprocess.CompletedProcess(["fake"], 0, stdout=output, stderr="")

    monkeypatch.setattr(harness_module.secrets, "token_hex", lambda _size: "fixed")
    monkeypatch.setattr(harness_module, "_run_stage", fake_stage)
    result = run_shadow_weighted45_tests(
        exercise,
        {"answer.cpp": source},
        expected_test_sha256=hashlib.sha256(hidden.encode()).hexdigest(),
    )

    syntax = next(script for script in scripts if "-fsyntax-only" in script)
    link = next(script for script in scripts if ".grader/test.o -o" in script)
    assert "answer.cpp" in syntax
    assert "answer.cpp" not in link
    assert result.status == "passed"


def test_weighted45_reward_keeps_all_45_outcomes_and_intermediates(tmp_path: Path) -> None:
    (tmp_path / "example.h").write_text("#pragma once\nint answer();\n", encoding="utf-8")
    (tmp_path / "example.cpp").write_text(
        '#include "example.h"\nint answer(){return 0;}\n', encoding="utf-8"
    )

    def runner(_path: Path, _files: dict[str, str]) -> AiderTestResult:
        checks = {check_id: True for check_id in WEIGHTED45_HARNESS_CHECK_IDS}
        return AiderTestResult(
            status="passed",
            tests_passed=5,
            tests_total=5,
            candidate_returncode=0,
            weighted45_checks=checks,
            weighted45_evidence={check_id: "unit pass" for check_id in checks},
        )

    result = compute_weighted45_aider_reward(_task(), tmp_path, _complete_response(), runner=runner)

    assert result.weighted45 is not None
    assert set(result.weighted45.checks) == WEIGHTED45_CHECK_IDS
    assert all(result.weighted45.checks.values())
    assert result.reward == 1.0
    assert result.weighted45.normalized_percentage == 100.0
    assert len(result.weighted45.tier_pass_counts) == 9


def test_weighted45_parse_failure_records_downstream_false_without_skipping_tiers(
    tmp_path: Path,
) -> None:
    result = compute_weighted45_aider_reward(_task(), tmp_path, "Please clarify the task")

    assert result.weighted45 is not None
    assert set(result.weighted45.checks) == WEIGHTED45_CHECK_IDS
    assert not any(result.weighted45.checks[check_id] for check_id in WEIGHTED45_HARNESS_CHECK_IDS)
    assert len(result.weighted45.tier_pass_counts) == 9
    assert -1.0 <= result.reward <= 1.0


def test_weighted45_invalid_text_encoding_is_a_scored_parse_failure(tmp_path: Path) -> None:
    result = compute_weighted45_aider_reward(_task(), tmp_path, "bad-surrogate:\ud800")

    assert result.weighted45 is not None
    assert result.weighted45.checks["P2"] is False
    assert result.reason == "fatal_parse_failure"


def test_weighted45_miles_record_and_optimizer_gate_require_exact_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "example.h").write_text("#pragma once\nint answer();\n", encoding="utf-8")
    (tmp_path / "example.cpp").write_text(
        '#include "example.h"\nint answer(){return 0;}\n', encoding="utf-8"
    )
    harness_checks = {check_id: True for check_id in WEIGHTED45_HARNESS_CHECK_IDS}
    breakdown = compute_weighted45_aider_reward(
        _task(),
        tmp_path,
        _complete_response(),
        runner=lambda _path, _files: AiderTestResult(
            status="passed",
            tests_passed=5,
            tests_total=5,
            weighted45_checks=harness_checks,
            weighted45_evidence={check_id: "unit pass" for check_id in harness_checks},
        ),
    )
    monkeypatch.setenv("MILES_AIDER_REWARD_MODE", "weighted45")
    sample = type(
        "Sample",
        (),
        {"index": 0, "rollout_id": 0, "response": _complete_response()},
    )()
    record = integration_module.reward_record(sample, _task(), breakdown)
    assert set(record["weighted45"]["checks"]) == WEIGHTED45_CHECK_IDS

    monkeypatch.setenv("GLM47_AIDER_EXPECTED_TRAIN_GROUPS", "1")
    monkeypatch.setenv("GLM47_AIDER_EXPECTED_SAMPLES_PER_GROUP", "1")
    integration_module.validate_aider_rollout_batch(
        type("Args", (), {"rollout_batch_size": 1, "n_samples_per_prompt": 1})(),
        [[type("Rollout", (), {"reward": record, "response": _complete_response()})()]],
    )

    malformed = dict(record)
    malformed["weighted45"] = {**record["weighted45"], "checks": {"F1": True}}
    with pytest.raises(
        integration_module.AiderRewardInfrastructureError,
        match="exact 45-check receipt",
    ):
        integration_module.validate_aider_rollout_batch(
            type("Args", (), {"rollout_batch_size": 1, "n_samples_per_prompt": 1})(),
            [[type("Rollout", (), {"reward": malformed, "response": "bad"})()]],
        )
