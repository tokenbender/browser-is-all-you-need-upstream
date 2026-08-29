#!/usr/bin/env python3
"""
Verifier 02: State Lifecycle & Boundary Verifier
Target Mistake: State Reset Logic (Bank Account)

OLD VERIFIER:
Used the standard official test suite. If the model didn't reset the balance on close(), 
a downstream test ("test_concurrent_transactions") would fail cryptically, confusing the model.

NEW VERIFIER:
Injects a "Metamorphic Test" specifically targeting the boundary lifecycle before running 
complex concurrency tests. It provides exact, semantic feedback about state transitions.
"""

def verify_lifecycle():
    print("--- Running Lifecycle Boundary Verifier ---")
    
    # In a real environment, this generates a targeted C++ file and compiles it with the candidate.
    metamorphic_test_cpp = """
    #include "bank_account.h"
    #include <cassert>
    #include <iostream>

    int main() {
        Bankaccount::Bankaccount account;
        account.open();
        account.deposit(100);
        account.close();
        
        account.open();
        if (account.balance() != 0) {
            std::cerr << "LIFECYCLE ERROR: Balance was not 0 after reopening." << std::endl;
            return 1;
        }
        return 0;
    }
    """
    
    print("Generated Metamorphic C++ Test:\n", metamorphic_test_cpp)
    print("✅ (Simulated) Execution: If this exits with code 1, return -1 reward with message: 'Account balance must be 0 after close and reopen.'")
    return 1

if __name__ == "__main__":
    verify_lifecycle()
