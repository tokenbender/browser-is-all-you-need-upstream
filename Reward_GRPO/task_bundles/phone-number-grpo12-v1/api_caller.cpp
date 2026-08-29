#include "phone_number.h"

#include <string>
#include <type_traits>
#include <utility>

using candidate_type = phone_number::phone_number;
static_assert(std::is_constructible_v<candidate_type, const std::string&>);
static_assert(!std::is_convertible_v<candidate_type, std::string>);
static_assert(std::is_same_v<decltype(std::declval<const candidate_type&>().area_code()), std::string>);
static_assert(std::is_same_v<decltype(std::declval<const candidate_type&>().number()), std::string>);
static_assert(std::is_same_v<decltype(static_cast<std::string>(std::declval<const candidate_type&>())), std::string>);

int main() {
    const candidate_type value("+1 (223) 456-7890");
    (void)value.area_code();
    (void)value.number();
    (void)static_cast<std::string>(value);
    return 0;
}
