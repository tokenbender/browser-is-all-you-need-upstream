#include "phone_number.h"

#include <iostream>
#include <stdexcept>
#include <string>

namespace {

std::string observe(const std::string& request) {
    const std::size_t separator = request.find('\t');
    if (separator == std::string::npos) {
        return "PROTOCOL_ERROR";
    }
    const std::string operation = request.substr(0, separator);
    const std::string input = request.substr(separator + 1);
    try {
        const phone_number::phone_number value(input);
        if (operation == "construct") {
            return "OK";
        }
        if (operation == "number") {
            return "OK:" + value.number();
        }
        if (operation == "observe") {
            return "OK:" + value.number() + "|" + value.area_code() + "|"
                + static_cast<std::string>(value);
        }
        return "PROTOCOL_ERROR";
    } catch (const std::domain_error&) {
        return "DOMAIN_ERROR";
    } catch (...) {
        return "OTHER_ERROR";
    }
}

}  // namespace

int main(int argc, char** argv) {
    for (int index = 1; index < argc; ++index) {
        std::cout << (index - 1) << '\t' << observe(argv[index]) << '\n';
    }
    return 0;
}
