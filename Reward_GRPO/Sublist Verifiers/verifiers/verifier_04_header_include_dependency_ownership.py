
import sys
sys.dont_write_bytecode = True
from _sublist_common import Context, KernelResult, run_kernel, run_policy

def verify_4a_direct_vector_include_ownership(ctx: Context) -> KernelResult: return run_kernel(ctx, "4a")
def verify_4b_header_self_contained(ctx: Context) -> KernelResult: return run_kernel(ctx, "4b")
def verify_4c_implementation_dependency_graph(ctx: Context) -> KernelResult: return run_kernel(ctx, "4c")
def verify_4d_pinned_fixed_dependencies(ctx: Context) -> KernelResult: return run_kernel(ctx, "4d")
def verify_4e_empty_workspace_rebuild(ctx: Context) -> KernelResult: return run_kernel(ctx, "4e")

if __name__ == "__main__":
    raise SystemExit(run_policy(4, [verify_4a_direct_vector_include_ownership, verify_4b_header_self_contained, verify_4c_implementation_dependency_graph, verify_4d_pinned_fixed_dependencies, verify_4e_empty_workspace_rebuild], __file__))
