
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
from pathlib import Path, PurePath
from typing import Any, Callable, Iterable


TASK_ID = "grade-school"
SOURCE_REVISION = "7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f"
CANDIDATE_FILES = ("grade_school.h", "grade_school.cpp")
PROTECTED_SHA256 = {
    "grade_school_test.cpp": "3a6f4266831b6d31b022e764bed44d1c02cfa10f7629f91053c02e0d53b29871",
    "CMakeLists.txt": "53d531120e650972adf19a2a42aa2d5bc716c93700ffac74c1c2868fdce633ff",
    ".meta/example.h": "5b6a05abfaf2b3c73976db3ddbd86adb283c1e5110e93f3d3b7f9032adc34f1b",
    ".meta/example.cpp": "1cdf88a95c3fb712a3ba13ff04f27e2cf499c6a9cc8c1bb0b0248a9f5b9b8f29",
    ".meta/config.json": "28bdbbdbb8c293860d1608973841b5fd4ded9bb28e3e92d9c3fa3bbdcd5ca5e2",
    ".docs/instructions.md": "8dc7133cd5f0564717108757c27ad96ebadf44f03b5fde5c35b826aaeb0b4e0f",
    "test/catch.hpp": "681e7505a50887c9085539e5135794fc8f66d8e5de28eadf13a30978627b0f47",
    "test/tests-main.cpp": "5847fda35c1320d94f8d088aaf34229d689f66f1da235f885cbb28c8f17e4260",
}
GCC_FLAGS = ("-std=c++17", "-Wall", "-Wextra", "-Wpedantic", "-Werror", "-fno-diagnostics-color")
EXPECTED_TESTS = (
    "a_new_school_has_an_empty_roster",
    "adding_a_student_adds_them_to_the_roster_for_the_given_grade",
    "adding_more_students_to_the_same_grade_adds_them_to_the_roster",
    "adding_students_to_different_grades_adds_them_to_the_roster",
    "grade_returns_the_students_in_that_grade_in_alphabetical_order",
    "grade_returns_an_empty_array_if_there_are_no_students_in_that_grade",
    "the_student_names_in_each_grade_in_the_roster_are_sorted",
    "checking_a_grade_should_not_change_the_roster",
)


@dataclass(frozen=True)
class CommandReceipt:
    command: list[str]
    cwd: str
    return_code: int
    timed_out: bool
    launch_error: bool
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
class CandidateContext:
    exercise_dir: Path
    output_dir: Path
    compiler: str
    compiler_identity: str
    candidate_hashes: dict[str, str]
    candidate_source_sha256: str
    protected_hashes: dict[str, str]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def combined_hash(root: Path, relative_paths: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(relative_paths):
        path = root / relative
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def safe_label(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def prepare_output(path: Path, forbidden_root: Path | None = None) -> tuple[bool, str]:
    try:
        resolved_output = path.resolve()
        if forbidden_root is not None:
            resolved_forbidden = forbidden_root.resolve(strict=True)
            if resolved_output == resolved_forbidden or resolved_forbidden in resolved_output.parents:
                return False, "output directory must be outside the immutable input tree"
        if path.exists():
            if not path.is_dir() or path.is_symlink():
                return False, "output path is not a real directory"
            if any(path.iterdir()):
                return False, "output directory is not empty"
        else:
            path.mkdir(parents=True)
    except OSError as error:
        return False, f"cannot prepare output directory: {error}"
    return True, "ready"


def output_preflight_failed(message: str) -> bool:
    return message.startswith(("output ", "cannot prepare output"))


def run_command(
    output_dir: Path,
    kernel_id: str,
    label: str,
    command: list[str],
    timeout_s: int,
    cwd: Path | None = None,
    env_extra: dict[str, str] | None = None,
) -> CommandReceipt:
    logs = output_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    stem = f"{kernel_id.lower()}_{safe_label(label)}"
    stdout_path = logs / f"{stem}.stdout.log"
    stderr_path = logs / f"{stem}.stderr.log"
    started = time.monotonic()
    timed_out = False
    launch_error = False
    try:
        environment = {**os.environ, "LC_ALL": "C", "LANG": "C"}
        if env_extra:
            environment.update(env_extra)
        completed = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=environment,
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
        launch_error = True
        return_code = 127
        stdout = ""
        stderr = f"{type(error).__name__}: {error}\n"
    duration = time.monotonic() - started
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    return CommandReceipt(
        command=command,
        cwd=str(cwd or Path.cwd()),
        return_code=return_code,
        timed_out=timed_out,
        launch_error=launch_error,
        duration_seconds=round(duration, 6),
        stdout_log=str(stdout_path),
        stderr_log=str(stderr_path),
    )


def passed(kernel_id: str, summary: str, commands: list[CommandReceipt] | None = None, facts: dict[str, Any] | None = None, artifacts: dict[str, str] | None = None) -> KernelReceipt:
    return KernelReceipt(kernel_id, 1, "pass", summary, commands or [], facts or {}, artifacts or {})


def failed(kernel_id: str, summary: str, commands: list[CommandReceipt] | None = None, facts: dict[str, Any] | None = None) -> KernelReceipt:
    return KernelReceipt(kernel_id, -1, "fail", summary, commands or [], facts or {}, {})


def invalid(kernel_id: str, summary: str, commands: list[CommandReceipt] | None = None, facts: dict[str, Any] | None = None) -> KernelReceipt:
    return KernelReceipt(kernel_id, None, "invalid", summary, commands or [], facts or {}, {})


def excluded(kernel_id: str, summary: str) -> KernelReceipt:
    return KernelReceipt(kernel_id, None, "excluded", summary, [], {}, {})


def command_result(kernel_id: str, command: CommandReceipt, success: str, failure: str, artifacts: dict[str, str] | None = None, facts: dict[str, Any] | None = None) -> KernelReceipt:
    if command.launch_error:
        return invalid(kernel_id, "required process could not start", [command], facts)
    if command.return_code == 0 and not command.timed_out:
        return passed(kernel_id, success, [command], facts, artifacts)
    return failed(kernel_id, failure, [command], {**(facts or {}), "return_code": command.return_code, "timed_out": command.timed_out})


def write_probe(ctx: CandidateContext, kernel_id: str, name: str, source: str) -> Path:
    probes = ctx.output_dir / "probes"
    probes.mkdir(parents=True, exist_ok=True)
    path = probes / f"{kernel_id.lower()}_{safe_label(name)}.cpp"
    path.write_text(source, encoding="utf-8")
    return path


def artifact_entry(path: Path) -> dict[str, str]:
    return {str(path): sha256(path)}


def candidate_unchanged(ctx: CandidateContext) -> tuple[bool, dict[str, str]]:
    try:
        observed = {relative: sha256(ctx.exercise_dir / relative) for relative in CANDIDATE_FILES}
    except OSError:
        return False, {}
    return observed == ctx.candidate_hashes, observed


def build_candidate_context(exercise_dir: Path, output_dir: Path, compiler_name: str, compiler_kind: str) -> tuple[CandidateContext | None, str]:
    try:
        root = exercise_dir.resolve(strict=True)
    except OSError as error:
        return None, f"exercise directory cannot be resolved: {error}"
    if not root.is_dir() or root.is_symlink():
        return None, "exercise path is not a real directory"
    ready, message = prepare_output(output_dir, root)
    if not ready:
        return None, message
    candidate_hashes: dict[str, str] = {}
    for relative in CANDIDATE_FILES:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            return None, f"candidate file is not a regular file: {relative}"
        candidate_hashes[relative] = sha256(path)
    protected_hashes: dict[str, str] = {}
    for relative, expected in PROTECTED_SHA256.items():
        path = root / relative
        if not path.is_file() or path.is_symlink():
            return None, f"protected asset is not a regular file: {relative}"
        observed = sha256(path)
        protected_hashes[relative] = observed
        if observed != expected:
            return None, f"protected asset hash mismatch: {relative}"
    resolved_compiler = shutil.which(compiler_name)
    if not resolved_compiler:
        return None, f"compiler is unavailable: {compiler_name}"
    compiler_check = run_command(output_dir, "PRE", "compiler_version", [resolved_compiler, "--version"], 10)
    if compiler_check.launch_error or compiler_check.return_code != 0:
        return None, "compiler identity could not be established"
    identity = Path(compiler_check.stdout_log).read_text(encoding="utf-8") + Path(compiler_check.stderr_log).read_text(encoding="utf-8")
    lowered = identity.lower()
    if compiler_kind == "gcc" and not re.search(r"\b13\.3(?:\.0)?\b", identity):
        return None, "GCC 13.3 is required"
    if compiler_kind == "clang" and "clang" not in lowered:
        return None, "Clang is required"
    return CandidateContext(
        exercise_dir=root,
        output_dir=output_dir.resolve(),
        compiler=resolved_compiler,
        compiler_identity=identity.strip(),
        candidate_hashes=candidate_hashes,
        candidate_source_sha256=combined_hash(root, CANDIDATE_FILES),
        protected_hashes=protected_hashes,
    ), "ready"


def finalize_receipt(
    output_dir: Path,
    policy_id: str,
    policy_name: str,
    kernels: list[KernelReceipt],
    verifier_path: Path,
    context: CandidateContext | None = None,
    extra: dict[str, Any] | None = None,
    preflight_error: str | None = None,
) -> int:
    applicable = [item for item in kernels if item.status not in {"excluded", "blocked"}]
    invalid_items = [item for item in applicable if item.status == "invalid"]
    failed_items = [item for item in applicable if item.status == "fail"]
    passed_items = [item for item in applicable if item.status == "pass"]
    if preflight_error or invalid_items:
        overall = "invalid"
        exit_code = 2
        kernel_sum: int | None = None
    elif failed_items:
        overall = "fail"
        exit_code = 1
        kernel_sum = sum(item.kernel or 0 for item in applicable)
    elif applicable and len(passed_items) == len(applicable):
        overall = "pass"
        exit_code = 0
        kernel_sum = len(passed_items)
    else:
        overall = "invalid"
        exit_code = 2
        kernel_sum = None
    immutable = None
    post_hashes: dict[str, str] = {}
    if context is not None:
        immutable, post_hashes = candidate_unchanged(context)
        if not immutable:
            overall = "invalid"
            exit_code = 2
            kernel_sum = None
    receipt = {
        "schema_version": 1,
        "policy_id": policy_id,
        "policy_name": policy_name,
        "task_id": TASK_ID,
        "source_revision": SOURCE_REVISION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "verifier_sha256": sha256(verifier_path),
        "shared_helper_sha256": sha256(Path(__file__)),
        "preflight_error": preflight_error,
        "candidate_source_sha256": context.candidate_source_sha256 if context else None,
        "candidate_hashes_before": context.candidate_hashes if context else None,
        "candidate_hashes_after": post_hashes if context else None,
        "candidate_immutable": immutable,
        "protected_hashes": context.protected_hashes if context else None,
        "compiler": context.compiler if context else None,
        "compiler_identity": context.compiler_identity if context else None,
        "kernels": [asdict(item) for item in kernels],
        "counts": {
            "applicable": len(applicable),
            "passed": len(passed_items),
            "failed": len(failed_items),
            "invalid": len(invalid_items),
            "excluded": sum(item.status == "excluded" for item in kernels),
            "blocked": sum(item.status == "blocked" for item in kernels),
        },
        "kernel_sum": kernel_sum,
        "applicable_maximum": len(applicable),
        "overall_status": overall,
        "extra": extra or {},
    }
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "verification_receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        return 2
    return exit_code


def candidate_parser(description: str, default_compiler: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--exercise-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--compiler", default=default_compiler)
    return parser


def run_candidate_policy(
    policy_id: str,
    policy_name: str,
    verifier_path: Path,
    kernel_functions: list[Callable[[CandidateContext], KernelReceipt]],
    compiler_kind: str,
    default_compiler: str,
) -> int:
    parser = candidate_parser(policy_name, default_compiler)
    args = parser.parse_args()
    context, error = build_candidate_context(args.exercise_dir, args.output_dir, args.compiler, compiler_kind)
    if context is None:
        if output_preflight_failed(error):
            return 2
        return finalize_receipt(args.output_dir, policy_id, policy_name, [], verifier_path, preflight_error=error)
    kernels: list[KernelReceipt] = []
    for function in kernel_functions:
        try:
            kernels.append(function(context))
        except (OSError, ValueError, json.JSONDecodeError) as error_value:
            kernel_id = function.__name__.split("_")[1].upper() if "_" in function.__name__ else "UNKNOWN"
            kernels.append(invalid(kernel_id, f"verifier exception: {type(error_value).__name__}: {error_value}"))
    return finalize_receipt(args.output_dir, policy_id, policy_name, kernels, verifier_path, context=context)


def safe_relative(root: Path, relative: str) -> Path:
    pure = PurePath(relative)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise ValueError(f"unsafe relative path: {relative}")
    path = root.joinpath(*pure.parts)
    cursor = root.resolve(strict=True)
    for part in pure.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError(f"bundle artifact path contains a symlink: {relative}")
    resolved_parent = path.parent.resolve(strict=True)
    if root.resolve() != resolved_parent and root.resolve() not in resolved_parent.parents:
        raise ValueError(f"path escapes bundle: {relative}")
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"bundle artifact is not a regular file: {relative}")
    return path


def load_bound_bytes(root: Path, entry: dict[str, Any]) -> bytes:
    if set(entry) != {"path", "sha256"} or not isinstance(entry["path"], str) or not isinstance(entry["sha256"], str):
        raise ValueError("artifact entry must contain string path and sha256")
    path = safe_relative(root, entry["path"])
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise ValueError(f"bundle artifact hash mismatch: {entry['path']}")
    return data


def load_bound_json(root: Path, entry: dict[str, Any]) -> dict[str, Any]:
    value = json.loads(load_bound_bytes(root, entry).decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("bound JSON artifact is not an object")
    return value


def tree_manifest(root: Path) -> tuple[dict[str, str], str]:
    if not root.is_dir() or root.is_symlink():
        raise ValueError("tree root is not a real directory")
    files: dict[str, str] = {}
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"tree contains symlink: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        value = sha256(path)
        files[relative] = value
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return files, digest.hexdigest()


def bundle_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--bundle-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser


if __name__ == "__main__":
    sys.exit(2)
