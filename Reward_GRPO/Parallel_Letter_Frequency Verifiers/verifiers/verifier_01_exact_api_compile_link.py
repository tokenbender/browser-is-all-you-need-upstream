
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


POLICY_ID = "PL-E01"
NAMES_PROBE = '#include "parallel_letter_frequency.h"\n#include <string_view>\n#include <vector>\nint main() {\n    const std::vector<std::string_view> texts{"Aa"};\n    return parallel_letter_frequency::frequency(texts).at(\'a\') == 2 ? 0 : 1;\n}\n'
SIGNATURE_PROBE = '#include "parallel_letter_frequency.h"\n#include <cstddef>\n#include <string_view>\n#include <type_traits>\n#include <unordered_map>\n#include <vector>\nusing Expected = std::unordered_map<char, std::size_t> (*)(const std::vector<std::string_view>&);\nstatic_assert(std::is_same_v<decltype(&parallel_letter_frequency::frequency), Expected>);\nint main() { return 0; }\n'
LINK_PROBE = '#include "parallel_letter_frequency.h"\n#include <iostream>\n#include <string_view>\n#include <vector>\nint main() {\n    const std::vector<std::string_view> texts{"Aa!"};\n    if (parallel_letter_frequency::frequency(texts).at(\'a\') != 2) return 1;\n    std::cout << "ok\\n";\n    return 0;\n}\n'


def checks(ctx: Context) -> list[KernelReceipt]:
    return [
        compile_only(ctx, "PL-E01-A", "public_names", "api_names.cpp", NAMES_PROBE),
        compile_only(ctx, "PL-E01-B", "exact_signatures", "api_signatures.cpp", SIGNATURE_PROBE),
        compile_and_run(ctx, "PL-E01-C", "implementation_link", "api_link.cpp", LINK_PROBE, 'ok\n'),
    ]


if __name__ == "__main__":
    raise SystemExit(execute(CONTRACT, POLICY_ID, Path(__file__), checks))
