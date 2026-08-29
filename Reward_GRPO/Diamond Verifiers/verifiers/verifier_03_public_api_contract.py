
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


TASK_ID = "diamond"
POLICY_ID = "03"
STRICT = ["-std=c++17", "-Wall", "-Wextra", "-Wpedantic", "-Werror"]
PROBES = {
    "3A": r'''#include "diamond.h"
int main() { return 0; }
''',
    "3B": r'''#include "diamond.h"
int main() { const auto value = diamond::rows('A'); return value.empty(); }
''',
    "3C": r'''#include "diamond.h"
#include <string>
#include <vector>
int main() {
    auto fn = static_cast<std::vector<std::string> (*)(char)>(&diamond::rows);
    return fn == nullptr;
}
''',
    "3D": r'''#include "diamond.h"
#include <string>
#include <vector>
int main() {
    const auto value = diamond::rows('A');
    return value == std::vector<std::string>{"A"} ? 0 : 1;
}
''',
}


class InvalidEvidence(RuntimeError):
    pass


@dataclass
class Context:
    exercise: Path
    output: Path
    compiler: str
    compile_timeout: int
    runtime_timeout: int
    commands: list[dict[str, Any]] = field(default_factory=list)
    source_before: dict[str, str] = field(default_factory=dict)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest(exercise: Path) -> dict[str, str]:
    return {name: sha256(exercise / name) for name in ("diamond.cpp", "diamond.h")}


def run(ctx: Context, kernel_id: str, label: str, args: list[str], timeout: int) -> dict[str, Any]:
    try:
        completed = subprocess.run(args, capture_output=True, timeout=timeout, check=False)
        returncode, timed_out, stdout, stderr = completed.returncode, False, completed.stdout, completed.stderr
    except subprocess.TimeoutExpired as exc:
        returncode, timed_out, stdout, stderr = None, True, exc.stdout or b"", exc.stderr or b""
    except OSError as exc:
        raise InvalidEvidence(f"could not start compiler or probe: {exc}") from exc
    stdout_path = ctx.output / f"{kernel_id}_{label}.stdout"
    stderr_path = ctx.output / f"{kernel_id}_{label}.stderr"
    stdout_path.write_bytes(stdout)
    stderr_path.write_bytes(stderr)
    record = {"kernel": kernel_id, "label": label, "args": args, "returncode": returncode, "timed_out": timed_out, "stdout_sha256": sha256(stdout_path), "stderr_sha256": sha256(stderr_path)}
    ctx.commands.append(record)
    return record


def result(kernel_id: str, function: str, passed: bool, summary: str, facts: dict[str, Any]) -> dict[str, Any]:
    return {"kernel_id": kernel_id, "verifier_function": function, "status": "pass" if passed else "fail", "score": 1 if passed else -1, "applicable": True, "summary": summary, "facts": facts}


def compile_probe(ctx: Context, kernel_id: str, function: str, link: bool = False) -> tuple[dict[str, Any], Path | None]:
    source = ctx.output / f"probe_{kernel_id}.cpp"
    source.write_text(PROBES[kernel_id])
    output = ctx.output / (f"probe_{kernel_id}" if link else f"probe_{kernel_id}.o")
    args = [ctx.compiler, *STRICT, "-I", str(ctx.exercise), str(source)]
    if link:
        args.append(str(ctx.exercise / "diamond.cpp"))
    else:
        args.append("-c")
    args.extend(["-o", str(output)])
    record = run(ctx, kernel_id, "build", args, ctx.compile_timeout)
    passed = record["returncode"] == 0 and not record["timed_out"] and output.is_file() and output.stat().st_size > 0
    return result(kernel_id, function, passed, "probe compiled" if passed else "candidate rejected exact API probe", {"returncode": record["returncode"], "timed_out": record["timed_out"], "artifact_sha256": sha256(output) if passed else None}), output if passed else None


def verify_3a_header_self_contained(ctx: Context) -> dict[str, Any]:
    return compile_probe(ctx, "3A", "verify_3a_header_self_contained")[0]


def verify_3b_public_names(ctx: Context) -> dict[str, Any]:
    return compile_probe(ctx, "3B", "verify_3b_public_names")[0]


def verify_3c_exact_signature(ctx: Context) -> dict[str, Any]:
    return compile_probe(ctx, "3C", "verify_3c_exact_signature")[0]


def verify_3d_linked_api_smoke(ctx: Context) -> dict[str, Any]:
    build_result, executable = compile_probe(ctx, "3D", "verify_3d_linked_api_smoke", True)
    if executable is None:
        return build_result
    run_result = run(ctx, "3D", "run", [str(executable)], ctx.runtime_timeout)
    passed = run_result["returncode"] == 0 and not run_result["timed_out"]
    return result("3D", "verify_3d_linked_api_smoke", passed, "linked API smoke passed" if passed else "linked call failed or returned the wrong A result", {"build_returncode": 0, "run_returncode": run_result["returncode"], "timed_out": run_result["timed_out"], "executable_sha256": sha256(executable)})


def preflight(ctx: Context, expected_source: str | None) -> dict[str, Any]:
    if ctx.exercise.name != TASK_ID or not ctx.exercise.is_dir():
        raise InvalidEvidence("exercise directory must be named diamond")
    for name in ("diamond.cpp", "diamond.h"):
        path = ctx.exercise / name
        if path.is_symlink() or not path.is_file():
            raise InvalidEvidence(f"missing or unsafe candidate file: {name}")
    ctx.source_before = manifest(ctx.exercise)
    combined = hashlib.sha256(json.dumps(ctx.source_before, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if expected_source and expected_source != combined:
        raise InvalidEvidence("candidate source digest mismatch")
    version = run(ctx, "preflight", "gcc_version", [ctx.compiler, "--version"], 10)
    text = (ctx.output / "preflight_gcc_version.stdout").read_text(errors="replace")
    if version["returncode"] != 0 or "13.3" not in text:
        raise InvalidEvidence("GNU GCC 13.3 unavailable")
    harmless = ctx.output / "harmless.cpp"
    harmless.write_text("int main() { return 0; }\n")
    harmless_bin = ctx.output / "harmless"
    check = run(ctx, "preflight", "harmless_compile", [ctx.compiler, *STRICT, str(harmless), "-o", str(harmless_bin)], ctx.compile_timeout)
    if check["returncode"] != 0 or not harmless_bin.is_file():
        raise InvalidEvidence("harmless compiler preflight failed")
    return {"candidate_files": ctx.source_before, "candidate_combined_sha256": combined, "gcc": text.splitlines()[0]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exercise-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--compiler", default="g++")
    parser.add_argument("--expected-source-sha256")
    parser.add_argument("--compile-timeout-s", type=int, default=120)
    parser.add_argument("--runtime-timeout-s", type=int, default=10)
    args = parser.parse_args()
    exercise_absolute = args.exercise_dir.absolute()
    output_absolute = args.output_dir.absolute()
    if any(path.is_symlink() for path in (exercise_absolute, *exercise_absolute.parents)):
        print(json.dumps({"overall_status": "INVALID", "reason": "exercise path must not contain symlinks"}))
        return 2
    if args.output_dir.exists() or any(path.is_symlink() for path in (output_absolute, *output_absolute.parents)):
        print(json.dumps({"overall_status": "INVALID", "reason": "output path must be new and contain no symlinks"}))
        return 2
    exercise = args.exercise_dir.resolve()
    output = args.output_dir.resolve()
    if output == exercise or exercise in output.parents:
        print(json.dumps({"overall_status": "INVALID", "reason": "output directory must be outside the candidate tree"}))
        return 2
    args.output_dir.mkdir(parents=True)
    compiler = shutil.which(args.compiler)
    ctx = Context(exercise, output, compiler or args.compiler, args.compile_timeout_s, args.runtime_timeout_s)
    receipt: dict[str, Any] = {"schema_version": 1, "task_id": TASK_ID, "contract_variant": "pristine-original-v1", "policy_id": POLICY_ID, "policy_name": "public_api_contract", "verifier_source_sha256": sha256(Path(__file__))}
    started = time.time()
    try:
        if compiler is None:
            raise InvalidEvidence("GCC is unavailable")
        receipt["preflight"] = preflight(ctx, args.expected_source_sha256)
        kernels = [verify_3a_header_self_contained(ctx), verify_3b_public_names(ctx), verify_3c_exact_signature(ctx), verify_3d_linked_api_smoke(ctx)]
        if manifest(ctx.exercise) != ctx.source_before:
            raise InvalidEvidence("candidate source changed during verification")
        receipt.update({"kernels": kernels, "commands": ctx.commands, "kernel_sum": sum(item["score"] for item in kernels), "applicable_kernel_count": 4, "overall_status": "pass" if all(item["score"] == 1 for item in kernels) else "fail"})
        exit_code = 0 if receipt["overall_status"] == "pass" else 1
    except InvalidEvidence as exc:
        receipt.update({"overall_status": "INVALID", "reason": str(exc), "commands": ctx.commands})
        exit_code = 2
    receipt["started_at"] = started
    if isinstance(receipt.get("kernels"), list):
        applicable = [item for item in receipt["kernels"] if item.get("applicable", True)]
        receipt["passed_kernel_count"] = sum(item.get("score") == 1 for item in applicable)
        receipt["failed_kernel_count"] = sum(item.get("score") == -1 for item in applicable)
    receipt["duration_seconds"] = round(time.time() - started, 6)
    receipt["source_immutable"] = manifest(ctx.exercise) == ctx.source_before if ctx.source_before else None
    (ctx.output / "verification_receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
