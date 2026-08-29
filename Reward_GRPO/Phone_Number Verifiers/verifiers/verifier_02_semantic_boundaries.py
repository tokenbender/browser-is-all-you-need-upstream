
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))

from strange_cpp import Context
from strange_cpp import KernelReceipt
from strange_cpp_semantic import compile_and_run
from strange_cpp import compile_only
from strange_cpp import execute
from strange_cpp import official_checks

from _contract import CONTRACT


POLICY_ID = "PH-E02"
SEMANTIC_PROBE = '#include "phone_number.h"\n#include <iostream>\n#include <stdexcept>\n#include <string>\nbool rejects(const std::string& text) {\n    try { const phone_number::phone_number value(text); static_cast<void>(value); }\n    catch (const std::domain_error&) { return true; }\n    return false;\n}\nint main(int argc, char** argv) {\n    if (argc != 2) return 90;\n    const std::string group(argv[1]);\n    if (group == "clean_and_format") {\n        const phone_number::phone_number a("+1 (223) 456-7890");\n        const phone_number::phone_number b("223.456.7890");\n        if (a.number() != "2234567890" || b.area_code() != "223") return 1;\n        if (static_cast<std::string>(a) != "(223) 456-7890") return 2;\n    } else if (group == "length_and_characters") {\n        if (!rejects("123456789") || !rejects("22234567890")) return 3;\n        if (!rejects("223-abc-7890") || !rejects("223-@:!-7890")) return 4;\n    } else if (group == "nanp_prefixes") {\n        if (!rejects("0234567890") || !rejects("1234567890")) return 5;\n        if (!rejects("2230567890") || !rejects("2231567890")) return 6;\n        if (!rejects("10234567890") || !rejects("12230567890")) return 7;\n    } else {\n        return 91;\n    }\n    std::cout << "ok:" << group << \'\\n\';\n    return 0;\n}\n'


def checks(ctx: Context) -> list[KernelReceipt]:
    return [
        compile_and_run(ctx, "PH-E02-A", "clean_and_format", "semantic_clean_and_format.cpp", SEMANTIC_PROBE, "ok:clean_and_format\n"),
        compile_and_run(ctx, "PH-E02-B", "length_and_characters", "semantic_length_and_characters.cpp", SEMANTIC_PROBE, "ok:length_and_characters\n"),
        compile_and_run(ctx, "PH-E02-C", "nanp_prefixes", "semantic_nanp_prefixes.cpp", SEMANTIC_PROBE, "ok:nanp_prefixes\n"),
    ]


if __name__ == "__main__":
    raise SystemExit(execute(CONTRACT, POLICY_ID, Path(__file__), checks))
