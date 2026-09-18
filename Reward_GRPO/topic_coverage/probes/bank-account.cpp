#include "bank_account.h"
#include "coverage.hpp"
#include <array>
#include <atomic>
#include <thread>
#include <cstring>
#include <new>

namespace {
struct Model { bool open = false; int balance = 0; };
using Bank = Bankaccount::Bankaccount;
void operation(Bank& candidate, Model& model, unsigned kind, int amount) {
    const std::array<std::string, 5> names{"open", "close", "deposit", "withdraw", "balance"};
    coverage::record(names.at(kind) + "(" + coverage::show(amount) + ")");
    const bool invalid = kind == 0 ? model.open : !model.open ||
        ((kind == 2 || kind == 3) && amount < 0) || (kind == 3 && amount > model.balance);
    const auto call = [&]() {
        if (kind == 0) candidate.open();
        else if (kind == 1) candidate.close();
        else if (kind == 2) candidate.deposit(amount);
        else if (kind == 3) candidate.withdraw(amount);
        else coverage::equal(candidate.balance(), model.balance, "balance observation");
    };
    if (invalid) coverage::rejects<std::runtime_error>(call, "invalid operation rejected");
    else {
        call();
        if (kind == 0) { model.open = true; model.balance = 0; }
        else if (kind == 1) model.open = false;
        else if (kind == 2) model.balance += amount;
        else if (kind == 3) model.balance -= amount;
    }
    if (model.open) coverage::equal(candidate.balance(), model.balance, "post-operation balance");
    else coverage::rejects<std::runtime_error>([&]() { static_cast<void>(candidate.balance()); }, "closed balance rejected");
}
}
void run_topic(const std::string& group) {
    if (group == "initial_state") {
        // Default construction must initialize its own state, independent of
        // allocator contents. No member names or implementation layout assumed.
        for (int pattern : {0x01, 0x55, 0x7f}) for (bool value_init : {false, true}) {
            alignas(Bank) unsigned char storage[sizeof(Bank)];
            std::memset(storage, pattern, sizeof(storage));
            coverage::context = "storage_pattern=" + coverage::show(pattern)
                + " value_init=" + coverage::show(value_init);
            Bank* candidate = value_init ? ::new (static_cast<void*>(storage)) Bank()
                                         : ::new (static_cast<void*>(storage)) Bank;
            try {
                coverage::rejects<std::runtime_error>([&]() { candidate->balance(); },
                                                      "new account starts closed");
                candidate->open();
                coverage::equal(candidate->balance(), 0, "first open starts at zero");
                candidate->close();
            } catch (...) { candidate->~Bank(); throw; }
            candidate->~Bank();
        }
    } else if (group == "lifecycle") {
        Bank candidate; Model model;
        for (int repeat = 0; repeat < 16; ++repeat) {
            operation(candidate, model, 0, 1);
            operation(candidate, model, 2, 37);
            operation(candidate, model, 1, 1);
        }
    } else if (group == "valid_transactions") {
        Bank candidate; Model model;
        operation(candidate, model, 0, 1);
        for (int amount : {1, 7, 100, 4096, 19}) {
            operation(candidate, model, 2, amount);
            operation(candidate, model, 3, amount);
            operation(candidate, model, 4, 1);
        }
    } else if (group == "rejected_state") {
        Bank candidate; Model model;
        operation(candidate, model, 0, 1);
        operation(candidate, model, 2, 73);
        for (int repeat = 0; repeat < 16; ++repeat) {
            // Each rejected action is immediately followed by a balance/state check.
            operation(candidate, model, 0, 1);
            operation(candidate, model, 2, -17);
            operation(candidate, model, 3, -11);
            operation(candidate, model, 3, model.balance + 1);
            operation(candidate, model, 2, 5);
            operation(candidate, model, 3, 5);
        }
        operation(candidate, model, 1, 1);
        for (unsigned kind : {1u, 2u, 3u, 4u}) operation(candidate, model, kind, 1);
        // Reopening/reset belongs to lifecycle, not rejected-state preservation.
    } else if (group == "transaction_sequences") {
        Bank candidate; Model model;
        operation(candidate, model, 0, 1);
        operation(candidate, model, 2, 100); operation(candidate, model, 3, 100);
        coverage::Generator generator{0x42414e4bu};
        for (unsigned step = 0; step < 1500; ++step) {
            coverage::context = "seed=0x42414e4b step=" + coverage::show(step);
            // Arithmetic sequences stay open and use valid positive amounts.
            const bool withdraw = model.balance > 0 && generator.pick(2) == 0;
            const unsigned kind = withdraw ? 3u : 2u;
            const int amount = 1 + static_cast<int>(generator.pick(
                withdraw ? static_cast<unsigned>(model.balance) : 200u));
            operation(candidate, model, kind, amount);
            if (step % 19 == 0) operation(candidate, model, 4, 1);
        }
    } else if (group == "account_isolation") {
        Bank first, second;
        first.open(); first.deposit(19);
        const int before_open = first.balance();
        second.open();
        coverage::equal(first.balance(), before_open, "opening second preserves first");
        for (int repeat = 0; repeat < 32; ++repeat) {
            const int before_second = second.balance();
            first.deposit(7);
            coverage::equal(second.balance(), before_second, "first transaction preserves second");
            const int before_first = first.balance();
            second.deposit(3);
            coverage::equal(first.balance(), before_first, "second transaction preserves first");
        }
        const int before_close = second.balance();
        first.close();
        coverage::equal(second.balance(), before_close, "closing first preserves second");
        second.deposit(5);
        coverage::rejects<std::runtime_error>([&]() { first.balance(); }, "first remains closed");
        const int before_reopen = second.balance();
        first.open();
        coverage::equal(second.balance(), before_reopen, "reopening first preserves second");
    } else if (group == "concurrent_transactions") {
        // Diagnostic only: scheduling-independent totals do not prove race freedom.
        for (int repeat = 0; repeat < 4; ++repeat) {
            Bank candidate; candidate.open(); candidate.deposit(16000);
            std::atomic<bool> start{false}, unexpected_exception{false};
            std::vector<std::thread> threads;
            for (int worker = 0; worker < 8; ++worker) threads.emplace_back([&]() {
                while (!start.load(std::memory_order_acquire)) std::this_thread::yield();
                try {
                    for (int i = 0; i < 500; ++i) { candidate.deposit(3); candidate.withdraw(2); }
                } catch (...) { unexpected_exception.store(true); }
            });
            start.store(true, std::memory_order_release);
            for (auto& thread : threads) thread.join();
            coverage::equal(unexpected_exception.load(), false, "parallel operations succeed");
            coverage::equal(candidate.balance(), 20000, "no lost parallel updates");
        }
    } else throw std::invalid_argument("unknown coverage group");
}
