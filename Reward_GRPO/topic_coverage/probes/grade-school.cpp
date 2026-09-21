#include "grade_school.h"
#include "coverage.hpp"
#include <utility>

namespace {
using Roster = std::map<int, std::vector<std::string>>;
std::string describe(const Roster& roster) {
    std::string out;
    for (const auto& entry : roster)
        out += coverage::show(entry.first) + ":" + coverage::show(entry.second) + ";";
    return out;
}
void inspect(const grade_school::school& school, const Roster& expected) {
    const Roster actual = school.roster();
    coverage::require(actual == expected, "full roster agrees", describe(expected), describe(actual));
    for (const auto& entry : expected)
        coverage::equal(school.grade(entry.first), entry.second, "grade agrees with roster");
    coverage::equal(school.grade(999), std::vector<std::string>{}, "missing grade empty");
    coverage::require(school.roster() == expected, "read operations preserve roster",
                      describe(expected), describe(school.roster()));
}
void sequence(const std::vector<std::pair<std::string, int>>& input) {
    grade_school::school candidate;
    Roster expected;
    coverage::trace.clear();
    inspect(candidate, expected);
    for (const auto& entry : input) {
        coverage::record("add(" + entry.first + "," + coverage::show(entry.second) + ")");
        candidate.add(entry.first, entry.second);
        expected[entry.second].push_back(entry.first);
        std::sort(expected[entry.second].begin(), expected[entry.second].end());
        inspect(candidate, expected);
    }
}
}
void run_topic(const std::string& group) {
    if (group == "insertion_orders") {
        std::vector<std::pair<std::string, int>> input{
            {"Zoe", 10}, {"Bradley", 2}, {"Anna", 1}, {"Mira", 11}, {"Franklin", 2}};
        std::sort(input.begin(), input.end());
        do { sequence(input); } while (std::next_permutation(input.begin(), input.end()));
    } else if (group == "generated_rosters") {
        std::vector<std::pair<std::string, int>> input;
        for (int i = 0; i < 128; ++i) {
            std::ostringstream name; name << "student_" << std::setw(3) << std::setfill('0') << i;
            input.emplace_back(name.str(), std::vector<int>{1, 2, 3, 10, 11}[static_cast<unsigned>(i) % 5]);
        }
        coverage::Generator generator{0x47524144u};
        for (std::size_t i = input.size(); i > 1; --i)
            std::swap(input[i - 1], input[generator.pick(static_cast<unsigned>(i))]);
        sequence(input);
    } else if (group == "read_stability_and_isolation") {
        grade_school::school first, second;
        first.add("Zoe", 2); first.add("Anna", 2); second.add("Mira", 11);
        for (int repeat = 0; repeat < 64; ++repeat) {
            inspect(first, {{2, {"Anna", "Zoe"}}}); inspect(second, {{11, {"Mira"}}});
        }
    } else throw std::invalid_argument("unknown coverage group");
}
