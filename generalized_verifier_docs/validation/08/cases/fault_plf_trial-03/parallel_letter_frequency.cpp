#include "parallel_letter_frequency.h"

#include <cctype>
#include <string_view>

namespace parallel_letter_frequency {

namespace {

std::unordered_map<char, size_t> count_letters(std::string_view text) {
    std::unordered_map<char, size_t> counts;
    for (char c : text) {
        if (std::isalpha(static_cast<unsigned char>(c))) {
            counts[std::tolower(static_cast<unsigned char>(c))]++;
        }
    }
    return counts;
}

}  // namespace

std::unordered_map<char, size_t> frequency(
    std::vector<std::string_view> const& texts) {
    if (texts.empty()) {
        return {};
    }

    std::vector<std::unordered_map<char, size_t>> map_chunks(texts.size());

    // Parallel counting
    std::for_each(
        std::execution::par, texts.begin(), texts.end(),
        [&](std::string_view text) {
            const size_t index = &text - texts.data();
            map_chunks[index] = count_letters(text);
        });

    // Sequential reduction (synchronization happens here automatically because par loop finishes first)
    std::unordered_map<char, size_t> result;
    for (const auto& chunk : map_chunks) {
        for (const auto& [letter, count] : chunk) {
            result[letter] += count;
        }
    }
    return result;
}

}  // namespace parallel_letter_frequency
