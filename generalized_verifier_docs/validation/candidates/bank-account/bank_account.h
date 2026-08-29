#if !defined(BANK_ACCOUNT_H)
#define BANK_ACCOUNT_H

#include <mutex>

namespace Bankaccount {

class Bankaccount {
public:
    void open();
    void deposit(int amount);
    void withdraw(int amount);
    void close();
    int balance();

private:
    int balance_;
    bool open_;
    std::mutex mutex_;

    // Private constructor to ensure proper initialization
    Bankaccount();
};

}  // namespace Bankaccount

#endif  // BANK_ACCOUNT_H
