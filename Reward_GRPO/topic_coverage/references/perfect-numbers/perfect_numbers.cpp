#include "perfect_numbers.h"
#include <cstdint>
namespace perfect_numbers {
classification classify(int n) {
    if (n <= 0) throw std::domain_error("Input must be positive");
    std::int64_t sum = n == 1 ? 0 : 1;
    for (int divisor = 2; divisor <= n / divisor; ++divisor) {
        if (n % divisor != 0) continue;
        sum += divisor;
        if (divisor != n / divisor) sum += n / divisor;
    }
    if (sum < n) return classification::deficient;
    if (sum > n) return classification::abundant;
    return classification::perfect;
}
}
