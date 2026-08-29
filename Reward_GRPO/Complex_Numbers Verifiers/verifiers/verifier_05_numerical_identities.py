
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))

from strange_cpp import Context, KernelReceipt, execute
from strange_cpp_semantic import compile_and_run

from _contract import CONTRACT


POLICY_ID = "CX-E05"
PROBE = r'''#include "complex_numbers.h"
#include <cmath>
#include <iostream>
#include <string>
using complex_numbers::Complex;
bool close(double a, double b) { return std::abs(a - b) < 1e-9; }
bool same(const Complex& a, const Complex& b) { return close(a.real(), b.real()) && close(a.imag(), b.imag()); }
int main(int argc, char** argv) {
    if (argc != 2) return 90;
    const std::string group(argv[1]);
    if (group == "division_identity") {
        const Complex z(1.25, -2.5), w(-0.75, 3.0);
        if (!same((z / w) * w, z) || !same((z * w) / w, z)) return 1;
    } else if (group == "conjugate_magnitude") {
        const Complex z(-3.0, 4.0); const Complex product = z * z.conj();
        if (!close(z.abs(), 5.0) || !close(product.real(), 25.0) || !close(product.imag(), 0.0)) return 2;
        if (!close(z.abs() * z.abs(), product.real())) return 3;
    } else if (group == "exponential") {
        const double pi = std::acos(-1.0);
        if (!same(Complex(0, 0).exp(), Complex(1, 0))) return 4;
        if (!same(Complex(std::log(2.0), 0).exp(), Complex(2, 0))) return 5;
        if (!same(Complex(0, pi).exp(), Complex(-1, 0))) return 6;
        const Complex mixed = Complex(1.0, pi / 2).exp();
        if (!close(mixed.real(), 0.0) || !close(mixed.imag(), std::exp(1.0))) return 7;
    } else return 91;
    std::cout << "ok:" << group << '\n';
}
'''


def checks(ctx: Context) -> list[KernelReceipt]:
    return [
        compile_and_run(ctx, "CX-E05-A", "division_identity", "numeric_division_identity.cpp", PROBE, "ok:division_identity\n"),
        compile_and_run(ctx, "CX-E05-B", "conjugate_magnitude", "numeric_conjugate_magnitude.cpp", PROBE, "ok:conjugate_magnitude\n"),
        compile_and_run(ctx, "CX-E05-C", "exponential", "numeric_exponential.cpp", PROBE, "ok:exponential\n"),
    ]


if __name__ == "__main__":
    raise SystemExit(execute(CONTRACT, POLICY_ID, Path(__file__), checks))
