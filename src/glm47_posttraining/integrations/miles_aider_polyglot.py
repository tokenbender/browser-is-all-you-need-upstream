"""Miles bridge for shadow-task GRPO and official Aider Polyglot C++ evaluation."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Sequence

from glm47_posttraining.aider_polyglot.dataset import build_aider_polyglot_datasets
from glm47_posttraining.aider_polyglot.grpo_advantage_contract import (
    POLICY_VERSION as GRPO_ADVANTAGE_POLICY_VERSION,
    summarize_advantage_batch,
    summarize_group_advantages,
)
from glm47_posttraining.aider_polyglot.harness import (
    DEFAULT_AIDER_DOCKER_IMAGE,
    build_aider_sandbox_image,
    run_aider_tests,
    run_sandbox_preflight,
    run_shadow_hybrid45_tests,
    run_shadow_tests,
    run_shadow_weighted45_tests,
)
from glm47_posttraining.aider_polyglot.hybrid45 import validate_hybrid45_receipt
from glm47_posttraining.aider_polyglot.mef45 import validate_mef45_receipt
from glm47_posttraining.aider_polyglot.parser import (
    AiderResponseError,
    Glm47ResponseSegments,
    parse_whole_file_response,
    segment_glm47_response,
)
from glm47_posttraining.aider_polyglot.reward import (
    AiderRewardBreakdown,
    compute_aider_reward,
    compute_hybrid45_aider_reward,
    compute_hybrid45_mef_aider_reward,
    compute_production_aider_reward,
    compute_weighted45_aider_reward,
)
from glm47_posttraining.aider_polyglot.rollout_receipts import (
    CONTEXT_ISOLATION_ENV,
    MAX_PROMPT_TOKENS_ENV,
    build_context_identity,
    build_hidden_partition_accounting,
    context_group_key,
    validate_context_identity,
    validate_hidden_partition_accounting,
)
from glm47_posttraining.aider_polyglot.schema import (
    AiderPolyglotTask,
    HYBRID45_MEF_POLICY_VERSION,
    HYBRID45_POLICY_VERSION,
    WEIGHTED45_CHECK_IDS,
)


DEFAULT_DATA_ROOT_ENV = "GLM47_DATA_DIR"
SANDBOX_IMAGE_ENV = "GLM47_CPP_SANDBOX_IMAGE"
REWARD_WORKERS_ENV = "GLM47_CPP_REWARD_WORKERS"
INCLUDE_LOGS_ENV = "MILES_CPP_INCLUDE_LOGS"
REWARD_MODE_ENV = "MILES_AIDER_REWARD_MODE"
DEFAULT_REWARD_WORKERS = 8
HYBRID45_NO_UPDATE_RECEIPT_ENV = "GLM47_HYBRID45_NO_UPDATE_RECEIPT_PATH"


class AiderRewardInfrastructureError(RuntimeError):
    """Abort the rollout when a verifier result cannot be trusted."""


def run_response_contract_preflight() -> None:
    """Prove the pinned thinking and retained-stop-token response contract."""

    raw_response = (
        "draft reasoning\nCMakeLists.txt\n```cmake\nproject(unsafe)\n```\n"
        "preflight.cpp\n```cpp\nint answer() { return 0; }\n```\n"
        "</think>\npreflight.cpp\n```cpp\nint answer() { return 42; }\n```<|user|>"
    )
    segments = segment_glm47_response(raw_response)
    parsed = parse_whole_file_response(
        segments.final_answer,
        ["preflight.cpp"],
    )
    if not segments.thinking_boundary_applied or parsed.files != {
        "preflight.cpp": "int answer() { return 42; }\n"
    }:
        raise RuntimeError("Aider response parser failed the thinking/final-answer contract")


def run_hybrid45_no_update_canary(*, image: str) -> dict[str, Any]:
    """Exercise V2 endpoints and caps through the real sandbox without optimization."""

    with tempfile.TemporaryDirectory(prefix="hybrid45_no_update_") as root_value:
        root = Path(root_value)
        exercise = root / "probe"
        grader = exercise / ".grader"
        grader.mkdir(parents=True)
        header = "#pragma once\nint answer();\n"
        starter = '#include "answer.h"\nint answer() { return 0; }\n'
        (exercise / "answer.h").write_text(header, encoding="utf-8")
        (exercise / "answer.cpp").write_text(starter, encoding="utf-8")
        grader_source = (
            '#include "answer.h"\n'
            "int main() {\n"
            "  if (answer() != 42) return 1;\n"
            "  if (answer() + 1 != 43) return 2;\n"
            "  if (answer() - 1 != 41) return 3;\n"
            "  if (answer() * 2 != 84) return 4;\n"
            "  if (answer() / 2 != 21) return 5;\n"
            "  return 0;\n"
            "}\n"
        )
        grader_path = grader / "test.cpp"
        grader_path.write_text(grader_source, encoding="utf-8")
        grader_sha256 = hashlib.sha256(grader_source.encode()).hexdigest()
        task = AiderPolyglotTask(
            task_id="aider-hybrid45-preflight/probe",
            exercise="probe",
            split="train",
            harness_kind="aider_cpp17",
            exercise_dir="probe",
            editable_files=["answer.h", "answer.cpp"],
            prompt=[{"role": "user", "content": "Implement answer()."}],
            hidden_test_sha256=grader_sha256,
            prompt_contract="hybrid45-isolated-wholefile-v2",
            reward_contract=HYBRID45_POLICY_VERSION,
        )

        def runner(path: Path, files: dict[str, str]):
            return run_shadow_hybrid45_tests(
                path,
                files,
                image=image,
                expected_test_sha256=grader_sha256,
            )

        def response(source: str) -> str:
            return "answer.h\n```cpp\n" + header + "```\nanswer.cpp\n```cpp\n" + source + "```\n"

        controls = {
            "reference": compute_hybrid45_aider_reward(
                task,
                exercise,
                response('#include "answer.h"\nint answer() { return 42; }\n'),
                runner=runner,
            ),
            "no_op": compute_hybrid45_aider_reward(
                task,
                exercise,
                response(starter),
                runner=runner,
            ),
            "compile_failure": compute_hybrid45_aider_reward(
                task,
                exercise,
                response('#include "answer.h"\nint answer( { return 42; }\n'),
                runner=runner,
            ),
            "safety_bypass": compute_hybrid45_aider_reward(
                task,
                exercise,
                response(
                    '#include "answer.h"\n#include <cstdlib>\n'
                    'int answer() { return std::system("true"); }\n'
                ),
                runner=runner,
            ),
        }
        receipts = {name: result.hybrid45 for name, result in controls.items()}
        if any(receipt is None for receipt in receipts.values()):
            raise RuntimeError("Hybrid45 no-update canary did not produce every V2 receipt")
        typed = {name: receipt for name, receipt in receipts.items() if receipt is not None}
        for receipt in typed.values():
            validate_hybrid45_receipt(receipt.to_record())
        if (
            typed["reference"].optimizer_score != 1.0
            or typed["reference"].reachability_stage != 8
            or typed["no_op"].optimizer_score is None
            or typed["no_op"].optimizer_score > 0.0
            or typed["no_op"].optimizer_override != "no_op"
            or typed["compile_failure"].optimizer_score is None
            or typed["compile_failure"].optimizer_score > 0.0
            or typed["compile_failure"].optimizer_override != "compile_or_link"
            or typed["safety_bypass"].optimizer_score != -1.0
            or typed["safety_bypass"].optimizer_override != "forbidden"
        ):
            observed = {
                name: {
                    "optimizer_score": receipt.optimizer_score,
                    "reachability_stage": receipt.reachability_stage,
                    "optimizer_override": receipt.optimizer_override,
                    "primary_failure_kernel": receipt.primary_failure_kernel,
                }
                for name, receipt in typed.items()
            }
            raise RuntimeError(
                "Hybrid45 no-update canary endpoint/cap contract failed: "
                + json.dumps(observed, sort_keys=True)
            )

        payload = {
            "schema_version": "glm47-hybrid45-no-update-canary-v1",
            "decision": "PASS",
            "policy_version": HYBRID45_POLICY_VERSION,
            "optimizer_updates": 0,
            "verifier_image": image,
            "hidden_grader_sha256": grader_sha256,
            "controls": {
                name: {
                    "optimizer_score": receipt.optimizer_score,
                    "reachability_stage": receipt.reachability_stage,
                    "optimizer_override": receipt.optimizer_override,
                    "receipt_sha256": hashlib.sha256(
                        json.dumps(
                            receipt.to_record(),
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode()
                    ).hexdigest(),
                }
                for name, receipt in typed.items()
            },
        }
        output_value = os.environ.get(HYBRID45_NO_UPDATE_RECEIPT_ENV, "").strip()
        if output_value:
            output_path = Path(output_value)
            if output_path.exists() or output_path.is_symlink():
                raise FileExistsError(f"refusing to overwrite no-update receipt: {output_path}")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = output_path.with_suffix(output_path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            temporary.replace(output_path)
        return payload


def run_hybrid45_mef_no_update_canary(*, image: str) -> dict[str, Any]:
    """Exercise MEF endpoints and calibration through the real sandbox with zero updates."""

    with tempfile.TemporaryDirectory(prefix="hybrid45_mef_no_update_") as root_value:
        root = Path(root_value)
        header = "#pragma once\nint answer();\n"
        grader_source = (
            '#include "answer.h"\n'
            "int main() {\n"
            "  if (answer() != 42) return 1;\n"
            "  if (answer() + 1 != 43) return 2;\n"
            "  if (answer() - 1 != 41) return 3;\n"
            "  if (answer() * 2 != 84) return 4;\n"
            "  if (answer() / 2 != 21) return 5;\n"
            "  return 0;\n"
            "}\n"
        )
        grader_sha256 = hashlib.sha256(grader_source.encode()).hexdigest()

        def make_exercise(name: str, starter: str) -> Path:
            exercise = root / name
            grader = exercise / ".grader"
            grader.mkdir(parents=True)
            (exercise / "answer.h").write_text(header, encoding="utf-8")
            (exercise / "answer.cpp").write_text(starter, encoding="utf-8")
            (grader / "test.cpp").write_text(grader_source, encoding="utf-8")
            return exercise

        ordinary_starter = '#include "answer.h"\nint answer() { return 0; }\n'
        calibration_starter = '#include "answer.h"\nint answer() { return 42; }\n'
        ordinary_exercise = make_exercise("ordinary", ordinary_starter)
        calibration_exercise = make_exercise("calibration", calibration_starter)

        def task(name: str, role: str) -> AiderPolyglotTask:
            return AiderPolyglotTask(
                task_id=f"aider-hybrid45-mef-preflight/{name}",
                exercise=name,
                split="train",
                harness_kind="aider_cpp17",
                exercise_dir=name,
                editable_files=["answer.h", "answer.cpp"],
                prompt=[{"role": "user", "content": "Implement answer()."}],
                tags=[f"curriculum-role-{role}"],
                hidden_test_sha256=grader_sha256,
                prompt_contract="hybrid45-isolated-wholefile-v2",
                reward_contract=HYBRID45_MEF_POLICY_VERSION,
            )

        ordinary_task = task("ordinary", "ordinary")
        calibration_task = task("calibration", "calibration")

        def runner(path: Path, files: dict[str, str]):
            return run_shadow_hybrid45_tests(
                path,
                files,
                image=image,
                expected_test_sha256=grader_sha256,
            )

        def response(source: str) -> str:
            return "answer.h\n```cpp\n" + header + "```\nanswer.cpp\n```cpp\n" + source + "```\n"

        controls = {
            "reference": compute_hybrid45_mef_aider_reward(
                ordinary_task,
                ordinary_exercise,
                response('#include "answer.h"\nint answer() { return 42; }\n'),
                runner=runner,
            ),
            "ordinary_no_op": compute_hybrid45_mef_aider_reward(
                ordinary_task,
                ordinary_exercise,
                response(ordinary_starter),
                runner=runner,
            ),
            "syntax_failure": compute_hybrid45_mef_aider_reward(
                ordinary_task,
                ordinary_exercise,
                response('#include "answer.h"\nint answer( { return 42; }\n'),
                runner=runner,
            ),
            "link_failure": compute_hybrid45_mef_aider_reward(
                ordinary_task,
                ordinary_exercise,
                response('#include "answer.h"\n'),
                runner=runner,
            ),
            "safety_bypass": compute_hybrid45_mef_aider_reward(
                ordinary_task,
                ordinary_exercise,
                response(
                    '#include "answer.h"\n#include <cstdlib>\n'
                    'int answer() { return std::system("true"); }\n'
                ),
                runner=runner,
            ),
            "calibration_exact_no_change": compute_hybrid45_mef_aider_reward(
                calibration_task,
                calibration_exercise,
                response(calibration_starter),
                runner=runner,
            ),
            "calibration_unnecessary_change": compute_hybrid45_mef_aider_reward(
                calibration_task,
                calibration_exercise,
                response(
                    '#include "answer.h"\n// unnecessary rewrite\nint answer() { return 42; }\n'
                ),
                runner=runner,
            ),
        }
        if any(result.hybrid45 is None or result.mef45 is None for result in controls.values()):
            raise RuntimeError("MEF45 no-update canary did not produce every receipt")
        typed = {
            name: (result.hybrid45, result.mef45)
            for name, result in controls.items()
            if result.hybrid45 is not None and result.mef45 is not None
        }
        for base, projection in typed.values():
            validate_hybrid45_receipt(base.to_record())
            validate_mef45_receipt(projection.to_record(), base.to_record())
        scores = {name: projection.optimizer_score for name, (_base, projection) in typed.items()}
        if (
            scores.get("reference") != 1.0
            or scores.get("ordinary_no_op") != -0.35
            or scores.get("syntax_failure", 0.0) > -0.65
            or scores.get("link_failure", 0.0) > -0.65
            or scores.get("safety_bypass") != -1.0
            or scores.get("calibration_exact_no_change") != 1.0
            or scores.get("calibration_unnecessary_change") != -0.35
        ):
            raise RuntimeError(
                "MEF45 no-update canary endpoint contract failed: "
                + json.dumps(scores, sort_keys=True)
            )
        payload = {
            "schema_version": "glm47-hybrid45-mef-no-update-canary-v1",
            "decision": "PASS",
            "policy_version": HYBRID45_MEF_POLICY_VERSION,
            "base_policy_version": HYBRID45_POLICY_VERSION,
            "optimizer_updates": 0,
            "verifier_image": image,
            "hidden_grader_sha256": grader_sha256,
            "controls": {
                name: {
                    "optimizer_score": projection.optimizer_score,
                    "optimizer_override": projection.optimizer_override,
                    "base_receipt_sha256": projection.base_receipt_sha256,
                }
                for name, (_base, projection) in typed.items()
            },
        }
        output_value = os.environ.get(HYBRID45_NO_UPDATE_RECEIPT_ENV, "").strip()
        if output_value:
            output_path = Path(output_value)
            if output_path.exists() or output_path.is_symlink():
                raise FileExistsError(f"refusing to overwrite no-update receipt: {output_path}")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = output_path.with_suffix(output_path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            temporary.replace(output_path)
        return payload


async def reward_func(
    args: Any, sample: Any, **_kwargs: Any
) -> dict[str, Any] | list[dict[str, Any]]:
    """Miles custom reward hook for one sample or a batch."""

    if isinstance(sample, list):
        workers = max(1, min(len(sample), _reward_workers()))
        semaphore = asyncio.Semaphore(workers)

        async def score(item: Any) -> dict[str, Any]:
            async with semaphore:
                return await asyncio.to_thread(_score_sample, item)

        return list(await asyncio.gather(*(score(item) for item in sample)))
    return await asyncio.to_thread(_score_sample, sample)


def _score_sample(sample: Any) -> dict[str, Any]:
    metadata = _sample_metadata(sample)
    task_path_value = metadata.get("task_path")
    if not task_path_value:
        raise AiderRewardInfrastructureError(
            "Aider reward sample is missing required metadata.task_path"
        )
    try:
        task_path = _resolve_task_path(str(task_path_value), metadata)
        task = AiderPolyglotTask.read_json(task_path)
        exercise_dir = _resolve_exercise_dir(task_path, task.exercise_dir)
        raw_response = _sample_response(sample)
        try:
            segments = segment_glm47_response(raw_response)
        except AiderResponseError:
            # Let the production parser turn malformed/oversized raw text into
            # the same deterministic format failure as before segmentation.
            segments = Glm47ResponseSegments(
                final_answer=raw_response,
                thinking_boundary_applied=False,
            )

        reward_mode = _reward_mode()
        harness_runner = (
            run_shadow_hybrid45_tests
            if reward_mode in {"hybrid_bipolar45", "hybrid_bipolar45_mef"}
            and task.harness_kind in {"shadow_cpp17", "aider_cpp17"}
            else run_shadow_weighted45_tests
            if reward_mode == "weighted45" and task.harness_kind in {"shadow_cpp17", "aider_cpp17"}
            else run_shadow_tests
            if task.harness_kind in {"shadow_cpp17", "aider_cpp17"}
            else run_aider_tests
        )

        if (
            reward_mode in {"hybrid_bipolar45", "hybrid_bipolar45_mef"}
            and task.harness_kind == "official_cmake"
        ):
            raise AiderRewardInfrastructureError(
                "Hybrid45 V2/MEF requires five independently executable hidden partitions; "
                f"official_cmake is not admitted for {task.task_id}"
            )

        def runner(path: Path, files: dict[str, str]):
            kwargs: dict[str, Any] = {
                "image": os.environ.get(SANDBOX_IMAGE_ENV, DEFAULT_AIDER_DOCKER_IMAGE)
            }
            if task.harness_kind in {"shadow_cpp17", "aider_cpp17"}:
                kwargs["expected_test_sha256"] = task.hidden_test_sha256
            return harness_runner(path, files, **kwargs)

        if reward_mode == "weighted45":
            breakdown = compute_weighted45_aider_reward(
                task, exercise_dir, segments.final_answer, runner=runner
            )
        elif reward_mode == "hybrid_bipolar45":
            breakdown = compute_hybrid45_aider_reward(
                task, exercise_dir, segments.final_answer, runner=runner
            )
        elif reward_mode == "hybrid_bipolar45_mef":
            breakdown = compute_hybrid45_mef_aider_reward(
                task, exercise_dir, segments.final_answer, runner=runner
            )
        elif reward_mode in {"production", "production_ast17"}:
            breakdown = compute_production_aider_reward(
                task, exercise_dir, segments.final_answer, runner=runner
            )
        else:
            breakdown = compute_aider_reward(
                task, exercise_dir, segments.final_answer, runner=runner
            )
        return reward_record(
            sample,
            task,
            breakdown,
            task_path=task_path,
            exercise_dir=exercise_dir,
            scored_response=segments.final_answer,
            thinking_boundary_applied=segments.thinking_boundary_applied,
        )
    except AiderRewardInfrastructureError:
        raise
    except Exception as exc:
        task_id = metadata.get("task_id") or metadata.get("problem_id") or task_path_value
        raise AiderRewardInfrastructureError(
            f"Aider reward verification failed for {task_id}: {type(exc).__name__}: {exc}"
        ) from exc


def reward_record(
    sample: Any,
    task: AiderPolyglotTask,
    breakdown: AiderRewardBreakdown,
    *,
    task_path: Path | None = None,
    exercise_dir: Path | None = None,
    scored_response: str | None = None,
    thinking_boundary_applied: bool = False,
) -> dict[str, Any]:
    harness = breakdown.harness
    parsed = breakdown.parsed
    if breakdown.infrastructure_error or (harness and harness.status == "infrastructure_error"):
        raise AiderRewardInfrastructureError(
            f"refusing numeric reward for verifier infrastructure failure: {task.task_id}"
        )
    if not math.isfinite(breakdown.reward):
        raise AiderRewardInfrastructureError(
            f"refusing non-finite Aider reward for {task.task_id}: {breakdown.reward}"
        )
    if breakdown.reason in {"reward_exception", "infrastructure_error", "missing_task_path"}:
        raise AiderRewardInfrastructureError(
            f"refusing infrastructure reason as an Aider reward: {breakdown.reason}"
        )
    raw_response = _sample_response(sample)
    consumer_response = raw_response if scored_response is None else scored_response
    record = {
        "score": breakdown.reward,
        "reward": breakdown.reward,
        "reward_mode": _reward_mode(),
        "reason": breakdown.reason,
        "task_id": task.task_id,
        "problem_id": task.exercise,
        "split": task.split,
        "sample_index": _sample_index(sample),
        "rollout_id": getattr(sample, "rollout_id", None),
        "response": raw_response,
        "response_contract": "glm47-thinking-final-answer-v1",
        "scored_response_sha256": hashlib.sha256(consumer_response.encode("utf-8")).hexdigest(),
        "thinking_boundary_applied": thinking_boundary_applied,
        "format_valid": bool(parsed.format_valid) if parsed else False,
        "modified_files": sorted(parsed.files) if parsed else [],
        "tests_passed": harness.tests_passed if harness else 0,
        "tests_total": harness.tests_total if harness else 0,
        "all_tests_pass": bool(harness.all_tests_pass) if harness else False,
        "compile_error": bool(harness and harness.status == "compile_failed"),
        "timeout": bool(harness and harness.status == "candidate_timeout"),
        "candidate_returncode": harness.candidate_returncode if harness else None,
        "infrastructure_error": breakdown.infrastructure_error,
        "hidden_test_sha256": task.hidden_test_sha256,
        "verification_gate": task.verification_gate,
    }
    if task_path is not None and exercise_dir is not None:
        receipt_workspace_id = None
        if harness is None or not harness.verification_workspace_id:
            with tempfile.TemporaryDirectory(prefix="aider_receipt_") as workspace:
                receipt_workspace_id = hashlib.sha256(
                    str(Path(workspace).resolve()).encode("utf-8")
                ).hexdigest()
        context_identity = build_context_identity(
            sample=sample,
            task=task,
            task_path=task_path,
            exercise_dir=exercise_dir,
            raw_response=raw_response,
            scored_response=consumer_response,
            harness=harness,
            receipt_workspace_id=receipt_workspace_id,
        )
        record["context_identity"] = context_identity
        record["logical_task_id"] = context_identity["logical_task_id"]
    else:
        context_identity = None
    for name in ("s_aider", "s_ast17", "s_style", "anti_bloat", "line_count"):
        value = getattr(breakdown, name, None)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            record[name] = value
    ast17_checks = getattr(breakdown, "ast17_checks", None)
    if isinstance(ast17_checks, dict):
        record["ast17_checks"] = ast17_checks
    weighted45 = getattr(breakdown, "weighted45", None)
    if weighted45 is not None:
        record["weighted45"] = weighted45.to_record()
    hybrid45 = getattr(breakdown, "hybrid45", None)
    if hybrid45 is not None:
        record["hybrid45"] = hybrid45.to_record()
        record.update(
            {
                "policy_version": hybrid45.policy_version,
                "binary_score": hybrid45.binary_score,
                "reachability_stage": hybrid45.reachability_stage,
                "discrete_score": hybrid45.discrete_score,
                "semantic_applicable": hybrid45.semantic_applicable,
                "continuous_semantic_score": hybrid45.continuous_semantic_score,
                "optimizer_score": hybrid45.optimizer_score,
                "primary_failure_kernel": hybrid45.primary_failure_kernel,
            }
        )
        if context_identity is not None:
            record["hidden_partition_accounting"] = build_hidden_partition_accounting(
                context_identity, record["hybrid45"]
            )
    mef45 = getattr(breakdown, "mef45", None)
    if mef45 is not None:
        record["mef45"] = mef45.to_record()
        record.update(
            {
                "policy_version": mef45.policy_version,
                "optimizer_score": mef45.optimizer_score,
                "curriculum_role": mef45.curriculum_role,
                "mef_optimizer_override": mef45.optimizer_override,
                "base_optimizer_score": mef45.base_optimizer_score,
            }
        )
    if harness and _include_logs():
        record["logs"] = harness.logs
    elif harness:
        record["log_keys"] = sorted(harness.logs)
    return record


def _sample_metadata(sample: Any) -> dict[str, Any]:
    metadata = (
        sample.get("metadata") if isinstance(sample, dict) else getattr(sample, "metadata", None)
    )
    return metadata if isinstance(metadata, dict) else {}


def _sample_response(sample: Any) -> str:
    value = sample.get("response") if isinstance(sample, dict) else getattr(sample, "response", "")
    return str(value or "")


def _sample_index(sample: Any) -> int | None:
    value = sample.get("index") if isinstance(sample, dict) else getattr(sample, "index", None)
    return int(value) if isinstance(value, int) else None


def _resolve_task_path(task_path: str, metadata: dict[str, Any]) -> Path:
    path = Path(task_path)
    if path.is_absolute():
        return path
    for root in (metadata.get("task_root"), os.environ.get(DEFAULT_DATA_ROOT_ENV), Path.cwd()):
        if root:
            candidate = Path(root) / path
            if candidate.exists():
                return candidate
    return Path.cwd() / path


def _resolve_exercise_dir(task_path: Path, exercise_dir: str) -> Path:
    for root in task_path.parents:
        candidate = root / exercise_dir
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(f"cannot resolve {exercise_dir} from descriptor {task_path}")


def _reward_workers() -> int:
    try:
        return max(1, int(os.environ.get(REWARD_WORKERS_ENV, DEFAULT_REWARD_WORKERS)))
    except ValueError:
        return DEFAULT_REWARD_WORKERS


def _reward_mode() -> str:
    return os.environ.get(REWARD_MODE_ENV, "textbook").strip().lower()


def _include_logs() -> bool:
    return os.environ.get(INCLUDE_LOGS_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _int_env_or_default(name: str, default: Any) -> int:
    value = os.environ.get(name, "")
    raw = default if value.strip() == "" else value
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise AiderRewardInfrastructureError(f"{name} must be an integer, got {raw!r}") from exc


def _write_signal_gate_receipt(
    output_dir_value: str | None, receipt: dict[str, Any], *, status: str
) -> Path | None:
    if not output_dir_value:
        return None
    output_dir = Path(output_dir_value)
    output_dir.mkdir(parents=True, exist_ok=True)
    canonical = json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    receipt["batch_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    output = output_dir / f"signal_gate_{status}_{receipt['batch_sha256'][:16]}.json"
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
    return output


def validate_aider_rollout_batch(args: Any, data: list[list[Any]]) -> None:
    """Fail before log-prob recomputation or optimization when a rollout is untrustworthy."""

    expected_groups = _int_env_or_default(
        "GLM47_AIDER_EXPECTED_TRAIN_GROUPS", getattr(args, "rollout_batch_size", 0)
    )
    expected_samples = _int_env_or_default(
        "GLM47_AIDER_EXPECTED_SAMPLES_PER_GROUP", getattr(args, "n_samples_per_prompt", 0)
    )
    require_context_isolation = os.environ.get(CONTEXT_ISOLATION_ENV, "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    maximum_prompt_tokens = _int_env_or_default(MAX_PROMPT_TOKENS_ENV, 2048)
    require_signal = os.environ.get("GLM47_AIDER_REQUIRE_SIGNAL", "0") == "1"
    optimizer_policy = os.environ.get("MILES_GRPO_ADVANTAGE_POLICY", "").strip()
    if (require_signal or require_context_isolation) and (
        optimizer_policy != GRPO_ADVANTAGE_POLICY_VERSION
    ):
        raise AiderRewardInfrastructureError(
            "signal-gated or context-isolated Aider rollout requires optimizer policy "
            f"{GRPO_ADVANTAGE_POLICY_VERSION}"
        )

    if len(data) != expected_groups:
        raise AiderRewardInfrastructureError(
            f"Aider rollout group count mismatch: {len(data)} != {expected_groups}"
        )

    group_records: list[dict[str, Any]] = []
    all_records: list[Mapping[str, Any]] = []
    sample_evidence: list[dict[str, Any]] = []
    reward_groups: list[list[float]] = []
    for group_index, group in enumerate(data):
        if not isinstance(group, list) or len(group) != expected_samples:
            raise AiderRewardInfrastructureError(
                f"Aider rollout group {group_index} sample count mismatch"
            )
        records = [getattr(sample, "reward", None) for sample in group]
        if not all(isinstance(record, Mapping) for record in records):
            raise AiderRewardInfrastructureError(
                f"Aider rollout group {group_index} contains a non-mapping reward"
            )
        typed_records = [record for record in records if isinstance(record, Mapping)]
        task_ids = {record.get("task_id") for record in typed_records}
        if len(task_ids) != 1 or not all(isinstance(task_id, str) for task_id in task_ids):
            raise AiderRewardInfrastructureError(
                f"Aider rollout group {group_index} does not bind exactly one task"
            )
        logical_task_ids = {
            record.get("logical_task_id") or record.get("problem_id") or record.get("task_id")
            for record in typed_records
        }
        if len(logical_task_ids) != 1 or not all(
            isinstance(task_id, str) and task_id for task_id in logical_task_ids
        ):
            raise AiderRewardInfrastructureError(
                f"Aider rollout group {group_index} does not bind one logical task lineage"
            )
        context_identity_sha256 = None
        if require_context_isolation:
            contexts: list[Mapping[str, Any]] = []
            try:
                for record in typed_records:
                    context = record.get("context_identity")
                    if not isinstance(context, Mapping):
                        raise ValueError("context identity is missing")
                    validate_context_identity(context, maximum_prompt_tokens=maximum_prompt_tokens)
                    if record.get("reward_mode") in {
                        "hybrid_bipolar45",
                        "hybrid_bipolar45_mef",
                    }:
                        partition_accounting = record.get("hidden_partition_accounting")
                        if not isinstance(partition_accounting, Mapping):
                            raise ValueError("hidden partition accounting is missing")
                        validate_hidden_partition_accounting(partition_accounting)
                    contexts.append(context)
            except Exception as exc:
                raise AiderRewardInfrastructureError(
                    f"Aider rollout group {group_index} has invalid context isolation: {exc}"
                ) from exc
            group_keys = {context_group_key(context) for context in contexts}
            if len(group_keys) != 1:
                raise AiderRewardInfrastructureError(
                    f"Aider rollout group {group_index} mixes task or prompt identities"
                )
            workspace_ids = [context.get("verification_workspace_id") for context in contexts]
            if (
                len(workspace_ids) != expected_samples
                or len(set(workspace_ids)) != expected_samples
            ):
                raise AiderRewardInfrastructureError(
                    f"Aider rollout group {group_index} reuses a verifier workspace"
                )
            response_hashes = [context.get("raw_response_sha256") for context in contexts]
            if len(response_hashes) != expected_samples or any(
                not isinstance(value, str) or not value for value in response_hashes
            ):
                raise AiderRewardInfrastructureError(
                    f"Aider rollout group {group_index} lacks response hashes"
                )
            sample_indices = [context.get("sample_index") for context in contexts]
            if (
                len(sample_indices) != expected_samples
                or len(set(sample_indices)) != expected_samples
            ):
                raise AiderRewardInfrastructureError(
                    f"Aider rollout group {group_index} reuses a sample index"
                )
            context_identity_sha256 = hashlib.sha256(
                json.dumps(
                    list(next(iter(group_keys))),
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
        scores: list[float] = []
        executed_test_counts: list[int] = []
        positive_semantic_reward = False
        for record in typed_records:
            score = record.get("score")
            reason = record.get("reason")
            if (
                isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not math.isfinite(float(score))
                or record.get("infrastructure_error") is not False
                or reason in {"reward_exception", "infrastructure_error", "missing_task_path"}
            ):
                raise AiderRewardInfrastructureError(
                    f"Aider rollout group {group_index} contains an invalid reward: {record}"
                )
            if record.get("reward_mode") == "weighted45":
                weighted45 = record.get("weighted45")
                weighted_checks = (
                    weighted45.get("checks") if isinstance(weighted45, Mapping) else None
                )
                if (
                    not isinstance(weighted_checks, Mapping)
                    or set(weighted_checks) != WEIGHTED45_CHECK_IDS
                    or any(not isinstance(value, bool) for value in weighted_checks.values())
                ):
                    raise AiderRewardInfrastructureError(
                        f"Aider rollout group {group_index} lacks the exact 45-check receipt"
                    )
            if record.get("reward_mode") in {"hybrid_bipolar45", "hybrid_bipolar45_mef"}:
                hybrid45 = record.get("hybrid45")
                if not isinstance(hybrid45, Mapping):
                    raise AiderRewardInfrastructureError(
                        f"Aider rollout group {group_index} lacks the Hybrid45 V2 receipt"
                    )
                try:
                    validated_hybrid = validate_hybrid45_receipt(hybrid45)
                except Exception as exc:
                    raise AiderRewardInfrastructureError(
                        f"Aider rollout group {group_index} has an invalid "
                        f"{HYBRID45_POLICY_VERSION} receipt: {exc}"
                    ) from exc
                expected_score = validated_hybrid.optimizer_score
                if record.get("reward_mode") == "hybrid_bipolar45_mef":
                    mef45 = record.get("mef45")
                    if not isinstance(mef45, Mapping):
                        raise AiderRewardInfrastructureError(
                            f"Aider rollout group {group_index} lacks the MEF45 receipt"
                        )
                    try:
                        validated_mef = validate_mef45_receipt(mef45, hybrid45)
                    except Exception as exc:
                        raise AiderRewardInfrastructureError(
                            f"Aider rollout group {group_index} has an invalid "
                            f"{HYBRID45_MEF_POLICY_VERSION} receipt: {exc}"
                        ) from exc
                    expected_score = validated_mef.optimizer_score
                    if record.get("curriculum_role") != validated_mef.curriculum_role:
                        raise AiderRewardInfrastructureError(
                            f"Aider rollout group {group_index} curriculum role drift"
                        )
                if expected_score is None or not math.isclose(
                    float(score), float(expected_score), abs_tol=1e-9
                ):
                    raise AiderRewardInfrastructureError(
                        f"Aider rollout group {group_index} score does not match "
                        "the versioned Hybrid45 optimizer projection"
                    )
            tests_passed = record.get("tests_passed")
            tests_total = record.get("tests_total")
            if (
                isinstance(tests_passed, bool)
                or not isinstance(tests_passed, int)
                or isinstance(tests_total, bool)
                or not isinstance(tests_total, int)
            ):
                raise AiderRewardInfrastructureError(
                    f"Aider rollout group {group_index} lacks integer test counts"
                )
            scores.append(float(score))
            if tests_total > 0:
                executed_test_counts.append(tests_passed)
                positive_semantic_reward = positive_semantic_reward or tests_passed > 0
        group_records.append(
            {
                "task_id": next(iter(task_ids)),
                "logical_task_id": next(iter(logical_task_ids)),
                "context_identity_sha256": context_identity_sha256,
                "sample_count": len(typed_records),
                "advantage_telemetry": (
                    summarize_group_advantages(scores) if len(scores) >= 2 else None
                ),
                "positive_semantic_reward": positive_semantic_reward,
                "reward_values": sorted(set(scores)),
                "executed_tests_passed_values": sorted(set(executed_test_counts)),
                "hybrid45_kernel_vectors": sorted(
                    {
                        tuple(
                            int(record["hybrid45"]["kernels"][check_id])
                            for check_id in sorted(WEIGHTED45_CHECK_IDS)
                        )
                        for record in typed_records
                        if record.get("reward_mode") in {"hybrid_bipolar45", "hybrid_bipolar45_mef"}
                        and isinstance(record.get("hybrid45"), Mapping)
                    }
                ),
            }
        )
        reward_groups.append(scores)
        sample_evidence.extend(
            {
                "group_index": getattr(sample, "group_index", group_index),
                "sample_index": getattr(sample, "index", None),
                "task_id": record.get("task_id"),
                "logical_task_id": record.get("logical_task_id")
                or record.get("problem_id")
                or record.get("task_id"),
                "response_sha256": hashlib.sha256(
                    str(getattr(sample, "response", "") or "").encode("utf-8")
                ).hexdigest(),
                "reward_sha256": hashlib.sha256(
                    json.dumps(dict(record), sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest(),
                "context_identity": record.get("context_identity"),
                "hidden_partition_accounting": record.get("hidden_partition_accounting"),
                "termination_reason": (
                    record.get("termination_reason")
                    or getattr(sample, "termination_reason", None)
                    or getattr(sample, "finish_reason", None)
                    or (
                        getattr(sample, "metadata", {}).get("termination_reason")
                        if isinstance(getattr(sample, "metadata", None), Mapping)
                        else None
                    )
                    or "unknown"
                ),
            }
            for sample, record in zip(group, typed_records, strict=True)
        )
        all_records.extend(typed_records)

    require_unique_task_groups = os.environ.get(
        "GLM47_AIDER_REQUIRE_UNIQUE_TASK_GROUPS",
        "1" if os.environ.get("GLM47_AIDER_REQUIRE_SIGNAL", "0") == "1" else "0",
    ).strip().lower() in {"1", "true", "yes", "on"}
    if (
        require_unique_task_groups
        and len({record["logical_task_id"] for record in group_records}) != expected_groups
    ):
        raise AiderRewardInfrastructureError("Aider rollout contains duplicate logical task groups")

    if require_signal and not require_unique_task_groups:
        raise AiderRewardInfrastructureError(
            "signal-gated Aider rollout requires unique logical task groups"
        )
    semantic_variance_groups = sum(
        len(record["executed_tests_passed_values"]) > 1 for record in group_records
    )
    reward_variance_groups = sum(len(record["reward_values"]) > 1 for record in group_records)
    kernel_variance_groups = sum(
        len(record["hybrid45_kernel_vectors"]) > 1 for record in group_records
    )
    hybrid45_groups = sum(bool(record["hybrid45_kernel_vectors"]) for record in group_records)
    zero_reward_variance_groups = sum(len(record["reward_values"]) == 1 for record in group_records)
    positive_groups = sum(record["positive_semantic_reward"] for record in group_records)
    format_valid = sum(record.get("format_valid") is True for record in all_records)
    parsed = [record for record in all_records if record.get("modified_files")]
    compiled = sum(
        record.get("compile_error") is False
        and isinstance(record.get("tests_total"), int)
        and record.get("tests_total", 0) > 0
        for record in parsed
    )
    exact_format_rate = format_valid / len(all_records)
    compile_rate = compiled / len(parsed) if parsed else 0.0
    advantage_telemetry = (
        summarize_advantage_batch(reward_groups)
        if all(len(group) >= 2 for group in reward_groups)
        else {
            "policy_version": GRPO_ADVANTAGE_POLICY_VERSION,
            "status": "not_applicable",
            "group_count": len(reward_groups),
            "reason": "fewer_than_two_samples_per_group",
        }
    )
    termination_reasons: dict[str, int] = {}
    for sample in sample_evidence:
        reason = str(sample["termination_reason"])
        termination_reasons[reason] = termination_reasons.get(reason, 0) + 1
    output_dir_value = os.environ.get("GLM47_AIDER_SIGNAL_GATE_DIR")
    existing_receipts = (
        sorted(Path(output_dir_value).glob("signal_gate_*.json"))
        if output_dir_value and Path(output_dir_value).is_dir()
        else []
    )
    apply_signal_requirements = require_signal
    minimum_positive_groups = int(os.environ.get("GLM47_AIDER_MIN_POSITIVE_GROUPS", "1"))
    minimum_semantic_variance = int(os.environ.get("GLM47_AIDER_MIN_SEMANTIC_VARIANCE_GROUPS", "2"))
    minimum_reward_variance = int(os.environ.get("GLM47_AIDER_MIN_REWARD_VARIANCE_GROUPS", "2"))
    minimum_kernel_variance = int(os.environ.get("GLM47_AIDER_MIN_KERNEL_VARIANCE_GROUPS", "2"))
    minimum_format_rate = float(os.environ.get("GLM47_AIDER_MIN_EXACT_FORMAT_RATE", "0.50"))
    minimum_compile_rate = float(os.environ.get("GLM47_AIDER_MIN_COMPILE_RATE", "0.20"))
    thresholds = {
        "minimum_positive_groups": minimum_positive_groups,
        "minimum_semantic_variance_groups": minimum_semantic_variance,
        "minimum_reward_variance_groups": minimum_reward_variance,
        "minimum_kernel_variance_groups": minimum_kernel_variance,
        "require_unique_task_groups": require_unique_task_groups,
        "minimum_exact_format_rate": minimum_format_rate,
        "minimum_compile_rate": minimum_compile_rate,
    }
    if apply_signal_requirements:
        failures = []
        if positive_groups < minimum_positive_groups:
            failures.append(f"positive_groups={positive_groups}<{minimum_positive_groups}")
        if semantic_variance_groups < minimum_semantic_variance:
            failures.append(
                f"semantic_variance_groups={semantic_variance_groups}<{minimum_semantic_variance}"
            )
        if reward_variance_groups < minimum_reward_variance:
            failures.append(
                f"reward_variance_groups={reward_variance_groups}<{minimum_reward_variance}"
            )
        if hybrid45_groups and kernel_variance_groups < minimum_kernel_variance:
            failures.append(
                f"kernel_variance_groups={kernel_variance_groups}<{minimum_kernel_variance}"
            )
        if exact_format_rate < minimum_format_rate:
            failures.append(f"exact_format_rate={exact_format_rate:.6f}<{minimum_format_rate}")
        if compile_rate < minimum_compile_rate:
            failures.append(f"compile_rate={compile_rate:.6f}<{minimum_compile_rate}")
        if failures:
            evidence_text = json.dumps(
                sample_evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            )
            _write_signal_gate_receipt(
                output_dir_value,
                {
                    "schema_version": 1,
                    "kind": "glm47-aider-pre-optimizer-signal-gate",
                    "status": "failed",
                    "sequence": len(existing_receipts),
                    "signal_requirements_applied": True,
                    "thresholds": thresholds,
                    "failures": failures,
                    "group_count": len(group_records),
                    "samples_per_group": expected_samples,
                    "optimizer_policy": optimizer_policy,
                    "advantage_telemetry": advantage_telemetry,
                    "termination_reasons": termination_reasons,
                    "sample_evidence_sha256": hashlib.sha256(evidence_text.encode()).hexdigest(),
                    "groups": sorted(group_records, key=lambda record: str(record["task_id"])),
                    "samples": sample_evidence,
                },
                status="failed",
            )
            raise AiderRewardInfrastructureError(
                "Aider rollout failed the pre-optimizer signal gate: " + ", ".join(failures)
            )

    evidence_text = json.dumps(
        sample_evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    receipt = {
        "schema_version": 1,
        "kind": "glm47-aider-pre-optimizer-signal-gate",
        "status": "passed",
        "sequence": len(existing_receipts),
        "signal_requirements_applied": apply_signal_requirements,
        "thresholds": thresholds,
        "group_count": len(group_records),
        "samples_per_group": expected_samples,
        "optimizer_policy": optimizer_policy or "legacy-unbound",
        "advantage_telemetry": advantage_telemetry,
        "termination_reasons": termination_reasons,
        "positive_groups": positive_groups,
        "semantic_variance_groups": semantic_variance_groups,
        "reward_variance_groups": reward_variance_groups,
        "kernel_variance_groups": kernel_variance_groups,
        "hybrid45_groups": hybrid45_groups,
        "zero_reward_variance_groups": zero_reward_variance_groups,
        "exact_format_rate": exact_format_rate,
        "compile_rate": compile_rate,
        "sample_evidence_sha256": hashlib.sha256(evidence_text.encode()).hexdigest(),
        "groups": sorted(group_records, key=lambda record: str(record["task_id"])),
    }
    _write_signal_gate_receipt(output_dir_value, receipt, status="passed")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build-data")
    build.add_argument("--tasks-dir", required=True, help="checked-in Aider shadow rubric tree")
    build.add_argument("--out", required=True)
    build.add_argument("--train-limit", type=int)
    build.add_argument("--eval-limit", type=int, help="training-task monitor size")
    build.add_argument(
        "--task-split-file",
        help="JSON file with exact train_task_ids and monitor_task_ids arrays",
    )
    build.add_argument("--eval-splits", default="validation,test")
    build.add_argument("--profile", default="aider-polyglot-cpp")
    build.add_argument("--run-id")
    build.add_argument(
        "--reward-policy",
        choices=("weighted45-v1", "hybrid-bipolar45-v2"),
        default="weighted45-v1",
        help="versioned dataset/reward contract; V2 remains canary-only",
    )
    build.add_argument("--sort-by-size", action="store_true")
    build.add_argument("--filter-train-oracle-full-marks", action="store_true")
    build.add_argument(
        "--oracle-workers",
        "--oracle-filter-workers",
        dest="oracle_workers",
        type=int,
        default=8,
        help="parallel workers for mandatory C++17/C++20 oracle certification",
    )
    build.add_argument("--oracle-cache-dir")
    build.add_argument("--force", action="store_true")
    image = subparsers.add_parser("build-image")
    image.add_argument("--image", default=DEFAULT_AIDER_DOCKER_IMAGE)
    subparsers.add_parser("preflight")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    if args.command == "build-image":
        result = build_aider_sandbox_image(image=args.image)
        print(result.stdout, end="")
        if result.returncode != 0:
            raise SystemExit(result.stderr or result.returncode)
        return
    if args.command == "preflight":
        run_response_contract_preflight()
        image = os.environ.get(SANDBOX_IMAGE_ENV, "").strip()
        if not image:
            raise RuntimeError(f"{SANDBOX_IMAGE_ENV} must bind the prebuilt verifier image")
        preflight_kwargs: dict[str, Any] = {"image": image}
        if "GLM47_CPP_TSAN_PREFLIGHT_REQUIRED" in os.environ:
            preflight_kwargs["require_tsan"] = (
                os.environ["GLM47_CPP_TSAN_PREFLIGHT_REQUIRED"] != "0"
            )
        run_sandbox_preflight(**preflight_kwargs)
        if _reward_mode() == "hybrid_bipolar45":
            receipt = run_hybrid45_no_update_canary(image=image)
            print(json.dumps(receipt, sort_keys=True))
        elif _reward_mode() == "hybrid_bipolar45_mef":
            receipt = run_hybrid45_mef_no_update_canary(image=image)
            print(json.dumps(receipt, sort_keys=True))
        print("AIDER_REWARD_SANDBOX_READY")
        return
    if args.filter_train_oracle_full_marks:
        raise ValueError(
            "the packaged shadow corpus is already restricted to terminal oracle passes"
        )
    train_task_ids = None
    monitor_task_ids = None
    if args.task_split_file:
        split = json.loads(Path(args.task_split_file).read_text(encoding="utf-8"))
        if not isinstance(split, dict):
            raise ValueError("task split file must contain a JSON object")
        train_task_ids = split.get("train_task_ids")
        monitor_task_ids = split.get("monitor_task_ids")
        if not isinstance(train_task_ids, list) or not all(
            isinstance(value, str) for value in train_task_ids
        ):
            raise ValueError("task split train_task_ids must be an array of strings")
        if not isinstance(monitor_task_ids, list) or not all(
            isinstance(value, str) for value in monitor_task_ids
        ):
            raise ValueError("task split monitor_task_ids must be an array of strings")
    paths = build_aider_polyglot_datasets(
        args.tasks_dir,
        args.out,
        train_limit=args.train_limit,
        monitor_limit=args.eval_limit or 32,
        train_task_ids=train_task_ids,
        monitor_task_ids=monitor_task_ids,
        profile=args.profile,
        run_id=args.run_id,
        sort_by_size=args.sort_by_size,
        force=args.force,
        oracle_workers=args.oracle_workers,
        oracle_cache_dir=args.oracle_cache_dir,
        reward_policy=args.reward_policy,
    )
    print(json.dumps({key: str(path) for key, path in paths.items()}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
