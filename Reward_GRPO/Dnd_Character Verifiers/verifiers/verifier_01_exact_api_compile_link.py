
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))

from strange_cpp import Context
from strange_cpp import KernelReceipt
from strange_cpp import compile_and_run
from strange_cpp import compile_only
from strange_cpp import execute
from strange_cpp import official_checks

from _contract import CONTRACT


POLICY_ID = "DN-E01"
NAMES_PROBE = '#include "dnd_character.h"\nint main() {\n    dnd_character::Character value;\n    return value.hitpoints == 10 + dnd_character::modifier(value.constitution) ? 0 : 1;\n}\n'
SIGNATURE_PROBE = '#include "dnd_character.h"\n#include <type_traits>\n#include <utility>\nstatic_assert(std::is_same_v<decltype(&dnd_character::modifier), int (*)(int)>);\nstatic_assert(std::is_same_v<decltype(&dnd_character::ability), int (*)()>);\nstatic_assert(std::is_default_constructible_v<dnd_character::Character>);\nstatic_assert(std::is_same_v<decltype(std::declval<dnd_character::Character>().strength), int>);\nstatic_assert(std::is_same_v<decltype(std::declval<dnd_character::Character>().hitpoints), int>);\nint main() { return 0; }\n'
LINK_PROBE = '#include "dnd_character.h"\n#include <iostream>\nint main() {\n    if (dnd_character::modifier(3) != -4) return 1;\n    std::cout << "ok\\n";\n    return 0;\n}\n'


def checks(ctx: Context) -> list[KernelReceipt]:
    return [
        compile_only(ctx, "DN-E01-A", "public_names", "api_names.cpp", NAMES_PROBE),
        compile_only(ctx, "DN-E01-B", "exact_signatures", "api_signatures.cpp", SIGNATURE_PROBE),
        compile_and_run(ctx, "DN-E01-C", "implementation_link", "api_link.cpp", LINK_PROBE, 'ok\n'),
    ]


if __name__ == "__main__":
    raise SystemExit(execute(CONTRACT, POLICY_ID, Path(__file__), checks))
