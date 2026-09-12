#include "perfect_numbers.h"
#include "coverage.hpp"
#include <climits>

namespace {
using Classification = perfect_numbers::classification;
// Independent oracle: product of prime-power divisor sums, not divisor pairs.
std::int64_t aliquot(int n) {
    std::int64_t remaining = n, sigma = 1;
    for (std::int64_t prime = 2; prime <= remaining / prime; ++prime) {
        if (remaining % prime) continue;
        std::int64_t power = 1, term = 1;
        do { remaining /= prime; power *= prime; term += power; }
        while (remaining % prime == 0);
        sigma *= term;
    }
    if (remaining > 1) sigma *= remaining + 1;
    return sigma - n;
}
std::string name(Classification value) {
    if (value == Classification::deficient) return "deficient";
    if (value == Classification::perfect) return "perfect";
    if (value == Classification::abundant) return "abundant";
    return "invalid classification " + coverage::show(value);
}
void inspect(int n) {
    const auto sum = aliquot(n);
    const std::string expected = sum < n ? "deficient" : sum > n ? "abundant" : "perfect";
    coverage::context = "n=" + coverage::show(n) + " proper_divisor_sum=" + coverage::show(sum);
    coverage::equal(name(perfect_numbers::classify(n)), expected, "proper divisor classification");
}
}
void run_topic(const std::string& group) {
    if (group == "domain_errors") {
        for (int n : {0, -1, -17, INT_MIN}) {
            coverage::context = "n=" + coverage::show(n);
            coverage::rejects<std::domain_error>([&]() { perfect_numbers::classify(n); },
                                                 "nonpositive input throws std::domain_error");
        }
    } else if (group == "unit_and_primes") {
        for (int n : {1, 2, 3, 5, 97, 997, 65537, 2147483647}) inspect(n);
    } else if (group == "known_perfect") {
        for (int n : {6, 28, 496, 8128, 33550336}) inspect(n);
    } else if (group == "bounded_domain") {
        for (int n = 1; n <= 4096; ++n) inspect(n);
    } else if (group == "square_boundaries") {
        // 196 is abundant only when the square-root divisor 14 is included.
        for (int root : {2, 3, 5, 7, 14, 25, 64, 127, 1024, 46340}) {
            const int square = root * root;
            inspect(square - 1); inspect(square); inspect(square + 1);
        }
    } else if (group == "wide_values") {
        for (int n : {2000000000, 2147483646, INT_MAX, 1073741824, 1900000000}) inspect(n);
        coverage::Generator generator{0x50455246u};
        for (int i = 0; i < 256; ++i)
            inspect(1 + static_cast<int>(generator.next() % static_cast<unsigned>(INT_MAX)));
    } else throw std::invalid_argument("unknown coverage group");
}
