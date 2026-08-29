#include "bank_account.h"

namespace Bankaccount {

Bankaccount::Bankaccount()
    : balance_(0), open_(false), mutex_() {}

void Bankaccount::open() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (open_) {
        throw std::runtime_error("Account is already open");
    }
    open_ = true;
    balance_ = 0;
}

void Bankaccount::deposit(int amount) {
    if (amount <= 0) {
        throw std::runtime_error("Amount must be positive");
    }
    std::lock_guard<std::mutex> lock(mutex_);
    if (!open_) {
        throw std::runtime_error("Account is not open");
    }
    balance_ += amount;
}

void Bankaccount::withdraw(int amount) {
    if (amount <= 0) {
        throw std::runtime_error("Amount must be positive");
    }
    std::lock_guard<std::mutex> lock(mutex_);
    if (!open_) {
        throw std::runtime_error("Account is not open");
    }
    if (amount > balance_) {
        throw std::runtime_error("Insufficient funds");
    }
    balance_ -= amount;
}

void Bankaccount::close() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!open_) {
        throw std::runtime_error("Account is not open");
    }
    open_ = false;
}

int Bankaccount::balance() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!open_) {
        throw std::runtime_error("Account is not open");
    }
    return balance_;
}

}  // namespace Bankaccount
