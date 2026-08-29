
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))

from strange_cpp import Context
from strange_cpp import KernelReceipt
from strange_cpp import compile_and_run
from strange_cpp import compile_only
from strange_cpp import execute
from strange_cpp import official_checks

from _contract import CONTRACT


POLICY_ID = "CS-E01"
NAMES_PROBE = '#include "crypto_square.h"\nint main() {\n    crypto_square::cipher value("abc");\n    return value.normalize_plain_text() == "abc" ? 0 : 1;\n}\n'
SIGNATURE_PROBE = '#include "crypto_square.h"\n#include <string>\n#include <type_traits>\n#include <utility>\n#include <vector>\nusing C = crypto_square::cipher;\nstatic_assert(std::is_constructible_v<C, const std::string&>);\nstatic_assert(std::is_same_v<decltype(std::declval<const C&>().normalize_plain_text()), std::string>);\nstatic_assert(std::is_same_v<decltype(std::declval<const C&>().size()), std::size_t>);\nstatic_assert(std::is_same_v<decltype(std::declval<const C&>().plain_text_segments()), std::vector<std::string>>);\nstatic_assert(std::is_same_v<decltype(std::declval<const C&>().cipher_text()), std::string>);\nstatic_assert(std::is_same_v<decltype(std::declval<const C&>().normalized_cipher_text()), std::string>);\nint main() { return 0; }\n'
LINK_PROBE = '#include "crypto_square.h"\n#include <iostream>\nint main() {\n    const crypto_square::cipher value("A b!");\n    std::cout << value.normalize_plain_text() << \'\\n\';\n    return 0;\n}\n'


def checks(ctx: Context) -> list[KernelReceipt]:
    return [
        compile_only(ctx, "CS-E01-A", "public_names", "api_names.cpp", NAMES_PROBE),
        compile_only(ctx, "CS-E01-B", "exact_signatures", "api_signatures.cpp", SIGNATURE_PROBE),
        compile_and_run(ctx, "CS-E01-C", "implementation_link", "api_link.cpp", LINK_PROBE, 'ab\n'),
    ]


if __name__ == "__main__":
    raise SystemExit(execute(CONTRACT, POLICY_ID, Path(__file__), checks))
