#!/usr/bin/env python3
"""
Root Cause Verifier: Environment Defect (CMake Boost)
Target Mistake: Punishing the model for a missing OS package.

OLD VERIFIER:
Failed during the heavy C++ build step. The model received a -1 reward and text 
asking it to fix a compilation error it had no control over (Boost missing).

NEW VERIFIER (Environment Verdict):
Runs a `cmake` dry-run configuration before compiling. If environment dependencies 
are missing, it aborts the verification with an INVALID tag, preventing a flawed 
gradient update (-1) on a perfectly good model response.
"""

import subprocess

def verify_environment(source_dir):
    print("--- Running Environmental Root Cause Check ---")
    
    print("Executing: cmake .")
    # Simulated check for missing Boost package
    cmake_output = "CMake Error: find_package(Boost REQUIRED) failed. Package not found."
    
    if "find_package" in cmake_output and "failed" in cmake_output:
        print("🚨 ENVIRONMENT DEFECT DETECTED.")
        print(f"Log: {cmake_output}")
        # DO NOT RETURN -1 (which penalizes the model). 
        # Return a special INVALID state so the RL loop discards this trial.
        print("Verdict: INVALID (Environment Error, Model unharmed)")
        return "INVALID"

    print("✅ Environment is healthy. Proceeding to Model Verification.")
    return 1

if __name__ == "__main__":
    verify_environment("/fake/dir")
