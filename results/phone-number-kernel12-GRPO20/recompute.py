#!/usr/bin/env python3


from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import statistics
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SEED = 20260805
REPLICATES = 100_000
EXPECTED_RECEIPTS = {
    "a1": "823dc7ac78b390e626aecc6f783dbba1176a93742aa64fe677893068da1a8f08",
    "a2": "2ffe1a8921ecb518a975de0ff71a12595698d0be65f474aa407376d63fc1b965",
    "a3": "756aafd73ff4c3caba58bf0d64f4134a29f7fec9976461cb711066bd780b44e0",
    "a4": "faf0afabb7b2c0e7e3391934c99f441c98c90ffdacd43dd07e0f41de72407075",
}
EXPECTED_FIRST = [11, 12, 11, 11]
EXPECTED_FINAL = [15, 15, 15, 16]


def percentile(values: list[float], probability: float) -> float:
    position = probability * (len(values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    weight = position - lower
    return values[lower] * (1 - weight) + values[upper] * weight


def load_trials() -> dict[str, dict]:
    trials = {}
    identity = None
    for trial, expected_hash in EXPECTED_RECEIPTS.items():
        path = ROOT / "trials" / trial / "run_receipt.json"
        payload_bytes = path.read_bytes()
        observed_hash = hashlib.sha256(payload_bytes).hexdigest()
        if observed_hash != expected_hash:
            raise RuntimeError(f"{trial} receipt hash drift: {observed_hash}")
        payload = json.loads(payload_bytes)
        validation = payload["validation"]
        if (
            payload["status"] != "complete"
            or validation["terminal_tasks"] != 26
            or validation["unique_testcases"] != 26
            or validation["well_formed_tasks"] != 26
            or validation["malformed_responses"] != 0
            or validation["test_timeouts"] != 0
            or not payload["lora_activation_verified"]
        ):
            raise RuntimeError(f"{trial} failed the evaluation health contract")
        current_identity = (
            payload["model_revision"],
            payload["adapter_sha256"],
            payload["training_data_manifest_sha256"],
            payload["aider_commit"],
            payload["polyglot_commit"],
            payload["eval_set_version"],
            payload["contract_overlay_sha256"],
            payload["prompt_test_audit_sha256"],
            payload["temperature"],
            payload["top_p"],
            payload["max_tokens"],
            payload["thinking_disabled"],
            payload["tries"],
        )
        if identity is None:
            identity = current_identity
        elif identity != current_identity:
            raise RuntimeError(f"{trial} evaluation identity drift")
        trials[trial] = payload
    return trials


def bootstrap(rows: dict[str, dict[str, tuple[bool, bool]]], tasks: list[str]) -> dict:
    rng = random.Random(SEED)
    first_means = []
    final_means = []
    recovery_rates = []
    for _ in range(REPLICATES):
        sampled = [tasks[rng.randrange(len(tasks))] for _ in tasks]
        first_total = final_total = failures = recoveries = 0
        for trial in rows.values():
            for task in sampled:
                first, final = trial[task]
                first_total += int(first)
                final_total += int(final)
                failures += int(not first)
                recoveries += int((not first) and final)
        first_means.append(first_total / len(rows))
        final_means.append(final_total / len(rows))
        recovery_rates.append(recoveries / failures if failures else 0.0)
    first_means.sort()
    final_means.sort()
    recovery_rates.sort()
    return {
        "pass_at_1": [percentile(first_means, 0.025), percentile(first_means, 0.975)],
        "turn_2": [percentile(final_means, 0.025), percentile(final_means, 0.975)],
        "recovery": [percentile(recovery_rates, 0.025), percentile(recovery_rates, 0.975)],
    }


def compute() -> tuple[dict, list[dict]]:
    payloads = load_trials()
    rows = {
        trial: {
            task: (outcomes[0], any(outcomes))
            for task, outcomes in payload["validation"]["outcomes"].items()
        }
        for trial, payload in payloads.items()
    }
    task_sets = [set(trial) for trial in rows.values()]
    if any(len(tasks) != 26 or tasks != task_sets[0] for tasks in task_sets):
        raise RuntimeError("Fixed26 task-set drift")
    tasks = sorted(task_sets[0])
    first_scores = [sum(rows[trial][task][0] for task in tasks) for trial in rows]
    final_scores = [sum(rows[trial][task][1] for task in tasks) for trial in rows]
    if first_scores != EXPECTED_FIRST or final_scores != EXPECTED_FINAL:
        raise RuntimeError(f"score drift: first={first_scores}, final={final_scores}")
    failures = sum(26 - score for score in first_scores)
    recoveries = sum(final - first for first, final in zip(first_scores, final_scores))
    intervals = bootstrap(rows, tasks)
    per_task = []
    for task in tasks:
        first = sum(rows[trial][task][0] for trial in rows)
        final = sum(rows[trial][task][1] for trial in rows)
        per_task.append({
            "task": task,
            "pass_at_1_successes_out_of_4": first,
            "multi_turn_successes_out_of_4": final,
            "turn_2_recoveries": final - first,
            "turn_1_failures": 4 - first,
        })
    summary = {
        "schema_version": 1,
        "pass_at_1": {
            "scores": first_scores,
            "mean": statistics.mean(first_scores),
            "sample_standard_deviation": statistics.stdev(first_scores),
            "range": [min(first_scores), max(first_scores)],
            "bootstrap_95_percent_interval": intervals["pass_at_1"],
        },
        "multi_turn_with_feedback_turn_2": {
            "scores": final_scores,
            "mean": statistics.mean(final_scores),
            "sample_standard_deviation": statistics.stdev(final_scores),
            "range": [min(final_scores), max(final_scores)],
            "bootstrap_95_percent_interval": intervals["turn_2"],
        },
        "conditional_turn_2_recovery": {
            "recoveries": recoveries,
            "turn_1_failures": failures,
            "rate": recoveries / failures,
            "bootstrap_95_percent_interval": intervals["recovery"],
        },
    }
    return summary, per_task


def write_outputs(summary: dict, per_task: list[dict]) -> None:
    (ROOT / "statistics.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with (ROOT / "per_task_success.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(per_task[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(per_task)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    summary, per_task = compute()
    if args.write:
        write_outputs(summary, per_task)
    if args.check or not args.write:
        print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
