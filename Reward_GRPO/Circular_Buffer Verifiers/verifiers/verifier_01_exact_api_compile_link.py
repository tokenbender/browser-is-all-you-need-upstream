
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


POLICY_ID = "CB-E01"
NAMES_PROBE = '#include "circular_buffer.h"\nint main() {\n    circular_buffer::circular_buffer<int> values(2);\n    values.write(1);\n    return values.read() == 1 ? 0 : 1;\n}\n'
SIGNATURE_PROBE = '#include "circular_buffer.h"\n#include <cstddef>\n#include <type_traits>\nusing Buffer = circular_buffer::circular_buffer<int>;\nstatic_assert(std::is_constructible_v<Buffer, std::size_t>);\nstatic_assert(std::is_same_v<decltype(&Buffer::read), int (Buffer::*)()>);\nstatic_assert(std::is_same_v<decltype(&Buffer::write), void (Buffer::*)(int)>);\nstatic_assert(std::is_same_v<decltype(&Buffer::overwrite), void (Buffer::*)(int)>);\nstatic_assert(std::is_same_v<decltype(&Buffer::clear), void (Buffer::*)()>);\nint main() { return 0; }\n'
LINK_PROBE = '#include "circular_buffer.h"\n#include <iostream>\nint main() {\n    circular_buffer::circular_buffer<int> values(2);\n    values.write(7);\n    values.overwrite(8);\n    if (values.read() != 7 || values.read() != 8) return 1;\n    values.clear();\n    std::cout << "ok\\n";\n    return 0;\n}\n'


def checks(ctx: Context) -> list[KernelReceipt]:
    return [
        compile_only(ctx, "CB-E01-A", "public_names", "api_names.cpp", NAMES_PROBE),
        compile_only(ctx, "CB-E01-B", "exact_signatures", "api_signatures.cpp", SIGNATURE_PROBE),
        compile_and_run(ctx, "CB-E01-C", "implementation_link", "api_link.cpp", LINK_PROBE, 'ok\n'),
    ]


if __name__ == "__main__":
    raise SystemExit(execute(CONTRACT, POLICY_ID, Path(__file__), checks))
