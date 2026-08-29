#include "zebra_puzzle.h"

#include <algorithm>
#include <array>
#include <iostream>
#include <stdexcept>
#include <utility>
#include <vector>

namespace zebra_puzzle {

namespace {

constexpr int HOUSE_COUNT = 5;

struct GameState {
    std::array<Assignment, HOUSE_COUNT> houses;
    int next_position = 0;
};

std::vector<Color> get_colors() {
    return { Color::Red, Color::Green, Color::Ivory, Color::Yellow, Color::Blue };
}

std::vector<Nation> get_nations() {
    return { Nation::Englishman, Nation::Spaniard, Nation::Ukrainian, Nation::Japanese, Nation::Norwegian };
}

std::vector<Pet> get_pets() {
    return { Pet::Dog, Pet::Snail, Pet::Horse, Pet::Fox, Pet::Zebra };
}

std::vector<Drink> get_drinks() {
    return { Drink::Coffee, Drink::Tea, Drink::Milk, Drink::OrangeJuice, Drink::Water };
}

std::vector<Hobby> get_hobbies() {
    return { Hobby::Dancing, Hobby::Painting, Hobby::Football, Hobby::Chess, Hobby::Reading };
}

bool is_assigned(const GameState& state, int position) {
    return state.houses[position].color != Color::Red &&  // placeholder values
           state.houses[position].nation != Nation::Englishman &&
           state.houses[position].pet != Pet::Dog &&
           state.houses[position].drink != Drink::Coffee &&
           state.houses[position].hobby != Hobby::Dancing;
}

bool check_constraints(const GameState& state) {
    for (int pos = 0; pos < HOUSE_COUNT; ++pos) {
        const Assignment& house = state.houses[pos];
        
        // Rule 2: Englishman lives in the red house
        if (house.nation == Nation::Englishman && house.color != Color::Red) return false;
        
        // Rule 3: Spaniard owns the dog
        if (house.nation == Nation::Spaniard && house.pet != Pet::Dog) return false;
        
        // Rule 4: Green house drinks coffee
        if (house.color == Color::Green && house.drink != Drink::Coffee) return false;
        
        // Rule 5: Ukrainian drinks tea
        if (house.nation == Nation::Ukrainian && house.drink != Drink::Tea) return false;
        
        // Rule 6: Green is immediately to the right of the ivory house
        if (house.color == Color::Green && pos > 0) {
            if (state.houses[pos - 1].color != Color::Ivory) return false;
        }
        
        // Rule 7: Snail owner likes to go dancing
        if (house.pet == Pet::Snail && house.hobby != Hobby::Dancing) return false;
        
        // Rule 8: Yellow house is a painter
        if (house.color == Color::Yellow && house.hobby != Hobby::Painting) return false;
        
        // Rule 9: Middle house drinks milk
        if (pos == 2 && house.drink != Drink::Milk) return false;
        
        // Rule 10: Norwegian lives in the first house
        if (house.nation == Nation::Norwegian && pos != 0) return false;
        
        // Rule 11: Reading next to Fox
        if (house.hobby == Hobby::Reading) {
            if (pos > 0 && state.houses[pos - 1].pet == Pet::Fox) return true;
            if (pos < HOUSE_COUNT - 1 && state.houses[pos + 1].pet == Pet::Fox) return true;
            return false;
        }
        
        // Rule 12: Painter next to the horse
        if (house.hobby == Hobby::Painting) {
            if (pos > 0 && state.houses[pos - 1].pet == Pet::Horse) return true;
            if (pos < HOUSE_COUNT - 1 && state.houses[pos + 1].pet == Pet::Horse) return true;
            return false;
        }
        
        // Rule 13: Football player drinks orange juice
        if (house.hobby == Hobby::Football && house.drink != Drink::OrangeJuice) return false;
        
        // Rule 14: Japanese person plays chess
        if (house.nation == Nation::Japanese && house.hobby != Hobby::Chess) return false;
    }

    // Rule 15: Norwegian lives next to the blue house
    for (int pos = 0; pos < HOUSE_COUNT; ++pos) {
        if (state.houses[pos].nation == Nation::Norwegian) {
            if (pos > 0 && state.houses[pos - 1].color == Color::Blue) return true;
            if (pos < HOUSE_COUNT - 1 && state.houses[pos + 1].color == Color::Blue) return true;
            return false;
        }
    }

    return true;
}

bool assign_and_check(GameState& state) {
    if (state.next_position == HOUSE_COUNT) {
        return check_constraints(state);
    }

    const int pos = state.next_position;
    const auto& prev_house = (pos > 0) ? state.houses[pos - 1] : Assignment{};
    const auto& next_house = (pos < HOUSE_COUNT - 1) ? state.houses[pos + 1] : Assignment{};

    for (const Color color : get_colors()) {
        if (is_assigned(state, pos)) break;
        if (prev_house.color == color) continue;
        if (next_house.color == color) continue;
        state.houses[pos].color = color;
        if (assign_and_check(state)) return true;
        state.houses[pos].color = Color::Red;
    }

    for (const Nation nation : get_nations()) {
        if (is_assigned(state, pos)) break;
        if (prev_house.nation == nation) continue;
        if (next_house.nation == nation) continue;
        state.houses[pos].nation = nation;
        if (assign_and_check(state)) return true;
        state.houses[pos].nation = Nation::Englishman;
    }

    for (const Pet pet : get_pets()) {
        if (is_assigned(state, pos)) break;
        if (prev_house.pet == pet) continue;
        if (next_house.pet == pet) continue;
        state.houses[pos].pet = pet;
        if (assign_and_check(state)) return true;
        state.houses[pos].pet = Pet::Dog;
    }

    for (const Drink drink : get_drinks()) {
        if (is_assigned(state, pos)) break;
        if (prev_house.drink == drink) continue;
        if (next_house.drink == drink) continue;
        state.houses[pos].drink = drink;
        if (assign_and_check(state)) return true;
        state.houses[pos].drink = Drink::Coffee;
    }

    for (const Hobby hobby : get_hobbies()) {
        if (is_assigned(state, pos)) break;
        if (prev_house.hobby == hobby) continue;
        if (next_house.hobby == hobby) continue;
        state.houses[pos].hobby = hobby;
        if (assign_and_check(state)) return true;
        state.houses[pos].hobby = Hobby::Dancing;
    }

    return false;
}

}  // namespace

Solution solve() {
    GameState state{};
    if (assign_and_check(state)) {
        Solution solution;
        for (const auto& house : state.houses) {
            if (house.drink == Drink::Water) {
                solution.drinksWater = "the " + std::to_string(
                    static_cast<int>(house.nation) + 1) + " " +
                    std::to_string(static_cast<int>(house.color) + 1) + " " +
                    std::to_string(static_cast<int>(house.pet) + 1) + " " +
                    std::to_string(static_cast<int>(house.drink) + 1) + " " +
                    std::to_string(static_cast<int>(house.hobby) + 1);
            }
            if (house.pet == Pet::Zebra) {
                solution.ownsZebra = "the " + std::to_string(
                    static_cast<int>(house.nation) + 1) + " " +
                    std::to_string(static_cast<int>(house.color) + 1) + " " +
                    std::to_string(static_cast<int>(house.pet) + 1) + " " +
                    std::to_string(static_cast<int>(house.drink) + 1) + " " +
                    std::to_string(static_cast<int>(house.hobby) + 1);
            }
        }
        return solution;
    }
    throw std::runtime_error("No solution found");
}

}  // namespace zebra_puzzle
