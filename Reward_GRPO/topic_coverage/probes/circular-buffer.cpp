#include "circular_buffer.h"
#include "coverage.hpp"
#include <deque>

void verify_wide_buffer();

namespace {
template <typename T> T item(unsigned value) {
    if constexpr (std::is_same_v<T, std::string>) return "value_" + coverage::show(value);
    else return static_cast<T>(value);
}
template <typename T> void sequence(unsigned capacity, std::uint32_t seed) {
    circular_buffer::circular_buffer<T> candidate(capacity);
    std::deque<T> expected;
    coverage::Generator generator{seed};
    coverage::trace.clear();
    for (unsigned step = 0; step < 1200; ++step) {
        coverage::context = "capacity=" + coverage::show(capacity) + " seed=" + coverage::show(seed)
                          + " step=" + coverage::show(step);
        const unsigned op = generator.pick(5);
        const auto value = item<T>(generator.pick(10000));
        if (op == 0 || op == 4) {
            coverage::record("write(" + coverage::show(value) + ")");
            if (expected.size() == capacity)
                coverage::rejects<std::domain_error>([&]() { candidate.write(value); }, "full write rejected");
            else { candidate.write(value); expected.push_back(value); }
        } else if (op == 1) {
            coverage::record("read()");
            if (expected.empty())
                coverage::rejects<std::domain_error>([&]() { static_cast<void>(candidate.read()); }, "empty read rejected");
            else {
                coverage::equal(candidate.read(), expected.front(), "oldest value read");
                expected.pop_front();
            }
        } else if (op == 2) {
            coverage::record("overwrite(" + coverage::show(value) + ")");
            candidate.overwrite(value);
            if (expected.size() == capacity) expected.pop_front();
            expected.push_back(value);
        } else { coverage::record("clear()"); candidate.clear(); expected.clear(); }
    }
    while (!expected.empty()) {
        coverage::record("final read()");
        coverage::equal(candidate.read(), expected.front(), "final contents agree"); expected.pop_front();
    }
    coverage::rejects<std::domain_error>([&]() { static_cast<void>(candidate.read()); }, "drained buffer empty");
}
}
void run_topic(const std::string& group) {
    if (group == "int_sequences") {
        for (unsigned capacity : {1u, 2u, 3u, 7u, 16u}) sequence<int>(capacity, 0x4342494eu + capacity);
    } else if (group == "string_sequences") {
        for (unsigned capacity : {1u, 2u, 3u, 7u, 16u}) sequence<std::string>(capacity, 0x43425354u + capacity);
    } else if (group == "wide_type") {
        verify_wide_buffer();
    } else if (group == "capacity_boundaries") {
        for (unsigned capacity : {1u, 2u, 3u, 7u, 16u}) {
            coverage::context = "capacity=" + coverage::show(capacity);
            circular_buffer::circular_buffer<int> candidate(capacity);
            for (int cycle = 0; cycle < 20; ++cycle) {
                candidate.clear(); candidate.clear();
                for (unsigned i = 0; i < capacity; ++i) candidate.write(static_cast<int>(i));
                coverage::rejects<std::domain_error>([&]() { candidate.write(999); }, "full write rejected unchanged");
                candidate.overwrite(100);
                for (unsigned i = 1; i < capacity; ++i)
                    coverage::equal(candidate.read(), static_cast<int>(i), "overwrite drops oldest only");
                coverage::equal(candidate.read(), 100, "overwritten value last");
                coverage::rejects<std::domain_error>([&]() { static_cast<void>(candidate.read()); }, "empty after drain");
                candidate.write(123); candidate.clear();
                coverage::rejects<std::domain_error>([&]() { static_cast<void>(candidate.read()); }, "clear removes contents");
            }
        }
    } else throw std::invalid_argument("unknown coverage group");
}
