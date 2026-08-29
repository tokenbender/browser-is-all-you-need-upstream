from __future__ import annotations

import importlib
import json
import shutil
import sys
from argparse import Namespace
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "Reward_GRPO/global_verifiers_set2"
sys.path.insert(0, str(PACKAGE))
runner = importlib.import_module("runner")

EXAMPLE = PACKAGE / "task_bundle_example"
HIDDEN_TEST = "official_cases.json.gz"


def _bundle(tmp_path: Path) -> Path:
    target = tmp_path / "bundle"
    shutil.copytree(EXAMPLE, target)
    return target


def _run(bundle: Path, candidate: Path, output: Path):
    return runner.run(
        Namespace(
            bundle=bundle,
            candidate=candidate,
            response=None,
            finish_reason=None,
            output=output,
            executor="host",
            full=False,
        )
    )


def _policy(receipt: Any, identifier: str):
    return next(item for item in receipt.policies if item.policy == identifier)


def test_hidden_tests_are_absent_through_g02_and_g03_then_reference_reaches_g04(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _bundle(tmp_path)
    real_run_host = runner.run_host
    observed = {
        "g02_compile": 0,
        "g03_ast": 0,
        "g03_link": 0,
        "g04_probe_compile": 0,
        "g04_probe_run": 0,
    }

    def observing_run_host(
        command: list[str], cwd: Path, limits: Any,
        env: dict[str, str] | None = None,
    ):
        hidden_source = cwd / HIDDEN_TEST
        if "-c" in command and "build_probe.cpp" in command:
            observed["g02_compile"] += 1
            assert not hidden_source.exists()
        if "-ast-dump=json" in command:
            observed["g03_ast"] += 1
            assert not hidden_source.exists()
            assert (cwd / "public_api.json").is_file()
            assert (cwd / "api_caller.cpp").is_file()
        if "api_caller.cpp" in command:
            observed["g03_link"] += 1
            assert not hidden_source.exists()
        if ".gv2/candidate_probe" in command:
            observed["g04_probe_compile"] += 1
            assert not hidden_source.exists()
        if command and command[0] == "./candidate_probe":
            observed["g04_probe_run"] += 1
            assert not hidden_source.exists()
        return real_run_host(command, cwd, limits, env)

    monkeypatch.setattr(runner, "run_host", observing_run_host)
    receipt = _run(task, task / "starter", tmp_path / "output")

    assert receipt.status == "PASS"
    assert (_policy(receipt, "G02").status, _policy(receipt, "G02").reason) == (
        "PASS", "OBJECTS_COMPILED",
    )
    assert (_policy(receipt, "G03").status, _policy(receipt, "G03").reason) == (
        "PASS", "API_LINKED",
    )
    assert (_policy(receipt, "G04").status, _policy(receipt, "G04").reason) == (
        "PASS", "FUNCTIONAL_PASS",
    )
    assert observed == {
        "g02_compile": 1,
        "g03_ast": 1,
        "g03_link": 1,
        "g04_probe_compile": 1,
        "g04_probe_run": 1,
    }


def test_tampered_hidden_test_is_invalid_before_candidate_compilation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _bundle(tmp_path)
    (task / HIDDEN_TEST).write_text("tampered hidden oracle\n", encoding="utf-8")
    execute_calls: list[list[str]] = []
    real_run_host = runner.run_host

    def observing_run_host(
        command: list[str], cwd: Path, limits: Any,
        env: dict[str, str] | None = None,
    ):
        execute_calls.append(list(command))
        return real_run_host(command, cwd, limits, env)

    monkeypatch.setattr(runner, "run_host", observing_run_host)
    receipt = _run(task, task / "starter", tmp_path / "output")

    assert receipt.status == "INVALID"
    g01 = _policy(receipt, "G01")
    assert (g01.status, g01.reason) == ("INVALID", "PROTECTED_ASSET_CORRUPTED")
    assert g01.facts["path"] == HIDDEN_TEST
    assert execute_calls == []
    for identifier in ("G02", "G03", "G04"):
        item = _policy(receipt, identifier)
        assert (item.status, item.reason) == ("NOT_RUN", "PREREQUISITE_FAILED")


def test_load_bundle_rejects_public_asset_overlap_with_hidden_functional_tests(
    tmp_path: Path,
) -> None:
    task = _bundle(tmp_path)
    manifest_path = task / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["build"]["public_assets"] = [HIDDEN_TEST]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError):
        runner.load_bundle(task)


def test_preflight_runs_in_empty_cwd_without_sibling_bundle_visibility(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _bundle(tmp_path)
    manifest_path = task / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["preflight_commands"] = [
        ["test", "!", "-e", f"../bundle/{HIDDEN_TEST}"],
    ]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    real_run_host = runner.run_host
    preflight_cwds: list[Path] = []

    def observing_run_host(
        command: list[str], cwd: Path, limits: Any,
        env: dict[str, str] | None = None,
    ):
        if command and command[0] == "test":
            preflight_cwds.append(cwd)
            assert list(cwd.iterdir()) == []
        return real_run_host(command, cwd, limits, env)

    monkeypatch.setattr(runner, "run_host", observing_run_host)
    receipt = _run(task, task / "starter", tmp_path / "output")

    assert preflight_cwds
    preflight = _policy(receipt, "PREFLIGHT")
    assert (preflight.status, preflight.reason) == (
        "PASS", "DEPENDENCIES_AVAILABLE",
    )
    assert receipt.status == "PASS"
    assert _policy(receipt, "G04").status == "PASS"
