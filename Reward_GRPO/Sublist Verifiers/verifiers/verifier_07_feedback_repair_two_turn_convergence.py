# Policy 07 verifier for hash-bound two-turn Sublist repair evidence.
import sys
sys.dont_write_bytecode = True
from _sublist_common import Context, KernelResult, run_kernel, run_policy

def verify_7a_first_response_health(ctx: Context) -> KernelResult: return run_kernel(ctx, "7a")
def verify_7b_exact_feedback_delivery(ctx: Context) -> KernelResult: return run_kernel(ctx, "7b")
def verify_7c_targeted_repair(ctx: Context) -> KernelResult: return run_kernel(ctx, "7c")
def verify_7d_diagnostic_reduction(ctx: Context) -> KernelResult: return run_kernel(ctx, "7d")
def verify_7e_pass_within_two_turns(ctx: Context) -> KernelResult: return run_kernel(ctx, "7e")

if __name__ == "__main__":
    raise SystemExit(run_policy(7, [verify_7a_first_response_health, verify_7b_exact_feedback_delivery, verify_7c_targeted_repair, verify_7d_diagnostic_reduction, verify_7e_pass_within_two_turns], __file__))
