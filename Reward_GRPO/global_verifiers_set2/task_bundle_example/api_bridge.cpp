#include "adder.h"

#include <iostream>
#include <stdexcept>
#include <string>

namespace {

std::string observe(const std::string& request) {
    const std::size_t separator = request.find(',');
    if (separator == std::string::npos) return "PROTOCOL_ERROR";
    try {
        const int left = std::stoi(request.substr(0, separator));
        const int right = std::stoi(request.substr(separator + 1));
        return "OK:" + std::to_string(add(left, right));
    } catch (...) {
        return "PROTOCOL_ERROR";
    }
}

}  // namespace

int main(int argc, char** argv) {
    for (int index = 1; index < argc; ++index) {
        std::cout << (index - 1) << '\t' << observe(argv[index]) << '\n';
    }
    return 0;
}
