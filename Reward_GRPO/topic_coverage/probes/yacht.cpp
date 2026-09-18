#include "yacht.h"
#include "coverage.hpp"
#include <array>

namespace {
using Dice = std::array<int, 5>;
using Counts = std::array<int, 7>;
const std::array<std::string, 6> faces{"ones", "twos", "threes", "fours", "fives", "sixes"};
void inspect(const Dice& dice, const std::string& category, int expected) {
    coverage::context = "dice=" + coverage::show(std::vector<int>(dice.begin(), dice.end()))
                      + " category=" + category;
    coverage::equal(yacht::score(dice, category), expected, "category score");
}
}

void run_topic(const std::string& group) {
    if (std::find(faces.begin(), faces.end(), group) == faces.end()
        && group != "choice" && group != "full_house" && group != "four_of_a_kind"
        && group != "yacht" && group != "little_straight" && group != "big_straight")
        throw std::invalid_argument("unknown coverage group");
    // All 6^5 ordered rolls. Independent frequency oracle instead of the
    // reference's sorted endpoints and pattern arrays.
    for (unsigned encoded = 0; encoded < 7776; ++encoded) {
        unsigned remaining = encoded;
        Dice dice{}; Counts counts{}; int sum = 0; unsigned mask = 0;
        for (auto& die : dice) {
            die = 1 + static_cast<int>(remaining % 6); remaining /= 6;
            ++counts[die]; sum += die; mask |= 1u << die;
        }
        if (std::find(faces.begin(), faces.end(), group) != faces.end()) {
            const int face = 1 + static_cast<int>(std::find(faces.begin(), faces.end(), group) - faces.begin());
            inspect(dice, group, face * counts[face]);
        } else if (group == "choice") {
            inspect(dice, "choice", sum);
        } else if (group == "full_house" || group == "four_of_a_kind" || group == "yacht") {
            bool pair = false, triple = false, five = false; int four_score = 0;
            for (int face = 1; face <= 6; ++face) {
                pair = pair || counts[face] == 2; triple = triple || counts[face] == 3;
                five = five || counts[face] == 5;
                if (counts[face] >= 4) four_score = 4 * face;
            }
            if (group == "full_house") inspect(dice, "full house", pair && triple ? sum : 0);
            if (group == "four_of_a_kind") inspect(dice, "four of a kind", four_score);
            if (group == "yacht") inspect(dice, "yacht", five ? 50 : 0);
        } else {
            if (group == "little_straight") inspect(dice, "little straight", mask == 0x3eu ? 30 : 0);
            if (group == "big_straight") inspect(dice, "big straight", mask == 0x7cu ? 30 : 0);
        }
    }
}
