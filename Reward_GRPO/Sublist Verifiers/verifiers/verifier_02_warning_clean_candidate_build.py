# Policy 02 verifier for Sublist warning-clean compilation.
import sys
sys.dont_write_bytecode = True
from _sublist_common import Context, KernelResult, run_kernel, run_policy

def verify_2a_wall(ctx: Context) -> KernelResult: return run_kernel(ctx, "2a")
def verify_2b_wextra(ctx: Context) -> KernelResult: return run_kernel(ctx, "2b")
def verify_2c_wpedantic(ctx: Context) -> KernelResult: return run_kernel(ctx, "2c")
def verify_2d_complete_werror_build(ctx: Context) -> KernelResult: return run_kernel(ctx, "2d")

if __name__ == "__main__":
    raise SystemExit(run_policy(2, [verify_2a_wall, verify_2b_wextra, verify_2c_wpedantic, verify_2d_complete_werror_build], __file__))
