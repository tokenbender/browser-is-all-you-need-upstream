#include "sublist.h"
#include "coverage.hpp"
#include <utility>

namespace {
using List = std::vector<int>;
using Relation = sublist::List_comparison;
std::vector<List> bounded_lists() {
    std::vector<List> lists;
    List current;
    const auto generate = [&](auto&& self, unsigned depth) -> void {
        lists.push_back(current);
        if (depth == 4) return;
        for (int value : {-1, 0, 1, 2}) {
            current.push_back(value); self(self, depth + 1); current.pop_back();
        }
    };
    generate(generate, 0);
    return lists;
}
bool contains(const List& whole, const List& part) {
    if (part.size() > whole.size()) return false;
    for (std::size_t start = 0; start <= whole.size() - part.size(); ++start) {
        bool same = true;
        for (std::size_t i = 0; i < part.size(); ++i)
            if (whole[start + i] != part[i]) { same = false; break; }
        if (same) return true;
    }
    return false;
}
Relation expected(const List& a, const List& b) {
    if (a == b) return Relation::equal;
    if (contains(b, a)) return Relation::sublist;
    if (contains(a, b)) return Relation::superlist;
    return Relation::unequal;
}
std::string name(Relation value) {
    if (value == Relation::equal) return "equal";
    if (value == Relation::sublist) return "sublist";
    if (value == Relation::superlist) return "superlist";
    if (value == Relation::unequal) return "unequal";
    return "invalid relation " + coverage::show(value);
}
Relation inverse(Relation value) {
    if (value == Relation::sublist) return Relation::superlist;
    if (value == Relation::superlist) return Relation::sublist;
    return value;
}
void inspect(const List& a, const List& b) {
    coverage::context = "first=" + coverage::show(a) + " second=" + coverage::show(b);
    const auto before_a = a, before_b = b;
    coverage::equal(name(sublist::sublist(a, b)), name(expected(a, b)), "contiguous relation");
    coverage::equal(a, before_a, "first input unchanged");
    coverage::equal(b, before_b, "second input unchanged");
}
}
void run_topic(const std::string& group) {
    if (group == "equal_relation" || group == "sublist_relation" || group == "superlist_relation" || group == "unequal_relation") {
        const auto lists = bounded_lists();
        for (const auto& a : lists) for (const auto& b : lists) {
            if (a.empty() || b.empty()) continue;  // scored once in empty_lists
            const auto relation = expected(a, b);
            const std::string requirement = relation == Relation::equal ? "equal_relation"
                : relation == Relation::sublist ? "sublist_relation"
                : relation == Relation::superlist ? "superlist_relation" : "unequal_relation";
            if (requirement == group) inspect(a, b);
        }
        coverage::equal(lists.size(), std::size_t{341}, "bounded exhaustive domain");
        coverage::observations["nonempty_ordered_pairs"] = "115600";
    } else if (group == "empty_lists") {
        inspect({}, {});
        // Preserve all 681 empty-containing pairs from the original exhaustive
        // domain, while assigning their credit exclusively to this family.
        for (const auto& values : bounded_lists()) if (!values.empty()) {
            inspect({}, values); inspect(values, {});
        }
        coverage::observations["bounded_empty_pairs"] = "681";
        for (unsigned n : {1u, 2u, 8u, 257u}) {
            const List values(n, 42);
            inspect({}, values); inspect(values, {});
        }
    } else if (group == "overlaps_and_boundaries") {
        const std::vector<std::pair<List, List>> cases{
            {{1, 3}, {1, 2, 3}}, {{1, 2, 5}, {0, 1, 2, 3, 1, 2, 5}},
            {{1, 1, 2}, {0, 1, 1, 1, 2}}, {{1, 2, 1, 2, 3}, {1, 2, 1, 2, 1, 2, 3}},
            {{1, 2}, {1, 22}}, {{7}, {0, 7}}};
        for (const auto& item : cases) { inspect(item.first, item.second); inspect(item.second, item.first); }
        List long_list(512, 1); long_list.push_back(2);
        List suffix(64, 1); suffix.push_back(2);
        inspect(suffix, long_list); inspect(long_list, suffix);
        // Repeated prefixes require retrying overlapping start positions; a
        // matching scattered subsequence is insufficient. Use a disjoint alphabet.
        for (int value : {-1009, 10007}) for (unsigned n : {31u, 129u, 513u}) {
            List whole(n, value); whole.push_back(value + 1);
            List needle(n / 2, value); needle.push_back(value + 1);
            inspect(needle, whole); inspect(whole, needle);
            needle.back() = value + 2;
            inspect(needle, whole); inspect(whole, needle);
            List alternating;
            for (unsigned i = 0; i < n; ++i) alternating.push_back(value + static_cast<int>(i % 2));
            alternating.push_back(value + 2);
            const List tail(alternating.end() - 17, alternating.end());
            inspect(tail, alternating); inspect(alternating, tail);
            inspect({value, value + 2}, alternating);
        }
    } else if (group == "swap_and_repeatability") {
        coverage::Generator generator{0x5355424cu};
        for (int n = 0; n < 256; ++n) {
            List a, b;
            const unsigned na = generator.pick(20), nb = generator.pick(20);
            for (unsigned i = 0; i < na; ++i) a.push_back(static_cast<int>(generator.pick(5)) - 2);
            for (unsigned i = 0; i < nb; ++i) b.push_back(static_cast<int>(generator.pick(5)) - 2);
            coverage::context = "first=" + coverage::show(a) + " second=" + coverage::show(b);
            const auto before_a = a, before_b = b;
            const auto first = sublist::sublist(a, b);
            const auto swapped = sublist::sublist(b, a);
            const auto repeated = sublist::sublist(a, b);
            coverage::equal(name(repeated), name(first), "repeated call is stable");
            coverage::equal(name(swapped), name(inverse(first)), "swapping reverses direction");
            coverage::equal(a, before_a, "first input unchanged");
            coverage::equal(b, before_b, "second input unchanged");
        }
    } else throw std::invalid_argument("unknown coverage group");
}
