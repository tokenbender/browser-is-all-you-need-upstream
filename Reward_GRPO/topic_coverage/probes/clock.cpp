#include "clock.h"
#include "coverage.hpp"
#include <array>

namespace {
using Clock = date_independent::clock;
int canonical(long long minutes) {
    const auto remainder = minutes % 1440;
    return static_cast<int>(remainder < 0 ? remainder + 1440 : remainder);
}
std::string expected_text(long long minutes) {
    const int value = canonical(minutes);
    std::string result = "00:00";
    result[0] = static_cast<char>('0' + value / 60 / 10);
    result[1] = static_cast<char>('0' + value / 60 % 10);
    result[3] = static_cast<char>('0' + value % 60 / 10);
    result[4] = static_cast<char>('0' + value % 60 % 10);
    return result;
}
void inspect(const Clock& clock, long long minutes) {
    const std::string rendered = clock;
    // Numeric normalization is independent of zero-padding, graded separately.
    std::istringstream parser(rendered);
    int hour = -1, minute = -1; char separator = 0;
    const bool parsed = static_cast<bool>(parser >> hour >> separator >> minute);
    parser >> std::ws;
    coverage::require(parsed && parser.eof() && separator == ':' && hour >= 0 && hour < 24
                      && minute >= 0 && minute < 60, "canonical time fields", "H:M in one day", rendered);
    coverage::equal(hour * 60 + minute, canonical(minutes), "normalized minutes");
}
constexpr std::array<int, 13> hours{-1000, -72, -25, -24, -1, 0, 1, 8, 23, 24, 25, 72, 1000};
constexpr std::array<int, 13> minutes{-2881, -1440, -61, -60, -59, -1, 0, 1, 59, 60, 61, 1440, 2881};
}

void run_topic(const std::string& group) {
    if (group == "canonical_creation") {
        for (const int hour : hours) {
            inspect(Clock::at(hour), 60LL * hour);
            for (const int minute : minutes) {
                coverage::context = "hour=" + coverage::show(hour) + " minute=" + coverage::show(minute);
                inspect(Clock::at(hour, minute), 60LL * hour + minute);
            }
        }
    } else if (group == "formatting") {
        for (int hour = 0; hour < 24; ++hour) for (int minute = 0; minute < 60; ++minute) {
            coverage::context = "hour=" + coverage::show(hour) + " minute=" + coverage::show(minute);
            const std::string rendered = Clock::at(hour, minute);
            coverage::equal(rendered, expected_text(60LL * hour + minute), "zero-padded HH:MM");
        }
        // Preserve formatting coverage after noncanonical construction and updates.
        const auto shape = [](const Clock& clock) {
            const std::string text = clock;
            coverage::require(text.size() == 5 && text[2] == ':'
                && text[0] >= '0' && text[0] <= '9' && text[1] >= '0' && text[1] <= '9'
                && text[3] >= '0' && text[3] <= '9' && text[4] >= '0' && text[4] <= '9',
                "zero-padded shape after normalization/update", "HH:MM", text);
        };
        for (int hour : hours) for (int minute : minutes) {
            auto clock = Clock::at(hour, minute); shape(clock);
            for (int delta : minutes) { clock.plus(delta); shape(clock); clock.minus(delta); shape(clock); }
            clock.plus(61).minus(1441).plus(-60); shape(clock);
        }
    } else if (group == "update_contract") {
        auto clock = Clock::at(1, 2);
        for (int delta : minutes) {
            coverage::require(&clock.plus(delta) == &clock, "plus returns the modified clock");
            coverage::require(&clock.minus(delta) == &clock, "minus returns the modified clock");
        }
    } else if (group == "signed_updates") {
        for (const int hour : hours) for (const int minute : minutes) {
            auto clock = Clock::at(hour, minute);
            long long expected = 60LL * hour + minute;
            for (const int delta : minutes) {
                coverage::context = "hour=" + coverage::show(hour) + " minute=" + coverage::show(minute)
                                  + " delta=" + coverage::show(delta);
                clock.plus(delta);
                expected += delta;
                inspect(clock, expected);
                clock.minus(delta);
                expected -= delta;
                inspect(clock, expected);
            }
            clock.plus(61).minus(1441).plus(-60);
            inspect(clock, expected - 1440);
        }
    } else if (group == "value_equality") {
        for (const int hour : hours) for (const int minute : minutes) {
            coverage::context = "hour=" + coverage::show(hour) + " minute=" + coverage::show(minute);
            const auto original = Clock::at(hour, minute);
            const auto normalized = Clock::at(0, canonical(60LL * hour + minute));
            const auto next_day = Clock::at(hour + 24, minute);
            const auto other_hour = Clock::at(hour + 1, minute);
            coverage::require(original == normalized && normalized == original, "equality uses normalized time");
            coverage::require(original == next_day && !(original != next_day), "whole days preserve equality");
            coverage::require(original != other_hour && !(original == other_hour), "equal minutes do not imply equal times");
        }
    } else if (group == "copy_isolation") {
        for (const int hour : hours) for (const int minute : minutes) {
            const auto original = Clock::at(hour, minute);
            auto changed = original;
            changed.plus(1);
            inspect(original, 60LL * hour + minute);
            inspect(changed, 60LL * hour + minute + 1);
            coverage::require(changed != original, "copy mutation is independent");
            changed.minus(1);
            coverage::require(changed == original, "inverse update restores equality");
        }
    } else throw std::invalid_argument("unknown coverage group");
}
