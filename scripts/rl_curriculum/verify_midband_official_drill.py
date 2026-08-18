#!/usr/bin/env python3
"""Verify the five-family official mid-band drill pack end to end on GCC."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from glm47_posttraining.aider_polyglot.midband_official_drill import (  # noqa: E402
    CURRICULUM_NAME,
    TASKS,
    _evaluate,
    build_midband_official_drill,
)
from glm47_posttraining.aider_polyglot.parser import parse_whole_file_response  # noqa: E402
from glm47_posttraining.aider_polyglot.reward import compute_aider_reward  # noqa: E402
from glm47_posttraining.aider_polyglot.schema import (  # noqa: E402
    AiderPolyglotTask,
    AiderTestResult,
)


EXPECTED_COUNTS = {
    "allergies": 6,
    "diamond": 5,
    "grade-school": 3,
    "perfect-numbers": 5,
    "sublist": 3,
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def result_adapter(path: Path, files: dict[str, str], *, compiler: str) -> AiderTestResult:
    task_files = {
        name: (path / name).read_text(encoding="utf-8")
        for name in files
    }
    task_files.update(files)
    result = _evaluate(path, task_files, compiler=compiler)
    if result.stage == "pass":
        return AiderTestResult(
            status="passed",
            tests_passed=result.tests_passed,
            tests_total=result.tests_total,
        )
    if result.stage == "semantic-counterexample":
        return AiderTestResult(
            status="tests_failed",
            tests_passed=result.tests_passed,
            tests_total=result.tests_total,
            logs={"test": result.diagnostic},
        )
    return AiderTestResult(status="compile_failed", logs={"compile": result.diagnostic})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--compiler", default="g++")
    args = parser.parse_args()

    with TemporaryDirectory(prefix="issue112-midband-env-") as temporary:
        output = Path(temporary) / "dataset"
        paths = build_midband_official_drill(
            args.source,
            output,
            compiler=args.compiler,
            run_id="issue112-cpu-verification",
        )
        manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
        require(manifest["profile"] == CURRICULUM_NAME, "wrong curriculum")
        require(manifest["contract"]["task_families"] == list(TASKS), "family drift")
        require(manifest["contract"]["zero_held_out"] is True, "zero-held-out contract lost")
        require(manifest["contract"]["strict_binary_reward"] is True, "reward contract lost")
        require(manifest["composition"]["families"] == EXPECTED_COUNTS, "episode counts drifted")
        expected_total = sum(EXPECTED_COUNTS.values())
        require(manifest["counts"]["train"] == expected_total, "train count drifted")
        require(manifest["counts"]["sft_train"] == expected_total, "SFT count drifted")

        grpo_rows = [
            json.loads(line)
            for line in paths["grpo_train"].read_text(encoding="utf-8").splitlines()
            if line
        ]
        sft_rows = [
            json.loads(line)
            for line in paths["sft_train"].read_text(encoding="utf-8").splitlines()
            if line
        ]
        require(len(grpo_rows) == expected_total, "GRPO row count drifted")
        require(len(sft_rows) == expected_total, "SFT row count drifted")
        require(len({row["task_id"] for row in grpo_rows}) == expected_total, "duplicate task IDs")
        require(
            {row["task_id"] for row in grpo_rows} == {row["task_id"] for row in sft_rows},
            "GRPO/SFT task identity mismatch",
        )

        sft_by_task = {row["task_id"]: row for row in sft_rows}
        reward_receipts = []
        semantic_families = set()
        verification_rows = [
            json.loads(line)
            for line in paths["verification"].read_text(encoding="utf-8").splitlines()
            if line
        ]
        for receipt in verification_rows:
            if receipt["starter_rejected_as"] == "semantic-counterexample":
                semantic_families.add(receipt["family"])
        require(semantic_families == set(TASKS), "a family lacks a compiling semantic negative")

        for row in grpo_rows:
            metadata = row["metadata"]
            descriptor = output / metadata["task_path"]
            task = AiderPolyglotTask.read_json(descriptor)
            exercise = output / task.exercise_dir
            require(task.harness_kind == "official_cmake", "wrong harness")
            require("strict-binary-reward" in task.tags, "strict reward tag missing")
            require(not (exercise / ".meta").exists(), f"{task.task_id}: reference metadata leaked")
            prompt_text = json.dumps(row["prompt"], sort_keys=True)
            test_path = exercise / f"{task.family.replace('-', '_')}_test.cpp"
            require(test_path.is_file(), f"{task.task_id}: hidden test missing")
            require(sha256(test_path) == task.hidden_test_sha256, f"{task.task_id}: test hash drift")
            require(test_path.read_text(encoding="utf-8") not in prompt_text, f"{task.task_id}: test leaked")

            sft = sft_by_task[row["task_id"]]
            response = sft["messages"][-1]["content"]
            parsed = parse_whole_file_response(response, task.editable_files)
            require(parsed.format_valid, f"{task.task_id}: target format invalid")
            applied = {
                name: (exercise / name).read_text(encoding="utf-8")
                for name in task.editable_files
            }
            applied.update(parsed.files)
            target_result = _evaluate(exercise, applied, compiler=args.compiler)
            require(
                target_result.stage == "pass",
                f"{task.task_id}: serialized target failed: {target_result}",
            )
            require(
                sft["metadata"]["imitation_target_sha256"]
                == hashlib.sha256(response.encode()).hexdigest(),
                f"{task.task_id}: target hash drift",
            )

            passed = compute_aider_reward(
                task,
                exercise,
                response,
                runner=lambda path, files: result_adapter(path, files, compiler=args.compiler),
                strict_binary=True,
            )
            require(passed.reward == 1.0 and passed.reason == "passed", f"{task.task_id}: pass reward")
            empty = compute_aider_reward(
                task,
                exercise,
                "",
                runner=lambda path, files: result_adapter(path, files, compiler=args.compiler),
                strict_binary=True,
            )
            require(empty.reward == 0.0, f"{task.task_id}: empty reward")
            reward_receipts.append(
                {
                    "task_id": task.task_id,
                    "family": task.family,
                    "episode_kind": task.episode_kind,
                    "failure_signature": task.failure_signature,
                    "pass_reward": passed.reward,
                    "empty_reward": empty.reward,
                }
            )

        representative = AiderPolyglotTask.read_json(
            output / grpo_rows[0]["metadata"]["task_path"]
        )
        exercise = output / representative.exercise_dir
        malformed = "allergies.cpp\n```cpp\nnamespace allergies {```"
        malformed_result = compute_aider_reward(
            representative,
            exercise,
            malformed,
            runner=lambda path, files: result_adapter(path, files, compiler=args.compiler),
            strict_binary=True,
        )
        require(malformed_result.reward == 0.0, "malformed reward")

        summary = {
            "status": "passed",
            "kind": "issue112-midband-official-environment-verification",
            "curriculum": CURRICULUM_NAME,
            "families": list(TASKS),
            "family_episode_counts": EXPECTED_COUNTS,
            "tasks": expected_total,
            "imitation_rows": len(sft_rows),
            "strict_binary_reward": True,
            "reference_reward": 1.0,
            "no_edit_reward": 0.0,
            "malformed_reward": malformed_result.reward,
            "semantic_negative_families": sorted(semantic_families),
            "manifest_sha256": sha256(paths["manifest"]),
            "verification_sha256": sha256(paths["verification"]),
            "reward_receipts": reward_receipts,
        }
        print(json.dumps(summary, indent=2, sort_keys=True))
        print("ISSUE112_MIDBAND_OFFICIAL_ENVIRONMENT_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
