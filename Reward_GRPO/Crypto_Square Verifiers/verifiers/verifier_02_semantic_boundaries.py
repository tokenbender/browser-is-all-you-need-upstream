
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


POLICY_ID = "CS-E02"
SEMANTIC_PROBE = '#include "crypto_square.h"\n#include <iostream>\n#include <string>\n#include <vector>\nint main(int argc, char** argv) {\n    if (argc != 2) return 90;\n    const std::string group(argv[1]);\n    if (group == "normalization_size") {\n        const crypto_square::cipher value("A man, a plan, a canal: Panama!");\n        if (value.normalize_plain_text() != "amanaplanacanalpanama") return 1;\n        if (crypto_square::cipher("").size() != 0) return 2;\n        if (crypto_square::cipher("ab").size() != 2) return 3;\n        if (crypto_square::cipher("123456789").size() != 3) return 4;\n        if (crypto_square::cipher("1234567890").size() != 4) return 5;\n    } else if (group == "segments") {\n        const crypto_square::cipher value("Chill out.");\n        const std::vector<std::string> expected{"chi", "llo", "ut"};\n        if (value.plain_text_segments() != expected) return 6;\n    } else if (group == "cipher_layout") {\n        const crypto_square::cipher value("Chill out.");\n        if (value.cipher_text() != "cluhltio") return 7;\n        if (value.normalized_cipher_text() != "clu hlt io ") return 8;\n        if (!crypto_square::cipher("").cipher_text().empty()) return 9;\n    } else {\n        return 91;\n    }\n    std::cout << "ok:" << group << \'\\n\';\n    return 0;\n}\n'


def checks(ctx: Context) -> list[KernelReceipt]:
    return [
        compile_and_run(ctx, "CS-E02-A", "normalization_size", "semantic_normalization_size.cpp", SEMANTIC_PROBE, "ok:normalization_size\n"),
        compile_and_run(ctx, "CS-E02-B", "segments", "semantic_segments.cpp", SEMANTIC_PROBE, "ok:segments\n"),
        compile_and_run(ctx, "CS-E02-C", "cipher_layout", "semantic_cipher_layout.cpp", SEMANTIC_PROBE, "ok:cipher_layout\n"),
    ]


if __name__ == "__main__":
    raise SystemExit(execute(CONTRACT, POLICY_ID, Path(__file__), checks))
