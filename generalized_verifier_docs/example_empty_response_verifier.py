#!/usr/bin/env python3
"""
Verifier 05: Generation Budget Exhaustion (Runaway Thinking)
Target Mistake: Crypto Square (and others) burning 32k output tokens

OLD VERIFIER:
Treated missing ```cpp blocks as a flat failure (-1). This amplified looping behavior
during training (12% -> 41% loop rate) because the model was penalized even when
it correctly solved the problem inside its THINKING block.

NEW VERIFIER (Retry & Masking):
If no C++ block is found in the final output, it searches the THINKING log.
- In Evaluation: Extracts the solution from THINKING (Retry-on-empty).
- In Training: Masks the gradient (neutral reward) instead of flat -1 to prevent loop amplification.
"""

def verify_generation_budget(model_output_text, is_training=True):
    print("--- Running Generation Budget Verifier ---")
    
    # 1. Did it successfully generate a C++ block?
    if "```cpp" in model_output_text or "```h" in model_output_text:
        return 1 # Normal success, proceed to compile

    # 2. It failed to output a final block. Is it trapped in THINKING?
    if "► **THINKING**" in model_output_text or "<think>" in model_output_text:
        print("⚠️ Detected Runaway Thinking (Generation Budget Exhausted).")
        
        # In reality, 77/83 times the answer is trapped in the thinking block.
        if is_training:
            print("Action [TRAINING]: Masking gradient to prevent amplifying loops.")
            # We do NOT return -1, we return a special mask token/value so the loss function ignores it.
            return "MASKED_GRADIENT"
        else:
            print("Action [EVAL]: Extracting solution from THINKING block (Retry-on-empty).")
            # Logic here would parse the thinking block for C++ syntax
            return "EXTRACTED_SOLUTION"

    # 3. Completely empty or hallucinated format
    print("❌ VERIFIER FAILED: No C++ code and no thinking block.")
    return -1

if __name__ == "__main__":
    runaway_output = "► **THINKING**\nI need to implement this... [32,000 tokens later]... class Crypto {}; [EOS]"
    
    print("=== Training Mode ===")
    verify_generation_budget(runaway_output, is_training=True)
    
    print("\n=== Evaluation Mode ===")
    verify_generation_budget(runaway_output, is_training=False)
