#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <exception>
#include <iomanip>
#include <iostream>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <utility>
#include <vector>

// Shared reporting only. Expected answers are calculated in each topic probe.
namespace coverage {
inline std::uint64_t checks = 0;
inline std::string context;
inline std::vector<std::string> trace;
inline std::map<std::string, std::string> observations;

template <typename T> std::string show(const T& value) {
    std::ostringstream out;
    out << std::setprecision(17);
    if constexpr (std::is_enum_v<T>) out << static_cast<int>(value);
    else out << value;
    return out.str();
}
template <typename T> std::string show(const std::vector<T>& values) {
    std::string out = "[";
    for (const auto& value : values) {
        if (out.size() > 1) out += ",";
        out += show(value);
    }
    return out + "]";
}
inline std::string quote(const std::string& value) {
    std::ostringstream out;
    out << '"';
    for (unsigned char ch : value) {
        if (ch == '"' || ch == '\\') out << '\\' << ch;
        else if (ch < 32) out << "\\u" << std::hex << std::setw(4)
                              << std::setfill('0') << static_cast<unsigned>(ch);
        else out << ch;
    }
    out << '"';
    return out.str();
}
struct Failure {
    std::string requirement, expected, actual;
};
inline void record(const std::string& event) {
    trace.push_back(event);
    if (trace.size() > 32) trace.erase(trace.begin());
}
inline void require(bool condition, const std::string& requirement,
                    std::string expected = "true", std::string actual = "false") {
    ++checks;
    if (!condition) throw Failure{requirement, std::move(expected), std::move(actual)};
}
template <typename A, typename B>
void equal(const A& actual, const B& expected, const std::string& requirement) {
    require(actual == expected, requirement, show(expected), show(actual));
}
inline void close(double actual, long double expected, const std::string& requirement,
                  long double tolerance = 0.005L) {
    require(std::isfinite(actual) && std::abs(static_cast<long double>(actual) - expected)
                <= tolerance,
            requirement, show(expected), show(actual));
}
template <typename Exception, typename Operation>
void rejects(Operation operation, const std::string& requirement) {
    bool rejected = false;
    try { operation(); }
    catch (const Exception&) { rejected = true; }
    catch (const std::exception& error) {
        require(false, requirement, "specified exception type", error.what());
    }
    require(rejected, requirement, "specified exception", "no exception");
}
// Explicit generator avoids implementation-dependent distribution/shuffle results.
struct Generator {
    std::uint32_t state;
    std::uint32_t next() { state = state * 1664525u + 1013904223u; return state; }
    unsigned pick(unsigned count) { return (next() >> 8) % count; }
};
inline void emit(const std::string& group, const std::string& status,
                 const Failure& failure = {"", "", ""}) {
    std::cout << "TOPIC_COVERAGE_RECEIPT {\"protocol\":\"topic-coverage-v1\",\"group\":"
              << quote(group) << ",\"status\":" << quote(status)
              << ",\"checks\":" << checks << ",\"requirement\":" << quote(failure.requirement)
              << ",\"expected\":" << quote(failure.expected)
              << ",\"actual\":" << quote(failure.actual)
              << ",\"context\":" << quote(context) << ",\"trace\":[";
    for (std::size_t i = 0; i < trace.size(); ++i) {
        if (i) std::cout << ',';
        std::cout << quote(trace[i]);
    }
    std::cout << "],\"observations\":{";
    bool first = true;
    for (const auto& item : observations) {
        if (!first) std::cout << ',';
        first = false;
        std::cout << quote(item.first) << ':' << quote(item.second);
    }
    std::cout << "}}\n";
}
}  // namespace coverage

#ifndef TOPIC_COVERAGE_HELPERS_ONLY
void run_topic(const std::string& group);
int main(int argc, char** argv) {
    if (argc != 2) return 2;
    const std::string group(argv[1]);
    try {
        run_topic(group);
        coverage::require(coverage::checks > 0, "probe executed assertions");
        coverage::emit(group, "pass");
        return 0;
    } catch (const coverage::Failure& failure) {
        coverage::emit(group, "fail", failure);
    } catch (const std::exception& error) {
        coverage::emit(group, "fail", {"unexpected exception", "normal completion", error.what()});
    } catch (...) {
        coverage::emit(group, "fail", {"unexpected exception", "normal completion", "nonstandard exception"});
    }
    return 1;
}

#endif  // TOPIC_COVERAGE_HELPERS_ONLY
