
import sys
sys.dont_write_bytecode = True
from _sublist_common import Context, KernelResult, run_kernel, run_policy

def verify_5a_authenticated_official_suite(ctx: Context) -> KernelResult: return run_kernel(ctx, "5a")
def verify_5b_equality_and_empty_boundaries(ctx: Context) -> KernelResult: return run_kernel(ctx, "5b")
def verify_5c_sublist_positions_and_recovery(ctx: Context) -> KernelResult: return run_kernel(ctx, "5c")
def verify_5d_superlist_positions(ctx: Context) -> KernelResult: return run_kernel(ctx, "5d")
def verify_5e_unequal_order_and_value_cases(ctx: Context) -> KernelResult: return run_kernel(ctx, "5e")
def verify_5f_deterministic_official_repetition(ctx: Context) -> KernelResult: return run_kernel(ctx, "5f")

if __name__ == "__main__":
    raise SystemExit(run_policy(5, [verify_5a_authenticated_official_suite, verify_5b_equality_and_empty_boundaries, verify_5c_sublist_positions_and_recovery, verify_5d_superlist_positions, verify_5e_unequal_order_and_value_cases, verify_5f_deterministic_official_repetition], __file__))
