
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))

from strange_cpp import Context, KernelReceipt, execute
from strange_cpp_semantic import compile_and_run

from _contract import CONTRACT


POLICY_ID = "SM-E04"
PROBE = r'''#include "spiral_matrix.h"
#include <cstdint>
#include <iostream>
#include <string>
#include <vector>
using Matrix = std::vector<std::vector<std::uint32_t>>;
int main(int argc, char** argv) {
    if (argc != 2) return 90;
    const std::string group(argv[1]);
    if (group == "zero_one") {
        if (spiral_matrix::spiral_matrix(0) != Matrix{}) return 1;
        if (spiral_matrix::spiral_matrix(1) != Matrix{{1}}) return 2;
    } else if (group == "size_two") {
        if (spiral_matrix::spiral_matrix(2) != Matrix{{1,2},{4,3}}) return 3;
    } else if (group == "sizes_three_to_five") {
        const Matrix three{{1,2,3},{8,9,4},{7,6,5}};
        const Matrix four{{1,2,3,4},{12,13,14,5},{11,16,15,6},{10,9,8,7}};
        const Matrix five{{1,2,3,4,5},{16,17,18,19,6},{15,24,25,20,7},{14,23,22,21,8},{13,12,11,10,9}};
        if (spiral_matrix::spiral_matrix(3) != three || spiral_matrix::spiral_matrix(4) != four || spiral_matrix::spiral_matrix(5) != five) return 4;
    } else return 91;
    std::cout << "ok:" << group << '\n';
}
'''


def checks(ctx: Context) -> list[KernelReceipt]:
    return [
        compile_and_run(ctx, "SM-E04-A", "zero_one", "minimal_zero_one.cpp", PROBE, "ok:zero_one\n"),
        compile_and_run(ctx, "SM-E04-B", "size_two", "minimal_size_two.cpp", PROBE, "ok:size_two\n"),
        compile_and_run(ctx, "SM-E04-C", "sizes_three_to_five", "minimal_three_to_five.cpp", PROBE, "ok:sizes_three_to_five\n"),
    ]


if __name__ == "__main__":
    raise SystemExit(execute(CONTRACT, POLICY_ID, Path(__file__), checks))
