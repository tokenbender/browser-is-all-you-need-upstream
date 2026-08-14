from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import glm47_posttraining.aider_polyglot.dataset as dataset_module
import glm47_posttraining.aider_polyglot.harness as harness_module
import glm47_posttraining.integrations.miles_aider_polyglot as integration_module
from glm47_posttraining.aider_polyglot.dataset import (
    DATASET_KIND,
    EXPECTED_SHADOW_TASKS,
    build_aider_polyglot_datasets,
)
from glm47_posttraining.aider_polyglot.harness import run_aider_tests, run_shadow_tests
from glm47_posttraining.aider_polyglot.parser import (
    MAX_RESPONSE_BYTES,
    AiderResponseError,
    parse_whole_file_response,
    segment_glm47_response,
)
from glm47_posttraining.aider_polyglot.reward import compute_aider_reward
from glm47_posttraining.aider_polyglot.schema import AiderPolyglotTask, AiderTestResult
from glm47_posttraining.aider_polyglot.schema import WEIGHTED45_CHECK_IDS
from glm47_posttraining.aider_polyglot.validator.oracle.oracle_receipt import (
    OracleCertificationReceipt,
    OracleEnvironment,
    OracleInputBinding,
    OracleRuleResult,
    OracleRunReceipt,
    SHA256_ZERO,
    canonical_sha256,
    compute_certification_sha256,
)
from glm47_posttraining.aider_polyglot.validator.oracle.oracle_runner import (
    OracleCertificationError,
)
from glm47_posttraining.aider_polyglot.validator.oracle.oracle_rules import ORACLE_RULES
from glm47_posttraining.cpp_perf.sandbox import SandboxInfrastructureError


def _task() -> AiderPolyglotTask:
    return AiderPolyglotTask(
        task_id="aider-shadow-cpp/example",
        exercise="example",
        split="train",
        harness_kind="shadow_cpp17",
        exercise_dir="shadow/example",
        editable_files=["example.cpp", "example.h"],
        prompt=[{"role": "user", "content": "solve"}],
        source_revision="abc123",
        hidden_test_sha256="a" * 64,
        source_prompt_sha256="b" * 64,
        verification_gate="unit",
    )


def _response(label: str = "example.cpp", *, prefix: str = "") -> str:
    return f"{prefix}{label}\n```cpp\nint answer() {{ return 42; }}\n```\n"


def _make_shadow_tree(tmp_path: Path) -> Path:
    root = tmp_path / "rubrics"
    practice = root / "cpp" / "exercises" / "practice"
    for index in range(EXPECTED_SHADOW_TASKS):
        slug = f"exercise-{index:03d}"
        exercise = practice / slug
        (exercise / ".docs").mkdir(parents=True)
        (exercise / ".reference").mkdir()
        (exercise / ".docs" / "instructions.md").write_text(
            f"# Introduction\n\n# {slug}\n\nImplement answer {index}.\n", encoding="utf-8"
        )
        header = f"{slug}.h"
        source = f"{slug}.cpp"
        test = f"{slug}_test.cpp"
        (exercise / header).write_text("#pragma once\nint answer();\n", encoding="utf-8")
        (exercise / source).write_text(
            f'#include "{header}"\nint answer() {{ return 0; }}\n', encoding="utf-8"
        )
        (exercise / ".reference" / header).write_text(
            "#pragma once\nint answer();\n", encoding="utf-8"
        )
        (exercise / ".reference" / source).write_text(
            f'#include "{header}"\nint answer() {{ return {index}; }}\n', encoding="utf-8"
        )
        test_bytes = (
            f'#include "{header}"\nint main() {{\n'
            f"  if (answer() != {index}) return 1;\n"
            f"  if (answer() < {index}) return 2;\n"
            f"  if (answer() > {index}) return 3;\n"
            f"  if (answer() != answer()) return 4;\n"
            f"  if ((answer() == {index}) == false) return 5;\n"
            "  return 0;\n}\n"
        )
        (exercise / test).write_text(test_bytes, encoding="utf-8")
        (exercise / "CMakeLists.txt").write_text("project(example CXX)\n", encoding="utf-8")
        rubric = {
            "category": f"category-{index % 6}",
            "editable_files": [header, source],
            "family": f"family-{index % 32}",
            "hidden_test_file": test,
            "hidden_test_sha256": hashlib.sha256(test_bytes.encode()).hexdigest(),
            "language": "cpp",
            "reference_answer_packaged": True,
            "reference_answer_model_facing": False,
            "schema_version": 2,
            "source_prompt_sha256": hashlib.sha256(slug.encode()).hexdigest(),
            "tags": ["cpp", "aider-whole-edit"],
            "task_id": slug,
            "verification_gate": "unit",
            "verification_stage": "passed",
        }
        (exercise / ".rubric.json").write_text(json.dumps(rubric), encoding="utf-8")
    manifest = {
        "kind": "aider-polyglot-cpp-shadow-rubrics",
        "schema_version": 2,
        "counts": {"tasks": EXPECTED_SHADOW_TASKS},
        "contract": {
            "official_task_id_overlap": [],
            "oracle_references_packaged": True,
            "reference_answers_model_facing": False,
        },
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def _unit_oracle_receipt(task: AiderPolyglotTask, *_args, config, **_kwargs):
    checks = {check_id: True for check_id in WEIGHTED45_CHECK_IDS}
    checks_sha256 = canonical_sha256(dict(sorted(checks.items())))
    runs = tuple(
        OracleRunReceipt(
            standard=standard,
            run_index=run_index,
            reward=1.0,
            normalized_percentage=100.0,
            reason="correct",
            infrastructure_error=False,
            harness_status="passed",
            tests_passed=5,
            tests_total=5,
            checks=checks,
            checks_sha256=checks_sha256,
            duration_ms=0,
        )
        for standard in config.standards
        for run_index in range(1, config.runs_per_standard + 1)
    )
    rules = tuple(
        OracleRuleResult(
            rule_id=definition.rule_id,
            rule_version=definition.version,
            passed=True,
            severity=definition.severity,
            observed="unit pass",
            expected=definition.description,
            evidence="deterministic unit fixture",
            remediation=definition.remediation,
        )
        for definition in ORACLE_RULES
    )
    receipt = OracleCertificationReceipt(
        task_id=task.task_id,
        status="certified",
        config=config,
        config_sha256=config.config_sha256,
        input_binding=OracleInputBinding(
            task_descriptor_sha256=canonical_sha256(task.model_dump(mode="json")),
            starter_tree_sha256="1" * 64,
            reference_tree_sha256="2" * 64,
            hidden_test_sha256=task.hidden_test_sha256 or SHA256_ZERO,
            source_prompt_sha256=task.source_prompt_sha256,
        ),
        environment=OracleEnvironment(
            python_version="unit",
            platform="unit",
            compiler="unit",
            sandbox_backend="unit",
            sandbox_unshare_net="unit",
        ),
        runs=runs,
        rules=rules,
        certification_sha256=SHA256_ZERO,
    )
    return receipt.model_copy(
        update={"certification_sha256": compute_certification_sha256(receipt)}
    )


@pytest.fixture(autouse=True)
def _stub_dataset_oracle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dataset_module, "certify_task_oracle", _unit_oracle_receipt)


def test_whole_file_parser_accepts_sft_and_public_environment_prefixes() -> None:
    direct = parse_whole_file_response(_response(), ["example.cpp", "example.h"])
    public = parse_whole_file_response(_response(prefix="///\n"), ["example.cpp", "example.h"])

    assert direct.files == public.files == {"example.cpp": "int answer() { return 42; }\n"}
    assert direct.format_valid is public.format_valid is True


def test_whole_file_parser_marks_markdown_filename_as_recoverable() -> None:
    parsed = parse_whole_file_response(_response("### example.cpp"), ["example.cpp"])
    assert parsed.files["example.cpp"].startswith("int answer")
    assert parsed.format_valid is False


def test_whole_file_parser_recovers_one_unlabelled_fence_for_one_editable_file() -> None:
    parsed = parse_whole_file_response(
        "```cpp\nint answer() { return 42; }\n```\n", ["example.cpp"]
    )
    assert parsed.files == {"example.cpp": "int answer() { return 42; }\n"}
    assert parsed.format_valid is False


def test_whole_file_parser_rejects_unlabelled_fence_for_multiple_editable_files() -> None:
    with pytest.raises(AiderResponseError) as exc:
        parse_whole_file_response(
            "```cpp\nint answer() { return 42; }\n```\n",
            ["example.cpp", "example.h"],
        )
    assert exc.value.reason == "invalid_format"


def test_whole_file_parser_recovers_unlabelled_source_with_exact_declared_header() -> None:
    parsed = parse_whole_file_response(
        '```cpp\n#include "example.h"\nint answer() { return 42; }\n```\n',
        ["example.cpp", "example.h"],
    )
    assert parsed.files == {"example.cpp": '#include "example.h"\nint answer() { return 42; }\n'}
    assert parsed.format_valid is False


def test_whole_file_parser_does_not_guess_source_for_unknown_header() -> None:
    with pytest.raises(AiderResponseError) as exc:
        parse_whole_file_response(
            '```cpp\n#include "other.h"\nint answer() { return 42; }\n```\n',
            ["example.cpp", "example.h"],
        )
    assert exc.value.reason == "invalid_format"


def test_glm47_response_segment_ignores_reasoning_fences_and_uses_first_boundary() -> None:
    final = (
        'example.cpp\n```cpp\nconst char *token = "</think>";\nint answer() { return 42; }\n```\n'
    )
    raw = (
        "draft\nCMakeLists.txt\n```cmake\nproject(unsafe)\n```\n"
        + _response()
        + "</think>\n"
        + final
    )

    segments = segment_glm47_response(raw)
    parsed = parse_whole_file_response(segments.final_answer, ["example.cpp"])

    assert segments.thinking_boundary_applied is True
    assert parsed.files == {
        "example.cpp": 'const char *token = "</think>";\nint answer() { return 42; }\n'
    }
    assert parsed.format_valid is True


def test_glm47_response_segment_preserves_legacy_no_marker_contract() -> None:
    response = _response()
    segments = segment_glm47_response(response)
    assert segments.final_answer == response
    assert segments.thinking_boundary_applied is False


def test_glm47_response_segment_validates_raw_bytes_before_boundary() -> None:
    raw = "x" * (MAX_RESPONSE_BYTES + 1) + "</think>\n" + _response()
    with pytest.raises(AiderResponseError) as exc:
        segment_glm47_response(raw)
    assert exc.value.reason == "response_too_large"


@pytest.mark.parametrize("marker", ["<|endoftext|>", "<|user|>", "<|observation|>"])
@pytest.mark.parametrize("separator", ["", "\n", " \n"])
def test_whole_file_parser_removes_only_terminal_glm_stop_markers(
    marker: str, separator: str
) -> None:
    response = _response().rstrip("\n") + separator + marker
    parsed = parse_whole_file_response(response, ["example.cpp"])
    assert parsed.files == {"example.cpp": "int answer() { return 42; }\n"}
    assert parsed.format_valid is True


def test_whole_file_parser_preserves_stop_marker_inside_file() -> None:
    response = 'example.cpp\n```cpp\nconst char *token = "<|user|>";\n```<|user|>'
    parsed = parse_whole_file_response(response, ["example.cpp"])
    assert parsed.files == {"example.cpp": 'const char *token = "<|user|>";\n'}
    assert parsed.format_valid is True


@pytest.mark.parametrize(
    "label", ["CMakeLists.txt", "example_test.cpp", "../example_test.cpp", "/tmp/CMakeLists.txt"]
)
def test_whole_file_parser_rejects_non_editable_targets(label: str) -> None:
    with pytest.raises(AiderResponseError) as exc:
        parse_whole_file_response(_response(label), ["example.cpp"])
    assert exc.value.reason == "forbidden_file"


@pytest.mark.parametrize("label", ["src/example.cpp", "../example.cpp", "/tmp/example.cpp"])
def test_whole_file_parser_maps_path_label_to_editable_basename(label: str) -> None:
    parsed = parse_whole_file_response(_response(label), ["example.cpp"])
    assert parsed.files == {"example.cpp": "int answer() { return 42; }\n"}
    assert parsed.format_valid is False


def test_whole_file_parser_skips_stray_fences_as_recoverable() -> None:
    response = (
        "Plan:\n```\npseudo code, not a file\n```\n\n"
        "Update example.cpp with this:\n```cpp\nint wrong() { return 0; }\n```\n\n" + _response()
    )
    parsed = parse_whole_file_response(response, ["example.cpp"])
    assert parsed.files == {"example.cpp": "int answer() { return 42; }\n"}
    assert parsed.format_valid is False


def test_whole_file_parser_requires_at_least_one_editable_file() -> None:
    with pytest.raises(AiderResponseError) as exc:
        parse_whole_file_response("Plan:\n```\njust prose\n```\n", ["example.cpp"])
    assert exc.value.reason == "invalid_format"


def test_whole_file_parser_rejects_duplicate_file() -> None:
    response = _response() + "\n" + _response()
    with pytest.raises(AiderResponseError) as exc:
        parse_whole_file_response(response, ["example.cpp"])
    assert exc.value.reason == "duplicate_file"


def test_aider_reward_prioritizes_tests_and_tiebreaks_format(tmp_path: Path) -> None:
    def passed(_path: Path, _files: dict[str, str]) -> AiderTestResult:
        return AiderTestResult(status="passed", tests_passed=1, tests_total=1)

    exact = compute_aider_reward(_task(), tmp_path, _response(), runner=passed)
    recoverable = compute_aider_reward(
        _task(), tmp_path, _response("### example.cpp"), runner=passed
    )
    assert (exact.reward, exact.reason) == (1.0, "passed")
    assert (recoverable.reward, recoverable.reason) == (0.9, "recoverable_format_passed")


def test_aider_reward_rejects_test_tampering_without_execution(tmp_path: Path) -> None:
    called = False

    def runner(_path: Path, _files: dict[str, str]) -> AiderTestResult:
        nonlocal called
        called = True
        return AiderTestResult(status="passed", tests_passed=1, tests_total=1)

    breakdown = compute_aider_reward(
        _task(), tmp_path, _response("example_test.cpp"), runner=runner
    )
    assert (breakdown.reward, breakdown.reason, called) == (-1.0, "forbidden_file", False)


def test_aider_reward_propagates_reported_infrastructure_error(tmp_path: Path) -> None:
    def infrastructure(_path: Path, _files: dict[str, str]) -> AiderTestResult:
        return AiderTestResult(status="infrastructure_error", logs={"error": "sandbox unavailable"})

    with pytest.raises(SandboxInfrastructureError, match="sandbox unavailable"):
        compute_aider_reward(_task(), tmp_path, _response(), runner=infrastructure)


def test_harness_parses_build_triggered_catch_success(tmp_path: Path, monkeypatch) -> None:
    exercise = tmp_path / "example"
    exercise.mkdir()
    (exercise / "example.cpp").write_text("int answer(){return 0;}\n", encoding="utf-8")
    results = iter(
        [
            subprocess.CompletedProcess(["cmake"], 0, stdout="configured\n", stderr=""),
            subprocess.CompletedProcess(
                ["cmake", "--build"],
                0,
                stdout="All tests passed (2004 assertions in 5 test cases)\n",
                stderr="",
            ),
        ]
    )
    monkeypatch.setattr(harness_module, "_run_stage", lambda *args, **kwargs: next(results))
    result = run_aider_tests(exercise, {"example.cpp": "int answer(){return 42;}\n"})
    assert (result.status, result.tests_passed, result.tests_total) == ("passed", 5, 5)


def test_shadow_harness_compiles_hidden_test_before_candidate(tmp_path: Path, monkeypatch) -> None:
    exercise = tmp_path / "shadow-example"
    (exercise / ".grader").mkdir(parents=True)
    (exercise / "example.cpp").write_text("int answer(){return 0;}\n", encoding="utf-8")
    hidden = "int answer(); int main(){return answer() == 42 ? 0 : 1;}\n"
    (exercise / ".grader" / "test.cpp").write_text(hidden, encoding="utf-8")
    results = iter(
        [
            subprocess.CompletedProcess(["c++"], 0, stdout="", stderr=""),
            subprocess.CompletedProcess(
                ["candidate_test"], 0, stdout="GLM47_AIDER_PASS_abc\n", stderr=""
            ),
        ]
    )
    commands: list[str] = []

    def stage(_scratch, script, **_kwargs):
        commands.append(script)
        return next(results)

    monkeypatch.setattr(harness_module, "_run_stage", stage)
    monkeypatch.setattr(harness_module.secrets, "token_hex", lambda _size: "abc")
    result = run_shadow_tests(
        exercise,
        {"example.cpp": "int answer(){return 42;}\n"},
        expected_test_sha256=hashlib.sha256(hidden.encode()).hexdigest(),
    )
    assert result.all_tests_pass
    assert "-std=c++17" in commands[0]
    assert ".grader/test.cpp" in commands[0]
    assert "rm .grader/test.cpp" in commands[0]
    assert commands[1].endswith(".grader/candidate_test")


def _run_ordinal_shadow(tmp_path: Path, monkeypatch, candidate_returncode: int):
    exercise = tmp_path / "shadow-ordinal"
    (exercise / ".grader").mkdir(parents=True)
    (exercise / "example.cpp").write_text("int answer(){return 0;}\n", encoding="utf-8")
    hidden = (
        "int answer();\n"
        "int main(){\n"
        "  if (answer() < 1) return 1;\n"
        "  if (answer() < 2) return 2;\n"
        "  if (answer() < 3) return 3;\n"
        "  if (answer() < 4) return 4;\n"
        "  if (answer() != 5) return 5;\n"
        "  return 0;\n"
        "}\n"
    )
    (exercise / ".grader" / "test.cpp").write_text(hidden, encoding="utf-8")
    marker = "GLM47_AIDER_PASS_abc\n" if candidate_returncode == 0 else ""
    results = iter(
        [
            subprocess.CompletedProcess(["c++"], 0, stdout="", stderr=""),
            subprocess.CompletedProcess(
                ["candidate_test"], candidate_returncode, stdout=marker, stderr=""
            ),
        ]
    )
    monkeypatch.setattr(harness_module, "_run_stage", lambda *a, **k: next(results))
    monkeypatch.setattr(harness_module.secrets, "token_hex", lambda _size: "abc")
    return run_shadow_tests(
        exercise,
        {"example.cpp": "int answer(){return 5;}\n"},
        expected_test_sha256=hashlib.sha256(hidden.encode()).hexdigest(),
    )


def test_shadow_harness_counted_grader_scores_all_five_checks(tmp_path, monkeypatch) -> None:
    exercise = tmp_path / "shadow-counted"
    (exercise / ".grader").mkdir(parents=True)
    (exercise / "example.cpp").write_text("int answer(){return 42;}\n", encoding="utf-8")
    hidden = (
        "#define GLM47_AIDER_COUNTED_TESTS 5\n"
        "int answer();\n"
        "int main(){\n"
        "  int failed = 0;\n"
        "  const int value = answer();\n"
        "  failed += value != 42;\n"
        "  failed += value < 0;\n"
        "  failed += value > 100;\n"
        "  failed += (value % 2) != 0;\n"
        "  failed += answer() != value;\n"
        "  return failed;\n"
        "}\n"
    )
    (exercise / ".grader" / "test.cpp").write_text(hidden, encoding="utf-8")
    results = iter(
        [
            subprocess.CompletedProcess(["c++"], 0, stdout="", stderr=""),
            # The counted contract returns two failed checks, so three passed.
            subprocess.CompletedProcess(["candidate_test"], 2, stdout="", stderr=""),
        ]
    )
    monkeypatch.setattr(harness_module, "_run_stage", lambda *a, **k: next(results))

    result = run_shadow_tests(
        exercise,
        {"example.cpp": "int answer(){return 42;}\n"},
        expected_test_sha256=hashlib.sha256(hidden.encode()).hexdigest(),
    )

    assert result.status == "tests_failed"
    assert result.tests_passed == 3
    assert result.tests_total == 5
    assert result.fraction_tests_passed == pytest.approx(0.6)


def test_shadow_harness_awards_partial_credit_for_ordinal_grader(tmp_path, monkeypatch) -> None:
    # Exit code 3 means checks 1 and 2 passed before check 3 failed: 2 of 5.
    result = _run_ordinal_shadow(tmp_path, monkeypatch, candidate_returncode=3)
    assert result.status == "tests_failed"
    assert result.tests_passed == 2
    assert result.tests_total == 5
    assert result.fraction_tests_passed == pytest.approx(0.4)
    assert not result.all_tests_pass


def test_shadow_harness_full_pass_uses_ordinal_total(tmp_path, monkeypatch) -> None:
    result = _run_ordinal_shadow(tmp_path, monkeypatch, candidate_returncode=0)
    assert result.all_tests_pass
    assert result.tests_passed == 5 and result.tests_total == 5


def test_shadow_harness_crash_exit_scores_zero(tmp_path, monkeypatch) -> None:
    # A crash signal (139) is outside [1, N]; award no partial credit but keep N.
    result = _run_ordinal_shadow(tmp_path, monkeypatch, candidate_returncode=139)
    assert result.status == "tests_failed"
    assert result.tests_passed == 0
    assert result.tests_total == 5


def test_shadow_harness_non_ordinal_grader_stays_binary(tmp_path, monkeypatch) -> None:
    exercise = tmp_path / "shadow-binary"
    (exercise / ".grader").mkdir(parents=True)
    (exercise / "example.cpp").write_text("int answer(){return 0;}\n", encoding="utf-8")
    # Macro-style grader always returns 1 on failure: no sequential ordinals to read.
    hidden = (
        "int answer();\n"
        "#define CHECK(c) do { if (!(c)) return 1; } while (0)\n"
        "int main(){ CHECK(answer()==1); CHECK(answer()==2); return 0; }\n"
    )
    (exercise / ".grader" / "test.cpp").write_text(hidden, encoding="utf-8")
    results = iter(
        [
            subprocess.CompletedProcess(["c++"], 0, stdout="", stderr=""),
            subprocess.CompletedProcess(["candidate_test"], 1, stdout="", stderr=""),
        ]
    )
    monkeypatch.setattr(harness_module, "_run_stage", lambda *a, **k: next(results))
    monkeypatch.setattr(harness_module.secrets, "token_hex", lambda _size: "abc")
    result = run_shadow_tests(
        exercise,
        {"example.cpp": "int answer(){return 1;}\n"},
        expected_test_sha256=hashlib.sha256(hidden.encode()).hexdigest(),
    )
    assert result.status == "tests_failed"
    assert result.tests_passed == 0
    assert result.tests_total == 1


def test_shadow_harness_rejects_early_exit_bypass(tmp_path: Path) -> None:
    exercise = tmp_path / "shadow-example"
    (exercise / ".grader").mkdir(parents=True)
    (exercise / "example.cpp").write_text("int answer(){return 0;}\n", encoding="utf-8")
    hidden = "int answer(); int main(){return answer() == 42 ? 0 : 1;}\n"
    (exercise / ".grader" / "test.cpp").write_text(hidden, encoding="utf-8")
    with pytest.raises(harness_module.CandidatePolicyError):
        run_shadow_tests(
            exercise,
            {"example.cpp": "struct Escape { Escape(){ _Exit(0); } } escape;\n"},
            expected_test_sha256=hashlib.sha256(hidden.encode()).hexdigest(),
        )


def test_linux_local_stage_is_fail_closed_and_mount_isolated(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GLM47_CPP_SANDBOX_BACKEND", "local")
    monkeypatch.delenv("GLM47_CPP_SANDBOX_UNSHARE_NET", raising=False)
    monkeypatch.setattr(harness_module.platform, "system", lambda: "Linux")
    monkeypatch.setattr(harness_module.shutil, "which", lambda name: "/usr/bin/bwrap")
    command = harness_module._local_sandbox_command(tmp_path, "true")
    rendered = " ".join(command)
    assert "--unshare-all" in command
    assert "--clearenv" in command
    assert str(tmp_path.resolve()) in command
    assert "/workspace" not in rendered


def test_linux_local_stage_can_skip_only_the_net_unshare(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GLM47_CPP_SANDBOX_BACKEND", "local")
    monkeypatch.setenv("GLM47_CPP_SANDBOX_UNSHARE_NET", "0")
    monkeypatch.setattr(harness_module.platform, "system", lambda: "Linux")
    monkeypatch.setattr(harness_module.shutil, "which", lambda name: "/usr/bin/bwrap")
    command = harness_module._local_sandbox_command(tmp_path, "true")
    assert "--unshare-all" not in command
    assert "--unshare-net" not in command
    for flag in (
        "--unshare-user-try",
        "--unshare-ipc",
        "--unshare-pid",
        "--unshare-uts",
        "--unshare-cgroup-try",
    ):
        assert flag in command
    assert "--clearenv" in command


def test_run_stage_replaces_non_utf8_output_without_hiding_exit_code(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("GLM47_CPP_SANDBOX_BACKEND", "local")
    monkeypatch.setattr(harness_module.platform, "system", lambda: "Darwin")
    result = harness_module._run_stage(
        tmp_path,
        "printf '\\377'; printf '\\376' >&2; exit 7",
        image="unused",
        timeout_s=5,
    )
    assert result.returncode == 7
    assert result.stdout == "\ufffd"
    assert result.stderr == "\ufffd"


def test_run_stage_treats_outer_timeout_as_infrastructure(tmp_path: Path, monkeypatch) -> None:
    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(
            cmd=["probe"], timeout=1, output=b"out:\xff", stderr=b"err:\xfe"
        )

    monkeypatch.setattr(harness_module.subprocess, "run", timeout)
    with pytest.raises(SandboxInfrastructureError) as caught:
        harness_module._run_stage(tmp_path, "true", image="unused", timeout_s=1)
    assert "stdout='out:\ufffd'" in str(caught.value)
    assert "stderr='err:\ufffd'" in str(caught.value)


def test_dataset_builder_materializes_only_answer_blind_training_files(tmp_path: Path) -> None:
    source = _make_shadow_tree(tmp_path)
    paths = build_aider_polyglot_datasets(
        source, tmp_path / "prepared", profile="unit", train_limit=3, monitor_limit=2
    )
    train_rows = [json.loads(line) for line in paths["grpo_train"].read_text().splitlines()]
    monitor_rows = [json.loads(line) for line in paths["eval"].read_text().splitlines()]
    manifest = json.loads(paths["manifest"].read_text())

    assert len(train_rows) == 3
    assert len(monitor_rows) == 2
    assert manifest["kind"] == DATASET_KIND
    assert manifest["counts"] == {"available_shadow": 253, "monitor": 2, "train": 3}
    assert manifest["split_contract"]["official_26"] == "external fixed evaluation only"
    assert manifest["schema_version"] == 6
    assert manifest["oracle_contract"]["status"] == "certified"
    assert manifest["oracle_contract"]["certified_tasks"] == 253
    assert manifest["oracle_contract"]["standards"] == ["c++17", "c++20"]
    oracle_report = json.loads(paths["oracle_report"].read_text(encoding="utf-8"))
    assert oracle_report["certified_count"] == 253
    assert oracle_report["rejected_count"] == 0
    assert manifest["reward_contract"] == {
        "checks_per_tier": 5,
        "hidden_suite_partitions": 5,
        "normalization_weight": 6.54,
        "policy": "weighted45-v1",
        "raw_tier_formula": "0.3*N_passed-0.5",
        "tiers": 9,
        "total_checks": 45,
    }
    first = AiderPolyglotTask.read_json(
        paths["manifest"].parent / train_rows[0]["metadata"]["task_path"]
    )
    materialized = paths["manifest"].parent / first.exercise_dir
    assert (materialized / ".grader" / "test.cpp").is_file()
    assert not (materialized / "CMakeLists.txt").exists()
    assert not any(materialized.glob("*_test.cpp"))
    assert not (materialized / ".reference").exists()
    assert [message.role for message in first.prompt] == [
        "system",
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
    ]
    assert "*file listing* format" in first.prompt[0].content
    assert "*added these files to the chat*" in first.prompt[5].content
    final = first.prompt[-1].content
    assert "Use the above instructions to modify the supplied files:" in final
    assert final.rstrip().endswith("including any appropriate path.")
    assert all("_test.cpp" not in message.content for message in first.prompt)
    assert all(".reference" not in message.content for message in first.prompt)


def test_dataset_builder_emits_v2_only_on_explicit_new_output(tmp_path: Path) -> None:
    source = _make_shadow_tree(tmp_path)
    paths = build_aider_polyglot_datasets(
        source,
        tmp_path / "prepared-v2",
        profile="unit-v2",
        train_limit=1,
        monitor_limit=1,
        reward_policy="hybrid-bipolar45-v2",
    )
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    row = json.loads(paths["grpo_train"].read_text(encoding="utf-8").splitlines()[0])
    task = AiderPolyglotTask.read_json(paths["manifest"].parent / row["metadata"]["task_path"])

    assert manifest["schema_version"] == 7
    assert manifest["reward_contract"]["policy"] == "hybrid-bipolar45-v2"
    assert manifest["reward_contract"]["activation_status"] == "NOT_ADMITTED"
    assert task.reward_contract == "hybrid-bipolar45-v2"
    assert task.prompt_contract == "hybrid45-isolated-wholefile-v2"
    assert [message.role for message in task.prompt] == ["system", "user"]


def test_dataset_builder_rejects_and_reports_any_failed_oracle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_shadow_tree(tmp_path)

    def reject_one(task: AiderPolyglotTask, *args, config, **kwargs):
        receipt = _unit_oracle_receipt(task, *args, config=config, **kwargs)
        if task.exercise != "exercise-017":
            return receipt
        failed_rule = receipt.rules[7].model_copy(
            update={
                "passed": False,
                "observed": "reward=0.98",
                "evidence": "oracle did not achieve the required endpoint",
            }
        )
        rejected = receipt.model_copy(
            update={
                "status": "rejected",
                "rules": (*receipt.rules[:7], failed_rule, *receipt.rules[8:]),
                "certification_sha256": SHA256_ZERO,
            }
        )
        return rejected.model_copy(
            update={"certification_sha256": compute_certification_sha256(rejected)}
        )

    monkeypatch.setattr(dataset_module, "certify_task_oracle", reject_one)
    output = tmp_path / "prepared"
    with pytest.raises(OracleCertificationError, match="exercise-017"):
        build_aider_polyglot_datasets(source, output, train_limit=3)

    assert not output.exists()
    rejection_report = json.loads(
        (tmp_path / "prepared.oracle-rejected" / "report.json").read_text(encoding="utf-8")
    )
    assert rejection_report["status"] == "rejected"
    assert rejection_report["rejected_count"] == 1
    assert rejection_report["failed_rule_counts"] == {"ORC-012": 1}


def test_dataset_builder_validates_source_before_replacing_output(tmp_path: Path) -> None:
    source = _make_shadow_tree(tmp_path)
    output = tmp_path / "prepared"
    output.mkdir()
    sentinel = output / "sentinel"
    sentinel.write_text("keep", encoding="utf-8")
    first = next((source / "cpp" / "exercises" / "practice").iterdir())
    (first / next(first.glob("*_test.cpp")).name).write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        build_aider_polyglot_datasets(source, output, force=True)
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_dataset_builder_materializes_exact_gradient_holdout_split(tmp_path: Path) -> None:
    source = _make_shadow_tree(tmp_path)
    train_ids = [
        "aider-shadow-cpp/exercise-005",
        "aider-shadow-cpp/exercise-011",
    ]
    monitor_ids = ["aider-shadow-cpp/exercise-017"]
    paths = build_aider_polyglot_datasets(
        source,
        tmp_path / "prepared",
        train_task_ids=train_ids,
        monitor_task_ids=monitor_ids,
        profile="rl-validity",
    )
    train_rows = [json.loads(line) for line in paths["grpo_train"].read_text().splitlines()]
    monitor_rows = [json.loads(line) for line in paths["eval"].read_text().splitlines()]
    manifest = json.loads(paths["manifest"].read_text())

    assert [row["task_id"] for row in train_rows] == train_ids
    assert [row["task_id"] for row in monitor_rows] == monitor_ids
    assert {row["split"] for row in train_rows} == {"train"}
    assert {row["split"] for row in monitor_rows} == {"validation"}
    assert manifest["counts"] == {"available_shadow": 253, "monitor": 1, "train": 2}
    assert manifest["selection"] == {
        "mode": "explicit_gradient_holdout",
        "train_task_ids": train_ids,
        "monitor_task_ids": monitor_ids,
    }
    descriptor = paths["manifest"].parent / monitor_rows[0]["metadata"]["task_path"]
    assert AiderPolyglotTask.read_json(descriptor).split == "validation"


def test_dataset_builder_rejects_overlapping_explicit_split(tmp_path: Path) -> None:
    source = _make_shadow_tree(tmp_path)
    with pytest.raises(ValueError, match="overlap"):
        build_aider_polyglot_datasets(
            source,
            tmp_path / "prepared",
            train_task_ids=["exercise-001"],
            monitor_task_ids=["aider-shadow-cpp/exercise-001"],
        )


def test_miles_preflight_uses_caller_bound_verifier_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[str] = []
    monkeypatch.setenv("GLM47_CPP_SANDBOX_IMAGE", "verifier@sha256:bound")
    monkeypatch.setattr(integration_module, "run_response_contract_preflight", lambda: None)
    monkeypatch.setattr(
        integration_module,
        "run_sandbox_preflight",
        lambda *, image: observed.append(image),
    )

    integration_module.main(["preflight"])

    assert observed == ["verifier@sha256:bound"]


def test_miles_preflight_rejects_missing_verifier_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GLM47_CPP_SANDBOX_IMAGE", raising=False)
    monkeypatch.setattr(integration_module, "run_response_contract_preflight", lambda: None)

    with pytest.raises(RuntimeError, match="must bind the prebuilt verifier image"):
        integration_module.main(["preflight"])


def test_miles_reward_hook_uses_shadow_task_and_returns_metrics(
    tmp_path: Path, monkeypatch
) -> None:
    data = tmp_path / "data"
    exercise = data / "shadow" / "example"
    (exercise / ".grader").mkdir(parents=True)
    task_path = _task().write_json(data / "tasks" / "train" / "example.json")
    monkeypatch.setenv("GLM47_DATA_DIR", str(data))
    monkeypatch.setattr(
        integration_module,
        "run_shadow_tests",
        lambda *args, **kwargs: AiderTestResult(
            status="passed", tests_passed=1, tests_total=1, candidate_returncode=0
        ),
    )
    sample = SimpleNamespace(
        index=2,
        rollout_id=3,
        response=_response(),
        metadata={"task_path": str(task_path.relative_to(data))},
    )
    record = asyncio.run(integration_module.reward_func(SimpleNamespace(), sample))
    assert 0.85 <= record["score"] <= 1.0
    assert record["all_tests_pass"] is True
    assert record["candidate_returncode"] == 0
    assert record["modified_files"] == ["example.cpp"]


def test_miles_reward_hook_scores_only_post_think_final_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / "data"
    exercise = data / "shadow" / "example"
    (exercise / ".grader").mkdir(parents=True)
    task_path = _task().write_json(data / "tasks" / "train" / "example.json")
    monkeypatch.setenv("GLM47_DATA_DIR", str(data))
    observed_files: list[dict[str, str]] = []

    def passed(_path: Path, files: dict[str, str], **_kwargs) -> AiderTestResult:
        observed_files.append(files)
        return AiderTestResult(
            status="passed", tests_passed=1, tests_total=1, candidate_returncode=0
        )

    monkeypatch.setattr(integration_module, "run_shadow_tests", passed)
    final_answer = "\n" + _response()
    raw_response = (
        "draft reasoning\nCMakeLists.txt\n```cmake\nproject(unsafe)\n```\n"
        + _response()
        + "</think>"
        + final_answer
    )
    sample = SimpleNamespace(
        index=2,
        rollout_id=3,
        response=raw_response,
        metadata={"task_path": str(task_path.relative_to(data))},
    )

    record = asyncio.run(integration_module.reward_func(SimpleNamespace(), sample))

    assert observed_files == [{"example.cpp": "int answer() { return 42; }\n"}]
    assert record["response"] == raw_response
    assert record["response_contract"] == "glm47-thinking-final-answer-v1"
    assert record["thinking_boundary_applied"] is True
    assert record["scored_response_sha256"] == hashlib.sha256(final_answer.encode()).hexdigest()
    assert record["format_valid"] is True


def test_miles_reward_hook_keeps_protected_file_enforcement_on_final_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / "data"
    exercise = data / "shadow" / "example"
    (exercise / ".grader").mkdir(parents=True)
    task_path = _task().write_json(data / "tasks" / "train" / "example.json")
    monkeypatch.setenv("GLM47_DATA_DIR", str(data))
    called = False

    def must_not_run(*_args, **_kwargs) -> AiderTestResult:
        nonlocal called
        called = True
        raise AssertionError("protected final answer reached the compiler")

    monkeypatch.setattr(integration_module, "run_shadow_tests", must_not_run)
    sample = SimpleNamespace(
        response="reasoning only</think>\n" + _response("CMakeLists.txt"),
        metadata={"task_path": str(task_path.relative_to(data))},
    )

    record = asyncio.run(integration_module.reward_func(SimpleNamespace(), sample))

    assert called is False
    assert record["score"] == -1.0
    assert record["reason"] == "forbidden_file"
    assert record["modified_files"] == []
    assert record["thinking_boundary_applied"] is True


def test_hybrid45_static_rejections_bind_distinct_isolated_receipt_workspaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / "data"
    exercise = data / "shadow" / "example"
    (exercise / ".grader").mkdir(parents=True)
    (exercise / "example.cpp").write_text(
        "int answer() { return 0; }\n", encoding="utf-8"
    )
    (exercise / "example.h").write_text("int answer();\n", encoding="utf-8")
    task = _task().model_copy(
        update={
            "reward_contract": "hybrid-bipolar45-v2",
            "prompt_contract": "hybrid45-isolated-wholefile-v2",
            "tags": ["clean-room-charm-r8"],
        }
    )
    task_path = task.write_json(data / "tasks" / "train" / "example.json")
    monkeypatch.setenv("GLM47_DATA_DIR", str(data))
    monkeypatch.setenv("MILES_AIDER_REWARD_MODE", "hybrid_bipolar45")
    monkeypatch.setenv("GLM47_TOKENIZER_REVISION", "glm47-tokenizer-pinned")
    monkeypatch.setenv("GLM47_TOKENIZER_MANIFEST_SHA256", "c" * 64)
    monkeypatch.setenv("GLM47_CHAT_TEMPLATE_SHA256", "d" * 64)
    monkeypatch.setenv("GLM47_CPP_SANDBOX_IMAGE", "sha256:" + "e" * 64)
    monkeypatch.setenv("GLM47_AIDER_EXPECTED_TRAIN_GROUPS", "1")
    monkeypatch.setenv("GLM47_AIDER_EXPECTED_SAMPLES_PER_GROUP", "2")
    monkeypatch.setenv("GLM47_AIDER_REQUIRE_CONTEXT_ISOLATION", "1")
    monkeypatch.setenv(
        "MILES_GRPO_ADVANTAGE_POLICY", "miles-standard-grpo-group-std-v1"
    )
    monkeypatch.setenv("GLM47_AIDER_MAX_PROMPT_TOKENS", "8")
    samples = [
        SimpleNamespace(
            index=index,
            rollout_id=3,
            prompt="<user>solve</user>",
            response="not a whole-file response",
            tokens=list(range(10)),
            response_length=2,
            status="finished",
            metadata={
                "base_task_id": "example",
                "prompt_variant": "short",
                "task_path": str(task_path.relative_to(data)),
            },
        )
        for index in range(2)
    ]

    records = asyncio.run(integration_module.reward_func(SimpleNamespace(), samples))

    contexts = [record["context_identity"] for record in records]
    assert all(context["verification_executed"] is False for context in contexts)
    assert all(
        context["verification_workspace_binding"] == "isolated_receipt"
        for context in contexts
    )
    assert len({context["verification_workspace_id"] for context in contexts}) == 2
    rollouts = [
        SimpleNamespace(index=sample.index, response=sample.response, reward=record)
        for sample, record in zip(samples, records, strict=True)
    ]
    integration_module.validate_aider_rollout_batch(
        SimpleNamespace(rollout_batch_size=1, n_samples_per_prompt=2), [rollouts]
    )


def test_miles_reward_hook_aborts_on_missing_task_binding() -> None:
    sample = SimpleNamespace(response=_response(), metadata={})
    with pytest.raises(
        integration_module.AiderRewardInfrastructureError,
        match="missing required metadata.task_path",
    ):
        asyncio.run(integration_module.reward_func(SimpleNamespace(), sample))


def test_miles_reward_hook_aborts_batch_on_sandbox_infrastructure_error(
    tmp_path: Path, monkeypatch
) -> None:
    data = tmp_path / "data"
    exercise = data / "shadow" / "example"
    (exercise / ".grader").mkdir(parents=True)
    task_path = _task().write_json(data / "tasks" / "train" / "example.json")
    monkeypatch.setenv("GLM47_DATA_DIR", str(data))
    monkeypatch.setattr(
        integration_module,
        "run_shadow_tests",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            SandboxInfrastructureError("docker unavailable")
        ),
    )
    samples = [
        SimpleNamespace(
            index=index,
            rollout_id=1,
            response=_response(),
            metadata={"task_path": str(task_path.relative_to(data))},
        )
        for index in range(2)
    ]
    with pytest.raises(
        integration_module.AiderRewardInfrastructureError,
        match="SandboxInfrastructureError: docker unavailable",
    ):
        asyncio.run(integration_module.reward_func(SimpleNamespace(), samples))


def _signal_record(task_id: str, score: float, tests_passed: int) -> dict[str, object]:
    return {
        "score": score,
        "reward": score,
        "reason": "tests_failed",
        "task_id": task_id,
        "infrastructure_error": False,
        "tests_passed": tests_passed,
        "tests_total": 5,
        "format_valid": True,
        "modified_files": ["example.cpp"],
        "compile_error": False,
    }


def test_pre_optimizer_signal_gate_writes_pass_receipt(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GLM47_AIDER_EXPECTED_TRAIN_GROUPS", "6")
    monkeypatch.setenv("GLM47_AIDER_EXPECTED_SAMPLES_PER_GROUP", "8")
    monkeypatch.setenv("GLM47_AIDER_REQUIRE_SIGNAL", "1")
    monkeypatch.setenv("MILES_GRPO_ADVANTAGE_POLICY", "miles-standard-grpo-group-std-v1")
    monkeypatch.setenv("GLM47_AIDER_SIGNAL_GATE_DIR", str(tmp_path / "gates"))
    data = []
    for group_index in range(6):
        samples = []
        for sample_index in range(8):
            varied = group_index < 4 and sample_index == 7
            tests_passed = 2 if group_index < 2 and varied else 1
            score = 0.2 if varied else 0.1
            samples.append(
                SimpleNamespace(
                    reward=_signal_record(
                        f"aider-shadow-cpp/task-{group_index}", score, tests_passed
                    )
                )
            )
        data.append(samples)

    integration_module.validate_aider_rollout_batch(
        SimpleNamespace(rollout_batch_size=6, n_samples_per_prompt=8), data
    )
    receipts = list((tmp_path / "gates").glob("signal_gate_passed_*.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text())
    assert receipt["status"] == "passed"
    assert receipt["signal_requirements_applied"] is True
    assert receipt["positive_groups"] == 6
    assert receipt["semantic_variance_groups"] == 2
    assert receipt["reward_variance_groups"] == 4
    assert receipt["optimizer_policy"] == "miles-standard-grpo-group-std-v1"
    assert receipt["advantage_telemetry"]["group_count"] == 6
    assert receipt["advantage_telemetry"]["non_finite_advantage_count"] == 0
    assert receipt["termination_reasons"] == {"unknown": 48}

    constant = [
        [
            SimpleNamespace(reward=_signal_record(f"aider-shadow-cpp/task-{group_index}", 0.1, 1))
            for _ in range(8)
        ]
        for group_index in range(6)
    ]
    with pytest.raises(
        integration_module.AiderRewardInfrastructureError,
        match="semantic_variance_groups=0<2, reward_variance_groups=0<2",
    ):
        integration_module.validate_aider_rollout_batch(
            SimpleNamespace(rollout_batch_size=6, n_samples_per_prompt=8), constant
        )
    failed = list((tmp_path / "gates").glob("signal_gate_failed_*.json"))
    assert len(failed) == 1
    failed_receipt = json.loads(failed[0].read_text())
    assert failed_receipt["sequence"] == 1
    assert failed_receipt["signal_requirements_applied"] is True
    assert failed_receipt["thresholds"]["minimum_exact_format_rate"] == 0.5


def test_rollout_validator_falls_back_when_expected_count_env_is_blank(monkeypatch) -> None:
    monkeypatch.setenv("GLM47_AIDER_EXPECTED_TRAIN_GROUPS", "")
    monkeypatch.setenv("GLM47_AIDER_EXPECTED_SAMPLES_PER_GROUP", "")
    data = [
        [
            SimpleNamespace(reward=_signal_record(f"aider-shadow-cpp/task-{group_index}", 0.1, 1))
            for _ in range(3)
        ]
        for group_index in range(2)
    ]

    integration_module.validate_aider_rollout_batch(
        SimpleNamespace(rollout_batch_size=2, n_samples_per_prompt=3), data
    )


def test_rollout_validator_allows_duplicate_task_groups_unless_strict(monkeypatch) -> None:
    monkeypatch.setenv("GLM47_AIDER_EXPECTED_TRAIN_GROUPS", "2")
    monkeypatch.setenv("GLM47_AIDER_EXPECTED_SAMPLES_PER_GROUP", "2")
    data = [
        [SimpleNamespace(reward=_signal_record("aider-shadow-cpp/task-a", 0.1, 1))],
        [SimpleNamespace(reward=_signal_record("aider-shadow-cpp/task-a", 0.2, 2))],
    ]
    for group in data:
        group.append(SimpleNamespace(reward=dict(group[0].reward)))

    integration_module.validate_aider_rollout_batch(
        SimpleNamespace(rollout_batch_size=2, n_samples_per_prompt=2), data
    )

    monkeypatch.setenv("GLM47_AIDER_REQUIRE_UNIQUE_TASK_GROUPS", "1")
    with pytest.raises(integration_module.AiderRewardInfrastructureError, match="duplicate"):
        integration_module.validate_aider_rollout_batch(
            SimpleNamespace(rollout_batch_size=2, n_samples_per_prompt=2), data
        )


def test_pre_optimizer_signal_gate_rejects_infrastructure_reward(monkeypatch) -> None:
    monkeypatch.setenv("GLM47_AIDER_EXPECTED_TRAIN_GROUPS", "1")
    monkeypatch.setenv("GLM47_AIDER_EXPECTED_SAMPLES_PER_GROUP", "1")
    bad = _signal_record("aider-shadow-cpp/task", 0.0, 0)
    bad["infrastructure_error"] = True
    with pytest.raises(integration_module.AiderRewardInfrastructureError, match="invalid reward"):
        integration_module.validate_aider_rollout_batch(
            SimpleNamespace(rollout_batch_size=1, n_samples_per_prompt=1),
            [[SimpleNamespace(reward=bad)]],
        )
