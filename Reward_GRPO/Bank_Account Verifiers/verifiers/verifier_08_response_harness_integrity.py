
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


PINNED_PARSER_SHA256 = "c8881a8bbe51715ecfbf8b35b9bdc099be7a73b228347af5ac18a64248bd97e2"
EDITABLE_FILES = ("bank_account.cpp", "bank_account.h")
REQUIRED_FILES = (
    "CMakeLists.txt",
    "bank_account.cpp",
    "bank_account.h",
    "bank_account_test.cpp",
    "test/catch.hpp",
    "test/tests-main.cpp",
)
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
REPO_ROOT = Path(__file__).resolve().parents[2]
PARSER_PATH = REPO_ROOT / "src/glm47_posttraining/aider_polyglot/parser.py"


class EvidenceError(ValueError):
    pass


@dataclass(frozen=True)
class KernelReceipt:
    kernel_id: str
    kernel: int | None
    verdict: str
    summary: str
    facts: dict[str, Any] = field(default_factory=dict)
    artifact_sha256: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class VerifierContext:
    bundle_dir: Path
    output_dir: Path
    manifest_path: Path
    manifest: dict[str, Any]
    manifest_sha256: str | None
    manifest_error: str | None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _safe_path(root: Path, relative: str, label: str) -> Path:
    posix = PurePosixPath(relative)
    if posix.is_absolute() or not posix.parts or ".." in posix.parts or "." in posix.parts:
        raise EvidenceError(f"{label} path is unsafe")
    raw = root.joinpath(*posix.parts)
    resolved = raw.resolve()
    if resolved == root or root not in resolved.parents:
        raise EvidenceError(f"{label} path escapes the bundle")
    cursor = raw
    while cursor != root:
        if cursor.is_symlink():
            raise EvidenceError(f"{label} path uses a symlink")
        cursor = cursor.parent
    return raw


def _artifact_reference(ctx: VerifierContext, reference: Any, label: str) -> tuple[Path, str]:
    if not isinstance(reference, dict):
        raise EvidenceError(f"{label} reference is absent")
    relative = reference.get("path")
    expected = reference.get("sha256")
    if not isinstance(relative, str) or not relative or not isinstance(expected, str):
        raise EvidenceError(f"{label} reference is malformed")
    if SHA256_PATTERN.fullmatch(expected) is None:
        raise EvidenceError(f"{label} SHA-256 is malformed")
    path = _safe_path(ctx.bundle_dir, relative, label)
    if not path.is_file():
        raise EvidenceError(f"{label} artifact is missing")
    observed = _sha256(path)
    if observed != expected:
        raise EvidenceError(f"{label} SHA-256 mismatch")
    return path, observed


def _artifact(ctx: VerifierContext, field_name: str) -> tuple[Path, str]:
    return _artifact_reference(ctx, ctx.manifest.get(field_name), field_name)


def _json_artifact(ctx: VerifierContext, field_name: str) -> tuple[dict[str, Any], Path, str]:
    path, digest = _artifact(ctx, field_name)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EvidenceError(f"{field_name} is not valid JSON: {error}") from error
    if not isinstance(value, dict):
        raise EvidenceError(f"{field_name} must contain a JSON object")
    return value, path, digest


def _tree_digest(root: Path) -> tuple[str, dict[str, str]]:
    if not root.is_dir():
        raise EvidenceError(f"tree directory is missing: {root.name}")
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise EvidenceError(f"tree contains a symlink: {path.relative_to(root).as_posix()}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise EvidenceError(f"tree contains a non-regular file: {path.relative_to(root).as_posix()}")
        relative = path.relative_to(root).as_posix()
        files[relative] = _sha256(path)
    if not files:
        raise EvidenceError(f"tree directory is empty: {root.name}")
    canonical = b"".join(
        relative.encode("utf-8") + b"\0" + digest.encode("ascii") + b"\n"
        for relative, digest in sorted(files.items())
    )
    return hashlib.sha256(canonical).hexdigest(), files


def _tree(ctx: VerifierContext, field_name: str) -> tuple[Path, str, dict[str, str]]:
    reference = ctx.manifest.get(field_name)
    if not isinstance(reference, dict):
        raise EvidenceError(f"{field_name} reference is absent")
    relative = reference.get("path")
    expected = reference.get("tree_sha256")
    if not isinstance(relative, str) or not relative or not isinstance(expected, str):
        raise EvidenceError(f"{field_name} reference is malformed")
    if SHA256_PATTERN.fullmatch(expected) is None:
        raise EvidenceError(f"{field_name} tree SHA-256 is malformed")
    root = _safe_path(ctx.bundle_dir, relative, field_name)
    observed, files = _tree_digest(root)
    if observed != expected:
        raise EvidenceError(f"{field_name} tree SHA-256 mismatch")
    return root, observed, files


def _task_manifest(ctx: VerifierContext) -> tuple[dict[str, Any], Path, str]:
    task, path, digest = _json_artifact(ctx, "task_manifest")
    if task.get("schema_version") != 1 or task.get("task_id") != "bank-account":
        raise EvidenceError("task manifest identity is invalid")
    if task.get("editable_files") != list(EDITABLE_FILES):
        raise EvidenceError("task editable_files are not the pinned Bank Account pair")
    required = task.get("required_files")
    if not isinstance(required, list) or not all(isinstance(item, str) and item for item in required):
        raise EvidenceError("task required_files are malformed")
    if not set(REQUIRED_FILES).issubset(required):
        raise EvidenceError("task manifest lacks required benchmark files")
    if not isinstance(task.get("source_revision"), str) or not task["source_revision"]:
        raise EvidenceError("task source_revision is missing")
    return task, path, digest


def _harness_receipt(ctx: VerifierContext) -> tuple[dict[str, Any], Path, str]:
    return _json_artifact(ctx, "harness_receipt")


def _parser_module() -> Any:
    if not PARSER_PATH.is_file() or _sha256(PARSER_PATH) != PINNED_PARSER_SHA256:
        raise EvidenceError("repository Aider parser does not match the pinned SHA-256")
    source_root = str(REPO_ROOT / "src")
    if source_root not in sys.path:
        sys.path.insert(0, source_root)
    return importlib.import_module("glm47_posttraining.aider_polyglot.parser")


def _parse_response(ctx: VerifierContext) -> tuple[dict[str, Any], dict[str, str], str]:
    response_path, response_digest = _artifact(ctx, "response")
    try:
        response = response_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise EvidenceError(f"response is not readable UTF-8: {error}") from error
    module = _parser_module()
    try:
        parsed = module.parse_whole_file_response(response, EDITABLE_FILES)
    except module.AiderResponseError as error:
        return {
            "status": "fail",
            "reason": error.reason,
            "format_valid": False,
            "parsed_files": [],
        }, {}, response_digest
    files = dict(parsed.files)
    return {
        "status": "pass",
        "reason": None,
        "format_valid": bool(parsed.format_valid),
        "parsed_files": sorted(files),
    }, files, response_digest


def _changed_files(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(
        name for name in set(before) | set(after) if before.get(name) != after.get(name)
    )


def _pass(kernel_id: str, summary: str, facts: dict[str, Any], artifacts: dict[str, str]) -> KernelReceipt:
    return KernelReceipt(kernel_id, 1, "pass", summary, facts, artifacts)


def _fail(kernel_id: str, summary: str, facts: dict[str, Any] | None = None, artifacts: dict[str, str] | None = None) -> KernelReceipt:
    return KernelReceipt(kernel_id, -1, "fail", summary, facts or {}, artifacts or {})


def _invalid(kernel_id: str, summary: str, facts: dict[str, Any] | None = None) -> KernelReceipt:
    return KernelReceipt(kernel_id, None, "invalid", summary, facts or {}, {})


def _preflight(ctx: VerifierContext) -> tuple[bool, str, dict[str, Any]]:
    if ctx.manifest_error is not None:
        return False, ctx.manifest_error, {}
    manifest = ctx.manifest
    if manifest.get("schema_version") != 1 or manifest.get("task_id") != "bank-account":
        return False, "integrity bundle identity is invalid", {}
    if manifest.get("parser_source_sha256") != PINNED_PARSER_SHA256:
        return False, "bundle parser binding is not pinned", {}
    if not PARSER_PATH.is_file() or _sha256(PARSER_PATH) != PINNED_PARSER_SHA256:
        return False, "repository parser SHA-256 mismatch", {}
    facts: dict[str, Any] = {}
    try:
        response_path, response_digest = _artifact(ctx, "response")
        task, task_path, task_digest = _task_manifest(ctx)
        harness, harness_path, harness_digest = _harness_receipt(ctx)
        before_root, before_digest, before_files = _tree(ctx, "before_tree")
        after_root, after_digest, after_files = _tree(ctx, "after_tree")
        missing_before = sorted(set(REQUIRED_FILES) - set(before_files))
        missing_after = sorted(set(REQUIRED_FILES) - set(after_files))
        if missing_before or missing_after:
            raise EvidenceError("source tree snapshots lack pinned benchmark files")
        facts = {
            "response_path": response_path.relative_to(ctx.bundle_dir).as_posix(),
            "task_manifest_path": task_path.relative_to(ctx.bundle_dir).as_posix(),
            "harness_receipt_path": harness_path.relative_to(ctx.bundle_dir).as_posix(),
            "before_tree_path": before_root.relative_to(ctx.bundle_dir).as_posix(),
            "after_tree_path": after_root.relative_to(ctx.bundle_dir).as_posix(),
            "response_sha256": response_digest,
            "task_manifest_sha256": task_digest,
            "harness_receipt_sha256": harness_digest,
            "before_tree_sha256": before_digest,
            "after_tree_sha256": after_digest,
            "before_file_count": len(before_files),
            "after_file_count": len(after_files),
            "source_revision": task["source_revision"],
            "harness_field_count": len(harness),
        }
    except EvidenceError as error:
        return False, str(error), facts
    return True, "bundle, trees, parser, task, and harness artifacts authenticated", facts


def verify_8a_aider_response_parse(ctx: VerifierContext) -> KernelReceipt:
    try:
        outcome, files, response_digest = _parse_response(ctx)
    except EvidenceError as error:
        return _invalid("8A", str(error))
    facts = {**outcome, "parsed_file_count": len(files)}
    artifacts = {"response": response_digest, "parser_source": PINNED_PARSER_SHA256}
    if outcome["status"] == "pass" and outcome["format_valid"] and files:
        return _pass("8A", "response parsed as a strict Aider whole-file edit", facts, artifacts)
    return _fail("8A", "response was rejected or required recoverable formatting", facts, artifacts)


def verify_8b_authorized_file_scope(ctx: VerifierContext) -> KernelReceipt:
    try:
        parse_outcome, parsed, response_digest = _parse_response(ctx)
        _, before_digest, before_files = _tree(ctx, "before_tree")
        _, after_digest, after_files = _tree(ctx, "after_tree")
    except EvidenceError as error:
        return _invalid("8B", str(error))
    changed = _changed_files(before_files, after_files)
    parsed_files = sorted(parsed)
    facts = {
        "parser_status": parse_outcome["status"],
        "parsed_files": parsed_files,
        "changed_files": changed,
        "authorized_files": list(EDITABLE_FILES),
    }
    artifacts = {
        "response": response_digest,
        "before_tree": before_digest,
        "after_tree": after_digest,
    }
    passed = (
        parse_outcome["status"] == "pass"
        and bool(changed)
        and changed == parsed_files
        and set(changed).issubset(EDITABLE_FILES)
    )
    if passed:
        return _pass("8B", "actual tree changes exactly matched authorized parsed files", facts, artifacts)
    return _fail("8B", "tree changes and authorized parsed files did not match", facts, artifacts)


def verify_8c_response_quality_counters(ctx: VerifierContext) -> KernelReceipt:
    try:
        harness, path, digest = _harness_receipt(ctx)
    except EvidenceError as error:
        return _invalid("8C", str(error))
    names = ("num_malformed_responses", "syntax_errors", "indentation_errors", "lazy_comments")
    counters: dict[str, int] = {}
    for name in names:
        value = harness.get(name)
        if not _is_int(value) or value < 0:
            return _invalid("8C", f"{name} must be a nonnegative integer")
        counters[name] = value
    compiler = harness.get("compiler")
    if not isinstance(compiler, dict) or compiler.get("status") not in {"passed", "failed"}:
        return _invalid("8C", "compiler result is malformed")
    return_code = compiler.get("return_code")
    if not _is_int(return_code):
        return _invalid("8C", "compiler return_code is malformed")
    facts = {**counters, "compiler_status": compiler["status"], "compiler_return_code": return_code}
    artifacts = {path.name: digest}
    passed = all(value == 0 for value in counters.values()) and compiler["status"] == "passed" and return_code == 0
    if passed:
        return _pass("8C", "response-quality counters were zero and candidate compilation succeeded", facts, artifacts)
    return _fail("8C", "a response-quality event or candidate compile failure was recorded", facts, artifacts)


def verify_8d_evaluation_completion(ctx: VerifierContext) -> KernelReceipt:
    try:
        harness, path, digest = _harness_receipt(ctx)
    except EvidenceError as error:
        return _invalid("8D", str(error))
    evaluation = harness.get("evaluation")
    if not isinstance(evaluation, dict):
        return _invalid("8D", "evaluation timing receipt is absent")
    status = evaluation.get("status")
    elapsed = evaluation.get("elapsed_seconds")
    timeout = evaluation.get("timeout_seconds")
    test_timeouts = evaluation.get("test_timeouts")
    if status not in {"complete", "candidate_timeout", "candidate_crash", "infrastructure_error"}:
        return _invalid("8D", "evaluation terminal status is malformed")
    if not _is_number(elapsed) or elapsed < 0 or not _is_number(timeout) or timeout <= 0:
        return _invalid("8D", "evaluation timing values are malformed")
    if not _is_int(test_timeouts) or test_timeouts < 0:
        return _invalid("8D", "test_timeouts must be a nonnegative integer")
    facts = {
        "evaluation_status": status,
        "elapsed_seconds": elapsed,
        "timeout_seconds": timeout,
        "test_timeouts": test_timeouts,
    }
    if status == "infrastructure_error":
        return _invalid("8D", "evaluation ended with an infrastructure error", facts)
    artifacts = {path.name: digest}
    passed = status == "complete" and elapsed <= timeout and test_timeouts == 0
    if passed:
        return _pass("8D", "evaluation completed within its pinned timeout", facts, artifacts)
    return _fail("8D", "candidate evaluation timed out, crashed, or exceeded its limit", facts, artifacts)


def verify_8e_receipt_integrity(ctx: VerifierContext) -> KernelReceipt:
    try:
        task, task_path, task_digest = _task_manifest(ctx)
        harness, harness_path, harness_digest = _harness_receipt(ctx)
        parse_outcome, _, response_digest = _parse_response(ctx)
        _, before_digest, before_files = _tree(ctx, "before_tree")
        _, after_digest, after_files = _tree(ctx, "after_tree")
        logs = harness.get("logs")
        if not isinstance(logs, dict):
            raise EvidenceError("harness logs map is absent")
        log_artifacts: dict[str, str] = {}
        for name in ("configure", "build_and_test"):
            log_path, log_digest = _artifact_reference(ctx, logs.get(name), f"logs.{name}")
            if log_path.stat().st_size == 0:
                raise EvidenceError(f"logs.{name} is empty")
            log_artifacts[f"log.{name}"] = log_digest
    except EvidenceError as error:
        return _invalid("8E", str(error))
    required_strings = ("run_id", "model", "source_revision")
    for name in required_strings:
        if not isinstance(harness.get(name), str) or not harness[name]:
            return _invalid("8E", f"harness {name} is missing")
    if harness.get("schema_version") != 1 or harness.get("task_id") != "bank-account":
        return _invalid("8E", "harness identity is invalid")
    if harness.get("edit_format") != "whole" or harness.get("expected_tries") != 2:
        return _invalid("8E", "harness edit format or try limit is invalid")
    if harness.get("attempt") not in {1, 2}:
        return _invalid("8E", "harness attempt is outside the two-turn limit")
    outcomes = harness.get("tests_outcomes")
    if (
        not isinstance(outcomes, list)
        or not 1 <= len(outcomes) <= 2
        or any(not isinstance(value, bool) for value in outcomes)
        or (len(outcomes) < 2 and not outcomes[-1])
        or (len(outcomes) > 1 and outcomes[0])
    ):
        return _invalid("8E", "tests_outcomes are incomplete or contradictory")
    compiler = harness.get("compiler")
    evaluation = harness.get("evaluation")
    if not isinstance(compiler, dict) or compiler.get("status") not in {"passed", "failed"}:
        return _invalid("8E", "compiler result is incomplete")
    if not isinstance(evaluation, dict) or evaluation.get("status") not in {
        "complete",
        "candidate_timeout",
        "candidate_crash",
        "infrastructure_error",
    }:
        return _invalid("8E", "evaluation result is incomplete")
    if any(outcomes) and (compiler.get("status") != "passed" or evaluation.get("status") != "complete"):
        return _invalid("8E", "passing tests contradict compiler or evaluation status")
    if evaluation.get("status") in {"candidate_timeout", "candidate_crash"} and any(outcomes):
        return _invalid("8E", "terminal candidate failure contradicts a passing outcome")
    expected_outcome = "passed" if any(outcomes) else "failed"
    changed = _changed_files(before_files, after_files)
    expected_bindings = {
        "response_sha256": response_digest,
        "task_manifest_sha256": task_digest,
        "before_tree_sha256": before_digest,
        "after_tree_sha256": after_digest,
        "parser_source_sha256": PINNED_PARSER_SHA256,
        "source_revision": task["source_revision"],
        "outcome": expected_outcome,
        "changed_files": changed,
        "parser": parse_outcome,
    }
    mismatches = sorted(name for name, expected in expected_bindings.items() if harness.get(name) != expected)
    facts = {
        "run_id": harness["run_id"],
        "model": harness["model"],
        "attempt": harness["attempt"],
        "tests_outcomes": outcomes,
        "expected_outcome": expected_outcome,
        "changed_files": changed,
        "binding_mismatches": mismatches,
    }
    artifacts = {
        "task_manifest": task_digest,
        "harness_receipt": harness_digest,
        "response": response_digest,
        "before_tree": before_digest,
        "after_tree": after_digest,
        "parser_source": PINNED_PARSER_SHA256,
        **log_artifacts,
    }
    if mismatches:
        return _invalid("8E", "harness receipt bindings are contradictory", facts)
    return _pass("8E", "task, parser, trees, response, outcome, and logs were completely bound", facts, artifacts)


def verify_policy_8(ctx: VerifierContext) -> dict[str, Any]:
    preflight_ok, preflight_summary, preflight_facts = _preflight(ctx)
    if preflight_ok:
        results = [
            verify_8a_aider_response_parse(ctx),
            verify_8b_authorized_file_scope(ctx),
            verify_8c_response_quality_counters(ctx),
            verify_8d_evaluation_completion(ctx),
            verify_8e_receipt_integrity(ctx),
        ]
    else:
        results = [_invalid(kernel_id, preflight_summary, preflight_facts) for kernel_id in ("8A", "8B", "8C", "8D", "8E")]
    invalid = any(result.kernel is None for result in results)
    kernel_sum = None if invalid else sum(result.kernel for result in results if result.kernel is not None)
    status = "invalid" if invalid else "pass" if kernel_sum == 5 else "fail"
    return {
        "schema_version": 1,
        "policy_id": "bank-account-policy-08-response-harness-integrity-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "kernel_model": {"pass": 1, "fail": -1, "infrastructure": "INVALID"},
        "kernel_sum": kernel_sum,
        "kernel_range": [-5, 5],
        "full_pass_required": 5,
        "applicable_kernel_ids": ["8A", "8B", "8C", "8D", "8E"],
        "excluded_conditions": {},
        "passed_kernels": sum(result.kernel == 1 for result in results),
        "failed_kernels": sum(result.kernel == -1 for result in results),
        "bundle_dir": str(ctx.bundle_dir),
        "manifest_sha256": ctx.manifest_sha256,
        "preflight": {
            "status": "pass" if preflight_ok else "invalid",
            "summary": preflight_summary,
            "facts": preflight_facts,
        },
        "checks": {result.kernel_id: asdict(result) for result in results},
    }


def _prepare_output(path: Path, bundle_dir: Path) -> None:
    resolved = path.resolve()
    if resolved == bundle_dir or bundle_dir in resolved.parents:
        raise ValueError("output directory must be outside the integrity bundle")
    if resolved.exists() and any(resolved.iterdir()):
        raise ValueError(f"output directory must be absent or empty: {resolved}")
    resolved.mkdir(parents=True, exist_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    bundle_dir = args.bundle_dir.resolve()
    output_dir = args.output_dir.resolve()
    if not bundle_dir.is_dir():
        raise SystemExit(f"bundle directory does not exist: {bundle_dir}")
    try:
        _prepare_output(output_dir, bundle_dir)
    except (OSError, ValueError) as error:
        raise SystemExit(str(error)) from error
    manifest_path = bundle_dir / "integrity_bundle.json"
    manifest: dict[str, Any] = {}
    manifest_sha256: str | None = None
    manifest_error: str | None = None
    try:
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise EvidenceError("integrity_bundle.json is missing or is a symlink")
        manifest_sha256 = _sha256(manifest_path)
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise EvidenceError("integrity_bundle.json must contain an object")
        manifest = loaded
    except (OSError, UnicodeError, json.JSONDecodeError, EvidenceError) as error:
        manifest_error = str(error)
    ctx = VerifierContext(
        bundle_dir=bundle_dir,
        output_dir=output_dir,
        manifest_path=manifest_path,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        manifest_error=manifest_error,
    )
    receipt = verify_policy_8(ctx)
    receipt_path = output_dir / "verification_receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: receipt[key] for key in ("status", "kernel_sum", "passed_kernels", "failed_kernels")}, sort_keys=True))
    print(receipt_path)
    return 0 if receipt["status"] == "pass" else 2 if receipt["status"] == "invalid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
