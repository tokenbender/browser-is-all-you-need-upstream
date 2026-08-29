
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


POLICY_ID = "CX-E02"
SEMANTIC_PROBE = '#include "complex_numbers.h"\n#include <cmath>\n#include <iostream>\n#include <string>\nusing complex_numbers::Complex;\nbool close(double a, double b) { return std::abs(a - b) < 1e-10; }\nbool close_complex(const Complex& a, const Complex& b) {\n    return close(a.real(), b.real()) && close(a.imag(), b.imag());\n}\nint main(int argc, char** argv) {\n    if (argc != 2) return 90;\n    const std::string group(argv[1]);\n    if (group == "components_arithmetic") {\n        const Complex a(1.0, 2.0), b(3.0, -4.0);\n        if (!close_complex(a + b, Complex(4.0, -2.0))) return 1;\n        if (!close_complex(a - b, Complex(-2.0, 6.0))) return 2;\n        if (!close_complex(a * b, Complex(11.0, 2.0))) return 3;\n        if (!close_complex(a / b, Complex(-0.2, 0.4))) return 4;\n    } else if (group == "magnitude_conjugate") {\n        const Complex a(-3.0, 4.0);\n        if (!close(a.abs(), 5.0)) return 5;\n        if (!close_complex(a.conj(), Complex(-3.0, -4.0))) return 6;\n    } else if (group == "scalar_exponential") {\n        const Complex a(1.0, 2.0);\n        if (!close_complex(a + 2.0, Complex(3.0, 2.0))) return 7;\n        if (!close_complex(2.0 - a, Complex(1.0, -2.0))) return 8;\n        if (!close_complex(2.0 / Complex(0.0, 2.0), Complex(0.0, -1.0))) return 9;\n        const double pi = std::acos(-1.0);\n        if (!close_complex(Complex(0.0, pi).exp(), Complex(-1.0, 0.0))) return 10;\n    } else {\n        return 91;\n    }\n    std::cout << "ok:" << group << \'\\n\';\n    return 0;\n}\n'


def checks(ctx: Context) -> list[KernelReceipt]:
    return [
        compile_and_run(ctx, "CX-E02-A", "components_arithmetic", "semantic_components_arithmetic.cpp", SEMANTIC_PROBE, "ok:components_arithmetic\n"),
        compile_and_run(ctx, "CX-E02-B", "magnitude_conjugate", "semantic_magnitude_conjugate.cpp", SEMANTIC_PROBE, "ok:magnitude_conjugate\n"),
        compile_and_run(ctx, "CX-E02-C", "scalar_exponential", "semantic_scalar_exponential.cpp", SEMANTIC_PROBE, "ok:scalar_exponential\n"),
    ]


if __name__ == "__main__":
    raise SystemExit(execute(CONTRACT, POLICY_ID, Path(__file__), checks))
