
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


POLICY_ID = "SM-E02"
SEMANTIC_PROBE = '#include "spiral_matrix.h"\n#include <algorithm>\n#include <cstdint>\n#include <iostream>\n#include <string>\n#include <vector>\nusing Matrix = std::vector<std::vector<std::uint32_t>>;\nMatrix oracle(std::uint32_t n) {\n    Matrix out(n, std::vector<std::uint32_t>(n));\n    if (n == 0) return out;\n    int top = 0, left = 0, bottom = static_cast<int>(n) - 1, right = static_cast<int>(n) - 1;\n    std::uint32_t value = 1;\n    while (top <= bottom && left <= right) {\n        for (int col = left; col <= right; ++col) out[static_cast<std::size_t>(top)][static_cast<std::size_t>(col)] = value++;\n        ++top;\n        for (int row = top; row <= bottom; ++row) out[static_cast<std::size_t>(row)][static_cast<std::size_t>(right)] = value++;\n        --right;\n        if (top <= bottom) {\n            for (int col = right; col >= left; --col) out[static_cast<std::size_t>(bottom)][static_cast<std::size_t>(col)] = value++;\n            --bottom;\n        }\n        if (left <= right) {\n            for (int row = bottom; row >= top; --row) out[static_cast<std::size_t>(row)][static_cast<std::size_t>(left)] = value++;\n            ++left;\n        }\n    }\n    return out;\n}\nint main(int argc, char** argv) {\n    if (argc != 2) return 90;\n    const std::string group(argv[1]);\n    if (group == "small_exact") {\n        if (spiral_matrix::spiral_matrix(0) != Matrix{}) return 1;\n        if (spiral_matrix::spiral_matrix(1) != Matrix{{1}}) return 2;\n        if (spiral_matrix::spiral_matrix(2) != Matrix{{1,2},{4,3}}) return 3;\n        if (spiral_matrix::spiral_matrix(3) != Matrix{{1,2,3},{8,9,4},{7,6,5}}) return 4;\n    } else if (group == "shape_permutation") {\n        for (std::uint32_t n = 1; n <= 25; ++n) {\n            const auto matrix = spiral_matrix::spiral_matrix(n);\n            if (matrix.size() != n) return 5;\n            std::vector<std::uint32_t> values;\n            for (const auto& row : matrix) {\n                if (row.size() != n) return 6;\n                values.insert(values.end(), row.begin(), row.end());\n            }\n            std::sort(values.begin(), values.end());\n            for (std::uint32_t i = 0; i < n * n; ++i) if (values[i] != i + 1) return 7;\n        }\n    } else if (group == "oracle_extended") {\n        for (std::uint32_t n = 4; n <= 20; ++n) {\n            if (spiral_matrix::spiral_matrix(n) != oracle(n)) return 8;\n        }\n    } else {\n        return 91;\n    }\n    std::cout << "ok:" << group << \'\\n\';\n    return 0;\n}\n'


def checks(ctx: Context) -> list[KernelReceipt]:
    return [
        compile_and_run(ctx, "SM-E02-A", "small_exact", "semantic_small_exact.cpp", SEMANTIC_PROBE, "ok:small_exact\n"),
        compile_and_run(ctx, "SM-E02-B", "shape_permutation", "semantic_shape_permutation.cpp", SEMANTIC_PROBE, "ok:shape_permutation\n"),
        compile_and_run(ctx, "SM-E02-C", "oracle_extended", "semantic_oracle_extended.cpp", SEMANTIC_PROBE, "ok:oracle_extended\n"),
    ]


if __name__ == "__main__":
    raise SystemExit(execute(CONTRACT, POLICY_ID, Path(__file__), checks))
