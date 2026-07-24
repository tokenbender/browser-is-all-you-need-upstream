#!/usr/bin/env python3
"""Verify and render the Aider SFT defect inventory."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = ROOT / "docs" / "aider_sft_defect_inventory.json"
DEFAULT_REPORT = ROOT / "docs" / "AIDER_SFT_DEFECT_INVENTORY.md"

ALLOWED_CATEGORIES = {
    "dataset",
    "loader",
    "training",
    "behavior",
    "evaluation",
    "observability",
}
ALLOWED_SEVERITIES = {"critical", "high", "medium"}
ALLOWED_EVIDENCE_STATUSES = {"confirmed", "risk"}

EXPECTED_RAW_715 = {
    "total_rows": 715,
    "train_ready_rows": 0,
    "review_rows": 643,
    "reject_rows": 72,
    "compile_pass_rows": 690,
    "compile_fail_rows": 25,
    "contradictory_pairs": 40,
    "gold_conflicts": 7,
    "unresolved_lineage_rows": 104,
    "missing_example_rows": 60,
    "dense_or_minified_answers": 606,
    "independent_row_semantic_receipts": 0,
    "raw_concat_total_rows": 875,
    "raw_715_share_percent": 81.71,
}

EXPECTED_HISTORY = {
    "sft-v1": (321, 320, 1, 1, 5),
    "sft-v2": (1211, 1184, 1, 1, 6),
    "sft-v3": (530, 520, 1, 0, 7),
    "sft-v4-1ep": (790, 780, 1, 1, 4),
    "sft-v4-3ep": (790, 780, 3, 0, 6),
}


class InventoryError(ValueError):
    """Raised when the checked-in inventory violates its contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise InventoryError(message)


def _count(records: list[dict[str, Any]], field: str) -> dict[str, int]:
    return dict(sorted(Counter(record[field] for record in records).items()))


def verify_inventory(data: dict[str, Any]) -> None:
    """Validate structure, evidence links, counts, and non-shrink invariants."""

    _require(data.get("schema_version") == 1, "schema_version must be 1")

    invariant = data.get("sft_dataset_size_invariant", {})
    minimum = invariant.get("minimum_unique_packaged_rows")
    current = invariant.get("current_unique_packaged_rows")
    consumed = invariant.get("current_rows_consumed_per_epoch")
    target_consumed = invariant.get("target_rows_consumed_per_epoch")
    _require(minimum == 790, "minimum unique packaged SFT rows must remain 790")
    _require(current is not None and current >= minimum, "current SFT corpus is below 790")
    _require(consumed == 780, "current v4 consumed-row baseline must remain recorded as 780")
    _require(
        target_consumed == current,
        "consume-all target must equal the unique packaged-row count",
    )
    policy = invariant.get("policy", "").lower()
    for phrase in ("repaired", "replaced", "backfilled", "must not reduce"):
        _require(phrase in policy, f"size policy is missing required phrase: {phrase}")

    sources = data.get("evidence_sources", {})
    _require(sources, "evidence_sources must not be empty")
    for source_id, source in sources.items():
        _require(
            bool(source.get("url") or source.get("path")),
            f"evidence source {source_id} has neither url nor path",
        )

    defects = data.get("defects", [])
    _require(defects, "defects must not be empty")
    ids = [record.get("id") for record in defects]
    _require(len(ids) == len(set(ids)), "defect IDs must be unique")
    _require(all(isinstance(item, str) and item for item in ids), "all defects need IDs")

    required_fields = {
        "id",
        "category",
        "severity",
        "evidence_status",
        "finding",
        "evidence_refs",
        "remediation",
        "acceptance_test",
    }
    for record in defects:
        missing = required_fields - set(record)
        _require(not missing, f"{record.get('id')} missing fields: {sorted(missing)}")
        _require(
            record["category"] in ALLOWED_CATEGORIES,
            f"{record['id']} has invalid category",
        )
        _require(
            record["severity"] in ALLOWED_SEVERITIES,
            f"{record['id']} has invalid severity",
        )
        _require(
            record["evidence_status"] in ALLOWED_EVIDENCE_STATUSES,
            f"{record['id']} has invalid evidence status",
        )
        _require(record["evidence_refs"], f"{record['id']} has no evidence")
        unknown = set(record["evidence_refs"]) - set(sources)
        _require(not unknown, f"{record['id']} has unknown evidence refs: {sorted(unknown)}")
        for field in ("finding", "remediation", "acceptance_test"):
            _require(bool(record[field].strip()), f"{record['id']} has blank {field}")

    summary = data.get("summary", {})
    _require(summary.get("defect_count") == len(defects), "defect summary count is stale")
    _require(summary.get("by_category") == _count(defects, "category"), "category counts are stale")
    _require(summary.get("by_severity") == _count(defects, "severity"), "severity counts are stale")
    _require(
        summary.get("by_evidence_status") == _count(defects, "evidence_status"),
        "evidence-status counts are stale",
    )

    raw = data.get("raw_715_audit", {})
    _require(raw == EXPECTED_RAW_715, "raw-715 audit counts changed or are incomplete")
    _require(
        raw["compile_pass_rows"] + raw["compile_fail_rows"] == raw["total_rows"],
        "raw-715 compile counts do not sum to total",
    )
    _require(
        raw["train_ready_rows"] + raw["review_rows"] + raw["reject_rows"]
        == raw["total_rows"],
        "raw-715 dispositions do not sum to total",
    )

    history = data.get("dataset_history", [])
    actual_history = {
        row["id"]: (
            row["unique_packaged_rows"],
            row["rows_consumed_per_epoch"],
            row["epochs"],
            row["first_turn_passes"],
            row["assisted_passes"],
        )
        for row in history
    }
    _require(actual_history == EXPECTED_HISTORY, "SFT dataset history is incomplete or stale")
    for row in history:
        _require(
            row["rows_consumed_per_epoch"] <= row["unique_packaged_rows"],
            f"{row['id']} consumes more rows than it packages",
        )

    terminal = data.get("v4_3ep_terminal_failures", [])
    _require(len(terminal) == 20, "v4 three-epoch terminal failure count must be 20")
    _require(
        len({row["task"] for row in terminal}) == 20,
        "terminal failure task names must be unique",
    )
    failure_classes = Counter(row["class"] for row in terminal)
    _require(
        failure_classes == {"interface_or_compile_contract": 16, "semantic": 4},
        "terminal failure classes must remain 16 contract and 4 semantic",
    )

    recoveries = data.get("v4_3ep_assisted_recoveries", [])
    _require(len(recoveries) == len(set(recoveries)) == 6, "assisted recoveries must be six unique tasks")
    _require(
        not set(recoveries) & {row["task"] for row in terminal},
        "a task cannot be both recovered and terminal",
    )

    defect_ids = set(ids)
    for required_id in ("D014", "L003", "T001", "B005", "E001", "O006"):
        _require(required_id in defect_ids, f"required coverage defect {required_id} is absent")


def _source_link(source_id: str, source: dict[str, Any]) -> str:
    target = source.get("url")
    if not target:
        target = f"../{source['path']}"
    return f"[{source_id}]({target})"


def render_report(data: dict[str, Any]) -> str:
    """Render a deterministic human-readable companion report."""

    invariant = data["sft_dataset_size_invariant"]
    summary = data["summary"]
    sources = data["evidence_sources"]
    lines = [
        "# Aider C++ SFT defect inventory",
        "",
        f"Updated: `{data['updated_at_utc']}`",
        "",
        "## Decision contract",
        "",
        "This inventory records defects; it does not claim that they are fixed. "
        "A checkpoint is not promotable from training loss alone.",
        "",
        f"- Corpus floor: **{invariant['minimum_unique_packaged_rows']} unique packaged rows**.",
        f"- Current v4 package: **{invariant['current_unique_packaged_rows']} rows**.",
        f"- Current consumption: **{invariant['current_rows_consumed_per_epoch']} rows per epoch**.",
        f"- Required consumption: **{invariant['target_rows_consumed_per_epoch']} rows per epoch**.",
        f"- Replacement rule: {invariant['policy']}",
        "- RL rollout settings are outside this inventory and are unchanged.",
        "",
        "## Inventory summary",
        "",
        f"- {summary['defect_count']} recorded defects: "
        + ", ".join(f"{count} {name}" for name, count in summary["by_category"].items())
        + ".",
        "- Severity: "
        + ", ".join(f"{count} {name}" for name, count in summary["by_severity"].items())
        + ".",
        "- Evidence status: "
        + ", ".join(
            f"{count} {name}" for name, count in summary["by_evidence_status"].items()
        )
        + ".",
        "",
        "## Dataset and outcome history",
        "",
        "| Stage | Unique packaged | Consumed / epoch | Epochs | pass@1 | multi-turn-with-error-feedback@2 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in data["dataset_history"]:
        lines.append(
            f"| {row['id']} | {row['unique_packaged_rows']} | "
            f"{row['rows_consumed_per_epoch']} | {row['epochs']} | "
            f"{row['first_turn_passes']}/26 | {row['assisted_passes']}/26 |"
        )

    raw = data["raw_715_audit"]
    lines.extend(
        [
            "",
            "## Raw-715 audit receipt",
            "",
            "| Check | Count |",
            "| --- | ---: |",
            f"| Total | {raw['total_rows']} |",
            f"| Train-ready | {raw['train_ready_rows']} |",
            f"| Review | {raw['review_rows']} |",
            f"| Reject | {raw['reject_rows']} |",
            f"| Compile pass / fail | {raw['compile_pass_rows']} / {raw['compile_fail_rows']} |",
            f"| Contradictory pairs | {raw['contradictory_pairs']} |",
            f"| Gold conflicts | {raw['gold_conflicts']} |",
            f"| Unresolved lineage | {raw['unresolved_lineage_rows']} |",
            f"| Missing examples | {raw['missing_example_rows']} |",
            f"| Dense or minified answers | {raw['dense_or_minified_answers']} |",
            f"| Independent semantic receipts | {raw['independent_row_semantic_receipts']} |",
            "",
            "## Defects",
            "",
        ]
    )

    for category in sorted(ALLOWED_CATEGORIES):
        title = category.replace("_", " ").title()
        lines.extend([f"### {title}", ""])
        for record in (item for item in data["defects"] if item["category"] == category):
            links = ", ".join(
                _source_link(ref, sources[ref]) for ref in record["evidence_refs"]
            )
            lines.extend(
                [
                    f"#### {record['id']} — {record['severity']} — {record['evidence_status']}",
                    "",
                    f"**Finding.** {record['finding']}",
                    "",
                    f"**Evidence.** {links}",
                    "",
                    f"**Remediation.** {record['remediation']}",
                    "",
                    f"**Acceptance test.** {record['acceptance_test']}",
                    "",
                ]
            )

    lines.extend(
        [
            "## V4 three-epoch terminal failure map",
            "",
            "| Task | Failure class |",
            "| --- | --- |",
        ]
    )
    for failure in data["v4_3ep_terminal_failures"]:
        lines.append(f"| {failure['task']} | {failure['class'].replace('_', ' ')} |")

    lines.extend(
        [
            "",
            "Assisted recoveries: "
            + ", ".join(f"`{task}`" for task in data["v4_3ep_assisted_recoveries"])
            + ".",
            "",
            "## Reproduce this inventory check",
            "",
            "```bash",
            "python3 scripts/verify_aider_sft_defect_inventory.py",
            "```",
            "",
            "The verifier checks the schema, evidence references, exact measured counts, "
            "failure taxonomy, report synchronization, and the 790-row non-shrink invariant.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--write-report",
        action="store_true",
        help="Replace the Markdown report with the deterministic rendering.",
    )
    args = parser.parse_args()

    data = json.loads(args.inventory.read_text(encoding="utf-8"))
    verify_inventory(data)
    rendered = render_report(data)

    if args.write_report:
        args.report.write_text(rendered, encoding="utf-8")
    else:
        _require(args.report.exists(), f"report is missing: {args.report}")
        _require(
            args.report.read_text(encoding="utf-8") == rendered,
            "Markdown report is stale; rerun with --write-report",
        )

    print(
        "Aider SFT defect inventory passed: "
        f"{len(data['defects'])} defects, "
        f"{data['sft_dataset_size_invariant']['current_unique_packaged_rows']} packaged rows, "
        f"{data['sft_dataset_size_invariant']['current_rows_consumed_per_epoch']} currently consumed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
