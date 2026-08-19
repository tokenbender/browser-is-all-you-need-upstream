# Policy 01 verifier for Sublist build stages and link completion.
import sys
sys.dont_write_bytecode = True
from _sublist_common import Context, KernelResult, run_kernel, run_policy

def verify_1a_primary_toolchain_and_fixture(ctx: Context) -> KernelResult: return run_kernel(ctx, "1a")
def verify_1b_candidate_translation_unit(ctx: Context) -> KernelResult: return run_kernel(ctx, "1b")
def verify_1c_official_and_external_callers(ctx: Context) -> KernelResult: return run_kernel(ctx, "1c")
def verify_1d_link_completion(ctx: Context) -> KernelResult: return run_kernel(ctx, "1d")
def verify_1e_clean_cmake_build(ctx: Context) -> KernelResult: return run_kernel(ctx, "1e")

if __name__ == "__main__":
    raise SystemExit(run_policy(1, [verify_1a_primary_toolchain_and_fixture, verify_1b_candidate_translation_unit, verify_1c_official_and_external_callers, verify_1d_link_completion, verify_1e_clean_cmake_build], __file__))
