"""Reviewable positive/negative audit controls; never solver-visible task edits."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Control:
    name: str
    sources: dict[str, str]
    expected: str
    kind: str
    required_failed_group: str | None = None


def edit(sources: dict[str, str], file: str, old: str, new: str) -> dict[str, str]:
    if sources[file].count(old) != 1:
        raise ValueError(f"control anchor is not unique: {file}: {old[:60]}")
    return {**sources, file: sources[file].replace(old, new, 1)}


def sublist_body(sources: dict[str, str], body: str) -> dict[str, str]:
    text = sources["sublist.cpp"]
    start, end = text.index("bool is_sublist("), text.index("\nList_comparison sublist(")
    replacement = (
        "bool is_sublist(const std::vector<int>& sublist, "
        "const std::vector<int>& superlist) {\n" + body + "\n}\n"
    )
    return {**sources, "sublist.cpp": text[:start] + replacement + text[end:]}


BUFFER_ALTERNATIVE = """#pragma once
#include <cstddef>
#include <deque>
#include <stdexcept>
namespace circular_buffer {
template<class T> class circular_buffer {
    std::deque<T> values;
    std::size_t limit;
public:
    explicit circular_buffer(std::size_t capacity): limit(capacity) {}
    T read() {
        if (values.empty()) throw std::domain_error("empty");
        T value=values.front(); values.pop_front(); return value;
    }
    void write(T value) {
        if (values.size()==limit) throw std::domain_error("full");
        values.push_back(value);
    }
    void overwrite(T value) {
        if (values.size()==limit) values.pop_front();
        values.push_back(value);
    }
    void clear() { values.clear(); }
};
}
"""

GRADE_ALTERNATIVE = """#pragma once
#include <algorithm>
#include <map>
#include <string>
#include <vector>
namespace grade_school {
class school {
    std::map<int,std::vector<std::string>> entries;
public:
    void add(const std::string& name, int grade) { entries[grade].push_back(name); }
    std::vector<std::string> grade(int grade) const {
        auto it=entries.find(grade);
        auto result=it==entries.end()?std::vector<std::string>{}:it->second;
        std::sort(result.begin(),result.end()); return result;
    }
    std::map<int,std::vector<std::string>> roster() const {
        auto result=entries;
        for(auto& item:result) std::sort(item.second.begin(),item.second.end());
        return result;
    }
};
}
"""



def clock_alternative(sources: dict[str, str]) -> dict[str, str]:
    text = sources["clock.cpp"]
    start, end = text.index("void clock::clean()"), text.index("clock clock::at(")
    body = """void clock::clean()
{
    const int raw = ((hour_ % 24) * 60 + minute_) % 1440;
    const int normalized = raw < 0 ? raw + 1440 : raw;
    hour_ = normalized / 60;
    minute_ = normalized % 60;
}

"""
    return {**sources, "clock.cpp": text[:start] + body + text[end:]}


YACHT_ALTERNATIVE = """#include "yacht.h"
#include <algorithm>
#include <numeric>
#include <stdexcept>
namespace yacht {
int score(std::array<int, 5> dice, const std::string& category) {
    const std::array<std::string, 6> names{"ones", "twos", "threes", "fours", "fives", "sixes"};
    std::array<int, 7> counts{};
    for (const int die : dice) ++counts[die];
    const int total = std::accumulate(dice.begin(), dice.end(), 0);
    for (int face = 1; face <= 6; ++face)
        if (category == names[face - 1]) return face * counts[face];
    if (category == "choice") return total;
    if (category == "yacht")
        return std::find(counts.begin(), counts.end(), 5) != counts.end() ? 50 : 0;
    if (category == "full house")
        return std::find(counts.begin(), counts.end(), 2) != counts.end()
            && std::find(counts.begin(), counts.end(), 3) != counts.end() ? total : 0;
    if (category == "four of a kind") {
        for (int face = 1; face <= 6; ++face) if (counts[face] >= 4) return face * 4;
        return 0;
    }
    if (category == "little straight" || category == "big straight") {
        const int first = category == "little straight" ? 1 : 2;
        for (int face = first; face < first + 5; ++face) if (counts[face] != 1) return 0;
        return 30;
    }
    throw std::invalid_argument("unknown category");
}
}
"""


def observed_failure_controls(task: str, sources: dict[str, str]) -> list[Control]:
    """Observed first-attempt mistakes; controls are never solver-visible."""
    result = []
    def add(name, file, old, new, group=None):
        result.append(Control(name, edit(sources, file, old, new), "fail",
                              "semantic" if group else "build", group))
    if task == "clock":
        base = clock_alternative(sources)
        for name, old, new, group in [
            ("negative_remainder", "raw < 0 ? raw + 1440 : raw", "raw", "canonical_creation"),
            ("unwrapped_hours", "hour_ = normalized / 60;", "hour_ = normalized / 60 + 24;", "canonical_creation"),
            ("minutes_only_equality", "return hour_ == rhs.hour_\\n        && minute_ == rhs.minute_;",
             "return minute_ == rhs.minute_;", "value_equality"),
            ("unpad_hour", "setw(2) << setfill('0') << hour_", "hour_", "formatting"),
        ]:
            # Stored literal escapes are expanded only in the matching anchor.
            old = old.replace("\\n", "\n")
            result.append(Control(name, edit(base, "clock.cpp", old, new), "fail", "semantic", group))
        add("missing_private_field", "clock.h", "    int hour_;", "", None)
    elif task == "yacht":
        add("frequency_instead_of_face", "yacht.cpp", "if (count_min >= 4) return min * 4;",
            "if (count_min >= 4) return count_min * 4;", "four_of_a_kind")
        add("face_times_frequency", "yacht.cpp", "if (count_max >= 4) return max * 4;",
            "if (count_max >= 4) return max * count_max * 4;", "four_of_a_kind")
        add("fixed_faces_full_house", "yacht.cpp", "if (min == max) return false;",
            "if (min != 2 || max != 3) return false;", "full_house")
        add("straight_missing_five", "yacht.cpp", "return dice == little_straight ? 30 : 0;",
            "return std::equal(dice.begin(), dice.begin() + 4, little_straight.begin()) ? 30 : 0;",
            "little_straight")
        add("missing_string_include", "yacht.h", "#include <string>", "", None)
        add("missing_numeric_include", "yacht.cpp", "#include <numeric>", "", None)
    elif task == "dnd-character":
        add("negative_even_overcorrection", "dnd_character.cpp",
            "std::floor((static_cast<double>(score) - 10) / 2)",
            "(score - 10) / 2 - (score < 10 ? 1 : 0)", "modifier_negative_even")
    elif task == "bank-account":
        add("closed_balance_not_rejected", "bank_account.cpp",
            "std::lock_guard guard(mutex_);\n    check_account_open();\n    return balance_;",
            "std::lock_guard guard(mutex_);\n    return balance_;", "lifecycle")
    elif task == "sublist":
        text = sources["sublist.cpp"].replace("return List_comparison::sublist;", "return List_comparison::SWAP;")
        text = text.replace("return List_comparison::superlist;", "return List_comparison::sublist;")
        text = text.replace("return List_comparison::SWAP;", "return List_comparison::superlist;")
        result.append(Control("reversed_relation", {**sources, "sublist.cpp": text},
                              "fail", "semantic", "sublist_relation"))
    elif task == "complex-numbers":
        add("componentwise_scalar_division", "complex_numbers.cpp",
            "Complex other{scalar, 0};\n    return other / complex;",
            "return Complex(scalar / complex.real(), -scalar / complex.imag());", "scalar_divide")
        add("scalar_subtracts_imaginary", "complex_numbers.cpp",
            "Complex diff{complex.real() - scalar, complex.imag()};",
            "Complex diff{complex.real() - scalar, complex.imag() - scalar};", "scalar_subtract")
        add("constructor_wrong_identifier", "complex_numbers.cpp",
            "Complex::Complex(double r, double i) : re(r), im(i) {}",
            "Complex::Complex(double r, double i) : re(r), im(imag) {}", None)
        add("private_comparison_access", "complex_numbers.cpp",
            "return lhs.real() == rhs.real() && lhs.imag() == rhs.imag();",
            "return lhs.re == rhs.re && lhs.im == rhs.im;", None)
        implementation = sources["complex_numbers.cpp"].replace('#include "complex_numbers.h"', '')
        for name, inline, expected, kind in [
            ("duplicate_header_definitions", False, "fail", "build"),
            ("inline_header_definitions", True, "pass", "positive"),
        ]:
            body = re.sub(r"(?m)^(Complex::Complex|Complex |double |bool |std::ostream& )",
                          r"inline \1", implementation) if inline else implementation
            candidate = {"complex_numbers.h": sources["complex_numbers.h"] + "\n" + body,
                         "complex_numbers.cpp": '#include "complex_numbers.h"\n'}
            result.append(Control(name, candidate, expected, kind))
        add("missing_link_definition", "complex_numbers.cpp",
            "double Complex::abs() const { return sqrt(re * re + im * im); }", "", None)
    return result


def alternative(task: str, sources: dict[str, str]) -> dict[str, str]:
    if task == "perfect-numbers":
        # Separate implementation: floating sqrt boundary, wide accumulation.
        from Reward_GRPO.generalized_cpp_grpo import _registry
        from Reward_GRPO.topic_coverage.runner import reference_sources
        legacy = reference_sources(_registry().resolve(task))
        text = legacy["perfect_numbers.cpp"].replace("int acc = 1;", "long long acc = 1;")
        text = text.replace("constexpr int aliquot", "constexpr long long aliquot")
        text = text.replace("int aliq = aliquot(n);", "long long aliq = aliquot(n);")
        return {**legacy, "perfect_numbers.cpp": text}
    if task == "clock":
        return clock_alternative(sources)
    if task == "yacht":
        return {**sources, "yacht.cpp": YACHT_ALTERNATIVE}
    if task == "allergies":
        result = edit(sources, "allergies.cpp",
                      "(result & allergen_value) == allergen_value",
                      "((result / allergen_value) % 2u) != 0u")
        return edit(result, "allergies.cpp", "(result & entry.second) == entry.second",
                    "((result / entry.second) % 2u) != 0u")
    if task == "bank-account":
        # Both interpretations of the disputed zero boundary must remain accepted.
        result = {**sources, "bank_account.cpp": sources["bank_account.cpp"].replace(
            "std::lock_guard guard(mutex_);", "std::scoped_lock guard(mutex_);")}
        return edit(result, "bank_account.cpp", "if (amount < 0)", "if (amount <= 0)")
    if task == "circular-buffer":
        return {"circular_buffer.h": BUFFER_ALTERNATIVE, "circular_buffer.cpp": ""}
    if task == "complex-numbers":
        return edit(sources, "complex_numbers.cpp",
                    "Complex other{scalar, 0};\n    return other / complex;",
                    "const double denominator = complex.real()*complex.real() + "
                    "complex.imag()*complex.imag();\n"
                    "    return Complex(scalar*complex.real()/denominator, "
                    "-scalar*complex.imag()/denominator);")
    if task == "dnd-character":
        return edit(sources, "dnd_character.cpp",
                    "std::floor((static_cast<double>(score) - 10) / 2)", "score / 2 - 5")
    if task == "grade-school":
        return {"grade_school.h": GRADE_ALTERNATIVE, "grade_school.cpp": ""}
    if task == "space-age":
        result = edit(sources, "space_age.cpp", "1.0/31557600.0", "31557600.0")
        return edit(result, "space_age.cpp", "seconds_*earth_years_per_second",
                    "seconds_/earth_years_per_second")
    if task == "sublist":
        return sublist_body(sources,
                            "if (sublist.empty()) return true;\n"
                            "return std::search(superlist.begin(),superlist.end(),"
                            "sublist.begin(),sublist.end()) != superlist.end();")
    raise ValueError("unsupported topic")


def controls(task: str, sources: dict[str, str]) -> list[Control]:
    result = [Control("alternative", alternative(task, sources), "pass", "positive")]
    def mutation(name: str, file: str, old: str, new: str, group: str) -> None:
        result.append(Control(name, edit(sources, file, old, new), "fail", "semantic", group))
    if task == "perfect-numbers":
        mutation("square_root_excluded", "perfect_numbers.cpp",
                 "divisor <= n / divisor", "divisor < n / divisor", "square_boundaries")
        mutation("narrow_sum", "perfect_numbers.cpp", "std::int64_t sum", "int sum", "wide_values")
        mutation("no_domain_error", "perfect_numbers.cpp",
                 'if (n <= 0) throw std::domain_error("Input must be positive");',
                 "if (n <= 0) return classification::deficient;", "domain_errors")
        mutation("wrong_exception", "perfect_numbers.cpp", "std::domain_error", "std::invalid_argument", "domain_errors")
        mutation("one_is_perfect", "perfect_numbers.cpp", "n == 1 ? 0 : 1", "1", "unit_and_primes")
        mutation("square_root_counted_twice", "perfect_numbers.cpp",
                 "if (divisor != n / divisor) sum += n / divisor;",
                 "sum += n / divisor;", "square_boundaries")
        mutation("number_included_as_divisor", "perfect_numbers.cpp", "n == 1 ? 0 : 1", "n + 1LL", "bounded_domain")
        from Reward_GRPO.generalized_cpp_grpo import _registry
        from Reward_GRPO.topic_coverage.runner import reference_sources
        result.append(Control("pinned_reference_overflow", reference_sources(_registry().resolve(task)),
                              "fail", "semantic", "wide_values"))
    elif task == "allergies":
        mutation("reversed_membership", "allergies.cpp",
                 "(result & allergen_value) == allergen_value",
                 "(result & allergen_value) == 0", "all_masks")
        mutation("missing_cats", "allergies.cpp",
                 "if((result & entry.second) == entry.second)",
                 "if(entry.second != 128u && (result & entry.second) == entry.second)", "all_masks")
        mutation("high_bit_alias", "allergies.cpp", "result(test_result)",
                 "result(test_result | (test_result >> 16u))", "higher_bits")
    elif task == "bank-account":
        mutation("uninitialized_open_state", "bank_account.h", "bool open_{false};", "bool open_;", "initial_state")
        initialized = edit(sources, "bank_account.h", "bool open_{false};", "bool open_;")
        initialized = edit(initialized, "bank_account.h", "   public:",
                           "   public:\n    Bankaccount() : balance_(0), open_(false) {}")
        result.append(Control("constructor_initialization", initialized, "pass", "positive"))
        renamed = {name: text.replace("balance_", "funds_").replace("open_", "active_")
                   for name, text in sources.items()}
        result.append(Control("renamed_private_state", renamed, "pass", "positive"))
        mutation("shared_balance_between_accounts", "bank_account.h", "int balance_{0};",
                 "inline static int balance_{0};", "account_isolation")
        mutation("withdraw_adds", "bank_account.cpp", "balance_ -= amount;",
                 "balance_ += amount;", "transaction_sequences")
        mutation("reopen_retains_balance", "bank_account.cpp", "balance_ = 0;",
                 "// incorrect: retained prior balance", "lifecycle")
    elif task == "circular-buffer":
        mutation("overwrite_wrong_head", "circular_buffer.h", "if (is_full()) move_position(head_);",
                 "if (is_full()) move_position(tail_);", "capacity_boundaries")
        mutation("clear_noop", "circular_buffer.h", "void clear() { head_ = tail_; }",
                 "void clear() {}", "capacity_boundaries")
    elif task == "complex-numbers":
        mutation("scalar_division_reversed", "complex_numbers.cpp", "return other / complex;",
                 "return complex / other;", "scalar_divide")
        mutation("exponential_missing_scale", "complex_numbers.cpp",
                 "std::exp(re) * std::sin(im)", "std::sin(im)", "identities_and_exponential")
    elif task == "dnd-character":
        mutation("negative_rounding", "dnd_character.cpp",
                 "std::floor((static_cast<double>(score) - 10) / 2)",
                 "(score - 10) / 2", "modifier_negative_odd")
        mutation("wrong_hitpoints", "dnd_character.h", "hitpoints = 10 +",
                 "hitpoints = 11 +", "character_rules")
        text = sources["dnd_character.cpp"]
        start = text.index("    auto rolls =")
        end = text.index("\n}", start)
        constant = {**sources, "dnd_character.cpp": text[:start] + "    return 10;" + text[end:]}
        result.append(Control("constant_ability_diagnostic", constant, "pass", "diagnostic"))
    elif task == "grade-school":
        bad = {**sources, "grade_school.h": GRADE_ALTERNATIVE.replace(
            "for(auto& item:result) std::sort(item.second.begin(),item.second.end());", ""),
            "grade_school.cpp": ""}
        result.append(Control("sort_only_grade", bad, "fail", "semantic", "insertion_orders"))
        mutation("query_inserts_grade", "grade_school.cpp", "auto it = roster_.find(grade);",
                 "const_cast<school*>(this)->roster_[grade];\n    auto it = roster_.find(grade);",
                 "read_stability_and_isolation")
    elif task == "space-age":
        mutation("narrow_seconds", "space_age.h", "unsigned long long seconds_;",
                 "unsigned int seconds_;", "wide_seconds")
        mutation("wrong_mars_period", "space_age.cpp", "= 1.8808158;", "= 1.9808158;",
                 "conversion_boundaries")
    elif task == "sublist":
        mutation("empty_is_equal", "sublist.cpp", "if (list_one == list_two) {",
                 "if (list_one.empty() || list_two.empty() || list_one == list_two) {", "empty_lists")
        mutation("call_order_changes_result", "sublist.cpp", "if (list_one == list_two) {",
                 "static unsigned calls = 0;\n    if (++calls % 2 == 1) return List_comparison::equal;\n    if (list_one == list_two) {",
                 "swap_and_repeatability")
        prefix = sublist_body(sources, "return sublist.size() <= superlist.size() && "
                              "std::equal(sublist.begin(), sublist.end(), superlist.begin());")
        result.append(Control("prefix_only", prefix, "fail", "semantic", "sublist_relation"))
        scattered = sublist_body(sources,
                                 "auto it=superlist.begin();\n"
                                 "for(int value:sublist) { it=std::find(it,superlist.end(),value); "
                                 "if(it==superlist.end()) return false; ++it; }\nreturn true;")
        result.append(Control("scattered_subsequence", scattered, "fail", "semantic", "unequal_relation"))
    if task == "yacht":
        mutation("yacht_fives_only", "yacht.cpp", "return is_yacht(dice) ? 50 : 0;",
                 "return std::all_of(dice.begin(), dice.end(), [](int value) { return value == 5; }) ? 50 : 0;",
                 "yacht")
    elif task == "complex-numbers":
        old = "Complex sum{complex.real() + scalar, complex.imag()};"
        # Both scalar addition overloads share this exact line.
        assert sources["complex_numbers.cpp"].count(old) == 2
        bad = {**sources, "complex_numbers.cpp": sources["complex_numbers.cpp"].replace(
            old, "Complex sum{complex.real() + scalar, complex.imag() + scalar};")}
        result.append(Control("scalar_adds_imaginary", bad, "fail", "semantic", "scalar_add"))
    elif task == "bank-account":
        mutation("overdraft_mutates_balance", "bank_account.cpp", "if (amount > balance_) {",
                 "if (amount > balance_) { balance_ = 0;", "rejected_state")
    elif task == "circular-buffer":
        bad = BUFFER_ALTERNATIVE.replace("std::deque<T> values;", "std::deque<int> values;")
        # Restrict the deliberate narrowing mistake to long long; other types remain correct.
        bad = BUFFER_ALTERNATIVE + bad.replace("template<class T> class circular_buffer", "template<> class circular_buffer<long long>").replace("T read()", "long long read()").replace("T value", "long long value")
        result.append(Control("narrow_wide_storage", {"circular_buffer.h": bad, "circular_buffer.cpp": ""},
                              "fail", "semantic", "wide_type"))
        # Definitions available only to the .cpp's explicit int/string instantiations.
        header = """#pragma once
#include <cstddef>
#include <deque>
#include <string>
#include <stdexcept>
namespace circular_buffer {
template<class T> class circular_buffer {
    std::deque<T> values;
    std::size_t limit;
public:
    explicit circular_buffer(std::size_t capacity);
    T read();
    void write(T value);
    void overwrite(T value);
    void clear();
};
}
"""
        source = """#include "circular_buffer.h"
namespace circular_buffer {
template<class T> circular_buffer<T>::circular_buffer(std::size_t capacity): limit(capacity) {}
template<class T> T circular_buffer<T>::read() {
    if(values.empty()) throw std::domain_error("empty");
    T value=values.front(); values.pop_front(); return value;
}
template<class T> void circular_buffer<T>::write(T value) {
    if(values.size()==limit) throw std::domain_error("full");
    values.push_back(value);
}
template<class T> void circular_buffer<T>::overwrite(T value) {
    if(values.size()==limit) values.pop_front();
    values.push_back(value);
}
template<class T> void circular_buffer<T>::clear() { values.clear(); }
template class circular_buffer<int>;
template class circular_buffer<std::string>;
}
"""
        result.append(Control("only_int_string_instantiations",
                              {"circular_buffer.h": header, "circular_buffer.cpp": source},
                              "fail", "build"))
    result.extend(observed_failure_controls(task, sources))
    stem = task.replace("-", "_")
    broken = {**sources, f"{stem}.cpp": sources[f"{stem}.cpp"] + "\n#error deliberate_build_control\n"}
    result.append(Control("compile_failure", broken, "fail", "build"))
    return result
