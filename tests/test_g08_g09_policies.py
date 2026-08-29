from __future__ import annotations

import copy
import importlib
import sys
from pathlib import Path

import pytest

from Reward_GRPO import global_verifier_grpo_mediator as mediator

ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "Reward_GRPO/global_verifiers_set2"
if str(PACKAGE) not in sys.path:
    sys.path.insert(0, str(PACKAGE))
g09 = importlib.import_module("g09_invalid_attribution")
receipt = importlib.import_module("receipt")


def _registry() -> mediator.TaskBundleRegistry:
    return mediator.TaskBundleRegistry(ROOT / "Reward_GRPO/global_verifier_task_registry.json")


def _response(expression: str = "left + right") -> str:
    return ("adder.h\n```cpp\n#pragma once\n"
            f"inline int add(int left, int right) {{ return {expression}; }}\n```\n")


def _policy(value: dict, identifier: str) -> dict:
    return next(item for item in value["policies"] if item["policy"] == identifier)


def test_g08_emits_all_four_checks_and_authenticates_final_envelope() -> None:
    binding = _registry().resolve("portable-adder")
    value = mediator.evaluate_response(binding, _response(), executor="host", invalid_retries=0)
    g08 = _policy(value, "G08")
    assert g08["status"] == "PASS"
    assert set(g08["facts"]["checks"]) == {"G08-A", "G08-B", "G08-C", "G08-D"}
    assert all(item["status"] == "PASS" for item in g08["facts"]["checks"].values())
    assert mediator.verify_mediator_receipt(value) == value

    tampered = copy.deepcopy(value)
    _policy(tampered, "G08")["facts"]["complete_final_envelope_signed"] = False
    tampered = mediator.sign_mediator_receipt(tampered)
    with pytest.raises(mediator.MediatorError, match="G08 receipt is malformed"):
        mediator.verify_mediator_receipt(tampered)


def test_g08_rejects_nonallowlisted_metadata_and_detects_mutation() -> None:
    binding = _registry().resolve("portable-adder")
    envelope = mediator.build_prompt(binding)
    copied = {**envelope.metadata, "official_tests": "hidden line-by-line content"}
    copied_policy = mediator._g08_policy(
        binding, copied, envelope.metadata["prompt_sha256"],
        mediator._metadata_sha256(copied), mediator._metadata_sha256(copied),
    )
    assert copied_policy["status"] == "INVALID"
    assert copied_policy["facts"]["checks"]["G08-B"]["reason"] == "NON_ALLOWLISTED_METADATA"

    mutated_policy = mediator._g08_policy(
        binding, envelope.metadata, envelope.metadata["prompt_sha256"], "0" * 64, "1" * 64,
    )
    assert mutated_policy["status"] == "INVALID"
    assert mutated_policy["facts"]["checks"]["G08-C"]["reason"] == "METADATA_MUTATED"


def test_g09_attributes_candidate_failure_without_promoting_it_to_invalid() -> None:
    source = receipt.policy(
        "G02", "FAIL", "COMPILE_FAIL",
        command={"command": ["g++", "bad.cpp"], "returncode": 1,
                 "stderr": "candidate syntax error", "stdout": "", "timed_out": False},
    )
    value = g09.verify([source, receipt.policy("G03", "NOT_RUN", "PREREQUISITE_FAILED")])
    assert value.status == "PASS"
    assert value.reason == "CANDIDATE_FAILURE_ATTRIBUTED"
    assert value.facts["classification"] == "FAIL"
    assert value.facts["originating_policy"] == "G02"
    assert value.facts["reason_code"] == "COMPILE_FAIL"


def test_g09_invalid_contains_bounded_log_errno_and_infrastructure_classification() -> None:
    source = receipt.policy(
        "PREFLIGHT", "INVALID", "DEPENDENCY_PREFLIGHT_FAILED",
        commands=[{"command": ["missing-compiler", "--version"], "returncode": 127,
                   "stderr": "x" * 5000 + " Permission denied EACCES", "stdout": "",
                   "timed_out": False, "launch_error_kind": "HOST_EXECUTABLE_MISSING"}],
    )
    value = g09.verify([source])
    assert value.status == "INVALID"
    assert value.facts["originating_policy"] == "PREFLIGHT"
    assert value.facts["returncode"] == 127
    assert value.facts["errno"] == {"name": "EACCES", "number": 13}
    assert value.facts["infrastructure_classification"] == "INFRASTRUCTURE_OR_CONTRACT"
    assert value.facts["main_error_log"]["truncated"] is True
    assert len(value.facts["main_error_log"]["text"]) == 4096


def test_g09_is_present_in_signed_runner_receipt() -> None:
    binding = _registry().resolve("portable-adder")
    value = mediator.evaluate_response(
        binding, _response("left - right"), executor="host", invalid_retries=0,
    )
    inner = value["attempts"][-1]["runner_receipt"]
    g09_policy = _policy(inner, "G09")
    assert inner["status"] == "FAIL"
    assert g09_policy["status"] == "PASS"
    assert g09_policy["facts"]["classification"] == "FAIL"
    assert g09_policy["facts"]["originating_policy"] == "G04"
    assert mediator.verify_mediator_receipt(value) == value
