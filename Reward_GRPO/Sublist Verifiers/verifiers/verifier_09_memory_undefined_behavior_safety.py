# Policy 09 verifier for Sublist memory and undefined-behavior safety.
import sys
sys.dont_write_bytecode = True
from _sublist_common import Context, KernelResult, run_kernel, run_policy

def verify_9a_address_sanitizer(ctx: Context) -> KernelResult: return run_kernel(ctx, "9a")
def verify_9b_undefined_behavior_sanitizer(ctx: Context) -> KernelResult: return run_kernel(ctx, "9b")
def verify_9c_repeated_sanitized_stress(ctx: Context) -> KernelResult: return run_kernel(ctx, "9c")

if __name__ == "__main__":
    raise SystemExit(run_policy(9, [verify_9a_address_sanitizer, verify_9b_undefined_behavior_sanitizer, verify_9c_repeated_sanitized_stress], __file__))
