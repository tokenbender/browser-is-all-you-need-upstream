
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))

from strange_cpp import Context, KernelReceipt, execute
from strange_cpp_semantic import compile_and_run

from _contract import CONTRACT


POLICY_ID = "CB-E05"
PROBE = r'''#include "circular_buffer.h"
#include <iostream>
#include <stdexcept>
#include <string>
int main(int argc, char** argv) {
    if (argc != 2) return 90;
    const std::string group(argv[1]);
    if (group == "overwrite_oldest") {
        circular_buffer::circular_buffer<int> values(2);
        values.write(1); values.write(2); values.overwrite(3);
        if (values.read() != 2 || values.read() != 3) return 1;
        bool empty = false;
        try { static_cast<void>(values.read()); } catch (const std::domain_error&) { empty = true; }
        if (!empty) return 2;
    } else if (group == "full_after_overwrite") {
        circular_buffer::circular_buffer<int> values(1);
        values.write(1); values.overwrite(2);
        bool full = false;
        try { values.write(3); } catch (const std::domain_error&) { full = true; }
        if (!full || values.read() != 2) return 3;
    } else if (group == "clear_wraparound") {
        circular_buffer::circular_buffer<int> values(3);
        values.clear(); values.write(1); values.write(2);
        if (values.read() != 1) return 4;
        values.write(3);
        if (values.read() != 2 || values.read() != 3) return 5;
        values.write(4); values.clear(); values.write(5); values.write(6);
        if (values.read() != 5 || values.read() != 6) return 6;
    } else return 91;
    std::cout << "ok:" << group << '\n';
}
'''


def checks(ctx: Context) -> list[KernelReceipt]:
    return [
        compile_and_run(ctx, "CB-E05-A", "overwrite_oldest", "overwrite_oldest.cpp", PROBE, "ok:overwrite_oldest\n"),
        compile_and_run(ctx, "CB-E05-B", "full_after_overwrite", "full_after_overwrite.cpp", PROBE, "ok:full_after_overwrite\n"),
        compile_and_run(ctx, "CB-E05-C", "clear_wraparound", "clear_wraparound.cpp", PROBE, "ok:clear_wraparound\n"),
    ]


if __name__ == "__main__":
    raise SystemExit(execute(CONTRACT, POLICY_ID, Path(__file__), checks))
