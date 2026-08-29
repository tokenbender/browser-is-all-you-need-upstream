#if !defined(PHONE_NUMBER_H)
#define PHONE_NUMBER_H

#include <string>

namespace phone_number {

class phone_number {
public:
    phone_number(const std::string& text);
    std::string area_code() const;
    std::string number() const;
    explicit operator std::string() const;

private:
    std::string digits_;
};

}  // namespace phone_number

#endif
