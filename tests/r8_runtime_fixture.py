"""Public synthetic fixtures for R7/R8 schedule-staging tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable


def _write_jsonl(path: Path, rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def build_schedule_runtime(
    root: Path,
    *,
    train_ids: list[str],
    canary_ids: list[str],
    reward_policy: str,
) -> Path:
    """Create the minimal public runtime shape consumed by schedule staging."""

    role_by_id = {
        task_id: (
            "repair_trajectory"
            if index % 4 == 0
            else "boundary_case"
            if index % 4 == 1
            else "direct_verified_success"
        )
        for index, task_id in enumerate(train_ids)
    }

    def base_rows(task_ids: list[str]) -> list[dict[str, object]]:
        return [
            {
                "messages": [{"role": "user", "content": f"synthetic {task_id}"}],
                "metadata": {
                    "base_task_id": task_id,
                    "curriculum_role": role_by_id[task_id],
                },
            }
            for task_id in task_ids
        ]

    def schedule(task_ids: list[str], epochs: int) -> list[dict[str, object]]:
        return [
            {
                "base_task_id": task_id,
                "curriculum_role": role_by_id[task_id],
                "epoch": epoch,
                "position": position,
            }
            for epoch in range(1, epochs + 1)
            for position, task_id in enumerate(task_ids)
        ]

    files = {
        "grpo_train": "grpo/train.jsonl",
        "grpo_canary": "grpo/canary.jsonl",
        "full_schedule": "schedules/full.jsonl",
        "canary_schedule": "schedules/canary.jsonl",
    }
    root.mkdir(parents=True)
    _write_jsonl(root / files["grpo_train"], base_rows(train_ids))
    _write_jsonl(root / files["grpo_canary"], base_rows(canary_ids))
    _write_jsonl(root / files["full_schedule"], schedule(train_ids, 3))
    _write_jsonl(root / files["canary_schedule"], schedule(canary_ids, 5))
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "files": files,
                "reward_contract": {"policy": reward_policy},
                "fixture_scope": "synthetic-public-schedule-only",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return root
