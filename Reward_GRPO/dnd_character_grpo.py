






from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Sequence

from glm47_posttraining.aider_polyglot.dataset import (
    SOURCE_MANIFEST_KIND,
    build_aider_polyglot_datasets,
)
from glm47_posttraining.aider_polyglot.harness import run_sandbox_preflight
from glm47_posttraining.aider_polyglot.schema import AiderShadowRubric
from glm47_posttraining.integrations.miles_aider_polyglot import (
    neutralize_infrastructure_scores,
)
from glm47_posttraining.integrations.miles_aider_polyglot import (
    reward_func as aider_reward_func,
)
from glm47_posttraining.integrations.miles_aider_polyglot import (
    run_response_contract_preflight,
)


CURRICULUM_NAME = "dnd-character-v1"
DATASET_KIND = "aider-polyglot-cpp-shadow-grpo"
POLYGLOT_COMMIT = "7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f"
VERIFICATION_GATE = "dnd-character-strange-12-independent-kernel-gcc13-v1"
EDITABLE_FILES = ["dnd_character.h", "dnd_character.cpp"]
HIDDEN_TEST = "dnd_character_hidden_test.cpp"
POLICY_IDS = ["DN-E01", "DN-E02", "DN-E03", "DN-E04"]
KERNEL_IDS = (
    "DN-E01-A",
    "DN-E01-B",
    "DN-E01-C",
    "DN-E02-A",
    "DN-E02-B",
    "DN-E02-C",
    "DN-E03-A",
    "DN-E03-B",
    "DN-E03-C",
    "DN-E04-A",
    "DN-E04-B",
    "DN-E04-C",
)
KERNEL_COUNT = len(KERNEL_IDS)
KERNEL_RECEIPT_RE = re.compile(
    r"GLM47_DND_KERNELS_V1:([01]{12})\nGLM47_AIDER_PASS_[0-9a-f]{32}"
)


INSTRUCTIONS = r"""# D&D Character

Generate a Dungeons & Dragons character. Each ability is the sum of the
largest three of four independent six-sided dice rolls. The ability modifier
is `(score - 10) / 2` rounded down mathematically, including for negative odd
values. Initial hit points are 10 plus the constitution modifier.

The public C++17 interface is exact:

```cpp
namespace dnd_character {
int modifier(int score);
int ability();

struct Character {
    Character();
    int strength;
    int dexterity;
    int constitution;
    int intelligence;
    int wisdom;
    int charisma;
    int hitpoints;
};
}
```

Every generated ability must be between 3 and 18. Definitions placed in a
header must obey C++ one-definition rules. Only `dnd_character.h` and
`dnd_character.cpp` are editable. The build uses C++17 with
`-Wall -Wextra -Wpedantic -Werror`. Do not modify or attempt to inspect the
hidden verifier.
"""


EXACT_HEADER = r"""#pragma once

namespace dnd_character {

int modifier(int score);
int ability();

struct Character {
    Character();
    int strength;
    int dexterity;
    int constitution;
    int intelligence;
    int wisdom;
    int charisma;
    int hitpoints;
};

}  // namespace dnd_character
"""


EMPTY_HEADER = r"""#pragma once

namespace dnd_character {
}
"""


EMPTY_SOURCE = r"""#include "dnd_character.h"

namespace dnd_character {
}
"""


MISSING_DEFINITIONS_SOURCE = EMPTY_SOURCE


TRUNCATING_SOURCE = r"""#include "dnd_character.h"

#include <algorithm>
#include <array>
#include <cstdlib>
#include <numeric>

namespace dnd_character {

int modifier(int score) { return (score - 10) / 2; }

int ability() {
    std::array<int, 4> rolls{};
    for (int& roll : rolls) roll = 1 + std::rand() % 6;
    return std::accumulate(rolls.begin(), rolls.end(), 0) -
           *std::min_element(rolls.begin(), rolls.end());
}

Character::Character()
    : strength(ability()),
      dexterity(ability()),
      constitution(ability()),
      intelligence(ability()),
      wisdom(ability()),
      charisma(ability()),
      hitpoints(10 + modifier(constitution)) {}

}  // namespace dnd_character
"""


OUT_OF_RANGE_SOURCE = r"""#include "dnd_character.h"

#include <cmath>

namespace dnd_character {

int modifier(int score) {
    return static_cast<int>(std::floor((score - 10) / 2.0));
}

int ability() { return 19; }

Character::Character()
    : strength(ability()),
      dexterity(ability()),
      constitution(ability()),
      intelligence(ability()),
      wisdom(ability()),
      charisma(ability()),
      hitpoints(10 + modifier(constitution)) {}

}  // namespace dnd_character
"""


BAD_DICE_SOURCE = r"""#include "dnd_character.h"

#include <cmath>
#include <cstdlib>

namespace dnd_character {

int modifier(int score) {
    return static_cast<int>(std::floor((score - 10) / 2.0));
}

int ability() { return 1 + std::rand() % 6; }

Character::Character()
    : strength(ability()),
      dexterity(ability()),
      constitution(ability()),
      intelligence(ability()),
      wisdom(ability()),
      charisma(ability()),
      hitpoints(10 + modifier(constitution)) {}

}  // namespace dnd_character
"""


BAD_HITPOINT_SOURCE = r"""#include "dnd_character.h"

#include <cmath>

namespace dnd_character {

int modifier(int score) {
    return static_cast<int>(std::floor((score - 10) / 2.0));
}

int ability() { return 10; }

Character::Character()
    : strength(ability()),
      dexterity(ability()),
      constitution(ability()),
      intelligence(ability()),
      wisdom(ability()),
      charisma(ability()),
      hitpoints(10 + constitution) {}

}  // namespace dnd_character
"""


BAD_CHARACTER_SOURCE = r"""#include "dnd_character.h"

#include <cmath>

namespace dnd_character {

int modifier(int score) {
    return static_cast<int>(std::floor((score - 10) / 2.0));
}

int ability() { return 10; }

Character::Character()
    : strength(ability()),
      dexterity(ability()),
      constitution(ability()),
      intelligence(ability()),
      wisdom(ability()),
      charisma(19),
      hitpoints(10 + modifier(constitution)) {}

}  // namespace dnd_character
"""


ODR_HEADER = r"""#pragma once

namespace dnd_character {

int modifier(int score);
int ability();

struct Character {
    Character();
    int strength;
    int dexterity;
    int constitution;
    int intelligence;
    int wisdom;
    int charisma;
    int hitpoints;
};

int modifier(int score) { return score < 10 ? (score - 11) / 2 : (score - 10) / 2; }
int ability() { return 10; }
Character::Character()
    : strength(ability()), dexterity(ability()), constitution(ability()),
      intelligence(ability()), wisdom(ability()), charisma(ability()),
      hitpoints(10 + modifier(constitution)) {}

}  // namespace dnd_character
"""


ODR_SOURCE = r"""#include "dnd_character.h"
"""


HIDDEN_TEST_SOURCE = r"""#include "dnd_character.h"

#include <array>
#include <iostream>
#include <type_traits>

static_assert(std::is_same_v<decltype(&dnd_character::modifier), int (*)(int)>);
static_assert(std::is_same_v<decltype(&dnd_character::ability), int (*)()>);
static_assert(std::is_default_constructible_v<dnd_character::Character>);
static_assert(std::is_same_v<decltype(dnd_character::Character::strength), int>);
static_assert(std::is_same_v<decltype(dnd_character::Character::dexterity), int>);
static_assert(std::is_same_v<decltype(dnd_character::Character::constitution), int>);
static_assert(std::is_same_v<decltype(dnd_character::Character::intelligence), int>);
static_assert(std::is_same_v<decltype(dnd_character::Character::wisdom), int>);
static_assert(std::is_same_v<decltype(dnd_character::Character::charisma), int>);
static_assert(std::is_same_v<decltype(dnd_character::Character::hitpoints), int>);

template <typename Function>
bool guarded(Function&& function) {
    try {
        return static_cast<bool>(function());
    } catch (...) {
        return false;
    }
}

bool modifier_table() {
    const std::array<int, 16> expected{-4, -3, -3, -2, -2, -1, -1, 0,
                                       0,  1,  1,  2,  2,  3,  3, 4};
    for (int score = 3; score <= 18; ++score) {
        if (dnd_character::modifier(score) !=
            expected[static_cast<std::size_t>(score - 3)]) return false;
    }
    return true;
}

bool abilities_in_range(int count) {
    for (int i = 0; i < count; ++i) {
        const int value = dnd_character::ability();
        if (value < 3 || value > 18) return false;
    }
    return true;
}

bool characters_valid(int count) {
    for (int i = 0; i < count; ++i) {
        const dnd_character::Character character;
        const std::array<int, 6> abilities{
            character.strength,
            character.dexterity,
            character.constitution,
            character.intelligence,
            character.wisdom,
            character.charisma,
        };
        for (const int value : abilities) {
            if (value < 3 || value > 18) return false;
        }
        if (character.hitpoints !=
            10 + dnd_character::modifier(character.constitution)) return false;
    }
    return true;
}

int main() {
    std::array<bool, 12> kernels{};

    kernels[0] = guarded([] { return characters_valid(1); });
    kernels[1] = true;
    kernels[2] = guarded([] { return dnd_character::modifier(3) == -4; });

    kernels[3] = guarded([] { return modifier_table(); });
    kernels[4] = guarded([] { return abilities_in_range(2000); });
    kernels[5] = guarded([] { return characters_valid(200); });

    kernels[6] = guarded([] { return modifier_table(); });
    kernels[7] = guarded([] { return abilities_in_range(1); });
    kernels[8] = guarded([] { return characters_valid(1); });

    kernels[9] = guarded([] {
        return dnd_character::modifier(3) == -4 &&
               dnd_character::modifier(5) == -3 &&
               dnd_character::modifier(7) == -2 &&
               dnd_character::modifier(9) == -1;
    });
    kernels[10] = guarded([] { return abilities_in_range(4000); });
    kernels[11] = guarded([] { return characters_valid(500); });

    std::cout << "GLM47_DND_KERNELS_V1:";
    for (const bool passed : kernels) std::cout << (passed ? '1' : '0');
    std::cout << '\n';
    return 0;
}
"""


EPISODES = (
    ("full-solve", "missing-public-api", EMPTY_HEADER, EMPTY_SOURCE, ""),
    (
        "missing-definitions-repair",
        "declared-functions-not-defined",
        EXACT_HEADER,
        MISSING_DEFINITIONS_SOURCE,
        "The linker reports unresolved D&D Character function definitions.",
    ),
    (
        "modifier-floor-repair",
        "negative-odd-modifier-truncation",
        EXACT_HEADER,
        TRUNCATING_SOURCE,
        "Negative odd ability modifiers are truncated toward zero instead of rounded down.",
    ),
    (
        "ability-range-repair",
        "generated-ability-out-of-range",
        EXACT_HEADER,
        OUT_OF_RANGE_SOURCE,
        "Generated abilities must always remain between 3 and 18.",
    ),
    (
        "dice-generation-repair",
        "single-die-instead-of-best-three",
        EXACT_HEADER,
        BAD_DICE_SOURCE,
        "The generator returns one die instead of the sum of the best three of four dice.",
    ),
    (
        "hitpoint-repair",
        "constitution-modifier-not-used",
        EXACT_HEADER,
        BAD_HITPOINT_SOURCE,
        "Hit points must be 10 plus the constitution modifier, not 10 plus constitution.",
    ),
    (
        "character-invariant-repair",
        "one-character-field-out-of-range",
        EXACT_HEADER,
        BAD_CHARACTER_SOURCE,
        "Every one of the six stored character abilities must be in the 3-to-18 range.",
    ),
    (
        "eval-feedback-repair",
        "observed-midbreak-header-odr-failure",
        ODR_HEADER,
        ODR_SOURCE,
        "Observed evaluation repair failure: free function and constructor bodies moved into the header caused multiple-definition linker errors.",
    ),
)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _write_task_root(root: Path) -> Path:
    practice = root / "cpp" / "exercises" / "practice"
    hidden_hash = _sha256_text(HIDDEN_TEST_SOURCE)
    task_ids: list[str] = []
    for episode_kind, signature, header, source, feedback in EPISODES:
        task_id = f"dnd-character--{episode_kind}"
        task_ids.append(task_id)
        exercise = practice / task_id
        docs = exercise / ".docs"
        docs.mkdir(parents=True)
        task_instructions = INSTRUCTIONS
        if feedback:
            task_instructions += f"\n\n## Executed failure evidence\n\n{feedback}\n"
        (docs / "instructions.md").write_text(task_instructions, encoding="utf-8")
        (exercise / "dnd_character.h").write_text(header, encoding="utf-8")
        (exercise / "dnd_character.cpp").write_text(source, encoding="utf-8")
        (exercise / HIDDEN_TEST).write_text(HIDDEN_TEST_SOURCE, encoding="utf-8")
        (exercise / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.16)\nproject(dnd_character LANGUAGES CXX)\n",
            encoding="utf-8",
        )
        rubric = AiderShadowRubric(
            task_id=task_id,
            split="train",
            editable_files=EDITABLE_FILES,
            hidden_test_file=HIDDEN_TEST,
            hidden_test_sha256=hidden_hash,
            source_prompt_sha256=_sha256_text(task_instructions),
            reference_answer_packaged=False,
            verification_stage="passed",
            verification_gate=VERIFICATION_GATE,
            family="dnd-character",
            category="dnd-character-strange",
            lineage_id="fixed26/dnd-character",
            episode_kind=episode_kind,
            objective_group="dnd-character-strange",
            failure_signature=signature,
            tags=[
                "official-task-training-authorized",
                "whole-file-action",
                "strange-kernel-reward",
                *POLICY_IDS,
            ],
        )
        (exercise / ".rubric.json").write_text(
            rubric.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
    manifest = {
        "kind": SOURCE_MANIFEST_KIND,
        "schema_version": 1,
        "source_locator": (
            f"official:Aider-AI/polyglot-benchmark@{POLYGLOT_COMMIT}/dnd-character"
        ),
        "counts": {"tasks": len(task_ids), "train": len(task_ids), "validation": 0},
        "task_ids": task_ids,
        "contract": {
            "official_task_id_overlap": ["dnd-character"],
            "official_training_authorized": True,
            "reference_answers_packaged": False,
            "shared_hidden_tests_within_lineage": True,
            "verifier_policy_ids": POLICY_IDS,
            "kernel_count": KERNEL_COUNT,
        },
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return root


def build_data(args: argparse.Namespace) -> dict[str, Path]:
    if args.curriculum not in (None, CURRICULUM_NAME):
        raise ValueError(f"unsupported curriculum: {args.curriculum}")
    with TemporaryDirectory(prefix="dnd-character-strange-tasks-") as temporary:
        task_root = _write_task_root(Path(temporary))
        return build_aider_polyglot_datasets(
            task_root,
            args.out,
            train_limit=args.train_limit,
            monitor_limit=args.eval_limit or len(EPISODES),
            profile=args.profile,
            run_id=args.run_id,
            sort_by_size=args.sort_by_size,
            force=args.force,
        )


def _invalid_kernel_reward(record: dict[str, Any], reason: str) -> dict[str, Any]:
    record["verifier_pack"] = "dnd-character-strange-v1"
    record["verifier_policy_ids"] = POLICY_IDS
    record["verification_gate"] = VERIFICATION_GATE
    record["kernel_results"] = [
        {"kernel_id": kernel_id, "kernel": None, "status": "invalid"}
        for kernel_id in KERNEL_IDS
    ]
    record["policy_results"] = [
        {"policy_id": policy_id, "kernel_sum": None, "status": "invalid"}
        for policy_id in POLICY_IDS
    ]
    record["kernel_sum"] = None
    record["kernel_total"] = KERNEL_COUNT
    record["kernel_status"] = "invalid"
    record["kernel_receipt_error"] = reason
    record["infrastructure_error"] = True
    record["reward"] = 0.0
    record["score"] = 0.0
    return record


def _extract_kernel_bits(record: dict[str, Any]) -> str | None:
    logs = record.get("logs")
    if not isinstance(logs, dict):
        return None
    test_log = logs.get("test")
    if not isinstance(test_log, str):
        return None
    matches = KERNEL_RECEIPT_RE.findall(test_log)
    return matches[-1] if matches else None


def _apply_kernel_reward(record: dict[str, Any]) -> dict[str, Any]:
    record["verifier_pack"] = "dnd-character-strange-v1"
    record["verifier_policy_ids"] = POLICY_IDS
    record["verification_gate"] = VERIFICATION_GATE
    if record.get("infrastructure_error"):
        return _invalid_kernel_reward(
            record, "underlying sandbox infrastructure error"
        )

    bits = _extract_kernel_bits(record)
    if bits is None:
        if record.get("all_tests_pass"):
            return _invalid_kernel_reward(
                record,
                "hidden verifier passed without an authenticated kernel receipt",
            )
        bits = "0" * KERNEL_COUNT

    kernel_values = [1 if value == "1" else -1 for value in bits]
    passed = sum(value == 1 for value in kernel_values)
    failed = KERNEL_COUNT - passed
    kernel_sum = sum(kernel_values)
    record["kernel_results"] = [
        {
            "kernel_id": kernel_id,
            "kernel": value,
            "status": "pass" if value == 1 else "fail",
        }
        for kernel_id, value in zip(KERNEL_IDS, kernel_values, strict=True)
    ]
    record["kernel_bits"] = bits
    record["policy_results"] = [
        {
            "policy_id": policy_id,
            "kernel_sum": sum(kernel_values[index : index + 3]),
            "status": (
                "pass"
                if all(value == 1 for value in kernel_values[index : index + 3])
                else "fail"
            ),
        }
        for policy_id, index in zip(
            POLICY_IDS, range(0, KERNEL_COUNT, 3), strict=True
        )
    ]
    record["kernel_passed"] = passed
    record["kernel_failed"] = failed
    record["kernel_sum"] = kernel_sum
    record["kernel_total"] = KERNEL_COUNT
    record["kernel_status"] = "pass" if passed == KERNEL_COUNT else "fail"
    record["tests_passed"] = passed
    record["tests_total"] = KERNEL_COUNT
    record["all_tests_pass"] = passed == KERNEL_COUNT
    record["reason"] = "passed" if passed == KERNEL_COUNT else "kernel_tests_failed"
    record["reward"] = kernel_sum / KERNEL_COUNT
    record["score"] = record["reward"]
    return record


async def reward_func(
    args: Any, sample: Any, **kwargs: Any
) -> dict[str, Any] | list[dict[str, Any]]:
    os.environ.setdefault("MILES_CPP_INCLUDE_LOGS", "1")
    result = await aider_reward_func(args, sample, **kwargs)
    if isinstance(result, list):
        records = [_apply_kernel_reward(record) for record in result]
        return neutralize_infrastructure_scores(records)
    return _apply_kernel_reward(result)


def preflight() -> None:
    run_response_contract_preflight()
    run_sandbox_preflight()
    with TemporaryDirectory(prefix="dnd-character-strange-preflight-") as temporary:
        root = Path(temporary)
        args = argparse.Namespace(
            curriculum=CURRICULUM_NAME,
            out=root / "data",
            train_limit=None,
            eval_limit=None,
            profile="dnd-character-preflight",
            run_id="dnd-character-preflight",
            sort_by_size=False,
            force=True,
        )
        paths = build_data(args)
        manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
        if (
            manifest.get("kind") != DATASET_KIND
            or manifest["counts"]["train"] != len(EPISODES)
        ):
            raise RuntimeError("D&D Character dataset preflight produced an invalid manifest")
    synthetic = _apply_kernel_reward(
        {
            "all_tests_pass": True,
            "infrastructure_error": False,
            "logs": {
                "test": (
                    "GLM47_DND_KERNELS_V1:101010101010\n"
                    "GLM47_AIDER_PASS_0123456789abcdef0123456789abcdef\n"
                )
            },
        }
    )
    if synthetic["kernel_sum"] != 0 or synthetic["kernel_passed"] != 6:
        raise RuntimeError("independent D&D Character kernel receipt preflight failed")
    print("DND_CHARACTER_STRANGE_REWARD_READY")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build-data")
    build.add_argument("--tasks-dir", required=True)
    build.add_argument("--out", required=True, type=Path)
    build.add_argument("--curriculum", choices=[CURRICULUM_NAME])
    build.add_argument("--train-limit", type=int)
    build.add_argument("--eval-limit", type=int)
    build.add_argument("--eval-splits", default="validation,test")
    build.add_argument("--profile", default="dnd-character-strange-grpo")
    build.add_argument("--run-id")
    build.add_argument("--sort-by-size", action="store_true")
    build.add_argument("--filter-train-oracle-full-marks", action="store_true")
    build.add_argument("--oracle-filter-workers", type=int, default=8)
    build.add_argument("--allow-non-gcc-curriculum", action="store_true")
    build.add_argument("--force", action="store_true")
    subparsers.add_parser("preflight")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    if args.command == "preflight":
        preflight()
        return
    if args.filter_train_oracle_full_marks:
        raise ValueError("the D&D Character curriculum is already verifier-bound")
    paths = build_data(args)
    print(
        json.dumps(
            {key: str(value) for key, value in paths.items()},
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
