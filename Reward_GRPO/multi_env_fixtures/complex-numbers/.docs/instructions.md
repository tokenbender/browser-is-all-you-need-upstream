# Instructions

A complex number is a number in the form `a + b * i` where `a` and `b` are real and `i` satisfies `i^2 = -1`.

`a` is called the real part and `b` is called the imaginary part of `z`.
The conjugate of the number `a + b * i` is the number `a - b * i`.
The absolute value of a complex number `z = a + b * i` is a real number `|z| = sqrt(a^2 + b^2)`. The square of the absolute value `|z|^2` is the result of multiplication of `z` by its complex conjugate.

The sum/difference of two complex numbers involves adding/subtracting their real and imaginary parts separately:
`(a + i * b) + (c + i * d) = (a + c) + (b + d) * i`,
`(a + i * b) - (c + i * d) = (a - c) + (b - d) * i`.

Multiplication result is by definition
`(a + i * b) * (c + i * d) = (a * c - b * d) + (b * c + a * d) * i`.

The reciprocal of a non-zero complex number is
`1 / (a + i * b) = a/(a^2 + b^2) - b/(a^2 + b^2) * i`.

Dividing a complex number `a + i * b` by another `c + i * d` gives:
`(a + i * b) / (c + i * d) = (a * c + b * d)/(c^2 + d^2) + (b * c - a * d)/(c^2 + d^2) * i`.

Raising e to a complex exponent can be expressed as `e^(a + i * b) = e^a * e^(i * b)`, the last term of which is given by Euler's formula `e^(i * b) = cos(b) + i * sin(b)`.

Implement the following operations:

- addition, subtraction, multiplication and division of two complex numbers,
- conjugate, absolute value, exponent of a given complex number.

Assume the programming language you are using does not have an implementation of complex numbers.


## C++ interface contract

The test file is not shown to you, so the interface it expects is stated here in
full. Implement exactly these names and signatures; the tests use nothing else.

```cpp
namespace complex_numbers {
class Complex {
public:
    Complex(double real, double imaginary);
    Complex operator+(const Complex& other) const;
    Complex operator-(const Complex& other) const;
    Complex operator*(const Complex& other) const;
    Complex operator/(const Complex& other) const;
    double abs() const;
    Complex conj() const;
    double real() const;
    double imag() const;
    Complex exp() const;
};
bool operator==(const Complex& lhs, const Complex& rhs);
std::ostream& operator<<(std::ostream& os, Complex const& value);
Complex operator+(const Complex& complex, double scalar);
Complex operator+(double scalar, const Complex& complex);
Complex operator-(const Complex& complex, double scalar);
Complex operator-(double scalar, const Complex& complex);
Complex operator*(const Complex& complex, double scalar);
Complex operator*(double scalar, const Complex& complex);
Complex operator/(const Complex& complex, double scalar);
Complex operator/(double scalar, const Complex& complex);
}
```

Both scalar orderings are required for each of the four arithmetic operators. The tests compare with a floating-point tolerance, so exact bit equality is not required.

## Build environment

- The exercise is compiled as C++17 with `-Wall -Wextra -Wpedantic -Werror`, so
  any warning fails the build.
- Only `complex_numbers.h` and `complex_numbers.cpp` are editable. `CMakeLists.txt` and the test
  file are fixed and must not be modified.
- The test file includes only `complex_numbers.h`, so every name above must be visible
  from that header.
- You may either declare in `complex_numbers.h` and define in `complex_numbers.cpp`, or define
  everything `inline`/in-class in `complex_numbers.h` and leave `complex_numbers.cpp` unchanged.
  Both are accepted.
