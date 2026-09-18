#include "circular_buffer.h"
#define TOPIC_COVERAGE_HELPERS_ONLY
#include "coverage.hpp"
#include <deque>

// A second caller translation unit instantiates a type outside int/string.
// Values exceed 32 bits to detect narrowing storage as well as missing definitions.
void verify_wide_buffer() {
    for (unsigned capacity : {1u, 2u, 3u, 7u, 16u}) {
        circular_buffer::circular_buffer<long long> candidate(capacity);
        std::deque<long long> expected;
        coverage::Generator generator{0x57494445u + capacity};
        for (unsigned step = 0; step < 1200; ++step) {
            const long long value = (1LL << 40) + generator.pick(10000);
            const long long signed_value = step % 2 ? value : -value;
            coverage::context = "type=long long capacity=" + coverage::show(capacity)
                              + " step=" + coverage::show(step);
            const auto operation = generator.pick(4);
            if (operation == 0) {
                if (expected.size() == capacity)
                    coverage::rejects<std::domain_error>([&]() { candidate.write(signed_value); }, "full wide write rejected");
                else { candidate.write(signed_value); expected.push_back(signed_value); }
            } else if (operation == 1) {
                candidate.overwrite(signed_value);
                if (expected.size() == capacity) expected.pop_front();
                expected.push_back(signed_value);
            } else if (operation == 2) {
                if (expected.empty())
                    coverage::rejects<std::domain_error>([&]() { static_cast<void>(candidate.read()); }, "empty wide read rejected");
                else {
                    coverage::equal(candidate.read(), expected.front(), "wide FIFO preserves value");
                    expected.pop_front();
                }
            } else { candidate.clear(); expected.clear(); }
        }
        while (!expected.empty()) {
            coverage::equal(candidate.read(), expected.front(), "wide final contents"); expected.pop_front();
        }
        coverage::rejects<std::domain_error>([&]() { static_cast<void>(candidate.read()); }, "wide drain empty");
    }
}
