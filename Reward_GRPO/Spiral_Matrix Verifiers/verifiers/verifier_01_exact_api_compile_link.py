
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


POLICY_ID = "SM-E01"
NAMES_PROBE = '#include "spiral_matrix.h"\nint main() {\n    const auto value = spiral_matrix::spiral_matrix(1);\n    return value.size() == 1 && value[0][0] == 1 ? 0 : 1;\n}\n'
SIGNATURE_PROBE = '#include "spiral_matrix.h"\n#include <cstdint>\n#include <type_traits>\n#include <vector>\nusing Expected = std::vector<std::vector<std::uint32_t>> (*)(std::uint32_t);\nstatic_assert(std::is_same_v<decltype(&spiral_matrix::spiral_matrix), Expected>);\nint main() { return 0; }\n'
LINK_PROBE = '#include "spiral_matrix.h"\n#include <iostream>\nint main() {\n    const auto value = spiral_matrix::spiral_matrix(2);\n    if (value.size() != 2) return 1;\n    std::cout << "ok\\n";\n    return 0;\n}\n'


def checks(ctx: Context) -> list[KernelReceipt]:
    return [
        compile_only(ctx, "SM-E01-A", "public_names", "api_names.cpp", NAMES_PROBE),
        compile_only(ctx, "SM-E01-B", "exact_signatures", "api_signatures.cpp", SIGNATURE_PROBE),
        compile_and_run(ctx, "SM-E01-C", "implementation_link", "api_link.cpp", LINK_PROBE, 'ok\n'),
    ]


if __name__ == "__main__":
    raise SystemExit(execute(CONTRACT, POLICY_ID, Path(__file__), checks))
