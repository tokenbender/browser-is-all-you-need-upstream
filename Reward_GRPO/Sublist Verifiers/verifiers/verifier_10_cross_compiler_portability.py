
import sys
sys.dont_write_bytecode = True
from _sublist_common import Context, KernelResult, run_kernel, run_policy

def verify_10a_clang_warning_clean_compile(ctx: Context) -> KernelResult: return run_kernel(ctx, "10a")
def verify_10b_clang_link_and_official_tests(ctx: Context) -> KernelResult: return run_kernel(ctx, "10b")
def verify_10c_clean_secondary_reproduction(ctx: Context) -> KernelResult: return run_kernel(ctx, "10c")

if __name__ == "__main__":
    raise SystemExit(run_policy(10, [verify_10a_clang_warning_clean_compile, verify_10b_clang_link_and_official_tests, verify_10c_clean_secondary_reproduction], __file__))
