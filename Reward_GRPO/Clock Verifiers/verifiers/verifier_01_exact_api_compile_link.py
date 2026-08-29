
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


POLICY_ID = "CL-E01"
NAMES_PROBE = '#include "clock.h"\nint main() {\n    auto value = date_independent::clock::at(0, 0);\n    value.plus(1).minus(1);\n    return value == date_independent::clock::at(0, 0) ? 0 : 1;\n}\n'
SIGNATURE_PROBE = '#include "clock.h"\n#include <string>\n#include <type_traits>\n#include <utility>\nusing Clock = date_independent::clock;\nstatic_assert(std::is_same_v<decltype(Clock::at(1, 2)), Clock>);\nstatic_assert(std::is_same_v<decltype(std::declval<Clock&>().plus(1)), Clock&>);\nstatic_assert(std::is_same_v<decltype(std::declval<Clock&>().minus(1)), Clock&>);\nstatic_assert(std::is_same_v<decltype(static_cast<std::string>(std::declval<const Clock&>())), std::string>);\nstatic_assert(std::is_same_v<decltype(std::declval<const Clock&>() == std::declval<const Clock&>()), bool>);\nint main() { return 0; }\n'
LINK_PROBE = '#include "clock.h"\n#include <iostream>\n#include <string>\nint main() {\n    auto value = date_independent::clock::at(24, -1);\n    std::cout << static_cast<std::string>(value) << \'\\n\';\n    return 0;\n}\n'


def checks(ctx: Context) -> list[KernelReceipt]:
    return [
        compile_only(ctx, "CL-E01-A", "public_names", "api_names.cpp", NAMES_PROBE),
        compile_only(ctx, "CL-E01-B", "exact_signatures", "api_signatures.cpp", SIGNATURE_PROBE),
        compile_and_run(ctx, "CL-E01-C", "implementation_link", "api_link.cpp", LINK_PROBE, '23:59\n'),
    ]


if __name__ == "__main__":
    raise SystemExit(execute(CONTRACT, POLICY_ID, Path(__file__), checks))
