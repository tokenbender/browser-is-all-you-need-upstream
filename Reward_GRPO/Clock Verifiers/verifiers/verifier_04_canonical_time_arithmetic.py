
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))

from strange_cpp import Context, KernelReceipt, execute
from strange_cpp_semantic import compile_and_run

from _contract import CONTRACT


POLICY_ID = "CL-E04"
PROBE = r'''#include "clock.h"
#include <iostream>
#include <string>
using Clock = date_independent::clock;
bool text(const Clock& value, const std::string& expected) { return static_cast<std::string>(value) == expected; }
int main(int argc, char** argv) {
    if (argc != 2) return 90;
    const std::string group(argv[1]);
    if (group == "whole_days") {
        const auto zero = Clock::at(0, 0);
        if (!text(Clock::at(24, 0), "00:00") || !text(Clock::at(-24, 0), "00:00")) return 1;
        if (!(zero == Clock::at(48, 0)) || !(Clock::at(-48, 0) == zero)) return 2;
    } else if (group == "negative_inputs") {
        if (!text(Clock::at(0, -1), "23:59")) return 3;
        if (!text(Clock::at(-25, -160), "20:20")) return 4;
        if (!text(Clock::at(100, -3000), "02:00")) return 5;
    } else if (group == "large_arithmetic") {
        auto a = Clock::at(23, 59); a.plus(2 + 5 * 1440);
        auto b = Clock::at(0, 1); b.minus(2 + 7 * 1440);
        auto c = Clock::at(12, 34); c.plus(100000).minus(100000);
        if (!text(a, "00:01") || !text(b, "23:59") || !text(c, "12:34")) return 6;
    } else return 91;
    std::cout << "ok:" << group << '\n';
}
'''


def checks(ctx: Context) -> list[KernelReceipt]:
    return [
        compile_and_run(ctx, "CL-E04-A", "whole_days", "canonical_whole_days.cpp", PROBE, "ok:whole_days\n"),
        compile_and_run(ctx, "CL-E04-B", "negative_inputs", "canonical_negative_inputs.cpp", PROBE, "ok:negative_inputs\n"),
        compile_and_run(ctx, "CL-E04-C", "large_arithmetic", "canonical_large_arithmetic.cpp", PROBE, "ok:large_arithmetic\n"),
    ]


if __name__ == "__main__":
    raise SystemExit(execute(CONTRACT, POLICY_ID, Path(__file__), checks))
