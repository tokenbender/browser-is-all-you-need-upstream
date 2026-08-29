#include "spiral_matrix.h"
#include <vector>

namespace spiral_matrix {

std::vector<std::vector<uint32_t>> spiral_matrix(uint32_t size) {
    if (size == 0) {
        return {};
    }

    std::vector<std::vector<uint32_t>> matrix(size, std::vector<uint32_t>(size, 0));

    uint32_t top = 0;
    uint32_t bottom = size - 1;
    uint32_t left = 0;
    uint32_t right = size - 1;
    uint32_t current = 1;

    while (current <= size * size) {
        // Fill top row from left to right
        for (uint32_t i = left; i <= right; ++i) {
            matrix[top][i] = current++;
        }
        ++top;

        // Fill right column from top to bottom
        for (uint32_t i = top; i <= bottom; ++i) {
            matrix[i][right] = current++;
        }
        --right;

        // Fill bottom row from right to left
        if (top <= bottom) {
            for (uint32_t i = right; i >= left; --i) {
                matrix[bottom][i] = current++;
            }
            --bottom;
        }

        // Fill left column from bottom to top
        if (left <= right) {
            for (uint32_t i = bottom; i >= top; --i) {
                matrix[i][left] = current++;
            }
            ++left;
        }
    }

    return matrix;
}

}  // namespace spiral_matrix
