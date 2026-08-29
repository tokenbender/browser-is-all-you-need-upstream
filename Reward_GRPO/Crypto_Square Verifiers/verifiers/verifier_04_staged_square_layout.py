
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))

from strange_cpp import Context, KernelReceipt, execute
from strange_cpp_semantic import compile_and_run

from _contract import CONTRACT


POLICY_ID = "CS-E04"
PROBE = r'''#include "crypto_square.h"
#include <iostream>
#include <string>
#include <vector>
int main(int argc, char** argv) {
    if (argc != 2) return 90;
    const std::string group(argv[1]);
    if (group == "normalization") {
        if (crypto_square::cipher("").normalize_plain_text() != "") return 1;
        if (crypto_square::cipher("... --- ...").normalize_plain_text() != "") return 2;
        if (crypto_square::cipher(" A1, b2! ").normalize_plain_text() != "a1b2") return 3;
    } else if (group == "dimensions_segments") {
        const crypto_square::cipher perfect("This is fun!");
        if (perfect.size() != 3 || perfect.plain_text_segments() != std::vector<std::string>{"thi","sis","fun"}) return 4;
        const crypto_square::cipher incomplete("Chill out.");
        if (incomplete.size() != 3 || incomplete.plain_text_segments() != std::vector<std::string>{"chi","llo","ut"}) return 5;
    } else if (group == "exact_layout") {
        const crypto_square::cipher perfect("This is fun!");
        if (perfect.cipher_text() != "tsfhiuisn" || perfect.normalized_cipher_text() != "tsf hiu isn") return 6;
        const crypto_square::cipher incomplete("Chill out.");
        if (incomplete.cipher_text() != "cluhltio" || incomplete.normalized_cipher_text() != "clu hlt io ") return 7;
    } else return 91;
    std::cout << "ok:" << group << '\n';
}
'''


def checks(ctx: Context) -> list[KernelReceipt]:
    return [
        compile_and_run(ctx, "CS-E04-A", "normalization", "staged_normalization.cpp", PROBE, "ok:normalization\n"),
        compile_and_run(ctx, "CS-E04-B", "dimensions_segments", "staged_dimensions_segments.cpp", PROBE, "ok:dimensions_segments\n"),
        compile_and_run(ctx, "CS-E04-C", "exact_layout", "staged_exact_layout.cpp", PROBE, "ok:exact_layout\n"),
    ]


if __name__ == "__main__":
    raise SystemExit(execute(CONTRACT, POLICY_ID, Path(__file__), checks))
