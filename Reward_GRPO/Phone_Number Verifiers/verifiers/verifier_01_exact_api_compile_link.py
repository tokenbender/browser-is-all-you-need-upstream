
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


POLICY_ID = "PH-E01"
NAMES_PROBE = '#include "phone_number.h"\nint main() {\n    phone_number::phone_number value("2234567890");\n    return value.area_code() == "223" ? 0 : 1;\n}\n'
SIGNATURE_PROBE = '#include "phone_number.h"\n#include <string>\n#include <type_traits>\n#include <utility>\nusing Phone = phone_number::phone_number;\nstatic_assert(std::is_constructible_v<Phone, const std::string&>);\nstatic_assert(std::is_same_v<decltype(std::declval<const Phone&>().area_code()), std::string>);\nstatic_assert(std::is_same_v<decltype(std::declval<const Phone&>().number()), std::string>);\nstatic_assert(std::is_same_v<decltype(static_cast<std::string>(std::declval<const Phone&>())), std::string>);\nint main() { return 0; }\n'
LINK_PROBE = '#include "phone_number.h"\n#include <iostream>\nint main() {\n    const phone_number::phone_number value("1 (223) 456-7890");\n    std::cout << value.number() << \'\\n\';\n    return 0;\n}\n'


def checks(ctx: Context) -> list[KernelReceipt]:
    return [
        compile_only(ctx, "PH-E01-A", "public_names", "api_names.cpp", NAMES_PROBE),
        compile_only(ctx, "PH-E01-B", "exact_signatures", "api_signatures.cpp", SIGNATURE_PROBE),
        compile_and_run(ctx, "PH-E01-C", "implementation_link", "api_link.cpp", LINK_PROBE, '2234567890\n'),
    ]


if __name__ == "__main__":
    raise SystemExit(execute(CONTRACT, POLICY_ID, Path(__file__), checks))
