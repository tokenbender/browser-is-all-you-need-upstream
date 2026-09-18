"""Fixed-denominator, macro-averaged requirement scoring of trusted audit receipts.

Each required group is all-or-nothing. Assertion progress is diagnostic only:
fail-fast counts and candidate stdout never determine partial credit.
"""
from __future__ import annotations

from Reward_GRPO.topic_coverage.specs import TOPICS

SCORING_VERSION = "topic-family-v3"


def summarize_requirements(task_id: str, audit: dict) -> dict:
    topic = TOPICS[task_id]
    candidate = audit.get("candidate", {})
    if audit.get("reference_status") != "pass" or audit.get("status") not in {"pass", "fail"}:
        raise ValueError("requirement scores need a healthy reference and valid verdict")
    if candidate.get("status") != audit["status"]:
        raise ValueError("candidate verdict disagrees with audit")
    build = candidate.get("build", {})
    if candidate.get("reason") == "build_failure":
        if (audit["status"] != "fail" or build.get("returncode") in (None, 0)
                or build.get("timed_out") or build.get("launch_error") or candidate.get("groups")):
            raise ValueError("inconsistent topic build failure")
        statuses = {name: "fail" for name in topic.groups}
    else:
        if build.get("returncode") != 0 or build.get("timed_out") or build.get("launch_error"):
            raise ValueError("requirement scores need a completed build")
        groups = candidate.get("groups", [])
        if not isinstance(groups, list) or any(not isinstance(group, dict) for group in groups):
            raise ValueError("malformed requirement list")
        statuses = {group.get("group"): group.get("status") for group in groups}
        if len(statuses) != len(groups) or set(statuses) != set(topic.groups):
            raise ValueError("missing, duplicate or unexpected required group")
        if any(status not in {"pass", "fail"} for status in statuses.values()):
            raise ValueError("invalid required group")
        if (audit["status"] == "pass") != all(status == "pass" for status in statuses.values()):
            raise ValueError("required groups disagree with audit verdict")
    families = []
    for name, members in topic.families:
        passed = sum(statuses[group] == "pass" for group in members)
        families.append(dict(family=name, passed=passed, total=len(members),
                             fraction=passed / len(members)))
    return dict(version=SCORING_VERSION, aggregation="equal_families_equal_groups",
                fraction=sum(row["fraction"] for row in families) / len(families),
                passed_groups=sum(status == "pass" for status in statuses.values()),
                total_groups=len(topic.groups), families=families,
                build_failed=candidate.get("reason") == "build_failure")
