#include "complex_numbers.h"
#include "coverage.hpp"
#include <array>

namespace {
using Complex = complex_numbers::Complex;
void inspect(const Complex& value, long double real, long double imag, const std::string& name,
             long double tolerance = .005L) {
    coverage::close(value.real(), real, name + ":real", tolerance);
    coverage::close(value.imag(), imag, name + ":imag", tolerance);
}
}
void run_topic(const std::string& group) {
    const std::array<long double, 7> values{-3, -1, -.5L, 0, .5L, 1, 3};
    if (group == "direct_add" || group == "direct_subtract" || group == "direct_multiply" || group == "direct_divide") {
        for (const auto a : values) for (const auto b : values)
        for (const auto c : values) for (const auto d : values) {
            const Complex left(static_cast<double>(a), static_cast<double>(b));
            const Complex right(static_cast<double>(c), static_cast<double>(d));
            coverage::context = "left=" + coverage::show(a) + "," + coverage::show(b)
                              + " right=" + coverage::show(c) + "," + coverage::show(d);
            if (group == "direct_add") inspect(left + right, a + c, b + d, "addition");
            if (group == "direct_subtract") inspect(left - right, a - c, b - d, "subtraction");
            if (group == "direct_multiply") inspect(left * right, a * c - b * d, a * d + b * c, "multiplication");
            if (group == "direct_divide" && (c != 0 || d != 0))
                inspect(left / right, (a * c + b * d) / (c * c + d * d),
                        (b * c - a * d) / (c * c + d * d), "division");
            inspect(left, a, b, "operands preserved"); inspect(right, c, d, "operands preserved");
        }
    } else if (group == "scalar_add" || group == "scalar_subtract" || group == "scalar_multiply" || group == "scalar_divide") {
        for (const auto a : values) for (const auto b : values) for (const auto s : values) {
            const Complex z(static_cast<double>(a), static_cast<double>(b));
            const double scalar = static_cast<double>(s);
            coverage::context = "z=" + coverage::show(a) + "," + coverage::show(b) + " scalar=" + coverage::show(s);
            if (group == "scalar_add") inspect(z + scalar, a + s, b, "complex plus scalar");
            if (group == "scalar_add") inspect(scalar + z, a + s, b, "scalar plus complex");
            if (group == "scalar_subtract") inspect(z - scalar, a - s, b, "complex minus scalar");
            if (group == "scalar_subtract") inspect(scalar - z, s - a, -b, "scalar minus complex");
            if (group == "scalar_multiply") inspect(z * scalar, a * s, b * s, "complex times scalar");
            if (group == "scalar_multiply") inspect(scalar * z, a * s, b * s, "scalar times complex");
            if (group == "scalar_divide" && s != 0) inspect(z / scalar, a / s, b / s, "complex divided by scalar");
            if (group == "scalar_divide" && (a != 0 || b != 0))
                inspect(scalar / z, s * a / (a * a + b * b), -s * b / (a * a + b * b), "scalar divided by complex");
            inspect(z, a, b, "scalar operand preserved");
        }
    } else if (group == "identities_and_exponential") {
        for (const auto a : values) for (const auto b : values) {
            const Complex z(static_cast<double>(a), static_cast<double>(b));
            coverage::context = "z=" + coverage::show(a) + "," + coverage::show(b);
            inspect(z.conj(), a, -b, "conjugation");
            inspect(z.conj().conj(), a, b, "double conjugation", .015L);
            coverage::close(z.abs(), std::sqrt(a * a + b * b), "magnitude");
            inspect(z.exp(), std::exp(a) * std::cos(b), std::exp(a) * std::sin(b), "exponential");
            const Complex w(1.25, -2.5);
            inspect((z / w) * w, a, b, "divide multiply identity", .1L);
            inspect(z * z.conj(), a * a + b * b, 0, "conjugate product", .1L);
        }
    } else throw std::invalid_argument("unknown coverage group");
}
