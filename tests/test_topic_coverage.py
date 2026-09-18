from __future__ import annotations

import json
import shutil
import sys

import pytest

from Reward_GRPO.generalized_cpp_grpo import BindingError, DEFAULT_REGISTRY, _reconstruct
from Reward_GRPO.topic_coverage import runner
from Reward_GRPO.topic_coverage.__main__ import control_matches, main
from Reward_GRPO.topic_coverage.controls import controls
from Reward_GRPO.topic_coverage.specs import TOPICS



# Explicit test-only source strings frozen from e6aee2c; D&D RNG-boundary repair
# is from f79da6f. These are NOT a training pool or benchmark fixture bundle.
# Exact source formatting is retained because mutation controls require unique anchors.
TOPIC_TEST_SOURCES = {'allergies': {'allergies.h': '#if !defined(ALLERGIES_H)\n'
                              '#define ALLERGIES_H\n'
                              '\n'
                              '#include <string>\n'
                              '#include <map>\n'
                              '#include <unordered_set>\n'
                              '\n'
                              'namespace allergies\n'
                              '{\n'
                              '\n'
                              'std::map<std::string, unsigned int> const ALLERGENS {\n'
                              '    {"eggs", 1},\n'
                              '    {"peanuts", 2},\n'
                              '    {"shellfish", 4},\n'
                              '    {"strawberries", 8},\n'
                              '    {"tomatoes", 16},\n'
                              '    {"chocolate", 32},\n'
                              '    {"pollen", 64},\n'
                              '    {"cats", 128}\n'
                              '};\n'
                              '\n'
                              'class allergy_test\n'
                              '{\n'
                              'public:\n'
                              '    allergy_test(unsigned int test_result);\n'
                              '\n'
                              '    bool is_allergic_to(std::string const& allergen) const;\n'
                              '    std::unordered_set<std::string> get_allergies() const;\n'
                              '\n'
                              'private:\n'
                              '    unsigned int const result;\n'
                              '};\n'
                              '\n'
                              '}\n'
                              '\n'
                              '#endif\n',
               'allergies.cpp': '#include "allergies.h"\n'
                                '\n'
                                '#include <string>\n'
                                '#include <map>\n'
                                '#include <unordered_set>\n'
                                '#include <algorithm>\n'
                                '\n'
                                'namespace allergies\n'
                                '{\n'
                                '\n'
                                'allergy_test::allergy_test(unsigned int test_result) : '
                                'result(test_result){}\n'
                                '\n'
                                'bool allergy_test::is_allergic_to(std::string const& allergen) '
                                'const\n'
                                '{\n'
                                '    unsigned int allergen_value = '
                                'allergies::ALLERGENS.at(allergen);\n'
                                '    return (result & allergen_value) == allergen_value;\n'
                                '}\n'
                                '\n'
                                'std::unordered_set<std::string> allergy_test::get_allergies() '
                                'const\n'
                                '{\n'
                                '    std::unordered_set<std::string> allergies; \n'
                                '    \n'
                                '    for(auto const& entry : allergies::ALLERGENS)\n'
                                '        if((result & entry.second) == entry.second)\n'
                                '            allergies.insert(entry.first);\n'
                                '\n'
                                '    return allergies;\n'
                                '}\n'
                                '\n'
                                '}\n'},
 'bank-account': {'bank_account.h': '#if !defined(BANK_ACCOUNT_H)\n'
                                    '#define BANK_ACCOUNT_H\n'
                                    '\n'
                                    '#include <mutex>\n'
                                    '\n'
                                    'namespace Bankaccount {\n'
                                    'class Bankaccount {\n'
                                    '   public:\n'
                                    '    void open();\n'
                                    '    void deposit(int amount);\n'
                                    '    void withdraw(int amount);\n'
                                    '    void close();\n'
                                    '    int balance();\n'
                                    '\n'
                                    '   private:\n'
                                    '    void check_account_open() const;\n'
                                    '    void check_amount_greater_zero(int amount) const;\n'
                                    '\n'
                                    '    int balance_{0};\n'
                                    '    bool open_{false};\n'
                                    '    std::mutex mutex_{};\n'
                                    '};\n'
                                    '}  // namespace Bankaccount\n'
                                    '#endif  // BANK_ACCOUNT_H',
                  'bank_account.cpp': '#include "bank_account.h"\n'
                                      '\n'
                                      '#include <stdexcept>\n'
                                      '\n'
                                      'namespace Bankaccount {\n'
                                      'void Bankaccount::open() {\n'
                                      '    if (open_) {\n'
                                      '        throw std::runtime_error{"account already open"};\n'
                                      '    }\n'
                                      '    open_ = true;\n'
                                      '    balance_ = 0;\n'
                                      '}\n'
                                      '\n'
                                      'void Bankaccount::deposit(int amount) {\n'
                                      '    std::lock_guard guard(mutex_);\n'
                                      '    check_account_open();\n'
                                      '    check_amount_greater_zero(amount);\n'
                                      '\n'
                                      '    balance_ += amount;\n'
                                      '}\n'
                                      '\n'
                                      'void Bankaccount::withdraw(int amount) {\n'
                                      '    std::lock_guard guard(mutex_);\n'
                                      '\n'
                                      '    check_account_open();\n'
                                      '    check_amount_greater_zero(amount);\n'
                                      '\n'
                                      '    if (amount > balance_) {\n'
                                      '        throw std::runtime_error{\n'
                                      '            "amount must be less or equal than current '
                                      'balance"};\n'
                                      '    }\n'
                                      '    balance_ -= amount;\n'
                                      '}\n'
                                      '\n'
                                      'void Bankaccount::close() {\n'
                                      '    check_account_open();\n'
                                      '    open_ = false;\n'
                                      '}\n'
                                      '\n'
                                      'int Bankaccount::balance() {\n'
                                      '    std::lock_guard guard(mutex_);\n'
                                      '    check_account_open();\n'
                                      '    return balance_;\n'
                                      '}\n'
                                      '\n'
                                      'void Bankaccount::check_account_open() const {\n'
                                      '    if (!open_) {\n'
                                      '        throw std::runtime_error{"account not open"};\n'
                                      '    }\n'
                                      '}\n'
                                      '\n'
                                      'void Bankaccount::check_amount_greater_zero(int amount) '
                                      'const {\n'
                                      '    if (amount < 0) {\n'
                                      '        throw std::runtime_error{"amount must be greater '
                                      'than 0"};\n'
                                      '    }\n'
                                      '}\n'
                                      '}  // namespace Bankaccount\n'},
 'circular-buffer': {'circular_buffer.h': '#if !defined(CIRCULAR_BUFFER_H_)\n'
                                          '#define CIRCULAR_BUFFER_H_\n'
                                          '\n'
                                          '#include <vector>\n'
                                          '#include <stdexcept>\n'
                                          '\n'
                                          'namespace circular_buffer {\n'
                                          '\n'
                                          'template <typename ValueType>\n'
                                          'class circular_buffer {\n'
                                          'public:\n'
                                          '    circular_buffer(std::size_t capacity) \n'
                                          '        : buffer_(capacity + 1), head_(0), tail_(0) {}\n'
                                          '    ValueType read();\n'
                                          '    void write(ValueType item);\n'
                                          '    void overwrite(ValueType item);\n'
                                          '    void clear() { head_ = tail_; }\n'
                                          '\n'
                                          'private:\n'
                                          '    std::vector<ValueType> buffer_;\n'
                                          '    std::size_t head_;\n'
                                          '    std::size_t tail_;\n'
                                          '\n'
                                          '    void push_back(ValueType item);\n'
                                          '    void move_position(std::size_t& position) { '
                                          'position = (position + 1) % buffer_.size(); }\n'
                                          '    bool is_empty() const { return head_ == tail_; }\n'
                                          '    bool is_full() const { return head_ == (tail_ + 1) '
                                          '% buffer_.size(); }\n'
                                          '};\n'
                                          '\n'
                                          'template <typename ValueType>\n'
                                          'ValueType circular_buffer<ValueType>::read() {\n'
                                          '    if (is_empty()) throw std::domain_error("Circular '
                                          'buffer is empty."); \n'
                                          '    ValueType item = buffer_[head_];\n'
                                          '    move_position(head_);\n'
                                          '    return item;\n'
                                          '}\n'
                                          '\n'
                                          'template <typename ValueType>\n'
                                          'void circular_buffer<ValueType>::write(ValueType item) '
                                          '{\n'
                                          '    if (is_full()) throw std::domain_error("Circular '
                                          'buffer is full.");\n'
                                          '    push_back(item);\n'
                                          '}\n'
                                          '\n'
                                          'template <typename ValueType>\n'
                                          'void circular_buffer<ValueType>::overwrite(ValueType '
                                          'item) {\n'
                                          '    if (is_full()) move_position(head_);\n'
                                          '    push_back(item);\n'
                                          '}\n'
                                          '\n'
                                          'template <typename ValueType>\n'
                                          'void circular_buffer<ValueType>::push_back(ValueType '
                                          'item) {\n'
                                          '    buffer_[tail_] = item;\n'
                                          '    move_position(tail_);\n'
                                          '}\n'
                                          '\n'
                                          '} // namespace circular_buffer\n'
                                          '\n'
                                          '#endif // !CIRCULAR_BUFFER_H_',
                     'circular_buffer.cpp': '#include "circular_buffer.h"\n'
                                            '\n'
                                            'namespace circular_buffer {\n'
                                            '\n'
                                            '}  // namespace circular_buffer\n'},
 'clock': {'clock.h': '#if !defined(CLOCK_H)\n'
                      '#define CLOCK_H\n'
                      '\n'
                      '#include <string>\n'
                      '\n'
                      'namespace date_independent\n'
                      '{\n'
                      '\n'
                      'class clock\n'
                      '{\n'
                      'public:\n'
                      '    static clock at(int hour, int minute = 0);\n'
                      '\n'
                      '    clock& plus(int minutes);\n'
                      '    clock& minus(int minutes);\n'
                      '\n'
                      '    operator std::string() const;\n'
                      '\n'
                      '    bool operator==(const clock& rhs) const;\n'
                      '\n'
                      'private:\n'
                      '    clock(int hour, int minute);\n'
                      '    void clean();\n'
                      '    int hour_;\n'
                      '    int minute_;\n'
                      '};\n'
                      '\n'
                      'inline bool operator!=(const clock& lhs, const clock& rhs)\n'
                      '{\n'
                      '    return !(lhs == rhs);\n'
                      '}\n'
                      '\n'
                      '}\n'
                      '\n'
                      '#endif\n',
           'clock.cpp': '#include "clock.h"\n'
                        '#include <iomanip>\n'
                        '#include <sstream>\n'
                        '\n'
                        'using namespace std;\n'
                        '\n'
                        'namespace\n'
                        '{\n'
                        '\n'
                        'const int minutes_per_hour = 60;\n'
                        'const int hours_per_day = 24;\n'
                        '\n'
                        '}\n'
                        '\n'
                        'namespace date_independent\n'
                        '{\n'
                        '\n'
                        'clock& clock::plus(int minutes)\n'
                        '{\n'
                        '    minute_ += minutes;\n'
                        '    clean();\n'
                        '    return *this;\n'
                        '}\n'
                        '\n'
                        'clock& clock::minus(int minutes)\n'
                        '{\n'
                        '    minute_ -= minutes;\n'
                        '    clean();\n'
                        '    return *this;\n'
                        '}\n'
                        '\n'
                        'clock::operator string() const\n'
                        '{\n'
                        '    ostringstream str;\n'
                        "    str << setw(2) << setfill('0') << hour_ << ':' << setw(2) << "
                        "setfill('0') << minute_;\n"
                        '    return str.str();\n'
                        '}\n'
                        '\n'
                        'clock::clock(int hour, int minute)\n'
                        '    : hour_(hour),\n'
                        '    minute_(minute)\n'
                        '{\n'
                        '    clean();\n'
                        '}\n'
                        '\n'
                        'void clock::clean()\n'
                        '{\n'
                        '    if (minute_ < 0) {\n'
                        '        int tmp = 1 + (minute_ / -minutes_per_hour);\n'
                        '        hour_ -= tmp;\n'
                        '        minute_ += minutes_per_hour * tmp;\n'
                        '    }\n'
                        '    if (hour_ < 0)\n'
                        '        hour_ += hours_per_day*(1 + (hour_ / -hours_per_day));\n'
                        '    hour_ += minute_ / minutes_per_hour;\n'
                        '    hour_ %= hours_per_day;\n'
                        '    minute_ %= minutes_per_hour;\n'
                        '}\n'
                        '\n'
                        'clock clock::at(int hour, int minute /*= 0*/)\n'
                        '{\n'
                        '    return clock(hour, minute);\n'
                        '}\n'
                        '\n'
                        'bool clock::operator==(const clock& rhs) const\n'
                        '{\n'
                        '    return hour_ == rhs.hour_\n'
                        '        && minute_ == rhs.minute_;\n'
                        '}\n'
                        '\n'
                        '}\n'},
 'complex-numbers': {'complex_numbers.h': '#if !defined(COMPLEX_NUMBERS_H)\n'
                                          '#define COMPLEX_NUMBERS_H\n'
                                          '#include <iostream>\n'
                                          '\n'
                                          'namespace complex_numbers {\n'
                                          '\n'
                                          'class Complex {\n'
                                          '   public:\n'
                                          '    Complex(double, double);\n'
                                          '    Complex operator+(const Complex& other) const;\n'
                                          '    Complex operator-(const Complex& other) const;\n'
                                          '    Complex operator*(const Complex& other) const;\n'
                                          '    Complex operator/(const Complex& other) const;\n'
                                          '    \n'
                                          '    double abs() const;\n'
                                          '    Complex conj() const;\n'
                                          '    double real() const;\n'
                                          '    double imag() const;\n'
                                          '    Complex exp() const;\n'
                                          '\n'
                                          '   private:\n'
                                          '    double re, im;\n'
                                          '};\n'
                                          '\n'
                                          'bool operator==(const Complex& lhs, const Complex& '
                                          'rhs);\n'
                                          'std::ostream& operator<<(std::ostream& os, Complex '
                                          'const& value);\n'
                                          'Complex operator+(const Complex& complex, double '
                                          'scalar);\n'
                                          'Complex operator+(double scalar, const Complex& '
                                          'complex);\n'
                                          'Complex operator-(const Complex& complex, double '
                                          'scalar);\n'
                                          'Complex operator-(double scalar, const Complex& '
                                          'complex);\n'
                                          'Complex operator*(const Complex& complex, double '
                                          'scalar);\n'
                                          'Complex operator*(double scalar, const Complex& '
                                          'complex);\n'
                                          'Complex operator/(const Complex& complex, double '
                                          'scalar);\n'
                                          'Complex operator/(double scalar, const Complex& '
                                          'complex);\n'
                                          '\n'
                                          '}  // namespace complex_numbers\n'
                                          '\n'
                                          '#endif\n',
                     'complex_numbers.cpp': '#include <cmath>\n'
                                            '#include <limits>\n'
                                            '\n'
                                            '#include "complex_numbers.h"\n'
                                            '\n'
                                            'namespace complex_numbers {\n'
                                            '\n'
                                            'Complex::Complex(double r, double i) : re(r), im(i) '
                                            '{}\n'
                                            '\n'
                                            'Complex Complex::operator+(const Complex& other) '
                                            'const {\n'
                                            '    Complex sum{re + other.re, im + other.im};\n'
                                            '    return sum;\n'
                                            '}\n'
                                            '\n'
                                            'Complex Complex::operator-(const Complex& other) '
                                            'const {\n'
                                            '    Complex diff{re - other.re, im - other.im};\n'
                                            '    return diff;\n'
                                            '}\n'
                                            '\n'
                                            'Complex Complex::operator*(const Complex& other) '
                                            'const {\n'
                                            '    Complex prod{re * other.re - im * other.im, im * '
                                            'other.re + re * other.im};\n'
                                            '    return prod;\n'
                                            '}\n'
                                            '\n'
                                            'Complex Complex::operator/(const Complex& other) '
                                            'const {\n'
                                            '    Complex quot{(re * other.re + im * other.im) /\n'
                                            '                     (other.re * other.re + other.im '
                                            '* other.im),\n'
                                            '                 (im * other.re - re * other.im) /\n'
                                            '                     (other.re * other.re + other.im '
                                            '* other.im)};\n'
                                            '    return quot;\n'
                                            '}\n'
                                            '\n'
                                            'double Complex::abs() const { return sqrt(re * re + '
                                            'im * im); }\n'
                                            '\n'
                                            'Complex Complex::conj() const {\n'
                                            '    Complex cx{re, -im};\n'
                                            '    return cx;\n'
                                            '}\n'
                                            '\n'
                                            'double Complex::real() const { return re; }\n'
                                            '\n'
                                            'double Complex::imag() const { return im; }\n'
                                            '\n'
                                            'Complex Complex::exp() const {\n'
                                            '    Complex ex{std::exp(re) * std::cos(im), '
                                            'std::exp(re) * std::sin(im)};\n'
                                            '    return ex;\n'
                                            '}\n'
                                            '\n'
                                            'bool operator==(const Complex& lhs, const Complex& '
                                            'rhs) {\n'
                                            '    return lhs.real() == rhs.real() && lhs.imag() == '
                                            'rhs.imag();\n'
                                            '}\n'
                                            '\n'
                                            'std::ostream& operator<<(std::ostream& os, Complex '
                                            'const& value) {\n'
                                            '    os << "(" << value.real() << "," << value.imag() '
                                            '<< ")";\n'
                                            '    return os;\n'
                                            '}\n'
                                            '\n'
                                            'Complex operator+(const Complex& complex, double '
                                            'scalar) {\n'
                                            '    Complex sum{complex.real() + scalar, '
                                            'complex.imag()};\n'
                                            '    return sum;\n'
                                            '}\n'
                                            '\n'
                                            'Complex operator+(double scalar, const Complex& '
                                            'complex) {\n'
                                            '    Complex sum{complex.real() + scalar, '
                                            'complex.imag()};\n'
                                            '    return sum;\n'
                                            '}\n'
                                            '\n'
                                            'Complex operator-(const Complex& complex, double '
                                            'scalar) {\n'
                                            '    Complex diff{complex.real() - scalar, '
                                            'complex.imag()};\n'
                                            '    return diff;\n'
                                            '}\n'
                                            '\n'
                                            'Complex operator-(double scalar, const Complex& '
                                            'complex) {\n'
                                            '    Complex diff{scalar - complex.real(), 0 - '
                                            'complex.imag()};\n'
                                            '    return diff;\n'
                                            '}\n'
                                            '\n'
                                            'Complex operator*(const Complex& complex, double '
                                            'scalar) {\n'
                                            '    Complex prod{complex.real() * scalar, '
                                            'complex.imag() * scalar};\n'
                                            '    return prod;\n'
                                            '}\n'
                                            '\n'
                                            'Complex operator*(double scalar, const Complex& '
                                            'complex) {\n'
                                            '    Complex prod{complex.real() * scalar, '
                                            'complex.imag() * scalar};\n'
                                            '    return prod;\n'
                                            '}\n'
                                            '\n'
                                            'Complex operator/(const Complex& complex, double '
                                            'scalar) {\n'
                                            '    Complex other{scalar, 0};\n'
                                            '    return complex / other;\n'
                                            '}\n'
                                            '\n'
                                            'Complex operator/(double scalar, const Complex& '
                                            'complex) {\n'
                                            '    Complex other{scalar, 0};\n'
                                            '    return other / complex;\n'
                                            '}\n'
                                            '\n'
                                            '}  // namespace complex_numbers\n'},
 'dnd-character': {'dnd_character.h': '#pragma once\n'
                                      '\n'
                                      'namespace dnd_character {\n'
                                      'int modifier(int score);\n'
                                      'int ability();\n'
                                      '\n'
                                      'struct Character {\n'
                                      '    Character() {\n'
                                      '        strength = ability();\n'
                                      '        dexterity = ability();\n'
                                      '        constitution = ability();\n'
                                      '        intelligence = ability();\n'
                                      '        wisdom = ability();\n'
                                      '        charisma = ability();\n'
                                      '        hitpoints = 10 + modifier(constitution);\n'
                                      '    };\n'
                                      '    int strength;\n'
                                      '    int dexterity;\n'
                                      '    int constitution;\n'
                                      '    int intelligence;\n'
                                      '    int wisdom;\n'
                                      '    int charisma;\n'
                                      '    int hitpoints;\n'
                                      '};\n'
                                      '\n'
                                      '}  // namespace dnd_character\n',
                   'dnd_character.cpp': '#include "dnd_character.h"\n'
                                        '\n'
                                        '#include <algorithm>\n'
                                        '#include <cmath>\n'
                                        '#include <cstdlib>\n'
                                        '#include <numeric>\n'
                                        '\n'
                                        'namespace dnd_character {\n'
                                        'int modifier(int score) {\n'
                                        '    return std::floor((static_cast<double>(score) - 10) / '
                                        '2);\n'
                                        '}\n'
                                        '\n'
                                        'int dice_roll() {\n'
                                        "    // Reject the incomplete bucket in rand()'s inclusive "
                                        'range.\n'
                                        '    constexpr auto bucket_size = (static_cast<unsigned '
                                        'long long>(RAND_MAX) + 1) / 6;\n'
                                        '    constexpr auto limit = bucket_size * 6;\n'
                                        '    unsigned long long draw;\n'
                                        '    do {\n'
                                        '        draw = static_cast<unsigned long '
                                        'long>(std::rand());\n'
                                        '    } while (draw >= limit);\n'
                                        '    return 1 + static_cast<int>(draw / bucket_size);\n'
                                        '}\n'
                                        '\n'
                                        'int ability() {\n'
                                        '    auto rolls = {dice_roll(), dice_roll(), dice_roll(), '
                                        'dice_roll()};\n'
                                        '    auto discard = std::min(rolls);\n'
                                        '\n'
                                        '    return std::accumulate(rolls.begin(), rolls.end(), 0) '
                                        '- discard;\n'
                                        '}\n'
                                        '}  // namespace dnd_character\n'},
 'grade-school': {'grade_school.h': '#if !defined(GRADE_SCHOOL_H)\n'
                                    '#define GRADE_SCHOOL_H\n'
                                    '\n'
                                    '#include <map>\n'
                                    '#include <string>\n'
                                    '#include <vector>\n'
                                    '\n'
                                    'namespace grade_school\n'
                                    '{\n'
                                    '\n'
                                    'class school\n'
                                    '{\n'
                                    'public:\n'
                                    '    const std::map<int, std::vector<std::string>>& roster() '
                                    'const {\n'
                                    '        return roster_;\n'
                                    '    }\n'
                                    '\n'
                                    '    void add(std::string const& name, int grade);\n'
                                    '\n'
                                    '    std::vector<std::string> grade(int grade) const;\n'
                                    '\n'
                                    'private:\n'
                                    '    std::map<int, std::vector<std::string>> roster_;\n'
                                    '};\n'
                                    '\n'
                                    '}\n'
                                    '\n'
                                    '#endif\n',
                  'grade_school.cpp': '#include "grade_school.h"\n'
                                      '#include <algorithm>\n'
                                      '\n'
                                      'using namespace std;\n'
                                      '\n'
                                      'namespace grade_school\n'
                                      '{\n'
                                      '\n'
                                      'void school::add(string const& name, int grade)\n'
                                      '{\n'
                                      '    vector<string>& grade_roster = roster_[grade];\n'
                                      '    auto it = lower_bound(grade_roster.begin(), '
                                      'grade_roster.end(), name);\n'
                                      '    grade_roster.insert(it, name);\n'
                                      '}\n'
                                      '\n'
                                      'vector<string> school::grade(int grade) const\n'
                                      '{\n'
                                      '    auto it = roster_.find(grade);\n'
                                      '    return (it != roster_.end()) ? it->second : '
                                      'vector<string>{};\n'
                                      '}\n'
                                      '\n'
                                      '}\n'},
 'space-age': {'space_age.h': '#if !defined(SPACE_AGE_H)\n'
                              '#define SPACE_AGE_H\n'
                              '\n'
                              'namespace space_age\n'
                              '{\n'
                              '\n'
                              'class space_age\n'
                              '{\n'
                              'public:\n'
                              '    explicit space_age(unsigned long long secs);\n'
                              '\n'
                              '    unsigned long long seconds() const;\n'
                              '    double on_earth() const;\n'
                              '    double on_mercury() const;\n'
                              '    double on_venus() const;\n'
                              '    double on_mars() const;\n'
                              '    double on_jupiter() const;\n'
                              '    double on_saturn() const;\n'
                              '    double on_uranus() const;\n'
                              '    double on_neptune() const;\n'
                              '\n'
                              'private:\n'
                              '    unsigned long long seconds_;\n'
                              '};\n'
                              '\n'
                              '}\n'
                              '\n'
                              '#endif\n',
               'space_age.cpp': '#include "space_age.h"\n'
                                '\n'
                                'namespace space_age\n'
                                '{\n'
                                '\n'
                                'namespace\n'
                                '{\n'
                                'const double earth_years_per_second = 1.0/31557600.0;\n'
                                'const double earth_years_per_mercury_year = 0.2408467;\n'
                                'const double earth_years_per_venus_year = 0.61519726;\n'
                                'const double earth_years_per_mars_year = 1.8808158;\n'
                                'const double earth_years_per_jupiter_year = 11.862615;\n'
                                'const double earth_years_per_saturn_year = 29.447498;\n'
                                'const double earth_years_per_uranus_year = 84.016846;\n'
                                'const double earth_years_per_neptune_year = 164.79132;\n'
                                '}\n'
                                '\n'
                                'space_age::space_age(unsigned long long secs)\n'
                                '    : seconds_(secs)\n'
                                '{\n'
                                '}\n'
                                '\n'
                                'unsigned long long space_age::seconds() const\n'
                                '{\n'
                                '    return seconds_;\n'
                                '}\n'
                                '\n'
                                'double space_age::on_earth() const\n'
                                '{\n'
                                '    return seconds_*earth_years_per_second;\n'
                                '}\n'
                                '\n'
                                'double space_age::on_mercury() const\n'
                                '{\n'
                                '    return on_earth()/earth_years_per_mercury_year;\n'
                                '}\n'
                                '\n'
                                'double space_age::on_venus() const\n'
                                '{\n'
                                '    return on_earth()/earth_years_per_venus_year;\n'
                                '}\n'
                                '\n'
                                'double space_age::on_mars() const\n'
                                '{\n'
                                '    return on_earth()/earth_years_per_mars_year;\n'
                                '}\n'
                                '\n'
                                'double space_age::on_jupiter() const\n'
                                '{\n'
                                '    return on_earth()/earth_years_per_jupiter_year;\n'
                                '}\n'
                                '\n'
                                'double space_age::on_saturn() const\n'
                                '{\n'
                                '    return on_earth()/earth_years_per_saturn_year;\n'
                                '}\n'
                                '\n'
                                'double space_age::on_uranus() const\n'
                                '{\n'
                                '    return on_earth()/earth_years_per_uranus_year;\n'
                                '}\n'
                                '\n'
                                'double space_age::on_neptune() const\n'
                                '{\n'
                                '    return on_earth()/earth_years_per_neptune_year;\n'
                                '}\n'
                                '\n'
                                '}\n'},
 'yacht': {'yacht.h': '#pragma once\n'
                      '\n'
                      '#include <array>\n'
                      '#include <string>\n'
                      '\n'
                      'namespace yacht {\n'
                      'int score(std::array<int, 5> dice, const std::string& category);\n'
                      '\n'
                      '}  // namespace yacht\n',
           'yacht.cpp': '#include "yacht.h"\n'
                        '\n'
                        '#include <algorithm>\n'
                        '#include <numeric>\n'
                        '#include <stdexcept>\n'
                        '\n'
                        'namespace yacht {\n'
                        '\n'
                        'int simple_scores(const std::array<int, 5>& dice, int target) {\n'
                        '    return std::accumulate(\n'
                        '        dice.begin(), dice.end(), 0,\n'
                        '        [target](int acc, int i) { return i == target ? acc + i : acc; '
                        '});\n'
                        '}\n'
                        '\n'
                        'bool is_yacht(const std::array<int, 5>& dice) {\n'
                        '    return std::all_of(dice.begin(), dice.end(),\n'
                        '                       [&dice](int i) { return i == dice[0]; });\n'
                        '}\n'
                        '\n'
                        'bool is_full_house(const std::array<int, 5>& dice) {\n'
                        '    const int min{dice.at(0)};\n'
                        '    const int max{dice.at(4)};\n'
                        '    if (min == max) return false;\n'
                        '    std::array<int, 5> full_house{min, min, max, max, max};\n'
                        '    if (dice == full_house) return true;\n'
                        '    full_house[2] = min;\n'
                        '    return dice == full_house;\n'
                        '}\n'
                        '\n'
                        'int four_of_a_kind_count(const std::array<int, 5>& dice) {\n'
                        '    const int min{dice.at(0)};\n'
                        '    const int max{dice.at(4)};\n'
                        '    int count_min{};\n'
                        '    int count_max{};\n'
                        '    for (auto element : dice) {\n'
                        '        if (element == min) ++count_min;\n'
                        '        if (element == max) ++count_max;\n'
                        '    }\n'
                        '    if (count_min >= 4) return min * 4;\n'
                        '    if (count_max >= 4) return max * 4;\n'
                        '    return 0;\n'
                        '}\n'
                        '\n'
                        'int score(std::array<int, 5> dice, const std::string& category) {\n'
                        '    if (category == "yacht") {\n'
                        '        return is_yacht(dice) ? 50 : 0;\n'
                        '    }\n'
                        '    if (category == "ones") {\n'
                        '        return simple_scores(dice, 1);\n'
                        '    }\n'
                        '    if (category == "twos") {\n'
                        '        return simple_scores(dice, 2);\n'
                        '    }\n'
                        '    if (category == "threes") {\n'
                        '        return simple_scores(dice, 3);\n'
                        '    }\n'
                        '    if (category == "fours") {\n'
                        '        return simple_scores(dice, 4);\n'
                        '    }\n'
                        '    if (category == "fives") {\n'
                        '        return simple_scores(dice, 5);\n'
                        '    }\n'
                        '    if (category == "sixes") {\n'
                        '        return simple_scores(dice, 6);\n'
                        '    }\n'
                        '    // the rest of the categories can make use of a sorted array:\n'
                        '    std::sort(dice.begin(), dice.end());\n'
                        '    if (category == "four of a kind") {\n'
                        '        return four_of_a_kind_count(dice);\n'
                        '    }\n'
                        '    if (category == "little straight") {\n'
                        '        std::array<int, 5> little_straight{1, 2, 3, 4, 5};\n'
                        '        return dice == little_straight ? 30 : 0;\n'
                        '    }\n'
                        '    if (category == "big straight") {\n'
                        '        std::array<int, 5> big_straight{2, 3, 4, 5, 6};\n'
                        '        return dice == big_straight ? 30 : 0;\n'
                        '    }\n'
                        '    // the last two categories need the sum of the dice:\n'
                        '    int total = std::reduce(dice.begin(), dice.end());\n'
                        '    if (category == "full house") {\n'
                        '        return is_full_house(dice) ? total : 0;\n'
                        '    }\n'
                        '    if (category == "choice") {\n'
                        '        return total;\n'
                        '    }\n'
                        '    throw std::invalid_argument("unknown category: " + category);\n'
                        '}\n'
                        '}  // namespace yacht\n'},
 'sublist': {'sublist.h': '#pragma once\n'
                          '\n'
                          '#include <vector>\n'
                          '\n'
                          'namespace sublist {\n'
                          '    enum class List_comparison { equal, sublist, superlist, unequal };\n'
                          '    \n'
                          '    List_comparison sublist(const std::vector<int>& list_one, const '
                          'std::vector<int>& list_two);\n'
                          '}  // namespace sublist\n',
             'sublist.cpp': '#include "sublist.h"\n'
                            '\n'
                            '#include <algorithm>\n'
                            '#include <iterator>\n'
                            '\n'
                            'namespace sublist {\n'
                            'bool is_sublist(const std::vector<int>& sublist,\n'
                            '                const std::vector<int>& superlist) {\n'
                            '    auto superlist_end = std::prev(\n'
                            '        superlist.end(), std::max<std::size_t>(1, sublist.size()) - '
                            '1);\n'
                            '    for (auto it{superlist.begin()}; it != superlist_end; '
                            'std::advance(it, 1)) {\n'
                            '        if (std::equal(sublist.begin(), sublist.end(), it)) return '
                            'true;\n'
                            '    }\n'
                            '    return false;\n'
                            '}\n'
                            '\n'
                            'List_comparison sublist(const std::vector<int>& list_one,\n'
                            '                        const std::vector<int>& list_two) {\n'
                            '    if (list_one == list_two) {\n'
                            '        return List_comparison::equal;\n'
                            '    }\n'
                            '    if (list_one.size() < list_two.size() && is_sublist(list_one, '
                            'list_two)) {\n'
                            '        return List_comparison::sublist;\n'
                            '    }\n'
                            '    if (list_one.size() > list_two.size() && is_sublist(list_two, '
                            'list_one)) {\n'
                            '        return List_comparison::superlist;\n'
                            '    }\n'
                            '    return List_comparison::unequal;\n'
                            '}\n'
                            '}  // namespace sublist\n'}}


def make_topic_test_registry(root):
    """Build explicit temporary bindings; never read the production DEFAULT_REGISTRY."""
    from pathlib import Path
    from Reward_GRPO.topic_coverage import runner as coverage
    root.mkdir(parents=True)
    tasks = {}
    sources_by_task = {task: dict(pair) for task, pair in TOPIC_TEST_SOURCES.items()}
    sources_by_task["perfect-numbers"] = {
        name: (coverage.PACKAGE / "references/perfect-numbers" / name).read_text()
        for name in ("perfect_numbers.h", "perfect_numbers.cpp")}
    for task, sources in sources_by_task.items():
        stem = task.replace("-", "_")
        fixture = root / "multi_env_fixtures" / task
        fixture.mkdir(parents=True)
        for name, text in sources.items():
            (fixture / name).write_text(text)
            ref = fixture / ".meta" / ("example" + Path(name).suffix)
            ref.parent.mkdir(exist_ok=True)
            ref.write_text(text)
        # Tiny official low-bit control, solely for the generalized-vs-topic
        # high-bit-alias regression. It is not the benchmark official suite.
        test = ('#include "allergies.h"\n#include <utility>\n'
                'std::pair<int,int> run_tests() {\n'
                '  allergies::allergy_test value(1);\n'
                '  return {int(value.is_allergic_to("eggs")) + '
                'int(!value.is_allergic_to("peanuts")), 2};\n}\n'
                if task == "allergies" else
                '#include <utility>\nstd::pair<int,int> run_tests() { return {1,1}; }\n')
        (fixture / (stem + "_test.cpp")).write_text(test)
        (fixture / "test").mkdir()
        harness = (coverage.PACKAGE.parents[1] /
                   "generalized_verifier_docs/validation/fixtures/arithmetic/test/tests-main.cpp")
        shutil.copyfile(harness, fixture / "test/tests-main.cpp")
        manifest = {"schema_version": 1, "task_id": task,
                    "source": "hermetic-topic-unit-test-not-benchmark",
                    "candidate_files": list(sources),
                    "protected_files": {p.relative_to(fixture).as_posix(): coverage.sha256(p)
                                        for p in fixture.rglob("*") if p.is_file()},
                    "fixture_dir": "multi_env_fixtures/" + task,
                    "policies": {f"G{i:02}": [] for i in range(2, 8)}}
        manifest_path = root / "manifests" / (task + ".json")
        manifest_path.parent.mkdir(exist_ok=True)
        manifest_path.write_text(json.dumps(manifest))
        tasks[task] = {"fixture_dir": manifest["fixture_dir"],
                       "manifest": manifest_path.relative_to(root).as_posix(),
                       "manifest_sha256": coverage.sha256(manifest_path)}
    path = root / "registry.json"
    path.write_text(json.dumps({"schema_version": 1, "tasks": tasks}))
    return path


@pytest.fixture(autouse=True)
def topic_registry(tmp_path, monkeypatch):
    from Reward_GRPO import generalized_cpp_grpo as adapter
    path = make_topic_test_registry(tmp_path / "topic-inputs")
    monkeypatch.setenv(adapter.REGISTRY_ENV, str(path))
    monkeypatch.setattr(adapter, "DEFAULT_REGISTRY", path)
    monkeypatch.setattr(runner, "DEFAULT_REGISTRY", path)
    monkeypatch.setitem(runner.AuditSession.__init__.__kwdefaults__, "registry_path", path)
    monkeypatch.setitem(globals(), "DEFAULT_REGISTRY", path)
    return path

def command(stdout: str, code: int = 0) -> dict:
    return {"stdout_tail": stdout, "returncode": code, "timed_out": False}


def receipt(**fields) -> str:
    return runner.MARKER + json.dumps({
        "protocol": "topic-coverage-v1", "group": "case", "status": "pass", "checks": 1,
        **fields,
    })


def test_exact_scope_and_diagnostic_separation():
    assert set(TOPICS) == {
        "allergies", "bank-account", "circular-buffer", "complex-numbers",
        "dnd-character", "grade-school", "space-age", "sublist", "clock", "yacht", "perfect-numbers",
    }
    assert sum(len(topic.groups) for topic in TOPICS.values()) == 64
    assert sum(len(topic.diagnostics) for topic in TOPICS.values()) == 2
    for topic in TOPICS.values():
        assert not set(topic.groups) & set(topic.diagnostics)


def test_cli_requires_explicit_local_execution(tmp_path, monkeypatch):
    output = tmp_path / "must-not-exist"
    monkeypatch.setattr(sys, "argv", ["topic_coverage", "validate", "--output", str(output)])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert not output.exists()


@pytest.mark.parametrize("fields", [
    {"protocol": "wrong"}, {"group": "wrong"}, {"status": "invalid"},
    {"checks": 0}, {"checks": True}, {"checks": -1}, {"checks": "100"},
])
def test_protocol_cannot_claim_false_success(fields):
    assert runner.parse_result(command(receipt(**fields)), "case")["status"] == "fail"


def test_protocol_requires_successful_exit_and_unique_receipt():
    assert runner.parse_result(command(receipt(), 1), "case")["status"] == "fail"
    assert runner.parse_result(command(receipt() + "\n" + receipt()), "case")["status"] == "fail"
    assert runner.parse_result(command("candidate debug line\n" + receipt()), "case")["status"] == "pass"
    assert runner.parse_result(command(""), "case")["status"] == "fail"


def test_protocol_distinguishes_launch_failure_and_timeout():
    assert runner.parse_result({"launch_error": "OSError"}, "case")["status"] == "invalid"
    assert runner.parse_result({"timed_out": True}, "case")["reason"] == "runtime_timeout"


def test_random_samples_need_not_fail_at_the_same_index():
    runs = [{"status": "fail", "checks": 7, "requirement": "hitpoints"},
            {"status": "fail", "checks": 35, "requirement": "hitpoints"}]
    random = runner.aggregate_group("character_rules", runs, variable_sampling=True)
    assert random["status"] == "fail"
    assert random["repeatable"] is False
    assert runner.aggregate_group("fixed_inputs", runs)["status"] == "fail"
    mixed = [{"status": "pass", "checks": 100}, runs[0]]
    assert runner.aggregate_group("ability_range", mixed, variable_sampling=True)["status"] == "fail"


def test_unknown_reference_failure_does_not_blame_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(runner.AuditSession, "_execute",
                        lambda *args: {"status": "fail", "reason": "reference_semantics"})
    with runner.AuditSession("allergies", tmp_path / "audit", allow_local_execution=True) as session:
        record = session.audit(runner.control_sources(session.binding, session.task_id))
    assert record["status"] == "invalid"
    assert record["reason"] == "reference_control_failed"


def test_source_reader_rejects_symlinks(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "allergies.h").write_text("// h")
    (real / "allergies.cpp").write_text("// cpp")
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError):
        runner.candidate_sources("allergies", linked)
    (real / "allergies.h").unlink()
    (real / "allergies.h").symlink_to(real / "allergies.cpp")
    with pytest.raises(ValueError):
        runner.candidate_sources("allergies", real)


def test_input_checks_do_not_launch(tmp_path):
    with pytest.raises(ValueError, match="acknowledgement"):
        runner.AuditSession("allergies", tmp_path / "out")
    with pytest.raises(ValueError, match="unsupported"):
        runner.AuditSession("phone-number", tmp_path / "out", allow_local_execution=True)
    with pytest.raises(ValueError, match="repeats"):
        runner.AuditSession("allergies", tmp_path / "out", repeats=0, allow_local_execution=True)
    with pytest.raises(ValueError, match="timeouts"):
        runner.AuditSession("allergies", tmp_path / "out", run_timeout=float("nan"),
                            allow_local_execution=True)
    assert not (tmp_path / "out").exists()


def test_output_is_never_overwritten(tmp_path):
    output = tmp_path / "existing"
    output.mkdir()
    with pytest.raises(ValueError, match="new directory"):
        runner.AuditSession("allergies", output, allow_local_execution=True)
    saved = output / "receipt.json"
    runner.write_json(saved, {"original": True})
    with pytest.raises(FileExistsError):
        runner.write_json(saved, {"original": False})
    assert json.loads(saved.read_text()) == {"original": True}


def test_dotdot_cannot_escape_protected_output_check():
    fixture = DEFAULT_REGISTRY.parent / "multi_env_fixtures" / "allergies"
    output = DEFAULT_REGISTRY.parent / "topic_coverage" / ".." / "multi_env_fixtures" / "allergies" / "not-created"
    with pytest.raises(ValueError, match="protected"):
        runner.AuditSession("allergies", output, allow_local_execution=True)
    assert not (fixture / "not-created").exists()


def test_other_topic_fixture_is_also_protected():
    output = DEFAULT_REGISTRY.parent / "multi_env_fixtures" / "bank-account" / "not-created"
    with pytest.raises(ValueError, match="protected"):
        runner.AuditSession("allergies", output, allow_local_execution=True)
    assert not output.exists()


def test_fixture_tampering_is_rejected_before_execution(tmp_path):
    root = DEFAULT_REGISTRY.parent
    entry = json.loads(DEFAULT_REGISTRY.read_text())["tasks"]["allergies"]
    fixture = tmp_path / entry["fixture_dir"]
    fixture.parent.mkdir(parents=True)
    shutil.copytree(root / entry["fixture_dir"], fixture)
    manifest = tmp_path / entry["manifest"]
    manifest.parent.mkdir(parents=True)
    shutil.copy2(root / entry["manifest"], manifest)
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"schema_version": 1, "tasks": {"allergies": entry}}))
    test = fixture / "allergies_test.cpp"
    test.write_text(test.read_text() + "\n// changed control\n")
    with pytest.raises(BindingError, match="allergies_test.cpp"):
        runner.AuditSession("allergies", tmp_path / "out", registry_path=registry,
                            allow_local_execution=True)
    assert not (tmp_path / "out").exists()


def test_missing_compiler_is_infrastructure_invalid(tmp_path):
    with runner.AuditSession("allergies", tmp_path / "audit", compiler="/nonexistent/topic-g++",
                             allow_local_execution=True) as session:
        record = session.audit(runner.control_sources(session.binding, session.task_id))
    assert record["status"] == "invalid"
    assert record["reason"] == "reference_control_failed"
    assert "candidate" not in record


@pytest.mark.skipif(shutil.which("g++") is None, reason="C++ compiler required")
@pytest.mark.parametrize("task", tuple(TOPICS))
def test_reference_alternative_and_semantic_mutant(task, tmp_path):
    with runner.AuditSession(task, tmp_path / task, allow_local_execution=True) as session:
        assert session.reference["status"] == "pass", session.reference
        positive, mutant, *_ = controls(task, runner.control_sources(session.binding, session.task_id))
        alternative = session.audit(positive.sources, "alternative")
        assert control_matches(alternative, positive), alternative
        bad = session.audit(mutant.sources, "mutant")
        assert control_matches(bad, mutant), bad
        assert bad["changes_grpo_reward"] is False
        assert bad["full_task_correctness_claim"] is False
        assert all(group["repeatable"] for group in bad["candidate"]["groups"])
        assert bad["candidate"]["candidate_source_unchanged"]


def test_diagnostic_warning_never_changes_topic_status(tmp_path):
    with runner.AuditSession("dnd-character", tmp_path / "audit", include_diagnostics=True,
                             allow_local_execution=True) as session:
        control = next(item for item in controls(
            "dnd-character", runner.control_sources(session.binding, session.task_id)
        ) if item.kind == "diagnostic")
        record = session.audit(control.sources)
        assert control_matches(record, control)
        assert record["status"] == "pass"
        assert record["changes_grpo_reward"] is False


def test_child_does_not_receive_credentials_and_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "unit-test-not-a-real-token")
    monkeypatch.setenv("WANDB_API_KEY", "unit-test-not-a-real-key")
    with runner.AuditSession("allergies", tmp_path / "audit",
                             allow_local_execution=True) as session:
        record = session._command(
            [sys.executable, "-c",
             "import os, shutil; assert shutil.which('g++'); assert 'HF_TOKEN' not in os.environ; "
             "assert 'WANDB_API_KEY' not in os.environ; print('clean')"],
            session.output, "environment", 5,
        )
        assert record["returncode"] == 0
        assert record["stdout_tail"].strip() == "clean"
        timed = session._command([sys.executable, "-c", "import time; time.sleep(10)"],
                                 session.output, "bounded", .1)
        assert timed["timed_out"]
        assert timed["elapsed_seconds"] < 5


def test_aider_response_reuses_existing_reconstruction(tmp_path):
    with runner.AuditSession("allergies", tmp_path / "audit", allow_local_execution=True) as session:
        response = runner.response_from_sources(runner.control_sources(session.binding, session.task_id))
        reconstructed = session.work / "response"
        assert _reconstruct(session.binding, response, reconstructed)
        sources = runner.candidate_sources("allergies", reconstructed)
        assert session.audit(sources)["status"] == "pass"


def test_added_coverage_beyond_generalized(tmp_path):
    with runner.AuditSession("allergies", tmp_path / "audit", allow_local_execution=True) as session:
        control = next(item for item in controls(
            "allergies", runner.control_sources(session.binding, session.task_id)
        ) if item.name == "high_bit_alias")
        extra = session.audit(control.sources)
        baseline = session.compare_generalized(control.sources)
        assert baseline["reason"] == "pass", baseline
        assert baseline["score"] == 1.0
        assert extra["status"] == "fail"
        assert extra["changes_grpo_reward"] is False


def test_yacht_rejects_fives_only_despite_old_benchmark_pass(tmp_path):
    """The archived trial-1 repair scored every yacht except five fives as zero."""
    from Reward_GRPO.topic_coverage.controls import edit
    with runner.AuditSession("yacht", tmp_path / "yacht-faces",
                             allow_local_execution=True) as session:
        sources = edit(
            runner.control_sources(session.binding, session.task_id), "yacht.cpp",
            "return is_yacht(dice) ? 50 : 0;",
            "return std::all_of(dice.begin(), dice.end(), [](int value) { return value == 5; }) ? 50 : 0;",
        )
        result = session.audit(sources)
        assert result["candidate"]["build"]["returncode"] == 0
        assert result["status"] == "fail"
        group = next(g for g in result["candidate"]["groups"] if g["group"] == "yacht")
        failure = group["runs"][0]
        assert failure["context"] == "dice=[1,1,1,1,1] category=yacht"
        assert failure["expected"] == "50" and failure["actual"] == "0"


@pytest.mark.parametrize("task,control_names", [
    ("clock", ["unpad_hour", "minutes_only_equality"]),
    ("complex-numbers", ["scalar_adds_imaginary", "scalar_subtracts_imaginary", "componentwise_scalar_division"]),
    ("bank-account", ["overdraft_mutates_balance"]),
    ("dnd-character", ["negative_even_overcorrection"]),
    ("circular-buffer", ["narrow_wide_storage", "only_int_string_instantiations"]),
])
def test_specific_failure_controls(task, control_names, tmp_path):
    with runner.AuditSession(task, tmp_path / task, allow_local_execution=True) as session:
        assert session.reference["status"] == "pass"
        available = {c.name: c for c in controls(task, runner.control_sources(session.binding, session.task_id))}
        for name in control_names:
            control = available[name]
            result = session.audit(control.sources, name)
            assert control_matches(result, control), result
            if task == "clock" and name == "unpad_hour":
                groups = {g["group"]: g["status"] for g in result["candidate"]["groups"]}
                assert groups["canonical_creation"] == "pass" and groups["formatting"] == "fail"


def test_reward_families_partition_requirements():
    from Reward_GRPO.topic_coverage.specs import Topic
    for topic in TOPICS.values():
        members = [member for _, family in topic.families for member in family]
        assert len(members) == len(set(members)) == len(topic.groups)
        assert set(members) == set(topic.groups)
    with pytest.raises(ValueError):
        Topic(("one", "two"), reward_families=(("incomplete", ("one",)),))


@pytest.mark.parametrize("runs", [
    [{"status": "fail", "checks": 4}, {"status": "fail", "reason": "probe_protocol_failure"}],
    [{"status": "pass", "checks": 40}, {"status": "fail", "reason": "runtime_timeout"}],
    [{"status": "pass", "checks": 40}, {"status": "pass", "checks": 39}],
])
def test_inconsistent_candidate_outcomes_are_failures(runs):
    result = runner.aggregate_group("fixed", runs)
    assert result["status"] == "fail" and not result["repeatable"]


def test_actual_launch_failure_stays_infrastructure_invalid():
    result = runner.aggregate_group("fixed", [{"status": "invalid"}, {"status": "fail"}])
    assert result["status"] == "invalid"



def test_sublist_preserves_all_original_empty_domain_pairs(tmp_path):
    with runner.AuditSession("sublist", tmp_path / "empty-domain", allow_local_execution=True) as session:
        group = next(g for g in session.reference["groups"] if g["group"] == "empty_lists")
        assert group["status"] == "pass"
        assert all(r["observations"]["bounded_empty_pairs"] == "681" for r in group["runs"])
        assert all(r["checks"] >= 681 * 3 for r in group["runs"])
