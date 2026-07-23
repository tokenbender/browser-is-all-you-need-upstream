from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.verify_aider_sft_defect_inventory import (
    InventoryError,
    render_report,
    verify_inventory,
)


INVENTORY = Path("docs/aider_sft_defect_inventory.json")
REPORT = Path("docs/AIDER_SFT_DEFECT_INVENTORY.md")


def _load() -> dict:
    return json.loads(INVENTORY.read_text(encoding="utf-8"))


def test_checked_in_inventory_and_report_verify() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/verify_aider_sft_defect_inventory.py"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "790 packaged rows" in result.stdout


def test_report_is_exact_deterministic_rendering() -> None:
    assert REPORT.read_text(encoding="utf-8") == render_report(_load())


def test_duplicate_defect_id_is_rejected() -> None:
    data = _load()
    data["defects"][1]["id"] = data["defects"][0]["id"]
    with pytest.raises(InventoryError, match="unique"):
        verify_inventory(data)


def test_sft_dataset_may_not_shrink_below_790() -> None:
    data = _load()
    data["sft_dataset_size_invariant"]["current_unique_packaged_rows"] = 780
    data["sft_dataset_size_invariant"]["target_rows_consumed_per_epoch"] = 780
    with pytest.raises(InventoryError, match="below 790"):
        verify_inventory(data)


def test_rejected_rows_require_repair_replacement_or_backfill() -> None:
    data = copy.deepcopy(_load())
    data["sft_dataset_size_invariant"]["policy"] = "Delete low-quality rows."
    with pytest.raises(InventoryError, match="required phrase"):
        verify_inventory(data)
