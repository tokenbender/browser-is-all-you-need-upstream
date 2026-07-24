#!/usr/bin/env python3
"""Repair replayed W&B histories that have no plottable ``_step`` axis.

The distributed SFT jobs recorded history in multiple W&B event-log segments.
Those source records contain ``train/step`` or ``rollout/step`` but no
top-level ``_step``. A raw ``wandb sync`` preserves summaries and metric
metadata, yet W&B cannot render the history tabs. This tool coalesces records
by their recorded logical step and appends one explicit W&B history row per
step to the already replayed run.

Dry-run is the default. Pass ``--upload`` to mutate W&B.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import wandb
from wandb.proto import wandb_internal_pb2
from wandb.sdk.internal.datastore import DataStore


REPAIR_SCHEMA_VERSION = 1
STEP_KEYS = ("train/step", "rollout/step")
RESERVED_SOURCE_KEYS = {"_runtime", "_step", "_timestamp"}


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def event_log_manifest(paths: Iterable[Path]) -> tuple[str, int]:
    records = []
    total_bytes = 0
    for path in sorted(paths):
        total_bytes += path.stat().st_size
        records.append(f"{sha256_path(path)}  {path.name}")
    payload = ("\n".join(records) + "\n").encode()
    return hashlib.sha256(payload).hexdigest(), total_bytes


def decode_history_item(item: Any) -> tuple[str, Any]:
    key = item.key or "/".join(item.nested_key)
    if not key:
        raise RuntimeError("W&B history item has no key")
    return key, json.loads(item.value_json)


def load_history(
    paths: Iterable[Path], expected_run_id: str
) -> tuple[list[tuple[int, dict[str, Any]]], dict[str, Any]]:
    paths = tuple(paths)
    run_ids: set[str] = set()
    rows: dict[int, dict[str, Any]] = {}
    source_history_records = 0
    overwritten_values = 0

    for path in sorted(paths):
        store = DataStore()
        store.open_for_scan(str(path))
        while True:
            payload = store.scan_data()
            if payload is None:
                break
            record = wandb_internal_pb2.Record()
            record.ParseFromString(payload)
            record_type = record.WhichOneof("record_type")
            if record_type == "run":
                run_ids.add(record.run.run_id)
                continue
            if record_type != "history":
                continue

            source_history_records += 1
            source_row = dict(map(decode_history_item, record.history.item))
            logical_steps = [
                int(source_row[key]) for key in STEP_KEYS if key in source_row
            ]
            if not logical_steps:
                raise RuntimeError("History record has no logical step")
            if len(set(logical_steps)) != 1:
                raise RuntimeError(
                    f"Conflicting logical steps in history record: {logical_steps}"
                )
            logical_step = logical_steps[0]
            repaired_row = rows.setdefault(logical_step, {})
            for key, value in source_row.items():
                if key in RESERVED_SOURCE_KEYS:
                    continue
                if key in repaired_row and repaired_row[key] != value:
                    overwritten_values += 1
                repaired_row[key] = value

    if run_ids != {expected_run_id}:
        raise RuntimeError(
            f"Expected source run ID {expected_run_id!r}, found {sorted(run_ids)!r}"
        )
    if not rows:
        raise RuntimeError("Source logs contain no history rows")
    expected_steps = list(range(max(rows) + 1))
    if sorted(rows) != expected_steps:
        raise RuntimeError(
            "Logical steps are not contiguous: "
            f"expected 0..{max(rows)}, found {sorted(rows)!r}"
        )

    manifest_sha256, total_bytes = event_log_manifest(paths)
    metadata = {
        "schema_version": REPAIR_SCHEMA_VERSION,
        "event_log_manifest_sha256": manifest_sha256,
        "event_log_bytes": total_bytes,
        "event_log_files": len(paths),
        "source_history_records": source_history_records,
        "repaired_history_rows": len(rows),
        "max_step": max(rows),
        "overwritten_values": overwritten_values,
    }
    return sorted(rows.items()), metadata


def existing_last_step(run: Any) -> int:
    return int(run.history_keys.get("lastStep", -1))


def verify_repaired_history(
    target_path: str, *, expected_max_step: int, expected_rows: int
) -> Any:
    """Wait briefly for W&B's history index, then verify the actual rows."""
    observed_last_step = -1
    observed_rows = 0
    for attempt in range(7):
        verified = wandb.Api(timeout=60).run(target_path)
        observed_last_step = existing_last_step(verified)
        if observed_last_step == expected_max_step:
            observed_rows = sum(1 for _ in verified.scan_history(page_size=1000))
            if observed_rows == expected_rows:
                return verified
        if attempt < 6:
            time.sleep(5)
    raise RuntimeError(
        f"{target_path} history repair did not persist: "
        f"lastStep={observed_last_step}, rows={observed_rows}; "
        f"expected lastStep={expected_max_step}, rows={expected_rows}"
    )


def upload_repaired_history(
    *,
    entity: str,
    project: str,
    run_id: str,
    rows: list[tuple[int, dict[str, Any]]],
    metadata: dict[str, Any],
) -> str:
    api = wandb.Api(timeout=60)
    target_path = f"{entity}/{project}/{run_id}"
    existing = api.run(target_path)
    summary = dict(existing.summary)
    prior_manifest = summary.get("history_repair/event_log_manifest_sha256")
    if prior_manifest == metadata["event_log_manifest_sha256"]:
        return verify_repaired_history(
            target_path,
            expected_max_step=metadata["max_step"],
            expected_rows=metadata["repaired_history_rows"],
        ).url
    if prior_manifest:
        raise RuntimeError(
            f"{target_path} has a different history repair manifest: "
            f"{prior_manifest}"
        )
    if existing_last_step(existing) != -1:
        raise RuntimeError(
            f"{target_path} already has plottable history with lastStep "
            f"{existing_last_step(existing)}"
        )

    run = wandb.init(
        entity=entity,
        project=project,
        id=run_id,
        resume="must",
        reinit="finish_previous",
    )
    if run is None:
        raise RuntimeError("wandb.init returned no run")
    for step, row in rows:
        run.log(row, step=step)
    for key, value in metadata.items():
        run.summary[f"history_repair/{key}"] = value
    run.summary["history_repair/status"] = "passed"
    run.finish()

    return verify_repaired_history(
        target_path,
        expected_max_step=metadata["max_step"],
        expected_rows=metadata["repaired_history_rows"],
    ).url


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--entity", default="ahm-rimer")
    parser.add_argument("--project", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--upload", action="store_true")
    parser.add_argument("event_logs", nargs="+", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paths = [path.resolve() for path in args.event_logs]
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(path)
    rows, metadata = load_history(paths, args.run_id)
    result: dict[str, Any] = {
        "entity": args.entity,
        "project": args.project,
        "run_id": args.run_id,
        "upload": args.upload,
        **metadata,
    }
    if args.upload:
        result["url"] = upload_repaired_history(
            entity=args.entity,
            project=args.project,
            run_id=args.run_id,
            rows=rows,
            metadata=metadata,
        )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
