"""Miles bridge for Aider C++ RL task GRPO and official Aider Polyglot C++ evaluation."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Sequence

from glm47_posttraining.aider_polyglot.dataset import build_aider_polyglot_datasets
from glm47_posttraining.aider_polyglot.harness import (
    DEFAULT_AIDER_DOCKER_IMAGE,
    build_aider_sandbox_image,
    run_aider_tests,
    run_sandbox_preflight,
    run_aider_rl_tests,
)
from glm47_posttraining.aider_polyglot.parser import parse_whole_file_response
from glm47_posttraining.aider_polyglot.reward import AiderRewardBreakdown, compute_aider_reward
from glm47_posttraining.aider_polyglot.schema import AiderPolyglotTask


DEFAULT_DATA_ROOT_ENV = "GLM47_DATA_DIR"
SANDBOX_IMAGE_ENV = "GLM47_CPP_SANDBOX_IMAGE"
REWARD_WORKERS_ENV = "GLM47_CPP_REWARD_WORKERS"
INCLUDE_LOGS_ENV = "MILES_CPP_INCLUDE_LOGS"
DEFAULT_REWARD_WORKERS = 8


class AiderRewardInfrastructureError(RuntimeError):
    """Abort the rollout when a verifier result cannot be trusted."""


def run_response_contract_preflight() -> None:
    """Prove that Miles-retained GLM stop tokens cannot hide the final file."""

    parsed = parse_whole_file_response(
        "preflight.cpp\n```cpp\nint answer() { return 42; }\n```<|user|>",
        ["preflight.cpp"],
    )
    if parsed.files != {"preflight.cpp": "int answer() { return 42; }\n"}:
        raise RuntimeError("Aider response parser failed the retained-stop-token contract")


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

        harness_runner = (
            run_aider_rl_tests if task.harness_kind == "aider_cpp17" else run_aider_tests
        )

        def runner(path: Path, files: dict[str, str]):
            kwargs: dict[str, Any] = {
                "image": os.environ.get(SANDBOX_IMAGE_ENV, DEFAULT_AIDER_DOCKER_IMAGE)
            }
            if task.harness_kind == "aider_cpp17":
                kwargs["expected_test_sha256"] = task.hidden_test_sha256
            return harness_runner(path, files, **kwargs)

        breakdown = compute_aider_reward(
            task, exercise_dir, _sample_response(sample), runner=runner
        )
        return reward_record(sample, task, breakdown)
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
    record = {
        "score": breakdown.reward,
        "reward": breakdown.reward,
        "reason": breakdown.reason,
        "task_id": task.task_id,
        "problem_id": task.exercise,
        "split": task.split,
        "sample_index": _sample_index(sample),
        "rollout_id": getattr(sample, "rollout_id", None),
        "response": _sample_response(sample),
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


def _include_logs() -> bool:
    return os.environ.get(INCLUDE_LOGS_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


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

    expected_groups = int(
        os.environ.get("GLM47_AIDER_EXPECTED_TRAIN_GROUPS", getattr(args, "rollout_batch_size", 0))
    )
    expected_samples = int(
        os.environ.get(
            "GLM47_AIDER_EXPECTED_SAMPLES_PER_GROUP", getattr(args, "n_samples_per_prompt", 0)
        )
    )
    if len(data) != expected_groups:
        raise AiderRewardInfrastructureError(
            f"Aider rollout group count mismatch: {len(data)} != {expected_groups}"
        )

    group_records: list[dict[str, Any]] = []
    all_records: list[Mapping[str, Any]] = []
    sample_evidence: list[dict[str, Any]] = []
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
                "sample_count": len(typed_records),
                "positive_semantic_reward": positive_semantic_reward,
                "reward_values": sorted(set(scores)),
                "executed_tests_passed_values": sorted(set(executed_test_counts)),
            }
        )
        sample_evidence.extend(
            {
                "group_index": getattr(sample, "group_index", group_index),
                "sample_index": getattr(sample, "index", None),
                "task_id": record.get("task_id"),
                "response": str(getattr(sample, "response", "") or ""),
                "reward": dict(record),
            }
            for sample, record in zip(group, typed_records, strict=True)
        )
        all_records.extend(typed_records)

    if len({record["task_id"] for record in group_records}) != expected_groups:
        raise AiderRewardInfrastructureError("Aider rollout contains duplicate task groups")

    require_signal = os.environ.get("GLM47_AIDER_REQUIRE_SIGNAL", "0") == "1"
    semantic_variance_groups = sum(
        len(record["executed_tests_passed_values"]) > 1 for record in group_records
    )
    reward_variance_groups = sum(len(record["reward_values"]) > 1 for record in group_records)
    positive_groups = sum(record["positive_semantic_reward"] for record in group_records)
    format_valid = sum(record.get("format_valid") is True for record in all_records)
    parsed = [record for record in all_records if record.get("modified_files")]
    compiled = sum(
        isinstance(record.get("tests_total"), int) and record.get("tests_total", 0) > 0
        for record in parsed
    )
    exact_format_rate = format_valid / len(all_records)
    compile_rate = compiled / len(parsed) if parsed else 0.0
    output_dir_value = os.environ.get("GLM47_AIDER_SIGNAL_GATE_DIR")
    existing_receipts = (
        sorted(Path(output_dir_value).glob("signal_gate_passed_*.json"))
        if output_dir_value and Path(output_dir_value).is_dir()
        else []
    )
    apply_signal_requirements = require_signal and not existing_receipts
    if apply_signal_requirements:
        minimum_positive_groups = int(
            os.environ.get("GLM47_AIDER_MIN_POSITIVE_GROUPS", str(expected_groups))
        )
        minimum_semantic_variance = int(
            os.environ.get("GLM47_AIDER_MIN_SEMANTIC_VARIANCE_GROUPS", "2")
        )
        minimum_reward_variance = int(os.environ.get("GLM47_AIDER_MIN_REWARD_VARIANCE_GROUPS", "4"))
        minimum_format_rate = float(os.environ.get("GLM47_AIDER_MIN_EXACT_FORMAT_RATE", "0.75"))
        minimum_compile_rate = float(os.environ.get("GLM47_AIDER_MIN_COMPILE_RATE", "0.90"))
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
                    "failures": failures,
                    "group_count": len(group_records),
                    "samples_per_group": expected_samples,
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
        "group_count": len(group_records),
        "samples_per_group": expected_samples,
        "positive_groups": positive_groups,
        "semantic_variance_groups": semantic_variance_groups,
        "reward_variance_groups": reward_variance_groups,
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
    build.add_argument("--tasks-dir", required=True, help="checked-in Aider C++ RL rubric tree")
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
    build.add_argument("--sort-by-size", action="store_true")
    build.add_argument("--filter-train-oracle-full-marks", action="store_true")
    build.add_argument("--oracle-filter-workers", type=int, default=8)
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
        run_sandbox_preflight()
        print("AIDER_REWARD_SANDBOX_READY")
        return
    if args.filter_train_oracle_full_marks:
        raise ValueError(
            "the packaged Aider C++ RL corpus is already restricted to terminal oracle passes"
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
    )
    print(json.dumps({key: str(path) for key, path in paths.items()}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
