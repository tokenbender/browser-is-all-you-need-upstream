#if !defined(PARALLEL_LETTER_FREQUENCY_H)
#define PARALLEL_LETTER_FREQUENCY_H

#include <algorithm>
#include <execution>
#include <string_view>
#include <unordered_map>
#include <vector>

namespace parallel_letter_frequency {

std::unordered_map<char, size_t> frequency(
    std::vector<std::string_view> const& texts);

}  // namespace parallel_letter_frequency

#endif  // PARALLEL_LETTER_FREQUENCY_H
