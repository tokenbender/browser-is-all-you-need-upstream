from __future__ import annotations

import importlib
import json
import shutil
import sys
from argparse import Namespace
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "Reward_GRPO/global_verifiers_set2"
sys.path.insert(0, str(PACKAGE))
runner = importlib.import_module("runner")
g01 = importlib.import_module("g01_integrity")


def bundle(tmp_path: Path) -> Path:
    target = tmp_path / "bundle"
    shutil.copytree(PACKAGE / "task_bundle_example", target)
    return target


def candidate(tmp_path: Path, code: str) -> Path:
    target = tmp_path / "candidate"
    target.mkdir()
    (target / "adder.h").write_text(code)
    return target


def execute(task: Path, cand: Path, output: Path, *, full: bool = False):
    return runner.run(Namespace(bundle=task, candidate=cand, response=None,
                                finish_reason=None, output=output,
                                executor="host", full=full))


def reasons(receipt):
    return {item.policy: (item.status, item.reason) for item in receipt.policies}


def test_package_contains_expected_portable_python_modules() -> None:
    assert sorted(path.name for path in PACKAGE.glob("*.py")) == [
        "candidate_reconstruction.py", "g01_integrity.py", "g02_build.py",
        "g03_api_link.py", "g04_functional.py", "g05_safety.py",
        "g07_portability.py", "g09_invalid_attribution.py", "receipt.py", "runner.py", "sandbox.py",
    ]


def test_reference_passes_g01_through_g07(tmp_path: Path) -> None:
    receipt = execute(bundle(tmp_path), PACKAGE / "task_bundle_example/starter",
                      tmp_path / "out", full=True)
    assert receipt.status == "PASS"
    assert reasons(receipt) == {
        "G01": ("PASS", "BOUNDARY_AUTHENTICATED"),
        "PREFLIGHT": ("PASS", "DEPENDENCIES_AVAILABLE"),
        "G02": ("PASS", "OBJECTS_COMPILED"),
        "G03": ("PASS", "API_LINKED"),
        "G04": ("PASS", "FUNCTIONAL_PASS"),
        "G05": ("PASS", "SAFETY_PASS"),
        "G07": ("PASS", "PORTABILITY_PASS"),
        "G09": ("PASS", "NO_FAILURE_TO_ATTRIBUTE"),
    }


def test_api_defect_stops_before_functional(tmp_path: Path) -> None:
    cand = candidate(tmp_path, "#pragma once\ninline int wrong(int a,int b){return a+b;}\n")
    receipt = execute(bundle(tmp_path), cand, tmp_path / "out")
    assert reasons(receipt)["G03"] == ("FAIL", "API_FAIL")
    assert reasons(receipt)["G04"] == ("NOT_RUN", "PREREQUISITE_FAILED")


def test_missing_definition_is_link_fail(tmp_path: Path) -> None:
    cand = candidate(tmp_path, "#pragma once\nint add(int left, int right);\n")
    receipt = execute(bundle(tmp_path), cand, tmp_path / "out")
    assert reasons(receipt)["G02"] == ("PASS", "OBJECTS_COMPILED")
    assert reasons(receipt)["G03"] == ("FAIL", "LINK_FAIL")


def test_logic_defect_reaches_g04(tmp_path: Path) -> None:
    cand = candidate(tmp_path, "#pragma once\ninline int add(int left,int right){return left-right;}\n")
    receipt = execute(bundle(tmp_path), cand, tmp_path / "out")
    assert reasons(receipt)["G03"] == ("PASS", "API_LINKED")
    assert reasons(receipt)["G04"] == ("FAIL", "SEMANTIC_FAIL")


def test_protected_asset_corruption_is_invalid(tmp_path: Path) -> None:
    task = bundle(tmp_path)
    manifest = json.loads((task / "manifest.json").read_text())
    (task / "official_cases.json.gz").write_bytes(b"tampered\n")
    result = g01.verify(task, manifest)
    assert (result.status, result.reason) == ("INVALID", "PROTECTED_ASSET_CORRUPTED")


def test_missing_compiler_is_invalid_and_blocks_downstream(tmp_path: Path) -> None:
    task = bundle(tmp_path)
    manifest_path = task / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["preflight_commands"] = []
    manifest["build"]["compiler"] = "compiler-that-does-not-exist"
    manifest_path.write_text(json.dumps(manifest))
    receipt = execute(task, PACKAGE / "task_bundle_example/starter", tmp_path / "out")
    assert reasons(receipt)["G02"] == ("INVALID", "COMPILER_UNAVAILABLE")
    assert reasons(receipt)["G03"] == ("NOT_RUN", "PREREQUISITE_FAILED")


def test_truncated_empty_response_is_distinct(tmp_path: Path) -> None:
    with pytest.raises(Exception) as raised:
        runner.run(Namespace(bundle=bundle(tmp_path), candidate=None,
                             response="unfinished", finish_reason="length",
                             output=tmp_path / "out", executor="host", full=False))
    assert getattr(raised.value, "reason", None) == "TRUNCATED"
