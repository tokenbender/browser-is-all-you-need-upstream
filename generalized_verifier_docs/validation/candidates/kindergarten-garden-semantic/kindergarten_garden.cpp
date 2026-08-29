#include "kindergarten_garden.h"

#include <algorithm>
#include <stdexcept>
#include <string_view>

namespace kindergarten_garden {

std::array<Plants, 4> plants(std::string_view diagram, std::string_view student) {
    static constexpr std::array<std::string_view, 12> student_order{
        "Alice", "Bob", "Charlie", "David", "Eve", "Fred", "Ginny", "Harriet", "Ileana", "Joseph", "Kincaid", "Larry"
    };

    auto found = std::find(student_order.begin(), student_order.end(), student);
    if (found == student_order.end()) {
        throw std::invalid_argument("Unknown student");
    }
    const std::size_t student_index = static_cast<std::size_t>(found - student_order.begin());

    const std::size_t front_cup = student_index;
    const std::size_t back_cup = 6 + student_index;

    if (diagram.size() < 12) {
        throw std::invalid_argument("Diagram must have 12 characters");
    }

    return {
        static_cast<Plants>(diagram[front_cup]),
        static_cast<Plants>(diagram[back_cup]),
        static_cast<Plants>(diagram[front_cup + 6]),
        static_cast<Plants>(diagram[back_cup + 6])
    };
}

}  // namespace kindergarten_garden
