
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


TASK_ID = "perfect-numbers"
POLICY_ID = "PN-E01"
SOURCE_FILES = ("perfect_numbers.h", "perfect_numbers.cpp")
REQUIRED_ASSETS = (
    ".docs/instructions.md",
    ".meta/config.json",
    ".meta/tests.toml",
    ".meta/example.h",
    ".meta/example.cpp",
    "CMakeLists.txt",
    "perfect_numbers.h",
    "perfect_numbers.cpp",
    "perfect_numbers_test.cpp",
    "test/catch.hpp",
    "test/tests-main.cpp",
)
PINNED_HASHES = {
    ".docs/instructions.md": "8db797c5f8e9c0efbb8c805ddefca892f764b4f3a72dff65c037f4bffb92b1cb",
    ".meta/config.json": "5ed306e3c419a01c3f7404c2cfe27ac6793591b913bb64714c455ba28956e0ec",
    ".meta/tests.toml": "8b0d194af6ebbefe95efab1fdb6958d3a88ee12cd50501869373b4b72be202b6",
    ".meta/example.h": "216164fb4b94a80a05b93785d787c92bca08d1712c851ade21c807df9e4469ed",
    ".meta/example.cpp": "068dec0c2dcb773232ec622cddd55951fd6d13421bf77155219f12d058f54262",
    "CMakeLists.txt": "53d531120e650972adf19a2a42aa2d5bc716c93700ffac74c1c2868fdce633ff",
    "perfect_numbers_test.cpp": "fa206f8feaa1f8aa63986db34fc96458b30ab0325c0855fd6659ab7cbcb50be3",
    "test/catch.hpp": "681e7505a50887c9085539e5135794fc8f66d8e5de28eadf13a30978627b0f47",
    "test/tests-main.cpp": "5847fda35c1320d94f8d088aaf34229d689f66f1da235f885cbb28c8f17e4260",
}
STRICT_FLAGS = (
    "-std=c++17",
    "-Wall",
    "-Wextra",
    "-Wpedantic",
    "-Werror",
    "-fno-diagnostics-color",
)
NAMES_PROBE = """#include \"perfect_numbers.h\"
#include <type_traits>

using perfect_numbers::classification;

static_assert(std::is_enum_v<classification>);
static_assert(!std::is_convertible_v<classification, int>);

constexpr classification deficient = classification::deficient;
constexpr classification perfect = classification::perfect;
constexpr classification abundant = classification::abundant;

int main() {
    return deficient == perfect || perfect == abundant;
}
"""
SIGNATURE_PROBE = """#include \"perfect_numbers.h\"
#include <type_traits>

using expected = perfect_numbers::classification (*)(int);
static_assert(std::is_same_v<decltype(&perfect_numbers::classify), expected>);

int main() { return 0; }
"""
LINK_PROBE = """#include \"perfect_numbers.h\"

int main() {
    auto function = &perfect_numbers::classify;
    return function == nullptr;
}
"""


@dataclass(frozen=True)
class CommandReceipt:
    command: list[str]
    cwd: str
    return_code: int
    timed_out: bool
    started: bool
    duration_seconds: float
    stdout_log: str
    stderr_log: str


@dataclass(frozen=True)
class KernelReceipt:
    kernel_id: str
    kernel: int | None
    status: str
    summary: str
    commands: list[CommandReceipt] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Context:
    exercise_dir: Path
    output_dir: Path
    compiler: str
    source_sha256: str
    fixed_hashes: dict[str, str]
    compile_timeout_s: int
    link_timeout_s: int


class PreflightError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _combined_digest(root: Path, relatives: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for relative in relatives:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise PreflightError(f"required regular file is missing or symlinked: {relative}")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _safe_label(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def _run(
    ctx: Context,
    kernel_id: str,
    label: str,
    command: list[str],
    timeout_s: int,
) -> CommandReceipt:
    logs_dir = ctx.output_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{kernel_id.lower()}_{_safe_label(label)}"
    stdout_path = logs_dir / f"{stem}.stdout.log"
    stderr_path = logs_dir / f"{stem}.stderr.log"
    started_at = time.monotonic()
    timed_out = False
    started = True
    try:
        completed = subprocess.run(
            command,
            cwd=ctx.exercise_dir,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env={**os.environ, "LC_ALL": "C", "LANG": "C"},
        )
        return_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as error:
        timed_out = True
        return_code = 124
        stdout_value = error.stdout or ""
        stderr_value = error.stderr or ""
        stdout = stdout_value.decode(errors="replace") if isinstance(stdout_value, bytes) else stdout_value
        stderr = stderr_value.decode(errors="replace") if isinstance(stderr_value, bytes) else stderr_value
        stderr = f"{stderr}\ncommand timed out after {timeout_s} seconds\n"
    except OSError as error:
        started = False
        return_code = 127
        stdout = ""
        stderr = f"{type(error).__name__}: {error}\n"
    duration = time.monotonic() - started_at
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    return CommandReceipt(
        command=command,
        cwd=str(ctx.exercise_dir),
        return_code=return_code,
        timed_out=timed_out,
        started=started,
        duration_seconds=round(duration, 6),
        stdout_log=str(stdout_path),
        stderr_log=str(stderr_path),
    )


def _pass(
    kernel_id: str,
    summary: str,
    commands: list[CommandReceipt],
    facts: dict[str, Any],
    artifacts: dict[str, str],
) -> KernelReceipt:
    return KernelReceipt(kernel_id, 1, "pass", summary, commands, facts, artifacts)


def _fail(
    kernel_id: str,
    summary: str,
    commands: list[CommandReceipt],
    facts: dict[str, Any],
) -> KernelReceipt:
    return KernelReceipt(kernel_id, -1, "fail", summary, commands, facts, {})


def _invalid(
    kernel_id: str,
    summary: str,
    commands: list[CommandReceipt] | None = None,
    facts: dict[str, Any] | None = None,
) -> KernelReceipt:
    return KernelReceipt(kernel_id, None, "invalid", summary, commands or [], facts or {}, {})


def _write_probe(ctx: Context, name: str, content: str) -> Path:
    probes_dir = ctx.output_dir / "probes"
    probes_dir.mkdir(parents=True, exist_ok=True)
    path = probes_dir / name
    path.write_text(content, encoding="utf-8")
    return path


def _source_unchanged(ctx: Context) -> bool:
    try:
        return _combined_digest(ctx.exercise_dir, SOURCE_FILES) == ctx.source_sha256
    except (OSError, PreflightError):
        return False


def _compile_probe(
    ctx: Context,
    kernel_id: str,
    label: str,
    filename: str,
    content: str,
) -> KernelReceipt:
    probe = _write_probe(ctx, filename, content)
    artifact = ctx.output_dir / "artifacts" / f"{Path(filename).stem}.o"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ctx.compiler,
        *STRICT_FLAGS,
        "-I",
        str(ctx.exercise_dir),
        "-c",
        str(probe),
        "-o",
        str(artifact),
    ]
    receipt = _run(ctx, kernel_id, label, command, ctx.compile_timeout_s)
    facts = {"probe_sha256": _sha256(probe)}
    if not receipt.started:
        return _invalid(kernel_id, "compiler process could not start", [receipt], facts)
    if receipt.return_code != 0 or not artifact.is_file() or artifact.is_symlink() or artifact.stat().st_size == 0:
        return _fail(kernel_id, f"{label} did not compile", [receipt], facts)
    if not _source_unchanged(ctx):
        return _invalid(kernel_id, "candidate source changed during verification", [receipt], facts)
    return _pass(
        kernel_id,
        f"{label} compiled",
        [receipt],
        facts,
        {"probe": _sha256(probe), "object": _sha256(artifact)},
    )


def verify_e01_a_names_and_scoping(ctx: Context) -> KernelReceipt:
    return _compile_probe(ctx, "E01-A", "names_and_scoping", "e01_a_names.cpp", NAMES_PROBE)


def verify_e01_b_function_signature(ctx: Context) -> KernelReceipt:
    return _compile_probe(ctx, "E01-B", "function_signature", "e01_b_signature.cpp", SIGNATURE_PROBE)


def verify_e01_c_definition_and_linkage(ctx: Context) -> KernelReceipt:
    probe = _write_probe(ctx, "e01_c_link.cpp", LINK_PROBE)
    executable = ctx.output_dir / "artifacts" / "e01_c_link"
    executable.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ctx.compiler,
        *STRICT_FLAGS,
        "-I",
        str(ctx.exercise_dir),
        str(probe),
        str(ctx.exercise_dir / "perfect_numbers.cpp"),
        "-o",
        str(executable),
    ]
    receipt = _run(ctx, "E01-C", "definition_and_linkage", command, ctx.link_timeout_s)
    facts = {"probe_sha256": _sha256(probe)}
    if not receipt.started:
        return _invalid("E01-C", "compiler process could not start", [receipt], facts)
    if receipt.return_code != 0 or not executable.is_file() or executable.is_symlink() or executable.stat().st_size == 0:
        return _fail("E01-C", "candidate definition did not compile and link", [receipt], facts)
    if not _source_unchanged(ctx):
        return _invalid("E01-C", "candidate source changed during verification", [receipt], facts)
    return _pass(
        "E01-C",
        "candidate definition linked to an external caller",
        [receipt],
        facts,
        {"probe": _sha256(probe), "executable": _sha256(executable)},
    )


def verify_e01_d_official_caller(ctx: Context) -> KernelReceipt:
    artifact = ctx.output_dir / "artifacts" / "perfect_numbers_test.o"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ctx.compiler,
        *STRICT_FLAGS,
        "-DEXERCISM_RUN_ALL_TESTS",
        "-I",
        str(ctx.exercise_dir),
        "-c",
        str(ctx.exercise_dir / "perfect_numbers_test.cpp"),
        "-o",
        str(artifact),
    ]
    receipt = _run(ctx, "E01-D", "official_caller", command, ctx.compile_timeout_s)
    facts = {"official_test_sha256": PINNED_HASHES["perfect_numbers_test.cpp"], "selected_tests": 13}
    if not receipt.started:
        return _invalid("E01-D", "compiler process could not start", [receipt], facts)
    if receipt.return_code != 0 or not artifact.is_file() or artifact.is_symlink() or artifact.stat().st_size == 0:
        return _fail("E01-D", "official caller did not compile against candidate declarations", [receipt], facts)
    if not _source_unchanged(ctx):
        return _invalid("E01-D", "candidate source changed during verification", [receipt], facts)
    return _pass(
        "E01-D",
        "all 13 official callers compiled against the candidate header",
        [receipt],
        facts,
        {"official_test_object": _sha256(artifact)},
    )


def _prepare(args: argparse.Namespace) -> Context:
    exercise_input = args.exercise_dir
    output_input = args.output_dir
    exercise_dir = exercise_input.resolve()
    if output_input.is_symlink():
        raise PreflightError("output directory must not be a symlink")
    output_dir = output_input.resolve()
    if exercise_input.is_symlink():
        raise PreflightError("exercise directory must not be a symlink")
    if not exercise_dir.is_dir():
        raise PreflightError("exercise directory does not exist")
    if output_dir == exercise_dir or output_dir.is_relative_to(exercise_dir):
        raise PreflightError("output directory must be outside the exercise directory")
    if output_dir.exists() and (not output_dir.is_dir() or any(output_dir.iterdir())):
        raise PreflightError("output directory must be new or empty")
    output_dir.mkdir(parents=True, exist_ok=True)
    for relative in REQUIRED_ASSETS:
        path = exercise_dir / relative
        if not path.is_file() or path.is_symlink():
            raise PreflightError(f"required regular task asset is missing or symlinked: {relative}")
    observed_fixed: dict[str, str] = {}
    for relative, expected in PINNED_HASHES.items():
        observed = _sha256(exercise_dir / relative)
        observed_fixed[relative] = observed
        if observed != expected:
            raise PreflightError(f"pinned task asset hash mismatch: {relative}")
    source_sha256 = _combined_digest(exercise_dir, SOURCE_FILES)
    compiler_path = shutil.which(args.compiler)
    if compiler_path is None:
        raise PreflightError(f"compiler is unavailable: {args.compiler}")
    version = subprocess.run(
        [compiler_path, "-dumpfullversion", "-dumpversion"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
        env={**os.environ, "LC_ALL": "C", "LANG": "C"},
    )
    if version.returncode != 0:
        raise PreflightError("compiler version could not be read")
    observed_version = version.stdout.strip()
    if not (observed_version == args.expected_gcc or observed_version.startswith(f"{args.expected_gcc}.")):
        raise PreflightError(f"expected GNU GCC {args.expected_gcc}, observed {observed_version or 'unknown'}")
    macros = subprocess.run(
        [compiler_path, "-dM", "-E", "-x", "c++", "-"],
        input="",
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
        env={**os.environ, "LC_ALL": "C", "LANG": "C"},
    )
    if macros.returncode != 0 or "#define __GNUC__ " not in macros.stdout or "#define __clang__ " in macros.stdout:
        raise PreflightError("compiler is not the required GNU GCC toolchain")
    return Context(
        exercise_dir=exercise_dir,
        output_dir=output_dir,
        compiler=compiler_path,
        source_sha256=source_sha256,
        fixed_hashes=observed_fixed,
        compile_timeout_s=args.compile_timeout_s,
        link_timeout_s=args.link_timeout_s,
    )


def _write_receipt(
    output_dir: Path,
    source_sha256: str | None,
    fixed_hashes: dict[str, str],
    results: list[KernelReceipt],
    preflight_error: str | None,
) -> dict[str, Any]:
    invalid = preflight_error is not None or any(result.kernel is None for result in results)
    kernel_sum = None if invalid else sum(result.kernel or 0 for result in results)
    status = "invalid" if invalid else "pass" if all(result.kernel == 1 for result in results) else "fail"
    payload: dict[str, Any] = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "policy_id": POLICY_ID,
        "status": status,
        "preflight_error": preflight_error,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "verifier_source_sha256": _sha256(Path(__file__).resolve()),
        "candidate_source_sha256": source_sha256,
        "fixed_asset_sha256": fixed_hashes,
        "kernel_results": [asdict(result) for result in results],
        "passed_count": sum(result.kernel == 1 for result in results),
        "failed_count": sum(result.kernel == -1 for result in results),
        "invalid_count": sum(result.kernel is None for result in results),
        "kernel_sum": kernel_sum,
        "maximum_kernel_sum": 4,
        "excluded_conditions": [],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "verification_receipt.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exercise-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--compiler", default="g++")
    parser.add_argument("--expected-gcc", default="13.3")
    parser.add_argument("--compile-timeout-s", type=int, default=120)
    parser.add_argument("--link-timeout-s", type=int, default=120)
    return parser


def main() -> int:
    args = _parser().parse_args()
    output_dir = args.output_dir.resolve()
    try:
        ctx = _prepare(args)
    except (OSError, subprocess.SubprocessError, PreflightError) as error:
        exercise_dir = args.exercise_dir.resolve()
        unsafe_output = (
            args.output_dir.is_symlink()
            or output_dir == exercise_dir
            or output_dir.is_relative_to(exercise_dir)
        )
        if unsafe_output or (output_dir.exists() and output_dir.is_dir() and any(output_dir.iterdir())):
            print(f"INVALID: {error}", file=sys.stderr)
            return 2
        payload = _write_receipt(output_dir, None, {}, [], str(error))
        print(json.dumps({"status": payload["status"], "receipt": str(output_dir / "verification_receipt.json")}))
        return 2
    checks: tuple[Callable[[Context], KernelReceipt], ...] = (
        verify_e01_a_names_and_scoping,
        verify_e01_b_function_signature,
        verify_e01_c_definition_and_linkage,
        verify_e01_d_official_caller,
    )
    results = [check(ctx) for check in checks]
    payload = _write_receipt(ctx.output_dir, ctx.source_sha256, ctx.fixed_hashes, results, None)
    print(json.dumps({"status": payload["status"], "kernel_sum": payload["kernel_sum"], "receipt": str(ctx.output_dir / "verification_receipt.json")}))
    return 0 if payload["status"] == "pass" else 2 if payload["status"] == "invalid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
