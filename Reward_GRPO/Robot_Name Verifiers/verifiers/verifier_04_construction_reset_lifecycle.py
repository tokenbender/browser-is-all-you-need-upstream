
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))

from strange_cpp import Context, KernelReceipt, execute
from strange_cpp_semantic import compile_and_run

from _contract import CONTRACT


POLICY_ID = "RN-E04"
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
int main(int argc, char** argv) {
    if (argc != 2) return 90;
    const std::string group(argv[1]);
    if (group == "construction") {
        const robot_name::robot value;
        if (!valid(value.name())) return 1;
    } else if (group == "stable_observer") {
        const robot_name::robot value; const std::string original = value.name();
        for (int i = 0; i < 100; ++i) if (value.name() != original) return 2;
    } else if (group == "reset_lifecycle") {
        robot_name::robot value; std::set<std::string> names{value.name()};
        for (int i = 0; i < 100; ++i) {
            value.reset();
            if (!valid(value.name()) || !names.insert(value.name()).second) return 3;
        }
    } else return 91;
    std::cout << "ok:" << group << '\n';
}
'''


def checks(ctx: Context) -> list[KernelReceipt]:
    return [
        compile_and_run(ctx, "RN-E04-A", "construction", "lifecycle_construction.cpp", PROBE, "ok:construction\n"),
        compile_and_run(ctx, "RN-E04-B", "stable_observer", "lifecycle_stable_observer.cpp", PROBE, "ok:stable_observer\n"),
        compile_and_run(ctx, "RN-E04-C", "reset_lifecycle", "lifecycle_reset.cpp", PROBE, "ok:reset_lifecycle\n"),
    ]


if __name__ == "__main__":
    raise SystemExit(execute(CONTRACT, POLICY_ID, Path(__file__), checks))
