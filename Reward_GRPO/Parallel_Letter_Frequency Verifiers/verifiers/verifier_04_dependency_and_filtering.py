
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))

from strange_cpp import Context, KernelReceipt, execute
from strange_cpp_semantic import compile_and_run

from _contract import CONTRACT


POLICY_ID = "PL-E04"
PROBE = r'''#include "parallel_letter_frequency.h"
#include <iostream>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>
int main(int argc, char** argv) {
    if (argc != 2) return 90;
    const std::string group(argv[1]);
    if (group == "dependency_surface") {
        const std::vector<std::string_view> empty;
        if (!parallel_letter_frequency::frequency(empty).empty()) return 1;
    } else if (group == "nonletters") {
        const std::vector<std::string_view> input{"0123456789", " !@#$%^&*() ", "\t\n_-+=,.?"};
        if (!parallel_letter_frequency::frequency(input).empty()) return 2;
    } else if (group == "case_folding") {
        const std::vector<std::string_view> input{"AaZ", "aAz", "Z"};
        const std::unordered_map<char, std::size_t> expected{{'a',4},{'z',3}};
        if (parallel_letter_frequency::frequency(input) != expected) return 3;
    } else return 91;
    std::cout << "ok:" << group << '\n';
}
'''


def checks(ctx: Context) -> list[KernelReceipt]:
    return [
        compile_and_run(ctx, "PL-E04-A", "dependency_surface", "dependency_surface.cpp", PROBE, "ok:dependency_surface\n"),
        compile_and_run(ctx, "PL-E04-B", "nonletters", "filter_nonletters.cpp", PROBE, "ok:nonletters\n"),
        compile_and_run(ctx, "PL-E04-C", "case_folding", "filter_case_folding.cpp", PROBE, "ok:case_folding\n"),
    ]


if __name__ == "__main__":
    raise SystemExit(execute(CONTRACT, POLICY_ID, Path(__file__), checks))
