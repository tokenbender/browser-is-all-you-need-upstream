
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


POLICY_ID = "PL-E02"
SEMANTIC_PROBE = '#include "parallel_letter_frequency.h"\n#include <iostream>\n#include <string>\n#include <string_view>\n#include <unordered_map>\n#include <vector>\nint main(int argc, char** argv) {\n    if (argc != 2) return 90;\n    const std::string group(argv[1]);\n    if (group == "filter_and_case") {\n        const std::vector<std::string_view> texts{"aA B-b! 123 _C"};\n        const std::unordered_map<char, std::size_t> expected{{\'a\',2},{\'b\',2},{\'c\',1}};\n        if (parallel_letter_frequency::frequency(texts) != expected) return 1;\n    } else if (group == "aggregation") {\n        const std::vector<std::string_view> texts{"abc", "", "Cab", "z z"};\n        const std::unordered_map<char, std::size_t> expected{{\'a\',2},{\'b\',2},{\'c\',2},{\'z\',2}};\n        if (parallel_letter_frequency::frequency(texts) != expected) return 2;\n    } else if (group == "large_deterministic") {\n        const std::string block(20000, \'x\');\n        std::vector<std::string_view> texts(64, block);\n        const auto first = parallel_letter_frequency::frequency(texts);\n        const auto second = parallel_letter_frequency::frequency(texts);\n        if (first != second || first.size() != 1 || first.at(\'x\') != 1280000) return 3;\n    } else {\n        return 91;\n    }\n    std::cout << "ok:" << group << \'\\n\';\n    return 0;\n}\n'


def checks(ctx: Context) -> list[KernelReceipt]:
    return [
        compile_and_run(ctx, "PL-E02-A", "filter_and_case", "semantic_filter_and_case.cpp", SEMANTIC_PROBE, "ok:filter_and_case\n"),
        compile_and_run(ctx, "PL-E02-B", "aggregation", "semantic_aggregation.cpp", SEMANTIC_PROBE, "ok:aggregation\n"),
        compile_and_run(ctx, "PL-E02-C", "large_deterministic", "semantic_large_deterministic.cpp", SEMANTIC_PROBE, "ok:large_deterministic\n"),
    ]


if __name__ == "__main__":
    raise SystemExit(execute(CONTRACT, POLICY_ID, Path(__file__), checks))
