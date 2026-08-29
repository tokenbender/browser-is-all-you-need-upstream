
from __future__ import annotations

from pathlib import Path
from typing import Any

from strange_cpp import Context
from strange_cpp import KernelReceipt
from strange_cpp import STRICT_FLAGS
from strange_cpp import failed
from strange_cpp import implementation_paths
from strange_cpp import invalid
from strange_cpp import passed
from strange_cpp import run_command
from strange_cpp import sha256
from strange_cpp import source_unchanged
from strange_cpp import write_probe


def compile_and_run(
    ctx: Context,
    kernel_id: str,
    label: str,
    filename: str,
    content: str,
    expected_stdout: str,
) -> KernelReceipt:
    probe = write_probe(ctx, filename, content)
    executable = ctx.output_dir / "artifacts" / Path(filename).stem
    executable.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ctx.compiler,
        *STRICT_FLAGS,
        "-pthread",
        "-I",
        str(ctx.exercise_dir),
        str(probe),
        *implementation_paths(ctx),
        "-o",
        str(executable),
    ]
    compile_receipt = run_command(ctx, kernel_id, f"{label}_compile", command, ctx.compile_timeout_s)
    facts: dict[str, Any] = {
        "probe_sha256": sha256(probe),
        "semantic_group": label,
        "expected_stdout": expected_stdout,
    }
    if not compile_receipt.started:
        return invalid(kernel_id, "compiler process could not start", [compile_receipt], facts)
    if (
        compile_receipt.return_code != 0
        or not executable.is_file()
        or executable.is_symlink()
        or executable.stat().st_size == 0
    ):
        return failed(kernel_id, f"{label} did not compile and link", [compile_receipt], facts)
    run_receipt = run_command(
        ctx,
        kernel_id,
        f"{label}_run",
        [str(executable), label],
        ctx.run_timeout_s,
    )
    commands = [compile_receipt, run_receipt]
    if not run_receipt.started:
        return invalid(kernel_id, "semantic probe could not start", commands, facts)
    observed_stdout = Path(run_receipt.stdout_log).read_text(encoding="utf-8")
    facts["observed_stdout"] = observed_stdout
    if run_receipt.return_code != 0 or observed_stdout != expected_stdout:
        return failed(kernel_id, f"{label} behavior check failed", commands, facts)
    if not source_unchanged(ctx):
        return invalid(kernel_id, "candidate source changed during verification", commands, facts)
    return passed(
        kernel_id,
        f"{label} passed",
        commands,
        facts,
        {"probe": sha256(probe), "executable": sha256(executable)},
    )
