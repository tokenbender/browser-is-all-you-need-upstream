#include "phone_number.h"

#include <algorithm>
#include <cctype>
#include <stdexcept>

namespace phone_number {

phone_number::phone_number(const std::string& text) {
    std::string digits;
    for (unsigned char value : text) {
        if (std::isdigit(value)) {
            digits.push_back(static_cast<char>(value));
        } else if (std::isalpha(value)) {
            throw std::domain_error("letters are invalid");
        } else if (value != ' ' && value != '-' && value != '.' && value != '(' && value != ')' && value != '+') {
            throw std::domain_error("punctuation is invalid");
        }
    }
    if (digits.size() == 11) {
        if (digits.front() != '1') {
            throw std::domain_error("country code is invalid");
        }
        digits.erase(digits.begin());
    }
    if (digits.size() != 10 || digits[0] < '2' || digits[3] < '2') {
        throw std::domain_error("NANP number is invalid");
    }
    digits_ = digits;
}

std::string phone_number::area_code() const { return digits_.substr(0, 3); }
std::string phone_number::number() const { return digits_; }
phone_number::operator std::string() const { return "(" + digits_.substr(0, 3) + ") " + digits_.substr(3, 3) + "-" + digits_.substr(6, 4); }

}  // namespace phone_number
