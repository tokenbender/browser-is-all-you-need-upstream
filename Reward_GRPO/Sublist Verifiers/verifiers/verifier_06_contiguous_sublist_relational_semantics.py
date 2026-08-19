# Policy 06 verifier for contiguous Sublist relational semantics.
import sys
sys.dont_write_bytecode = True
from _sublist_common import Context, KernelResult, run_kernel, run_policy

def verify_6a_exhaustive_independent_oracle(ctx: Context) -> KernelResult: return run_kernel(ctx, "6a")
def verify_6b_contiguity_order_and_identity(ctx: Context) -> KernelResult: return run_kernel(ctx, "6b")
def verify_6c_false_start_and_repeated_values(ctx: Context) -> KernelResult: return run_kernel(ctx, "6c")
def verify_6d_swap_relations(ctx: Context) -> KernelResult: return run_kernel(ctx, "6d")
def verify_6e_input_preservation_and_repeatability(ctx: Context) -> KernelResult: return run_kernel(ctx, "6e")

if __name__ == "__main__":
    raise SystemExit(run_policy(6, [verify_6a_exhaustive_independent_oracle, verify_6b_contiguity_order_and_identity, verify_6c_false_start_and_repeated_values, verify_6d_swap_relations, verify_6e_input_preservation_and_repeatability], __file__))
