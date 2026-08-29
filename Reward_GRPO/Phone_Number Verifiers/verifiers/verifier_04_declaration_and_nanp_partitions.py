
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))

from strange_cpp import Context, KernelReceipt, execute
from strange_cpp_semantic import compile_and_run

from _contract import CONTRACT


POLICY_ID = "PH-E04"
PROBE = r'''#include "phone_number.h"
#include <iostream>
#include <stdexcept>
#include <string>
bool rejects(const std::string& text) {
    try { const phone_number::phone_number value(text); static_cast<void>(value); }
    catch (const std::domain_error&) { return true; }
    return false;
}
int main(int argc, char** argv) {
    if (argc != 2) return 90;
    const std::string group(argv[1]);
    if (group == "declaration_surface") {
        const phone_number::phone_number value("2234567890");
        if (value.number() != "2234567890" || value.area_code() != "223") return 1;
        if (static_cast<std::string>(value) != "(223) 456-7890") return 2;
    } else if (group == "valid_inputs") {
        const phone_number::phone_number a("223.456.7890");
        const phone_number::phone_number b("+1 (223) 456-7890");
        const phone_number::phone_number c("223 456   7890");
        if (a.number() != "2234567890" || b.number() != a.number() || c.number() != a.number()) return 3;
    } else if (group == "invalid_partitions") {
        const std::string bad[]{"123456789","22234567890","321234567890","123-abc-7890","123-@:!-7890","0234567890","1234567890","2230567890","2231567890","10234567890","12230567890"};
        for (const auto& value : bad) if (!rejects(value)) return 4;
    } else return 91;
    std::cout << "ok:" << group << '\n';
}
'''


def checks(ctx: Context) -> list[KernelReceipt]:
    return [
        compile_and_run(ctx, "PH-E04-A", "declaration_surface", "declaration_surface.cpp", PROBE, "ok:declaration_surface\n"),
        compile_and_run(ctx, "PH-E04-B", "valid_inputs", "nanp_valid_inputs.cpp", PROBE, "ok:valid_inputs\n"),
        compile_and_run(ctx, "PH-E04-C", "invalid_partitions", "nanp_invalid_partitions.cpp", PROBE, "ok:invalid_partitions\n"),
    ]


if __name__ == "__main__":
    raise SystemExit(execute(CONTRACT, POLICY_ID, Path(__file__), checks))
