
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


POLICY_ID = "RN-E01"
NAMES_PROBE = '#include "robot_name.h"\nint main() {\n    robot_name::robot value;\n    const auto before = value.name();\n    value.reset();\n    return before == value.name() ? 1 : 0;\n}\n'
SIGNATURE_PROBE = '#include "robot_name.h"\n#include <string>\n#include <type_traits>\nusing Robot = robot_name::robot;\nstatic_assert(std::is_default_constructible_v<Robot>);\nstatic_assert(std::is_same_v<decltype(&Robot::name), const std::string& (Robot::*)() const>);\nstatic_assert(std::is_same_v<decltype(&Robot::reset), void (Robot::*)()>);\nint main() { return 0; }\n'
LINK_PROBE = '#include "robot_name.h"\n#include <iostream>\nint main() {\n    robot_name::robot value;\n    if (value.name().size() != 5) return 1;\n    std::cout << "ok\\n";\n    return 0;\n}\n'


def checks(ctx: Context) -> list[KernelReceipt]:
    return [
        compile_only(ctx, "RN-E01-A", "public_names", "api_names.cpp", NAMES_PROBE),
        compile_only(ctx, "RN-E01-B", "exact_signatures", "api_signatures.cpp", SIGNATURE_PROBE),
        compile_and_run(ctx, "RN-E01-C", "implementation_link", "api_link.cpp", LINK_PROBE, 'ok\n'),
    ]


if __name__ == "__main__":
    raise SystemExit(execute(CONTRACT, POLICY_ID, Path(__file__), checks))
