#include <iostream>
#include <utility>

std::pair<int, int> run_tests();

int main() {
    const auto [passed, total] = run_tests();
    if (passed == total) {
        std::cout << "All tests passed (" << total
                  << " assertions in 1 test case)\n";
        return 0;
    }
    std::cout << "----------------------------------------\n"
              << "arithmetic semantics\n"
              << "----------------------------------------\n"
              << "assertions: " << total << " | " << passed
              << " passed | " << total - passed << " failed\n";
    return 1;
}
