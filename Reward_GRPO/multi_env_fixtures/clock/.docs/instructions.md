# Instructions

Implement a clock that handles times without dates.

You should be able to add and subtract minutes to it.

Two clocks that represent the same time should be equal to each other.


## C++ interface contract

The test file is not shown to you, so the interface it expects is stated here in
full. Implement exactly these names and signatures; the tests use nothing else.

```cpp
namespace date_independent {
class clock {
public:
    static clock at(int hour, int minute = 0);
    clock& plus(int minutes);
    clock& minus(int minutes);
    operator std::string() const;
    bool operator==(const clock& rhs) const;
};
bool operator!=(const clock& lhs, const clock& rhs);
}
```

Note the namespace is `date_independent`, not `clock`.

The conversion to `std::string` must be implicit (the tests write `string(clock::at(8, 0))`) and must produce zero-padded `HH:MM`, e.g. `"08:00"`. Hours and minutes wrap in both directions, including negative values and multiples of a day.

## Build environment

- The exercise is compiled as C++17 with `-Wall -Wextra -Wpedantic -Werror`, so
  any warning fails the build.
- Only `clock.h` and `clock.cpp` are editable. `CMakeLists.txt` and the test
  file are fixed and must not be modified.
- The test file includes only `clock.h`, so every name above must be visible
  from that header.
- You may either declare in `clock.h` and define in `clock.cpp`, or define
  everything `inline`/in-class in `clock.h` and leave `clock.cpp` unchanged.
  Both are accepted.
