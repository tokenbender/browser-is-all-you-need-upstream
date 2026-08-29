
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


POLICY_ID = "RN-E02"
SEMANTIC_PROBE = '#include "robot_name.h"\n#include <cctype>\n#include <iostream>\n#include <set>\n#include <string>\nbool valid(const std::string& name) {\n    return name.size() == 5 &&\n        std::isupper(static_cast<unsigned char>(name[0])) &&\n        std::isupper(static_cast<unsigned char>(name[1])) &&\n        std::isdigit(static_cast<unsigned char>(name[2])) &&\n        std::isdigit(static_cast<unsigned char>(name[3])) &&\n        std::isdigit(static_cast<unsigned char>(name[4]));\n}\nint main(int argc, char** argv) {\n    if (argc != 2) return 90;\n    const std::string group(argv[1]);\n    if (group == "format_stability") {\n        const robot_name::robot value;\n        const std::string first = value.name();\n        if (!valid(first) || value.name() != first || value.name() != first) return 1;\n    } else if (group == "reset") {\n        robot_name::robot value;\n        const std::string first = value.name();\n        value.reset();\n        if (!valid(value.name()) || value.name() == first) return 2;\n    } else if (group == "uniqueness") {\n        std::set<std::string> names;\n        for (int i = 0; i < 2000; ++i) {\n            robot_name::robot value;\n            if (!valid(value.name()) || !names.insert(value.name()).second) return 3;\n        }\n        if (names.size() != 2000) return 4;\n    } else {\n        return 91;\n    }\n    std::cout << "ok:" << group << \'\\n\';\n    return 0;\n}\n'


def checks(ctx: Context) -> list[KernelReceipt]:
    return [
        compile_and_run(ctx, "RN-E02-A", "format_stability", "semantic_format_stability.cpp", SEMANTIC_PROBE, "ok:format_stability\n"),
        compile_and_run(ctx, "RN-E02-B", "reset", "semantic_reset.cpp", SEMANTIC_PROBE, "ok:reset\n"),
        compile_and_run(ctx, "RN-E02-C", "uniqueness", "semantic_uniqueness.cpp", SEMANTIC_PROBE, "ok:uniqueness\n"),
    ]


if __name__ == "__main__":
    raise SystemExit(execute(CONTRACT, POLICY_ID, Path(__file__), checks))
