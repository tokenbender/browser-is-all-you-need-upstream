#include "dnd_character.h"
#include "coverage.hpp"
#include <array>
#include <set>

namespace {
int expected_modifier(int score) {
    const std::array<int, 16> expected{-4, -3, -3, -2, -2, -1, -1, 0, 0, 1, 1, 2, 2, 3, 3, 4};
    return expected.at(static_cast<std::size_t>(score - 3));
}
void within(int value, const std::string& name) {
    coverage::require(value >= 3 && value <= 18, name, "3..18", coverage::show(value));
}
}
void run_topic(const std::string& group) {
    if (group == "modifier_negative_odd" || group == "modifier_negative_even" || group == "modifier_nonnegative") {
        for (int repeat = 0; repeat < 16; ++repeat) for (int score = 3; score <= 18; ++score) {
            const std::string requirement = score >= 10 ? "modifier_nonnegative"
                : score % 2 ? "modifier_negative_odd" : "modifier_negative_even";
            if (group != requirement) continue;
            coverage::context = "score=" + coverage::show(score);
            coverage::equal(dnd_character::modifier(score), expected_modifier(score), "floor modifier");
        }
    } else if (group == "ability_range") {
        for (int i = 0; i < 4000; ++i) {
            coverage::context = "sample=" + coverage::show(i);
            within(dnd_character::ability(), "ability range");
        }
    } else if (group == "character_rules") {
        for (int i = 0; i < 500; ++i) {
            coverage::context = "character=" + coverage::show(i);
            const dnd_character::Character c;
            for (int ability : {c.strength, c.dexterity, c.constitution, c.intelligence, c.wisdom, c.charisma})
                within(ability, "character ability range");
            coverage::equal(c.hitpoints, 10 + expected_modifier(c.constitution), "constitution-derived hitpoints");
        }
    } else if (group == "randomness_observation") {
        // Diagnostic only: no exact RNG sequence, frequency threshold or seed injection.
        std::set<int> seen;
        for (int i = 0; i < 512; ++i) {
            const int value = dnd_character::ability(); within(value, "observed ability range"); seen.insert(value);
        }
        coverage::observations["distinct_values"] = coverage::show(seen.size());
        coverage::observations["suspicious_constant_output"] = seen.size() == 1 ? "true" : "false";
        coverage::observations["distribution_proven"] = "false";
    } else throw std::invalid_argument("unknown coverage group");
}
