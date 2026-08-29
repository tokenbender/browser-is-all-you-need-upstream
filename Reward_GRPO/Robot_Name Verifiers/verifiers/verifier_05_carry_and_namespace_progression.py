
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))

from strange_cpp import Context, KernelReceipt, execute
from strange_cpp_semantic import compile_and_run

from _contract import CONTRACT


POLICY_ID = "RN-E05"
PROBE = r'''#include "robot_name.h"
#include <cctype>
#include <iostream>
#include <set>
#include <string>
bool valid(const std::string& name) {
    return name.size() == 5 && std::isupper(static_cast<unsigned char>(name[0])) &&
        std::isupper(static_cast<unsigned char>(name[1])) && std::isdigit(static_cast<unsigned char>(name[2])) &&
        std::isdigit(static_cast<unsigned char>(name[3])) && std::isdigit(static_cast<unsigned char>(name[4]));
}
bool add(std::set<std::string>& names, const std::string& value) { return valid(value) && names.insert(value).second; }
int main(int argc, char** argv) {
    if (argc != 2) return 90;
    const std::string group(argv[1]);
    std::set<std::string> names;
    if (group == "constructor_carry") {
        for (int i = 0; i < 1100; ++i) { const robot_name::robot value; if (!add(names, value.name())) return 1; }
    } else if (group == "reset_carry") {
        robot_name::robot value;
        if (!add(names, value.name())) return 2;
        for (int i = 0; i < 1100; ++i) { value.reset(); if (!add(names, value.name())) return 3; }
    } else if (group == "mixed_progression") {
        for (int i = 0; i < 5000; ++i) {
            robot_name::robot value;
            if (!add(names, value.name())) return 4;
            if (i % 2 == 0) { value.reset(); if (!add(names, value.name())) return 5; }
        }
    } else return 91;
    std::cout << "ok:" << group << '\n';
}
'''


def checks(ctx: Context) -> list[KernelReceipt]:
    return [
        compile_and_run(ctx, "RN-E05-A", "constructor_carry", "carry_constructors.cpp", PROBE, "ok:constructor_carry\n"),
        compile_and_run(ctx, "RN-E05-B", "reset_carry", "carry_resets.cpp", PROBE, "ok:reset_carry\n"),
        compile_and_run(ctx, "RN-E05-C", "mixed_progression", "carry_mixed.cpp", PROBE, "ok:mixed_progression\n"),
    ]


if __name__ == "__main__":
    raise SystemExit(execute(CONTRACT, POLICY_ID, Path(__file__), checks))
