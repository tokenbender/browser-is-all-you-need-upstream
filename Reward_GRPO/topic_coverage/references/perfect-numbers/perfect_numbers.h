#pragma once
#include <stdexcept>
namespace perfect_numbers {
enum class classification { deficient, perfect, abundant };
classification classify(int n);
}
