
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


POLICY_ID = "CB-E02"
SEMANTIC_PROBE = '#include "circular_buffer.h"\n#include <iostream>\n#include <stdexcept>\n#include <string>\nint main(int argc, char** argv) {\n    if (argc != 2) return 90;\n    const std::string group(argv[1]);\n    if (group == "underflow_overflow") {\n        circular_buffer::circular_buffer<int> values(2);\n        bool underflow = false;\n        bool overflow = false;\n        try { static_cast<void>(values.read()); } catch (const std::domain_error&) { underflow = true; }\n        values.write(1);\n        values.write(2);\n        try { values.write(3); } catch (const std::domain_error&) { overflow = true; }\n        if (!underflow || !overflow) return 1;\n    } else if (group == "fifo_wraparound") {\n        circular_buffer::circular_buffer<std::string> values(3);\n        values.write("a"); values.write("b"); values.write("c");\n        if (values.read() != "a") return 2;\n        values.write("d");\n        if (values.read() != "b" || values.read() != "c" || values.read() != "d") return 3;\n    } else if (group == "clear_overwrite") {\n        circular_buffer::circular_buffer<int> values(2);\n        values.write(1); values.write(2); values.overwrite(3);\n        if (values.read() != 2 || values.read() != 3) return 4;\n        values.write(4); values.clear(); values.write(5);\n        if (values.read() != 5) return 5;\n        bool empty = false;\n        try { static_cast<void>(values.read()); } catch (const std::domain_error&) { empty = true; }\n        if (!empty) return 6;\n    } else {\n        return 91;\n    }\n    std::cout << "ok:" << group << \'\\n\';\n    return 0;\n}\n'


def checks(ctx: Context) -> list[KernelReceipt]:
    return [
        compile_and_run(ctx, "CB-E02-A", "underflow_overflow", "semantic_underflow_overflow.cpp", SEMANTIC_PROBE, "ok:underflow_overflow\n"),
        compile_and_run(ctx, "CB-E02-B", "fifo_wraparound", "semantic_fifo_wraparound.cpp", SEMANTIC_PROBE, "ok:fifo_wraparound\n"),
        compile_and_run(ctx, "CB-E02-C", "clear_overwrite", "semantic_clear_overwrite.cpp", SEMANTIC_PROBE, "ok:clear_overwrite\n"),
    ]


if __name__ == "__main__":
    raise SystemExit(execute(CONTRACT, POLICY_ID, Path(__file__), checks))
