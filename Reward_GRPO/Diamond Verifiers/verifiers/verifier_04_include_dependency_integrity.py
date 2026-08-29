
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


TASK_ID = "diamond"
POLICY_ID = "04"
PINNED = {
    ".docs/instructions.md": "ff20bbc2d91cf1ffb8b35ffbe4715867a8e0fdec29a83bf8d9ef8a18da2d9d68",
    ".meta/config.json": "ab687c7bd48e4c78c4ebc23650a79d7a876c0562ca8163875ea99cb143fe6b5c",
    ".meta/tests.toml": "2b9c8ee60ab2b86ac7ba50cee1f39727d4a8fab13e1a5f794452670562c9ed8c",
    "CMakeLists.txt": "53d531120e650972adf19a2a42aa2d5bc716c93700ffac74c1c2868fdce633ff",
    "diamond_test.cpp": "235fc2baac052df9b1efd981d93924b37a738dc85e5b056547a78eeb8840da3f",
    "test/catch.hpp": "681e7505a50887c9085539e5135794fc8f66d8e5de28eadf13a30978627b0f47",
    "test/tests-main.cpp": "5847fda35c1320d94f8d088aaf34229d689f66f1da235f885cbb28c8f17e4260",
}
STRICT = ["-std=c++17", "-Wall", "-Wextra", "-Wpedantic", "-Werror"]


class InvalidEvidence(RuntimeError):
    pass


@dataclass
class Context:
    exercise: Path
    output: Path
    compiler: str
    timeout: int
    commands: list[dict[str, Any]] = field(default_factory=list)
    source_before: dict[str, str] = field(default_factory=dict)
    fixed: dict[str, str] = field(default_factory=dict)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest(exercise: Path) -> dict[str, str]:
    return {name: sha256(exercise / name) for name in ("diamond.cpp", "diamond.h")}


def run(ctx: Context, kernel_id: str, label: str, args: list[str]) -> dict[str, Any]:
    try:
        completed = subprocess.run(args, capture_output=True, timeout=ctx.timeout, check=False)
        returncode, timed_out, stdout, stderr = completed.returncode, False, completed.stdout, completed.stderr
    except subprocess.TimeoutExpired as exc:
        returncode, timed_out, stdout, stderr = None, True, exc.stdout or b"", exc.stderr or b""
    except OSError as exc:
        raise InvalidEvidence(f"could not start compiler: {exc}") from exc
    stdout_path = ctx.output / f"{kernel_id}_{label}.stdout"
    stderr_path = ctx.output / f"{kernel_id}_{label}.stderr"
    stdout_path.write_bytes(stdout)
    stderr_path.write_bytes(stderr)
    record = {"kernel": kernel_id, "label": label, "args": args, "returncode": returncode, "timed_out": timed_out, "stdout_sha256": sha256(stdout_path), "stderr_sha256": sha256(stderr_path)}
    ctx.commands.append(record)
    return record


def result(kernel_id: str, function: str, passed: bool, summary: str, facts: dict[str, Any]) -> dict[str, Any]:
    return {"kernel_id": kernel_id, "verifier_function": function, "status": "pass" if passed else "fail", "score": 1 if passed else -1, "applicable": True, "summary": summary, "facts": facts}


def includes(text: str) -> set[str]:
    return set(re.findall(r"^\s*#\s*include\s*<([^>]+)>", text, re.MULTILINE))


def verify_4a_direct_include_ownership(ctx: Context) -> dict[str, Any]:
    header = (ctx.exercise / "diamond.h").read_text(errors="replace")
    present = includes(header)
    required = set()
    if "std::string" in header:
        required.add("string")
    if "std::vector" in header:
        required.add("vector")
    missing = sorted(required - present)
    passed = not missing
    return result("4A", "verify_4a_direct_include_ownership", passed, "all standard symbols have direct owning includes" if passed else "candidate header relies on transitive includes", {"required": sorted(required), "present": sorted(present), "missing": missing})


def verify_4b_header_self_contained(ctx: Context) -> dict[str, Any]:
    probe = ctx.output / "header_probe.cpp"
    probe.write_text('#include "diamond.h"\nint main() { return 0; }\n')
    obj = ctx.output / "header_probe.o"
    record = run(ctx, "4B", "header_compile", [ctx.compiler, *STRICT, "-I", str(ctx.exercise), "-c", str(probe), "-o", str(obj)])
    passed = record["returncode"] == 0 and not record["timed_out"] and obj.is_file() and obj.stat().st_size > 0
    return result("4B", "verify_4b_header_self_contained", passed, "header compiled independently" if passed else "header is not self-contained", {"returncode": record["returncode"], "timed_out": record["timed_out"], "object_sha256": sha256(obj) if passed else None})


def dependency_paths(path: Path) -> list[str]:
    text = path.read_text(errors="replace").replace("\\\n", " ")
    payload = text.split(":", 1)[1] if ":" in text else ""
    return shlex.split(payload)


def verify_4c_dependency_graph(ctx: Context) -> dict[str, Any]:
    probe = ctx.output / "dependency_probe.cpp"
    probe.write_text('#include "diamond.h"\nint main() { return 0; }\n')
    units = [("header", probe), ("implementation", ctx.exercise / "diamond.cpp")]
    dependencies: dict[str, list[str]] = {}
    forbidden: list[str] = []
    compile_ok = True
    for label, source in units:
        dep = ctx.output / f"{label}.d"
        obj = ctx.output / f"{label}.o"
        record = run(ctx, "4C", label, [ctx.compiler, *STRICT, "-I", str(ctx.exercise), "-MMD", "-MF", str(dep), "-c", str(source), "-o", str(obj)])
        if record["returncode"] != 0 or record["timed_out"] or not dep.is_file():
            compile_ok = False
            dependencies[label] = []
            continue
        dependencies[label] = dependency_paths(dep)
        for raw in dependencies[label]:
            candidate = Path(raw)
            resolved = candidate.resolve() if candidate.is_absolute() else (Path.cwd() / candidate).resolve()
            try:
                relative = resolved.relative_to(ctx.exercise)
            except ValueError:
                continue
            if relative.as_posix() not in {"diamond.cpp", "diamond.h"}:
                forbidden.append(relative.as_posix())
    passed = compile_ok and not forbidden
    return result("4C", "verify_4c_dependency_graph", passed, "candidate dependency graph is isolated" if passed else "candidate compilation failed or used forbidden task dependencies", {"dependencies": dependencies, "forbidden": sorted(set(forbidden)), "compile_ok": compile_ok})


def verify_4d_pinned_dependencies(ctx: Context) -> dict[str, Any]:
    cmake = (ctx.exercise / "CMakeLists.txt").read_text(errors="replace")
    facts = {
        "hashes": ctx.fixed,
        "cxx_standard_17": "CXX_STANDARD 17" in cmake,
        "extensions_off": "CXX_EXTENSIONS OFF" in cmake,
        "strict_flags": all(flag in cmake for flag in ("-Wall", "-Wextra", "-Wpedantic", "-Werror")),
        "derived_target": "get_filename_component(exercise" in cmake,
    }
    passed = all(value for key, value in facts.items() if key != "hashes") and ctx.fixed == PINNED
    return result("4D", "verify_4d_pinned_dependencies", passed, "pinned dependencies and CMake contract match" if passed else "pinned dependency contract mismatch", facts)


def preflight(ctx: Context, expected_source: str | None) -> dict[str, Any]:
    if ctx.exercise.name != TASK_ID or not ctx.exercise.is_dir():
        raise InvalidEvidence("exercise directory must be named diamond")
    for name in ("diamond.cpp", "diamond.h", *PINNED):
        path = ctx.exercise / name
        if path.is_symlink() or not path.is_file():
            raise InvalidEvidence(f"missing or unsafe required file: {name}")
    ctx.fixed = {name: sha256(ctx.exercise / name) for name in PINNED}
    mismatches = {name: {"expected": PINNED[name], "actual": value} for name, value in ctx.fixed.items() if value != PINNED[name]}
    if mismatches:
        raise InvalidEvidence(f"pinned dependency mismatch: {json.dumps(mismatches, sort_keys=True)}")
    ctx.source_before = manifest(ctx.exercise)
    combined = hashlib.sha256(json.dumps(ctx.source_before, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if expected_source and expected_source != combined:
        raise InvalidEvidence("candidate source digest mismatch")
    version = run(ctx, "preflight", "gcc_version", [ctx.compiler, "--version"])
    text = (ctx.output / "preflight_gcc_version.stdout").read_text(errors="replace")
    if version["returncode"] != 0 or "13.3" not in text:
        raise InvalidEvidence("GNU GCC 13.3 unavailable")
    return {"candidate_files": ctx.source_before, "candidate_combined_sha256": combined, "fixed_assets": ctx.fixed, "gcc": text.splitlines()[0]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exercise-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--compiler", default="g++")
    parser.add_argument("--expected-source-sha256")
    parser.add_argument("--compile-timeout-s", type=int, default=120)
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
    ctx = Context(exercise, output, compiler or args.compiler, args.compile_timeout_s)
    receipt: dict[str, Any] = {"schema_version": 1, "task_id": TASK_ID, "contract_variant": "pristine-original-v1", "policy_id": POLICY_ID, "policy_name": "include_dependency_integrity", "verifier_source_sha256": sha256(Path(__file__))}
    started = time.time()
    try:
        if compiler is None:
            raise InvalidEvidence("GCC is unavailable")
        receipt["preflight"] = preflight(ctx, args.expected_source_sha256)
        kernels = [verify_4a_direct_include_ownership(ctx), verify_4b_header_self_contained(ctx), verify_4c_dependency_graph(ctx), verify_4d_pinned_dependencies(ctx)]
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
