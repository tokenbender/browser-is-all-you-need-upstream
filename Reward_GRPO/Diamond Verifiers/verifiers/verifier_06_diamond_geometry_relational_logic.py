# Policy 6 verifier: check six independent exact-output and relational Diamond kernels over A through Z.
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
POLICY_ID = "06"
STRICT = ["-std=c++17", "-Wall", "-Wextra", "-Wpedantic", "-Werror"]
PROBE = r'''#include "diamond.h"
#include <algorithm>
#include <cstddef>
#include <iostream>
#include <string>
#include <vector>

std::vector<std::string> oracle(char letter) {
    const int n = letter - 'A';
    const int side = 2 * n + 1;
    std::vector<std::string> value;
    for (int row = 0; row < side; ++row) {
        const int level = std::min(row, 2 * n - row);
        const int outer = n - level;
        std::string line(static_cast<std::size_t>(side), ' ');
        line.at(static_cast<std::size_t>(outer)) = static_cast<char>('A' + level);
        if (level > 0) {
            line.at(static_cast<std::size_t>(outer + 2 * level)) = static_cast<char>('A' + level);
        }
        value.push_back(line);
    }
    return value;
}

int fail(char letter, std::size_t row, const std::string& message) {
    std::cout << "letter=" << letter << " row=" << row << " failure=" << message << '\n';
    return 1;
}

bool anchors(char letter) {
    return letter == 'A' || letter == 'B' || letter == 'C' || letter == 'D' || letter == 'Z';
}

int main() {
    int checked = 0;
    for (char letter = 'A'; letter <= 'Z'; ++letter) {
        const int n = letter - 'A';
        const std::size_t side = static_cast<std::size_t>(2 * n + 1);
        const auto actual = diamond::rows(letter);
        const auto expected = oracle(letter);
        if (MODE == 1) {
            if (anchors(letter)) {
                ++checked;
                if (actual != expected) return fail(letter, 0, "anchor_bytes");
            }
        } else if (MODE == 2) {
            ++checked;
            if (actual.size() != side) return fail(letter, actual.size(), "row_count");
            for (std::size_t row = 0; row < actual.size(); ++row) {
                if (actual.at(row).size() != side) return fail(letter, row, "row_width");
            }
        } else if (MODE == 3) {
            ++checked;
            if (actual.size() != side) return fail(letter, actual.size(), "row_count");
            for (std::size_t row = 0; row < actual.size(); ++row) {
                if (actual.at(row).size() != side) return fail(letter, row, "row_width");
                const int signed_row = static_cast<int>(row);
                const int level = std::min(signed_row, 2 * n - signed_row);
                const int outer = n - level;
                const char glyph = static_cast<char>('A' + level);
                int glyph_count = 0;
                for (std::size_t column = 0; column < side; ++column) {
                    const bool left = static_cast<int>(column) == outer;
                    const bool right = level > 0 && static_cast<int>(column) == outer + 2 * level;
                    const char expected_byte = left || right ? glyph : ' ';
                    if (actual.at(row).at(column) != expected_byte) return fail(letter, row, "spacing_or_glyph");
                    if (actual.at(row).at(column) != ' ') ++glyph_count;
                }
                if (glyph_count != (level == 0 ? 1 : 2)) return fail(letter, row, "glyph_count");
            }
        } else if (MODE == 4) {
            ++checked;
            if (actual.size() != side) return fail(letter, actual.size(), "row_count");
            for (std::size_t row = 0; row < actual.size(); ++row) {
                const int signed_row = static_cast<int>(row);
                const int level = std::min(signed_row, 2 * n - signed_row);
                const char glyph = static_cast<char>('A' + level);
                for (char byte : actual.at(row)) {
                    if (byte != ' ' && byte != glyph) return fail(letter, row, "letter_order");
                }
                if (actual.at(row).find(glyph) == std::string::npos) return fail(letter, row, "missing_row_glyph");
            }
            if (actual.at(static_cast<std::size_t>(n)).find(letter) == std::string::npos) return fail(letter, static_cast<std::size_t>(n), "missing_center");
        } else if (MODE == 5) {
            ++checked;
            if (actual.size() != side) return fail(letter, actual.size(), "row_count");
            for (std::size_t row = 0; row < actual.size(); ++row) {
                std::string reversed = actual.at(row);
                std::reverse(reversed.begin(), reversed.end());
                if (reversed != actual.at(row)) return fail(letter, row, "horizontal_symmetry");
                if (actual.at(row) != actual.at(actual.size() - 1 - row)) return fail(letter, row, "vertical_symmetry");
            }
        } else if (MODE == 6) {
            ++checked;
            if (actual != expected) {
                const std::size_t limit = std::min(actual.size(), expected.size());
                for (std::size_t row = 0; row < limit; ++row) {
                    if (actual.at(row) != expected.at(row)) return fail(letter, row, "oracle_bytes");
                }
                return fail(letter, limit, "oracle_size");
            }
        } else {
            return 2;
        }
    }
    std::cout << "mode=" << MODE << " checked=" << checked << '\n';
    return 0;
}
'''


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


def verify_mode(ctx: Context, kernel_id: str, function: str, mode: int, expected_checked: int) -> dict[str, Any]:
    source = ctx.output / f"probe_{kernel_id}.cpp"
    source.write_text(PROBE)
    executable = ctx.output / f"probe_{kernel_id}"
    build = run(ctx, kernel_id, "build", [ctx.compiler, *STRICT, f"-DMODE={mode}", "-I", str(ctx.exercise), str(source), str(ctx.exercise / "diamond.cpp"), "-o", str(executable)], ctx.compile_timeout)
    if build["returncode"] != 0 or build["timed_out"] or not executable.is_file():
        return result(kernel_id, function, False, "candidate did not compile with semantic probe", {"build_returncode": build["returncode"], "timed_out": build["timed_out"]})
    execution = run(ctx, kernel_id, "run", [str(executable)], ctx.runtime_timeout)
    text = (ctx.output / f"{kernel_id}_run.stdout").read_text(errors="replace")
    marker = f"mode={mode} checked={expected_checked}"
    passed = execution["returncode"] == 0 and not execution["timed_out"] and marker in text
    return result(kernel_id, function, passed, "semantic relation passed" if passed else "candidate violated semantic relation", {"build_returncode": build["returncode"], "run_returncode": execution["returncode"], "timed_out": execution["timed_out"], "expected_marker": marker, "actual_output": text, "probe_sha256": sha256(source), "executable_sha256": sha256(executable)})


def verify_6a_exact_anchor_outputs(ctx: Context) -> dict[str, Any]:
    return verify_mode(ctx, "6A", "verify_6a_exact_anchor_outputs", 1, 5)


def verify_6b_square_dimensions(ctx: Context) -> dict[str, Any]:
    return verify_mode(ctx, "6B", "verify_6b_square_dimensions", 2, 26)


def verify_6c_spacing_and_glyph_counts(ctx: Context) -> dict[str, Any]:
    return verify_mode(ctx, "6C", "verify_6c_spacing_and_glyph_counts", 3, 26)


def verify_6d_letter_order_and_center(ctx: Context) -> dict[str, Any]:
    return verify_mode(ctx, "6D", "verify_6d_letter_order_and_center", 4, 26)


def verify_6e_horizontal_vertical_symmetry(ctx: Context) -> dict[str, Any]:
    return verify_mode(ctx, "6E", "verify_6e_horizontal_vertical_symmetry", 5, 26)


def verify_6f_full_domain_oracle(ctx: Context) -> dict[str, Any]:
    return verify_mode(ctx, "6F", "verify_6f_full_domain_oracle", 6, 26)


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
    return {"candidate_files": ctx.source_before, "candidate_combined_sha256": combined, "gcc": text.splitlines()[0], "valid_domain": "A-Z"}


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
    receipt: dict[str, Any] = {"schema_version": 1, "task_id": TASK_ID, "contract_variant": "pristine-original-v1", "policy_id": POLICY_ID, "policy_name": "diamond_geometry_relational_logic", "verifier_source_sha256": sha256(Path(__file__)), "excluded_conditions": [{"condition": "invalid_character_inputs", "reason": "outside_pinned_A_to_Z_contract"}]}
    started = time.time()
    try:
        if compiler is None:
            raise InvalidEvidence("GCC is unavailable")
        receipt["preflight"] = preflight(ctx, args.expected_source_sha256)
        kernels = [verify_6a_exact_anchor_outputs(ctx), verify_6b_square_dimensions(ctx), verify_6c_spacing_and_glyph_counts(ctx), verify_6d_letter_order_and_center(ctx), verify_6e_horizontal_vertical_symmetry(ctx), verify_6f_full_domain_oracle(ctx)]
        if manifest(ctx.exercise) != ctx.source_before:
            raise InvalidEvidence("candidate source changed during verification")
        receipt.update({"kernels": kernels, "commands": ctx.commands, "kernel_sum": sum(item["score"] for item in kernels), "applicable_kernel_count": 6, "overall_status": "pass" if all(item["score"] == 1 for item in kernels) else "fail"})
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
