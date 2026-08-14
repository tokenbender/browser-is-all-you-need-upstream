"""Owner helpers for the v6 fmt compile-gated mechanism contract."""

from __future__ import annotations

import copy
from typing import Any


PROBE_PATH = "configs/public_pr_eval/private_probes/fmt_chrono_mechanism_probe.cpp"
PROBE_SHA256 = "360233b20fbade4155bea5cf743805a4d3cb899e0a295bf8b352b800a19f7096"
LOCAL_IDS = {"localtime-to-time-t", "local-time-root-fix"}


def verifier_bound_checklist(
    legacy_checklist: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {**copy.deepcopy(item), "verifier_id": str(item["id"])}
        for item in legacy_checklist
    ]


def _command(name: str, argv: list[str], timeout: int = 900) -> dict[str, Any]:
    return {
        "name": name,
        "argv": argv,
        "timeout_seconds": timeout,
        "continue_on_failure": True,
    }


def mechanism_verification(checklist: list[dict[str, Any]]) -> dict[str, Any]:
    probe = "{mechanism_probe}"
    private = ".public-pr-eval-private"
    common = ["-Wall", "-Wextra", "-Werror", "-Iinclude", probe]
    commands = [
        _command(
            "compile-gcc-cxx11-safe-on",
            [
                "g++-13",
                "-std=c++11",
                "-DFMT_SAFE_DURATION_CAST=1",
                *common,
                "-o",
                f"{private}/mechanism-probe-gcc-safe-on",
            ],
        ),
        _command(
            "compile-gcc-cxx11-safe-off",
            [
                "g++-13",
                "-std=c++11",
                "-DFMT_SAFE_DURATION_CAST=0",
                *common,
                "-o",
                f"{private}/mechanism-probe-gcc-safe-off",
            ],
        ),
        _command(
            "compile-gcc-cxx11-ubsan",
            [
                "g++-13",
                "-std=c++11",
                "-DFMT_SAFE_DURATION_CAST=1",
                "-fsanitize=undefined",
                "-fno-sanitize-recover=undefined",
                *common,
                "-o",
                f"{private}/mechanism-probe-gcc-ubsan",
            ],
        ),
        _command(
            "compile-gcc-cxx20-local",
            [
                "g++-13",
                "-std=c++20",
                "-DFMT_SAFE_DURATION_CAST=1",
                *common,
                "-o",
                f"{private}/mechanism-probe-gcc-cxx20",
            ],
        ),
        _command(
            "compile-clang-cxx11-safe-on",
            [
                "clang++",
                "-std=c++11",
                "-DFMT_SAFE_DURATION_CAST=1",
                *common,
                "-o",
                f"{private}/mechanism-probe-clang-safe-on",
            ],
        ),
    ]
    for item in checklist:
        verifier_id = str(item["id"])
        if verifier_id in LOCAL_IDS:
            commands.append(
                _command(
                    f"run-gcc-cxx20-{verifier_id}",
                    [f"{private}/mechanism-probe-gcc-cxx20", verifier_id],
                    300,
                )
            )
        else:
            for mode in ("safe-on", "safe-off", "ubsan"):
                commands.append(
                    _command(
                        f"run-gcc-{mode}-{verifier_id}",
                        [f"{private}/mechanism-probe-gcc-{mode}", verifier_id],
                        300,
                    )
                )

    verifiers = []
    for item in checklist:
        verifier_id = str(item["id"])
        if verifier_id in LOCAL_IDS:
            run_name = f"run-gcc-cxx20-{verifier_id}"
            verifiers.append(
                {
                    "id": verifier_id,
                    "command_names": ["compile-gcc-cxx20-local", run_name],
                    "platform_gate_command_names": [
                        "compile-gcc-cxx20-local",
                        run_name,
                    ],
                }
            )
        else:
            verifiers.append(
                {
                    "id": verifier_id,
                    "command_names": [
                        f"run-gcc-safe-on-{verifier_id}",
                        f"run-gcc-safe-off-{verifier_id}",
                        f"run-gcc-ubsan-{verifier_id}",
                    ],
                    "platform_gate_command_names": [],
                }
            )
    return {
        "schema_version": "public-pr-mechanism-verification-v1",
        "required_for_pass": True,
        "source_path": "include/fmt/chrono.h",
        "structure_verifier_id": "fmt-chrono-structure-v1",
        "probe": {"path": PROBE_PATH, "sha256": PROBE_SHA256},
        "build_compile_gate_command_names": ["configure-offline", "build-chrono"],
        "compile_gate_command_names": [
            "configure-offline",
            "build-chrono",
            "compile-gcc-cxx11-safe-on",
            "compile-gcc-cxx11-safe-off",
            "compile-gcc-cxx11-ubsan",
        ],
        "optional_portability_commands": ["compile-clang-cxx11-safe-on"],
        "platform_gate_returncodes": [77, 127],
        "commands": commands,
        "verifiers": verifiers,
    }


def upgrade_thinking_row(
    row: dict[str, Any], legacy_checklist: list[dict[str, Any]]
) -> dict[str, Any]:
    upgraded = copy.deepcopy(row)
    checklist = verifier_bound_checklist(legacy_checklist)
    upgraded["diagnostic_checklist"] = checklist
    upgraded["hidden_validation"]["mechanism_verification"] = (
        mechanism_verification(checklist)
    )
    upgraded["demo_evaluation_policy"] = {
        "schema_version": "public-pr-demo-baseline-v2",
        "textual_hints": "diagnostic_only",
        "structural_checks": "diagnostic_until_compile_and_focused_probe_pass",
        "verified_mechanisms": "compile_gated_named_verifiers",
        "final_pass": "executable_oracle_only",
        "platform_gated_denominator_policy": (
            "exclude only explicitly unavailable C++20 local-time mechanisms"
        ),
    }
    upgraded["harness_instructions"] = {
        **upgraded["harness_instructions"],
        "schema_version": "public-pr-verified-mechanism-harness-v1",
        "suite_mode": "fmtlib-verified-mechanisms-thinking",
        "strict_pass": (
            "scope, build, upstream chrono test, independent probe, and every "
            "applicable named mechanism verifier must pass"
        ),
        "mechanism_reporting": {
            "textual_hints": "diagnostic_only",
            "structural_mechanisms": "tokenized_scope_checks",
            "verified_mechanisms": "compile_and_focused_probe_gated",
            "compile_failure": "verified_mechanisms_unavailable",
        },
    }
    upgraded["demo_contract"] = {
        **upgraded["demo_contract"],
        "schema_version": "public-pr-verified-mechanism-thinking-demo-v1",
        "success_condition": (
            "scope, build, tests, independent probe, and every applicable named "
            "mechanism verifier pass"
        ),
        "claim_template": (
            "One task was evaluated with thinking enabled, best-of-four compiler "
            "repair, and compile-gated named mechanism verification."
        ),
    }
    return upgraded
