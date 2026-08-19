# Policy 03 verifier for the exact pinned Sublist public API.
import sys
sys.dont_write_bytecode = True
from _sublist_common import Context, KernelResult, run_kernel, run_policy

def verify_3a_namespace_enum_type(ctx: Context) -> KernelResult: return run_kernel(ctx, "3a")
def verify_3b_lowercase_enumerators(ctx: Context) -> KernelResult: return run_kernel(ctx, "3b")
def verify_3c_exact_non_template_signature(ctx: Context) -> KernelResult: return run_kernel(ctx, "3c")
def verify_3d_braced_call_compatibility(ctx: Context) -> KernelResult: return run_kernel(ctx, "3d")
def verify_3e_enum_distinctness_and_smoke(ctx: Context) -> KernelResult: return run_kernel(ctx, "3e")

if __name__ == "__main__":
    raise SystemExit(run_policy(3, [verify_3a_namespace_enum_type, verify_3b_lowercase_enumerators, verify_3c_exact_non_template_signature, verify_3d_braced_call_compatibility, verify_3e_enum_distinctness_and_smoke], __file__))
