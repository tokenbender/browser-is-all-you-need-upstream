#include "arithmetic.h"

#include <utility>

std::pair<int, int> run_tests() {
    int passed = 0;
    constexpr int total = 4;
    passed += demo::add(2, 3) == 5;
    passed += demo::add(-2, 2) == 0;
    passed += demo::multiply(2, 3) == 6;
    passed += demo::multiply(-2, 3) == -6;
    return {passed, total};
}

