#include "space_age.h"
#include "coverage.hpp"
#include <array>
#include <limits>

namespace {
using Age = space_age::space_age;
using Method = double (Age::*)() const;
const std::array<Method, 8> methods{&Age::on_earth, &Age::on_mercury, &Age::on_venus,
    &Age::on_mars, &Age::on_jupiter, &Age::on_saturn, &Age::on_uranus, &Age::on_neptune};
const std::array<long double, 8> periods{1.L, .2408467L, .61519726L, 1.8808158L,
    11.862615L, 29.447498L, 84.016846L, 164.79132L};
void inspect(unsigned long long seconds) {
    coverage::context = "seconds=" + coverage::show(seconds);
    const Age candidate(seconds);
    coverage::equal(candidate.seconds(), seconds, "original seconds preserved exactly");
    for (std::size_t planet = 0; planet < methods.size(); ++planet) {
        const long double expected = static_cast<long double>(seconds) / (31557600.L * periods[planet]);
        // Keep the pinned 0.005 absolute tolerance; allow rounding noise at huge magnitudes.
        const long double tolerance = std::max(.005L,
            std::abs(expected) * 8 * std::numeric_limits<double>::epsilon());
        coverage::close((candidate.*methods[planet])(), expected,
                        "planet=" + coverage::show(planet), tolerance);
    }
    coverage::equal(candidate.seconds(), seconds, "conversion does not change seconds");
}
}
void run_topic(const std::string& group) {
    if (group == "conversion_boundaries") {
        for (auto seconds : {0ULL, 1ULL, 59ULL, 60ULL, 31557599ULL, 31557600ULL,
                             31557601ULL, 1000000000ULL}) inspect(seconds);
    } else if (group == "wide_seconds") {
        for (auto seconds : {2147483647ULL, 2147483648ULL, 4294967295ULL, 4294967296ULL,
                             8210123456ULL, 1000000000000ULL,
                             std::numeric_limits<unsigned long long>::max()}) inspect(seconds);
    } else if (group == "scaling_and_repeatability") {
        coverage::Generator generator{0x53504143u};
        for (int i = 0; i < 128; ++i) {
            const unsigned long long seconds = 1ULL + generator.next();
            inspect(seconds);
            inspect(seconds * 2);
            const Age first(seconds), doubled(seconds * 2);
            for (const auto method : methods) {
                const double before = (first.*method)();
                coverage::close((doubled.*method)(), 2.L * before, "doubling age", .015L);
                coverage::equal((first.*method)(), before, "repeated conversion stable");
            }
        }
    } else throw std::invalid_argument("unknown coverage group");
}
