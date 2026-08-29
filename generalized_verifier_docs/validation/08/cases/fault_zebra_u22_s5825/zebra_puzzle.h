#if !defined(ZEBRA_PUZZLE_H)
#define ZEBRA_PUZZLE_H

#include <array>
#include <string>
#include <vector>

namespace zebra_puzzle {

enum class Color { Red, Green, Ivory, Yellow, Blue };
enum class Nation { Englishman, Spaniard, Ukrainian, Japanese, Norwegian };
enum class Pet { Dog, Snail, Horse, Fox, Zebra };
enum class Drink { Coffee, Tea, Milk, OrangeJuice, Water };
enum class Hobby { Dancing, Painting, Football, Chess, Reading };

struct Assignment {
    Color color;
    Nation nation;
    Pet pet;
    Drink drink;
    Hobby hobby;
};

struct Solution {
    std::string drinksWater;
    std::string ownsZebra;
};

Solution solve();

}  // namespace zebra_puzzle

#endif  // ZEBRA_PUZZLE_H
