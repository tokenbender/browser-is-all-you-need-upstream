
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))

from strange_cpp import Context, KernelReceipt, execute
from strange_cpp_semantic import compile_and_run

from _contract import CONTRACT


POLICY_ID = "DN-E04"
PROBE = r'''#include "dnd_character.h"
#include <array>
#include <iostream>
#include <string>
int main(int argc, char** argv) {
    if (argc != 2) return 90;
    const std::string group(argv[1]);
    if (group == "negative_floor") {
        if (dnd_character::modifier(3) != -4 || dnd_character::modifier(5) != -3) return 1;
        if (dnd_character::modifier(7) != -2 || dnd_character::modifier(9) != -1) return 2;
    } else if (group == "ability_link_range") {
        for (int i = 0; i < 4000; ++i) {
            const int value = dnd_character::ability();
            if (value < 3 || value > 18) return 3;
        }
    } else if (group == "character_derivation") {
        for (int i = 0; i < 500; ++i) {
            const dnd_character::Character c;
            const std::array<int, 6> abilities{c.strength,c.dexterity,c.constitution,c.intelligence,c.wisdom,c.charisma};
            for (int value : abilities) if (value < 3 || value > 18) return 4;
            if (c.hitpoints != 10 + dnd_character::modifier(c.constitution)) return 5;
        }
    } else return 91;
    std::cout << "ok:" << group << '\n';
}
'''


def checks(ctx: Context) -> list[KernelReceipt]:
    return [
        compile_and_run(ctx, "DN-E04-A", "negative_floor", "signed_negative_floor.cpp", PROBE, "ok:negative_floor\n"),
        compile_and_run(ctx, "DN-E04-B", "ability_link_range", "signed_ability_link.cpp", PROBE, "ok:ability_link_range\n"),
        compile_and_run(ctx, "DN-E04-C", "character_derivation", "signed_character_derivation.cpp", PROBE, "ok:character_derivation\n"),
    ]


if __name__ == "__main__":
    raise SystemExit(execute(CONTRACT, POLICY_ID, Path(__file__), checks))
