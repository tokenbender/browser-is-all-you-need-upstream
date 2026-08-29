
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


POLICY_ID = "CX-E01"
NAMES_PROBE = '#include "complex_numbers.h"\nint main() {\n    complex_numbers::Complex a(1.0, 2.0);\n    complex_numbers::Complex b(3.0, 4.0);\n    auto c = a + b;\n    return c.real() == 4.0 ? 0 : 1;\n}\n'
SIGNATURE_PROBE = '#include "complex_numbers.h"\n#include <type_traits>\n#include <utility>\nusing C = complex_numbers::Complex;\nstatic_assert(std::is_constructible_v<C, double, double>);\nstatic_assert(std::is_same_v<decltype(std::declval<const C&>().real()), double>);\nstatic_assert(std::is_same_v<decltype(std::declval<const C&>().imag()), double>);\nstatic_assert(std::is_same_v<decltype(std::declval<const C&>().abs()), double>);\nstatic_assert(std::is_same_v<decltype(std::declval<const C&>().conj()), C>);\nstatic_assert(std::is_same_v<decltype(std::declval<const C&>().exp()), C>);\nstatic_assert(std::is_same_v<decltype(std::declval<const C&>() + std::declval<const C&>()), C>);\nstatic_assert(std::is_same_v<decltype(2.0 / std::declval<const C&>()), C>);\nint main() { return 0; }\n'
LINK_PROBE = '#include "complex_numbers.h"\n#include <iostream>\nint main() {\n    const complex_numbers::Complex value(1.0, -2.0);\n    const auto result = value.conj();\n    if (result.real() != 1.0 || result.imag() != 2.0) return 1;\n    std::cout << "ok\\n";\n    return 0;\n}\n'


def checks(ctx: Context) -> list[KernelReceipt]:
    return [
        compile_only(ctx, "CX-E01-A", "public_names", "api_names.cpp", NAMES_PROBE),
        compile_only(ctx, "CX-E01-B", "exact_signatures", "api_signatures.cpp", SIGNATURE_PROBE),
        compile_and_run(ctx, "CX-E01-C", "implementation_link", "api_link.cpp", LINK_PROBE, 'ok\n'),
    ]


if __name__ == "__main__":
    raise SystemExit(execute(CONTRACT, POLICY_ID, Path(__file__), checks))
