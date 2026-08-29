
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))

from strange_cpp import Context
from strange_cpp import KernelReceipt
from strange_cpp_semantic import compile_and_run
from strange_cpp import compile_only
from strange_cpp import execute
from strange_cpp import official_checks

from _contract import CONTRACT


POLICY_ID = "DN-E02"
SEMANTIC_PROBE = '#include "dnd_character.h"\n#include <array>\n#include <iostream>\n#include <string>\nint main(int argc, char** argv) {\n    if (argc != 2) return 90;\n    const std::string group(argv[1]);\n    if (group == "modifier_table") {\n        const std::array<int, 16> expected{-4,-3,-3,-2,-2,-1,-1,0,0,1,1,2,2,3,3,4};\n        for (int score = 3; score <= 18; ++score) {\n            if (dnd_character::modifier(score) != expected[static_cast<std::size_t>(score - 3)]) return 1;\n        }\n    } else if (group == "ability_range") {\n        for (int i = 0; i < 2000; ++i) {\n            const int value = dnd_character::ability();\n            if (value < 3 || value > 18) return 2;\n        }\n    } else if (group == "character_invariants") {\n        for (int i = 0; i < 200; ++i) {\n            const dnd_character::Character c;\n            const std::array<int, 6> values{c.strength,c.dexterity,c.constitution,c.intelligence,c.wisdom,c.charisma};\n            for (const int value : values) if (value < 3 || value > 18) return 3;\n            if (c.hitpoints != 10 + dnd_character::modifier(c.constitution)) return 4;\n        }\n    } else {\n        return 91;\n    }\n    std::cout << "ok:" << group << \'\\n\';\n    return 0;\n}\n'


def checks(ctx: Context) -> list[KernelReceipt]:
    return [
        compile_and_run(ctx, "DN-E02-A", "modifier_table", "semantic_modifier_table.cpp", SEMANTIC_PROBE, "ok:modifier_table\n"),
        compile_and_run(ctx, "DN-E02-B", "ability_range", "semantic_ability_range.cpp", SEMANTIC_PROBE, "ok:ability_range\n"),
        compile_and_run(ctx, "DN-E02-C", "character_invariants", "semantic_character_invariants.cpp", SEMANTIC_PROBE, "ok:character_invariants\n"),
    ]


if __name__ == "__main__":
    raise SystemExit(execute(CONTRACT, POLICY_ID, Path(__file__), checks))
