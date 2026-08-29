#include "crypto_square.h"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <sstream>
#include <utility>

namespace crypto_square {

cipher::cipher(std::string const& text) {
    // Normalization
    std::string normalized;
    std::transform(text.begin(), text.end(), std::back_inserter(normalized),
                   [](unsigned char c) { return std::tolower(c); });
    normalized.erase(std::remove_if(normalized.begin(), normalized.end(),
                                   [](unsigned char c) { return !std::isalnum(c); }),
                   normalized.end());
    normalized_ = std::move(normalized);

    // Dimensions
    std::size_t length = normalized_.size();
    if (length == 0) {
        columns_ = 0;
        rows_ = 0;
        return;
    }
    columns_ = static_cast<std::size_t>(std::ceil(std::sqrt(length)));
    rows_ = static_cast<std::size_t>(std::ceil(static_cast<double>(length) / columns_));
}

std::string cipher::normalize_plain_text() const {
    return normalized_;
}

std::size_t cipher::size() const {
    return columns_;
}

std::vector<std::string> cipher::plain_text_segments() const {
    std::vector<std::string> segments;
    if (normalized_.empty()) return segments;

    for (std::size_t start = 0; start < normalized_.size(); start += columns_) {
        std::size_t end = std::min(start + columns_, normalized_.size());
        segments.push_back(normalized_.substr(start, end - start));
    }
    return segments;
}

std::string cipher::cipher_text() const {
    if (normalized_.empty()) return "";
    std::string result;
    result.reserve(normalized_.size());

    for (std::size_t col = 0; col < columns_; ++col) {
        for (std::size_t row = 0; row < rows_; ++row) {
            std::size_t index = row * columns_ + col;
            if (index < normalized_.size()) {
                result.push_back(normalized_[index]);
            }
        }
    }
    return result;
}

std::string cipher::normalized_cipher_text() const {
    if (normalized_.empty()) return "";
    std::string result;
    result.reserve(normalized_.size());

    for (std::size_t row = 0; row < rows_; ++row) {
        for (std::size_t col = 0; col < columns_; ++col) {
            std::size_t index = row * columns_ + col;
            if (index < normalized_.size()) {
                result.push_back(normalized_[index]);
            } else {
                result.push_back(' ');
            }
        }
    }
    return result;
}

}  // namespace crypto_square
