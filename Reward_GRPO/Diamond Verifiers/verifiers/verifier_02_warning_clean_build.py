# Policy 2 verifier: isolate Diamond warning-family deltas and the complete strict warning-as-error build.
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
POLICY_ID = "02"
PINNED = {
    "diamond_test.cpp": "235fc2baac052df9b1efd981d93924b37a738dc85e5b056547a78eeb8840da3f",
    "test/catch.hpp": "681e7505a50887c9085539e5135794fc8f66d8e5de28eadf13a30978627b0f47",
    "test/tests-main.cpp": "5847fda35c1320d94f8d088aaf34229d689f66f1da235f885cbb28c8f17e4260",
}
API_PROBE = r'''#include "diamond.h"
#include <string>
#include <vector>
int main() {
    auto fn = static_cast<std::vector<std::string> (*)(char)>(&diamond::rows);
    return fn('A') == std::vector<std::string>{"A"} ? 0 : 1;
}
'''


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


def parse_json_diagnostics(path: Path) -> tuple[set[str], bool]:
    text = path.read_text(errors="replace").strip()
    if not text:
        return set(), True
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return set(), False
    items = payload if isinstance(payload, list) else [payload]
    warnings = set()
    for item in items:
        if isinstance(item, dict) and item.get("kind") == "warning":
            warnings.add(f"{item.get('option', '')}:{item.get('message', '')}")
    return warnings, True


def diagnostic_compile(ctx: Context, kernel_id: str, label: str, flags: list[str]) -> tuple[dict[str, Any], set[str]]:
    command = [ctx.compiler, "-std=c++17", "-fdiagnostics-format=json", *flags, "-I", str(ctx.exercise), "-fsyntax-only", str(ctx.exercise / "diamond.cpp")]
    record = run(ctx, kernel_id, label, command)
    warnings, valid_json = parse_json_diagnostics(ctx.output / f"{kernel_id}_{label}.stderr")
    if not valid_json:
        raise InvalidEvidence("GCC JSON diagnostics were not parseable")
    return record, warnings


def verify_delta(ctx: Context, kernel_id: str, function: str, lower: list[str], upper: list[str]) -> dict[str, Any]:
    low_record, low_warnings = diagnostic_compile(ctx, kernel_id, "lower", lower)
    high_record, high_warnings = diagnostic_compile(ctx, kernel_id, "upper", upper)
    delta = sorted(high_warnings - low_warnings)
    passed = low_record["returncode"] == 0 and high_record["returncode"] == 0 and not low_record["timed_out"] and not high_record["timed_out"] and not delta
    return result(kernel_id, function, passed, "no new warning" if passed else "warning tier introduced diagnostics or candidate failed to compile", {"lower_warnings": sorted(low_warnings), "upper_warnings": sorted(high_warnings), "delta": delta, "lower_returncode": low_record["returncode"], "upper_returncode": high_record["returncode"]})


def verify_2a_wall(ctx: Context) -> dict[str, Any]:
    return verify_delta(ctx, "2A", "verify_2a_wall", [], ["-Wall"])


def verify_2b_wextra(ctx: Context) -> dict[str, Any]:
    return verify_delta(ctx, "2B", "verify_2b_wextra", ["-Wall"], ["-Wall", "-Wextra"])


def verify_2c_wpedantic(ctx: Context) -> dict[str, Any]:
    return verify_delta(ctx, "2C", "verify_2c_wpedantic", ["-Wall", "-Wextra"], ["-Wall", "-Wextra", "-Wpedantic"])


def verify_2d_complete_werror_build(ctx: Context) -> dict[str, Any]:
    strict = ["-std=c++17", "-Wall", "-Wextra", "-Wpedantic", "-Werror"]
    api_probe = ctx.output / "api_probe.cpp"
    api_probe.write_text(API_PROBE)
    api_obj = ctx.output / "api_probe.o"
    api = run(ctx, "2D", "api_compile", [ctx.compiler, *strict, "-I", str(ctx.exercise), "-c", str(api_probe), "-o", str(api_obj)])
    executable = ctx.output / "diamond"
    official = run(ctx, "2D", "complete_build", [ctx.compiler, *strict, "-DEXERCISM_RUN_ALL_TESTS", "-I", str(ctx.exercise), str(ctx.exercise / "diamond.cpp"), str(ctx.exercise / "diamond_test.cpp"), str(ctx.exercise / "test/tests-main.cpp"), "-o", str(executable)])
    passed = api["returncode"] == 0 and official["returncode"] == 0 and not api["timed_out"] and not official["timed_out"] and api_obj.is_file() and executable.is_file()
    return result("2D", "verify_2d_complete_werror_build", passed, "complete warning-as-error build passed" if passed else "complete strict build failed", {"api_returncode": api["returncode"], "official_returncode": official["returncode"], "api_object_sha256": sha256(api_obj) if api_obj.is_file() else None, "executable_sha256": sha256(executable) if executable.is_file() else None})


def preflight(ctx: Context, expected_source: str | None) -> dict[str, Any]:
    if ctx.exercise.name != TASK_ID or not ctx.exercise.is_dir():
        raise InvalidEvidence("exercise directory must be named diamond")
    for name in ("diamond.cpp", "diamond.h", *PINNED):
        path = ctx.exercise / name
        if path.is_symlink() or not path.is_file():
            raise InvalidEvidence(f"missing or unsafe required file: {name}")
    fixed = {name: sha256(ctx.exercise / name) for name in PINNED}
    if fixed != PINNED:
        raise InvalidEvidence("pinned test dependency hash mismatch")
    ctx.source_before = manifest(ctx.exercise)
    combined = hashlib.sha256(json.dumps(ctx.source_before, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if expected_source and expected_source != combined:
        raise InvalidEvidence("candidate source digest mismatch")
    version = run(ctx, "preflight", "gcc_version", [ctx.compiler, "--version"])
    version_text = (ctx.output / "preflight_gcc_version.stdout").read_text(errors="replace")
    if version["returncode"] != 0 or "13.3" not in version_text:
        raise InvalidEvidence("GNU GCC 13.3 unavailable")
    probe = ctx.output / "json_probe.cpp"
    probe.write_text("int main() { return 0; }\n")
    probe_record = run(ctx, "preflight", "json_diagnostics", [ctx.compiler, "-std=c++17", "-fdiagnostics-format=json", "-fsyntax-only", str(probe)])
    _, valid = parse_json_diagnostics(ctx.output / "preflight_json_diagnostics.stderr")
    if probe_record["returncode"] != 0 or not valid:
        raise InvalidEvidence("GCC JSON diagnostic preflight failed")
    return {"candidate_files": ctx.source_before, "candidate_combined_sha256": combined, "fixed_assets": fixed, "gcc": version_text.splitlines()[0]}


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
    receipt: dict[str, Any] = {"schema_version": 1, "task_id": TASK_ID, "contract_variant": "pristine-original-v1", "policy_id": POLICY_ID, "policy_name": "warning_clean_build", "verifier_source_sha256": sha256(Path(__file__))}
    started = time.time()
    try:
        if compiler is None:
            raise InvalidEvidence("GCC is unavailable")
        receipt["preflight"] = preflight(ctx, args.expected_source_sha256)
        kernels = [verify_2a_wall(ctx), verify_2b_wextra(ctx), verify_2c_wpedantic(ctx), verify_2d_complete_werror_build(ctx)]
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
