
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))

from strange_cpp import Context, KernelReceipt, compile_and_run as compile_plain, execute
from strange_cpp_semantic import compile_and_run

from _contract import CONTRACT


POLICY_ID = "SM-E05"
ORACLE_PROBE = r'''#include "spiral_matrix.h"
#include <algorithm>
#include <cstdint>
#include <iostream>
#include <string>
#include <vector>
using Matrix = std::vector<std::vector<std::uint32_t>>;
Matrix oracle(std::uint32_t n) {
    Matrix out(n, std::vector<std::uint32_t>(n));
    int top = 0, left = 0, bottom = static_cast<int>(n) - 1, right = static_cast<int>(n) - 1;
    std::uint32_t value = 1;
    while (top <= bottom && left <= right) {
        for (int c = left; c <= right; ++c) out[static_cast<std::size_t>(top)][static_cast<std::size_t>(c)] = value++;
        ++top;
        for (int r = top; r <= bottom; ++r) out[static_cast<std::size_t>(r)][static_cast<std::size_t>(right)] = value++;
        --right;
        if (top <= bottom) { for (int c = right; c >= left; --c) out[static_cast<std::size_t>(bottom)][static_cast<std::size_t>(c)] = value++; --bottom; }
        if (left <= right) { for (int r = bottom; r >= top; --r) out[static_cast<std::size_t>(r)][static_cast<std::size_t>(left)] = value++; ++left; }
    }
    return out;
}
int main(int argc, char** argv) {
    if (argc != 2) return 90;
    const std::string group(argv[1]);
    if (group == "extended_oracle") {
        for (std::uint32_t n = 6; n <= 40; ++n) if (spiral_matrix::spiral_matrix(n) != oracle(n)) return 1;
    } else if (group == "shape_permutation") {
        for (std::uint32_t n = 1; n <= 64; ++n) {
            const auto matrix = spiral_matrix::spiral_matrix(n);
            if (matrix.size() != n) return 2;
            std::vector<std::uint32_t> values;
            for (const auto& row : matrix) { if (row.size() != n) return 3; values.insert(values.end(), row.begin(), row.end()); }
            std::sort(values.begin(), values.end());
            for (std::uint32_t i = 0; i < n * n; ++i) if (values[i] != i + 1) return 4;
        }
    } else return 91;
    std::cout << "ok:" << group << '\n';
}
'''
SANITIZER_PROBE = r'''#include "spiral_matrix.h"
#include <cstdint>
#include <iostream>
int main() {
    for (std::uint32_t n = 0; n <= 64; ++n) {
        const auto matrix = spiral_matrix::spiral_matrix(n);
        if (matrix.size() != n) return 1;
        for (const auto& row : matrix) if (row.size() != n) return 2;
    }
    std::cout << "ok:sanitized\n";
}
'''


def checks(ctx: Context) -> list[KernelReceipt]:
    return [
        compile_and_run(ctx, "SM-E05-A", "extended_oracle", "extended_oracle.cpp", ORACLE_PROBE, "ok:extended_oracle\n"),
        compile_and_run(ctx, "SM-E05-B", "shape_permutation", "extended_shape.cpp", ORACLE_PROBE, "ok:shape_permutation\n"),
        compile_plain(ctx, "SM-E05-C", "sanitized", "sanitized_extended.cpp", SANITIZER_PROBE, "ok:sanitized\n", extra_flags=("-fsanitize=address,undefined", "-fno-omit-frame-pointer")),
    ]


if __name__ == "__main__":
    raise SystemExit(execute(CONTRACT, POLICY_ID, Path(__file__), checks))
