#include "allergies.h"
#include "coverage.hpp"
#include <array>
#include <limits>
#include <unordered_set>

namespace {
const std::array<std::string, 8> names{
    "eggs", "peanuts", "shellfish", "strawberries", "tomatoes", "chocolate", "pollen", "cats"};
void inspect(unsigned score) {
    coverage::context = "score=" + coverage::show(score);
    const allergies::allergy_test candidate(score);
    std::unordered_set<std::string> expected;
    for (unsigned bit = 0; bit < names.size(); ++bit) {
        const bool present = ((score >> bit) % 2) != 0;
        if (present) expected.insert(names[bit]);
        coverage::equal(candidate.is_allergic_to(names[bit]), present, "membership:" + names[bit]);
    }
    const auto actual = candidate.get_allergies();
    coverage::equal(actual.size(), expected.size(), "list size");
    for (const auto& name : names)
        coverage::equal(actual.count(name), expected.count(name), "list membership:" + name);
}
}
void run_topic(const std::string& group) {
    if (group == "all_masks") {
        for (unsigned score = 0; score < 256; ++score) inspect(score);
    } else if (group == "higher_bits") {
        for (unsigned low = 0; low < 256; ++low) {
            for (unsigned bit = 8; bit < std::numeric_limits<unsigned>::digits; ++bit)
                inspect(low | (1u << bit));
            inspect(low | (~255u));
        }
    } else if (group == "query_stability") {
        const allergies::allergy_test first(5), second(250);
        for (int repeat = 0; repeat < 32; ++repeat) {
            inspect(static_cast<unsigned>(repeat * 7));
            coverage::equal(first.is_allergic_to("eggs"), true, "objects remain independent");
            coverage::equal(second.is_allergic_to("eggs"), false, "second object remains independent");
            coverage::equal(first.get_allergies().size(), std::size_t{2}, "queries do not mutate");
        }
    } else throw std::invalid_argument("unknown coverage group");
}
