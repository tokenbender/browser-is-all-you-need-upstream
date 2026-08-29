
import sys
sys.dont_write_bytecode = True
from _sublist_common import Context, KernelResult, run_kernel, run_policy

def verify_8a_pinned_aider_parse(ctx: Context) -> KernelResult: return run_kernel(ctx, "8a")
def verify_8b_authorized_changed_file_scope(ctx: Context) -> KernelResult: return run_kernel(ctx, "8b")
def verify_8c_response_context_counters(ctx: Context) -> KernelResult: return run_kernel(ctx, "8c")
def verify_8d_evaluation_completion(ctx: Context) -> KernelResult: return run_kernel(ctx, "8d")
def verify_8e_hash_bound_receipt_integrity(ctx: Context) -> KernelResult: return run_kernel(ctx, "8e")

if __name__ == "__main__":
    raise SystemExit(run_policy(8, [verify_8a_pinned_aider_parse, verify_8b_authorized_changed_file_scope, verify_8c_response_context_counters, verify_8d_evaluation_completion, verify_8e_hash_bound_receipt_integrity], __file__))
