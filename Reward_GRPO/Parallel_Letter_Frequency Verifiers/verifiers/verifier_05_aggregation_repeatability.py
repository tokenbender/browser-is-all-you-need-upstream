
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))

from strange_cpp import Context, KernelReceipt, execute
from strange_cpp_semantic import compile_and_run

from _contract import CONTRACT


POLICY_ID = "PL-E05"
PROBE = r'''#include "parallel_letter_frequency.h"
#include <iostream>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>
int main(int argc, char** argv) {
    if (argc != 2) return 90;
    const std::string group(argv[1]);
    if (group == "uneven_partitions") {
        const std::vector<std::string_view> input{"", "abca", "B", "cccccc", "z z z"};
        const std::unordered_map<char, std::size_t> expected{{'a',2},{'b',2},{'c',7},{'z',3}};
        if (parallel_letter_frequency::frequency(input) != expected) return 1;
    } else if (group == "large_oracle") {
        const std::string a(4096, 'a'), b(2048, 'B'), c(1024, 'c');
        std::vector<std::string_view> input;
        for (int i = 0; i < 64; ++i) { input.push_back(a); input.push_back(b); input.push_back(c); }
        const std::unordered_map<char, std::size_t> expected{{'a',262144},{'b',131072},{'c',65536}};
        if (parallel_letter_frequency::frequency(input) != expected) return 2;
    } else if (group == "repeatability") {
        const std::vector<std::string_view> input{"The quick brown fox", "JUMPS over 13 lazy dogs!", "abc ABC"};
        const auto expected = parallel_letter_frequency::frequency(input);
        for (int i = 0; i < 25; ++i) if (parallel_letter_frequency::frequency(input) != expected) return 3;
    } else return 91;
    std::cout << "ok:" << group << '\n';
}
'''


def checks(ctx: Context) -> list[KernelReceipt]:
    return [
        compile_and_run(ctx, "PL-E05-A", "uneven_partitions", "aggregate_uneven.cpp", PROBE, "ok:uneven_partitions\n"),
        compile_and_run(ctx, "PL-E05-B", "large_oracle", "aggregate_large_oracle.cpp", PROBE, "ok:large_oracle\n"),
        compile_and_run(ctx, "PL-E05-C", "repeatability", "aggregate_repeatability.cpp", PROBE, "ok:repeatability\n"),
    ]


if __name__ == "__main__":
    raise SystemExit(execute(CONTRACT, POLICY_ID, Path(__file__), checks))
