
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))

from strange_cpp import Context, KernelReceipt, execute
from strange_cpp_semantic import compile_and_run

from _contract import CONTRACT


POLICY_ID = "CX-E04"
PROBE = r'''#include "complex_numbers.h"
#include <cmath>
#include <iostream>
#include <sstream>
#include <string>
using complex_numbers::Complex;
bool close(double a, double b) { return std::abs(a - b) < 1e-10; }
bool same(const Complex& value, double re, double im) { return close(value.real(), re) && close(value.imag(), im); }
int main(int argc, char** argv) {
    if (argc != 2) return 90;
    const std::string group(argv[1]);
    if (group == "equality_stream") {
        if (!(Complex(1, -2) == Complex(1, -2)) || Complex(1, -2) == Complex(1, 2)) return 1;
        std::ostringstream out; out << Complex(1, -2);
        if (!out) return 2;
    } else if (group == "scalar_add_subtract") {
        const Complex value(1, 2);
        if (!same(value + 3.0, 4, 2) || !same(3.0 + value, 4, 2)) return 3;
        if (!same(value - 3.0, -2, 2) || !same(3.0 - value, 2, -2)) return 4;
    } else if (group == "scalar_multiply_divide") {
        const Complex value(1, 2);
        if (!same(value * 3.0, 3, 6) || !same(3.0 * value, 3, 6)) return 5;
        if (!same(value / 2.0, 0.5, 1) || !same(2.0 / value, 0.4, -0.8)) return 6;
    } else return 91;
    std::cout << "ok:" << group << '\n';
}
'''


def checks(ctx: Context) -> list[KernelReceipt]:
    return [
        compile_and_run(ctx, "CX-E04-A", "equality_stream", "free_equality_stream.cpp", PROBE, "ok:equality_stream\n"),
        compile_and_run(ctx, "CX-E04-B", "scalar_add_subtract", "free_scalar_add_subtract.cpp", PROBE, "ok:scalar_add_subtract\n"),
        compile_and_run(ctx, "CX-E04-C", "scalar_multiply_divide", "free_scalar_multiply_divide.cpp", PROBE, "ok:scalar_multiply_divide\n"),
    ]


if __name__ == "__main__":
    raise SystemExit(execute(CONTRACT, POLICY_ID, Path(__file__), checks))
