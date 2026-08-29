
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))

from strange_cpp import Context, KernelReceipt, execute
from strange_cpp_semantic import compile_and_run

from _contract import CONTRACT


POLICY_ID = "CB-E04"
PROBE = r'''#include "circular_buffer.h"
#include <iostream>
#include <stdexcept>
#include <string>
int main(int argc, char** argv) {
    if (argc != 2) return 90;
    const std::string group(argv[1]);
    if (group == "new_buffer") {
        circular_buffer::circular_buffer<int> values(1);
        bool empty_before = false, empty_after = false;
        try { static_cast<void>(values.read()); } catch (const std::domain_error&) { empty_before = true; }
        try { values.write(7); } catch (...) { return 1; }
        if (values.read() != 7) return 2;
        try { static_cast<void>(values.read()); } catch (const std::domain_error&) { empty_after = true; }
        if (!empty_before || !empty_after) return 3;
    } else if (group == "full_release") {
        circular_buffer::circular_buffer<int> values(2);
        values.write(1); values.write(2);
        bool full = false;
        try { values.write(3); } catch (const std::domain_error&) { full = true; }
        if (!full || values.read() != 1) return 4;
        values.write(3);
        if (values.read() != 2 || values.read() != 3) return 5;
    } else if (group == "generic_type") {
        circular_buffer::circular_buffer<std::string> values(2);
        values.write("alpha"); values.write("beta");
        if (values.read() != "alpha" || values.read() != "beta") return 6;
    } else return 91;
    std::cout << "ok:" << group << '\n';
}
'''


def checks(ctx: Context) -> list[KernelReceipt]:
    return [
        compile_and_run(ctx, "CB-E04-A", "new_buffer", "lifecycle_new_buffer.cpp", PROBE, "ok:new_buffer\n"),
        compile_and_run(ctx, "CB-E04-B", "full_release", "lifecycle_full_release.cpp", PROBE, "ok:full_release\n"),
        compile_and_run(ctx, "CB-E04-C", "generic_type", "lifecycle_generic_type.cpp", PROBE, "ok:generic_type\n"),
    ]


if __name__ == "__main__":
    raise SystemExit(execute(CONTRACT, POLICY_ID, Path(__file__), checks))
