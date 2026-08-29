
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))

from strange_cpp import Context, KernelReceipt, execute
from strange_cpp_semantic import compile_and_run

from _contract import CONTRACT


POLICY_ID = "CL-E05"
PROBE = r'''#include "clock.h"
#include <iostream>
#include <string>
#include <type_traits>
using Clock = date_independent::clock;
static_assert(std::is_same_v<decltype(&Clock::at), Clock (*)(int, int)>);
static_assert(std::is_same_v<decltype(&Clock::plus), Clock& (Clock::*)(int)>);
static_assert(std::is_same_v<decltype(&Clock::minus), Clock& (Clock::*)(int)>);
static_assert(std::is_same_v<decltype(&Clock::operator==), bool (Clock::*)(const Clock&) const>);
int main(int argc, char** argv) {
    if (argc != 2) return 90;
    const std::string group(argv[1]);
    if (group == "api_shape") {
        auto value = Clock::at(1, 2); value.plus(1).minus(1);
        if (!(value == Clock::at(1, 2))) return 1;
    } else if (group == "const_observer") {
        const auto value = Clock::at(8, 3);
        const std::string first = static_cast<std::string>(value);
        const std::string second = static_cast<std::string>(value);
        if (first != "08:03" || second != first) return 2;
    } else if (group == "independent_factory") {
        auto first = Clock::at(1, 0); auto second = Clock::at(2, 0);
        first.plus(60);
        if (!(first == second) || static_cast<std::string>(second) != "02:00") return 3;
    } else return 91;
    std::cout << "ok:" << group << '\n';
}
'''


def checks(ctx: Context) -> list[KernelReceipt]:
    return [
        compile_and_run(ctx, "CL-E05-A", "api_shape", "factory_api_shape.cpp", PROBE, "ok:api_shape\n"),
        compile_and_run(ctx, "CL-E05-B", "const_observer", "factory_const_observer.cpp", PROBE, "ok:const_observer\n"),
        compile_and_run(ctx, "CL-E05-C", "independent_factory", "factory_independent.cpp", PROBE, "ok:independent_factory\n"),
    ]


if __name__ == "__main__":
    raise SystemExit(execute(CONTRACT, POLICY_ID, Path(__file__), checks))
