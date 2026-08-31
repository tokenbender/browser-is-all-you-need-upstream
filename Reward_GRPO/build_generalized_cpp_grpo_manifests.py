"""Rebuild the generalized C++ GRPO registry and per-task trusted manifests.

Manifests follow the canary shape: candidate files are the fixture starter
pair, protected files pin every other fixture asset (including the starter
pair, which doubles as the rollout starting point), and policy entries stay
advisory and empty because the direct runner dispatches wrappers by policy id.
Each registry entry carries an oracle ``preflight_response`` rendered from the
fixture's ``.meta/example.*`` reference, which ``preflight`` must score 1.0.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "multi_env_fixtures"
OUTPUT = ROOT / "generalized_cpp_grpo_tasks"
REGISTRY = ROOT / "generalized_cpp_grpo_registry.json"
CANARY = ROOT / "generalized_cpp_grpo_canary"

# Starter curriculum: oracle-verified against the live verifier profile
# (G01..G05) on GCC 13.3; every task carries a complete .meta/example.h +
# .meta/example.cpp reference.  meetup is excluded (its header-only reference
# does not build standalone, so the G03 reference control is invalid), and
# robot-name / parallel-letter-frequency are excluded as nondeterministic
# under reward-worker load.
TASKS = [
    "clock",
    "complex-numbers",
    "crypto-square",
    "grade-school",
    "kindergarten-garden",
    "perfect-numbers",
]

POLICY_IDS = ("G02", "G03", "G04", "G05", "G06", "G07")
POLYGLOT_COMMIT = "7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def aider_listing(name: str, text: str) -> str:
    return f"{name}\n```cpp\n{text.rstrip()}\n```\n"


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    tasks: dict[str, object] = {
        "portable-arithmetic": {
            "manifest": "generalized_cpp_grpo_canary/manifest.json",
            "manifest_sha256": sha256(CANARY / "manifest.json"),
            "fixture_dir": "generalized_cpp_grpo_canary/fixture",
            "starter_dir": "generalized_cpp_grpo_canary/fixture",
            "train": False,
            "preflight_response": (
                "arithmetic.h\n```cpp\n#pragma once\n"
                "namespace demo { int add(int, int); int multiply(int, int); }\n```\n\n"
                "arithmetic.cpp\n```cpp\n#include \"arithmetic.h\"\n"
                "namespace demo { int add(int a, int b) { return a + b; } "
                "int multiply(int a, int b) { return a * b; } }\n```\n"
            ),
        }
    }
    for task_id in TASKS:
        fixture = FIXTURES / task_id
        if not fixture.is_dir() or fixture.is_symlink():
            raise ValueError(f"missing fixture: {task_id}")
        stem = task_id.replace("-", "_")
        candidate_files = [f"{stem}.cpp", f"{stem}.h"]
        protected = {
            path.relative_to(fixture).as_posix(): sha256(path)
            for path in sorted(fixture.rglob("*"))
            if path.is_file()
        }
        missing = [name for name in candidate_files if name not in protected]
        if missing:
            raise ValueError(f"{task_id} is missing starter files: {missing}")
        manifest = {
            "schema_version": 1,
            "task_id": task_id,
            "source": (
                f"official:Aider-AI/polyglot-benchmark@{POLYGLOT_COMMIT}"
                f"/cpp/exercises/practice/{task_id}"
            ),
            "candidate_files": candidate_files,
            "protected_files": protected,
            "fixture_dir": f"multi_env_fixtures/{task_id}",
            "policies": {policy: [] for policy in POLICY_IDS},
        }
        destination = OUTPUT / f"{task_id}.json"
        destination.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        example_h = (fixture / ".meta/example.h").read_text(encoding="utf-8")
        example_cpp = (fixture / ".meta/example.cpp").read_text(encoding="utf-8")
        preflight_response = (
            aider_listing(f"{stem}.h", example_h)
            + "\n"
            + aider_listing(f"{stem}.cpp", example_cpp)
        )
        tasks[task_id] = {
            "manifest": f"generalized_cpp_grpo_tasks/{task_id}.json",
            "manifest_sha256": sha256(destination),
            "fixture_dir": f"multi_env_fixtures/{task_id}",
            "preflight_response": preflight_response,
        }
        print(f"{task_id} {sha256(destination)}")
    registry = {"schema_version": 1, "tasks": tasks}
    REGISTRY.write_text(
        json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"registry {sha256(REGISTRY)}")


if __name__ == "__main__":
    main()
