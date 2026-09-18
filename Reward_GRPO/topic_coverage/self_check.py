#!/usr/bin/env python3
"""Validate the static topic registry, probe coverage, and reward scoring."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from Reward_GRPO.topic_coverage.scoring import (  # noqa: E402
    SCORING_VERSION,
    summarize_requirements,
)
from Reward_GRPO.topic_coverage.specs import TOPICS  # noqa: E402


EXPECTED_TASKS = {
    "allergies",
    "bank-account",
    "circular-buffer",
    "clock",
    "complex-numbers",
    "dnd-character",
    "grade-school",
    "perfect-numbers",
    "space-age",
    "sublist",
    "yacht",
}


def receipt(task_id, failed=()):
    topic = TOPICS[task_id]
    groups = [
        {"group": group, "status": "fail" if group in failed else "pass"}
        for group in topic.groups
    ]
    status = "fail" if failed else "pass"
    return {
        "status": status,
        "reference_status": "pass",
        "candidate": {
            "status": status,
            "reason": "topic_checks",
            "build": {"returncode": 0},
            "groups": groups,
        },
    }


def main():
    failures = []
    probes = Path(__file__).with_name("probes")

    if set(TOPICS) != EXPECTED_TASKS:
        failures.append("topic registry does not contain the expected 11 tasks")
    if sum(len(topic.groups) for topic in TOPICS.values()) != 64:
        failures.append("topic registry does not contain 64 behavioral groups")
    if sum(len(topic.families) for topic in TOPICS.values()) != 39:
        failures.append("topic registry does not contain 39 reward families")
    if SCORING_VERSION != "topic-family-v3":
        failures.append("unexpected scoring version")

    for task_id, topic in TOPICS.items():
        if not (probes / f"{task_id}.cpp").is_file():
            failures.append(f"missing primary probe: {task_id}")
        for auxiliary in topic.auxiliary_sources:
            if not (probes / auxiliary).is_file():
                failures.append(f"missing auxiliary probe: {task_id}/{auxiliary}")

        complete = summarize_requirements(task_id, receipt(task_id))
        if complete["fraction"] != 1 or complete["total_groups"] != len(topic.groups):
            failures.append(f"complete scoring mismatch: {task_id}")

        first_group = topic.groups[0]
        partial = summarize_requirements(task_id, receipt(task_id, (first_group,)))
        if not 0 <= partial["fraction"] < 1:
            failures.append(f"partial scoring mismatch: {task_id}")

    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 1
    print(
        "PASS topic verifier contract: "
        "11 tasks, 64 groups, 39 families, all probes present"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
