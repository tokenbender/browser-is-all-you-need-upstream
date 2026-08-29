
from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path, PurePath
from types import ModuleType
from typing import Any

from _grade_school_common import CANDIDATE_FILES, PROTECTED_SHA256, SOURCE_REVISION, KernelReceipt, bundle_parser, failed, finalize_receipt, invalid, load_bound_bytes, load_bound_json, output_preflight_failed, passed, prepare_output, safe_relative, sha256, tree_manifest


PARSER_SHA256 = "82558ec14d4ed56ff88b170e36b196a15654e08b624857daf755e530641b3705"


@dataclass(frozen=True)
class IntegrityContext:
    bundle_dir: Path
    output_dir: Path
    manifest: dict[str, Any]
    task_manifest: dict[str, Any]
    harness_receipt: dict[str, Any]
    before_dir: Path
    after_dir: Path
    before_files: dict[str, str]
    after_files: dict[str, str]
    before_tree_sha256: str
    after_tree_sha256: str
    parser_source: Path


def _safe_tree(root: Path, entry: dict[str, Any]) -> Path:
    if set(entry) != {"path", "tree_sha256"} or not isinstance(entry["path"], str) or not isinstance(entry["tree_sha256"], str):
        raise ValueError("tree entry must contain path and tree_sha256")
    pure = PurePath(entry["path"])
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise ValueError("unsafe tree path")
    path = root.joinpath(*pure.parts)
    cursor = root.resolve(strict=True)
    for part in pure.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError("tree path contains a symlink")
    if not path.is_dir() or path.is_symlink():
        raise ValueError("tree path is not a real directory")
    resolved = path.resolve()
    if root.resolve() not in resolved.parents:
        raise ValueError("tree path escapes bundle")
    return resolved


def _changed_files(ctx: IntegrityContext) -> list[str]:
    names = set(ctx.before_files) | set(ctx.after_files)
    return sorted(name for name in names if ctx.before_files.get(name) != ctx.after_files.get(name))


def _load_parser(ctx: IntegrityContext) -> ModuleType:
    if sha256(ctx.parser_source) != PARSER_SHA256:
        raise ValueError("pinned parser hash mismatch")
    specification = importlib.util.spec_from_file_location("grade_school_pinned_parser", ctx.parser_source)
    if specification is None or specification.loader is None:
        raise ValueError("parser module could not be loaded")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


def _parse(ctx: IntegrityContext) -> Any:
    response = load_bound_bytes(ctx.bundle_dir, ctx.manifest["response"]).decode("utf-8")
    module = _load_parser(ctx)
    return module.parse_whole_file_response(response, CANDIDATE_FILES)


def verify_8a_aider_response_parse(ctx: IntegrityContext) -> KernelReceipt:
    try:
        parsed = _parse(ctx)
    except Exception as error:
        if type(error).__name__ == "AiderResponseError":
            return failed("8A", f"pinned parser rejected the response: {error}")
        raise
    facts = {"parsed_files": sorted(parsed.files), "format_valid": parsed.format_valid, "parser_sha256": PARSER_SHA256}
    if parsed.files and parsed.format_valid:
        return passed("8A", "response is an exact Aider whole-file edit", facts=facts)
    return failed("8A", "response required parser recovery or contained no files", facts=facts)


def verify_8b_authorized_scope(ctx: IntegrityContext) -> KernelReceipt:
    try:
        parsed = _parse(ctx)
    except Exception as error:
        if type(error).__name__ == "AiderResponseError":
            return failed("8B", f"response targets could not be authorized: {error}")
        raise
    parsed_files = sorted(parsed.files)
    changed = _changed_files(ctx)
    authorized = set(CANDIDATE_FILES)
    facts = {"parsed_files": parsed_files, "changed_files": changed, "authorized_files": sorted(authorized)}
    if set(parsed_files).issubset(authorized) and set(changed).issubset(authorized):
        return passed("8B", "parsed and changed files stay in the authorized scope", facts=facts)
    return failed("8B", "response or applied edit changed an unauthorized file", facts=facts)


def verify_8c_effective_change(ctx: IntegrityContext) -> KernelReceipt:
    try:
        parsed = _parse(ctx)
    except Exception as error:
        if type(error).__name__ == "AiderResponseError":
            return failed("8C", f"effective edit could not be parsed: {error}")
        raise
    parsed_files = sorted(parsed.files)
    changed = _changed_files(ctx)
    facts = {"parsed_files": parsed_files, "changed_files": changed}
    if changed and parsed_files == changed:
        return passed("8C", "response produced an exact nonempty effective edit", facts=facts)
    return failed("8C", "response was a no-op or parsed and changed sets disagree", facts=facts)


def verify_8d_quality_and_compile(ctx: IntegrityContext) -> KernelReceipt:
    counters = ctx.harness_receipt.get("response_counters")
    compiler = ctx.harness_receipt.get("compiler_result")
    if not isinstance(counters, dict) or not isinstance(compiler, dict):
        raise ValueError("response counters and compiler result must be objects")
    names = ("num_malformed_responses", "syntax_errors", "indentation_errors", "lazy_comments")
    if any(not isinstance(counters.get(name), int) or counters[name] < 0 for name in names):
        raise ValueError("response counters must be nonnegative integers")
    facts = {"counters": {name: counters[name] for name in names}, "compiler_status": compiler.get("status"), "compiler_return_code": compiler.get("return_code")}
    clean = all(counters[name] == 0 for name in names) and compiler.get("status") == "passed" and compiler.get("return_code") == 0
    return passed("8D", "response counters were clean and candidate compiled", facts=facts) if clean else failed("8D", "response quality or candidate compilation failed", facts=facts)


def verify_8e_evaluation_completion(ctx: IntegrityContext) -> KernelReceipt:
    evaluation = ctx.harness_receipt.get("evaluation")
    if not isinstance(evaluation, dict):
        raise ValueError("evaluation must be an object")
    status = evaluation.get("status")
    elapsed = evaluation.get("elapsed_seconds")
    timeout = evaluation.get("timeout_seconds")
    timeouts = evaluation.get("test_timeouts")
    if not isinstance(elapsed, (int, float)) or not isinstance(timeout, (int, float)) or timeout <= 0 or not isinstance(timeouts, int) or timeouts < 0:
        raise ValueError("evaluation timing fields are invalid")
    facts = {"status": status, "elapsed_seconds": elapsed, "timeout_seconds": timeout, "test_timeouts": timeouts}
    complete = status == "complete" and elapsed <= timeout and timeouts == 0
    return passed("8E", "evaluation completed within its pinned limit", facts=facts) if complete else failed("8E", "evaluation crashed, timed out, or exceeded its limit", facts=facts)


def verify_8f_receipt_integrity(ctx: IntegrityContext) -> KernelReceipt:
    response = load_bound_bytes(ctx.bundle_dir, ctx.manifest["response"])
    task = load_bound_json(ctx.bundle_dir, ctx.manifest["task_manifest"])
    harness = load_bound_json(ctx.bundle_dir, ctx.manifest["harness_receipt"])
    logs = harness.get("logs")
    if not isinstance(logs, dict) or set(logs) != {"configure", "build_test"}:
        raise ValueError("harness logs must bind configure and build_test")
    for entry in logs.values():
        if not load_bound_bytes(ctx.bundle_dir, entry):
            raise ValueError("bound log is empty")
    changed = _changed_files(ctx)
    expected_required = sorted([*CANDIDATE_FILES, *PROTECTED_SHA256])
    identities = task.get("task_id") == "grade-school" and task.get("source_revision") == SOURCE_REVISION and sorted(task.get("editable_files", [])) == sorted(CANDIDATE_FILES) and sorted(task.get("required_files", [])) == expected_required
    bindings = harness.get("response_sha256") == ctx.manifest["response"]["sha256"] and harness.get("parser_sha256") == PARSER_SHA256 and harness.get("before_tree_sha256") == ctx.before_tree_sha256 and harness.get("after_tree_sha256") == ctx.after_tree_sha256 and sorted(harness.get("changed_files", [])) == changed
    compiler = harness.get("compiler_result", {})
    tests = harness.get("tests_result", {})
    expected_outcome = "passed" if compiler.get("status") == "passed" and tests.get("passed") is True else "failed"
    outcome = harness.get("final_outcome") == expected_outcome
    facts = {"identities_valid": identities, "bindings_valid": bindings, "outcome_valid": outcome, "changed_files": changed, "response_size": len(response)}
    if identities and bindings and outcome:
        return passed("8F", "complete harness evidence is internally consistent", facts=facts)
    return invalid("8F", "harness evidence is contradictory", facts=facts)


def _build_context(bundle_dir: Path, output_dir: Path, parser_source: Path) -> tuple[IntegrityContext | None, str]:
    try:
        root = bundle_dir.resolve(strict=True)
        if not root.is_dir() or root.is_symlink():
            return None, "bundle is not a real directory"
        ready, message = prepare_output(output_dir, root)
        if not ready:
            return None, message
        manifest_path = root / "integrity_bundle.json"
        if not manifest_path.is_file() or manifest_path.is_symlink():
            return None, "integrity_bundle.json is missing or unsafe"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or manifest.get("schema_version") != 1 or manifest.get("task_id") != "grade-school" or manifest.get("parser_source_sha256") != PARSER_SHA256:
            return None, "integrity manifest identity is invalid"
        task = load_bound_json(root, manifest["task_manifest"])
        harness = load_bound_json(root, manifest["harness_receipt"])
        load_bound_bytes(root, manifest["response"])
        before_dir = _safe_tree(root, manifest["before_tree"])
        after_dir = _safe_tree(root, manifest["after_tree"])
        before_files, before_hash = tree_manifest(before_dir)
        after_files, after_hash = tree_manifest(after_dir)
        if before_hash != manifest["before_tree"]["tree_sha256"] or after_hash != manifest["after_tree"]["tree_sha256"]:
            return None, "tree hash mismatch"
        parser_path = parser_source.resolve(strict=True)
        if not parser_path.is_file() or parser_path.is_symlink() or sha256(parser_path) != PARSER_SHA256:
            return None, "pinned parser is missing, unsafe, or changed"
        return IntegrityContext(root, output_dir.resolve(), manifest, task, harness, before_dir, after_dir, before_files, after_files, before_hash, after_hash, parser_path), "ready"
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as error:
        return None, f"integrity preflight failed: {error}"


def main() -> int:
    parser = bundle_parser("Aider Response and Harness Integrity")
    default_parser = Path(__file__).resolve().parents[3] / "src/glm47_posttraining/aider_polyglot/parser.py"
    parser.add_argument("--parser-source", type=Path, default=default_parser)
    args = parser.parse_args()
    context, error = _build_context(args.bundle_dir, args.output_dir, args.parser_source)
    if context is None:
        if output_preflight_failed(error):
            return 2
        return finalize_receipt(args.output_dir, "8", "Aider Response and Harness Integrity", [], Path(__file__), preflight_error=error)
    kernels: list[KernelReceipt] = []
    for function in [verify_8a_aider_response_parse, verify_8b_authorized_scope, verify_8c_effective_change, verify_8d_quality_and_compile, verify_8e_evaluation_completion, verify_8f_receipt_integrity]:
        try:
            kernels.append(function(context))
        except (OSError, KeyError, ValueError, json.JSONDecodeError) as error_value:
            kernel_id = function.__name__.split("_")[1].upper()
            kernels.append(invalid(kernel_id, f"integrity evidence is invalid: {error_value}"))
    extra = {"bundle_manifest_sha256": sha256(context.bundle_dir / "integrity_bundle.json"), "before_tree_sha256": context.before_tree_sha256, "after_tree_sha256": context.after_tree_sha256}
    return finalize_receipt(args.output_dir, "8", "Aider Response and Harness Integrity", kernels, Path(__file__), extra=extra)


if __name__ == "__main__":
    sys.exit(main())
