
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


POLICY_ID = "CL-E02"
SEMANTIC_PROBE = '#include "clock.h"\n#include <iostream>\n#include <string>\nbool text(const date_independent::clock& value, const std::string& expected) {\n    return static_cast<std::string>(value) == expected;\n}\nint main(int argc, char** argv) {\n    if (argc != 2) return 90;\n    const std::string group(argv[1]);\n    if (group == "normalization") {\n        if (!text(date_independent::clock::at(25, 160), "03:40")) return 1;\n        if (!text(date_independent::clock::at(-25, -160), "20:20")) return 2;\n        if (!text(date_independent::clock::at(100, -3000), "02:00")) return 3;\n    } else if (group == "arithmetic") {\n        auto a = date_independent::clock::at(10, 3); a.plus(61);\n        auto b = date_independent::clock::at(0, 3); b.minus(4);\n        auto c = date_independent::clock::at(23, 59); c.plus(2).minus(1441);\n        if (!text(a, "11:04") || !text(b, "23:59") || !text(c, "00:00")) return 4;\n    } else if (group == "format_equality") {\n        if (!text(date_independent::clock::at(8, 3), "08:03")) return 5;\n        if (!(date_independent::clock::at(24, 0) == date_independent::clock::at(0, 0))) return 6;\n        if (date_independent::clock::at(0, 1) == date_independent::clock::at(0, 2)) return 7;\n        if (!(date_independent::clock::at(-1, 60) == date_independent::clock::at(0, 0))) return 8;\n    } else {\n        return 91;\n    }\n    std::cout << "ok:" << group << \'\\n\';\n    return 0;\n}\n'


def checks(ctx: Context) -> list[KernelReceipt]:
    return [
        compile_and_run(ctx, "CL-E02-A", "normalization", "semantic_normalization.cpp", SEMANTIC_PROBE, "ok:normalization\n"),
        compile_and_run(ctx, "CL-E02-B", "arithmetic", "semantic_arithmetic.cpp", SEMANTIC_PROBE, "ok:arithmetic\n"),
        compile_and_run(ctx, "CL-E02-C", "format_equality", "semantic_format_equality.cpp", SEMANTIC_PROBE, "ok:format_equality\n"),
    ]


if __name__ == "__main__":
    raise SystemExit(execute(CONTRACT, POLICY_ID, Path(__file__), checks))
