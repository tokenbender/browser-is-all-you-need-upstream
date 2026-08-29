
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any


TASK_ID = "diamond"
POLICY_ID = "08"
AUTHORIZED = {"diamond.cpp", "diamond.h"}
PINNED_PARSER_SHA256 = "82558ec14d4ed56ff88b170e36b196a15654e08b624857daf755e530641b3705"
REPO_ROOT = Path(__file__).resolve().parents[3]
PARSER_PATH = REPO_ROOT / "src/glm47_posttraining/aider_polyglot/parser.py"


class InvalidEvidence(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidEvidence(f"invalid JSON evidence: {path}") from exc
    if not isinstance(value, dict):
        raise InvalidEvidence(f"JSON evidence must be an object: {path}")
    return value


def reject_symlink_components(bundle: Path, relative: Path, label: str) -> None:
    current = bundle
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise InvalidEvidence(f"symlink evidence is forbidden: {label}")


def resolve_file(bundle: Path, reference: Any, label: str) -> Path:
    if not isinstance(reference, dict) or not isinstance(reference.get("path"), str) or not isinstance(reference.get("sha256"), str):
        raise InvalidEvidence(f"invalid file reference: {label}")
    relative = Path(reference["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise InvalidEvidence(f"unsafe file reference: {label}")
    reject_symlink_components(bundle, relative, label)
    unresolved = bundle / relative
    if unresolved.is_symlink():
        raise InvalidEvidence(f"symlink evidence is forbidden: {label}")
    path = unresolved.resolve()
    try:
        path.relative_to(bundle)
    except ValueError as exc:
        raise InvalidEvidence(f"file escapes bundle: {label}") from exc
    if not path.is_file() or sha256(path) != reference["sha256"]:
        raise InvalidEvidence(f"missing file or hash mismatch: {label}")
    return path


def resolve_tree(bundle: Path, reference: Any, label: str) -> tuple[Path, dict[str, str], str]:
    if not isinstance(reference, dict) or not isinstance(reference.get("path"), str) or not isinstance(reference.get("tree_sha256"), str):
        raise InvalidEvidence(f"invalid tree reference: {label}")
    relative = Path(reference["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise InvalidEvidence(f"unsafe tree reference: {label}")
    reject_symlink_components(bundle, relative, label)
    unresolved = bundle / relative
    if unresolved.is_symlink():
        raise InvalidEvidence(f"symlink tree is forbidden: {label}")
    root = unresolved.resolve()
    try:
        root.relative_to(bundle)
    except ValueError as exc:
        raise InvalidEvidence(f"tree escapes bundle: {label}") from exc
    if not root.is_dir():
        raise InvalidEvidence(f"tree is missing: {label}")
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise InvalidEvidence(f"symlink inside evidence tree: {label}")
        if path.is_file():
            files[path.relative_to(root).as_posix()] = sha256(path)
    digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if digest != reference["tree_sha256"]:
        raise InvalidEvidence(f"tree hash mismatch: {label}")
    return root, files, digest


def kernel(kernel_id: str, function: str, passed: bool, summary: str, facts: dict[str, Any]) -> dict[str, Any]:
    return {"kernel_id": kernel_id, "verifier_function": function, "status": "pass" if passed else "fail", "score": 1 if passed else -1, "applicable": True, "summary": summary, "facts": facts}


def parser_module() -> Any:
    if PARSER_PATH.is_symlink() or not PARSER_PATH.is_file() or sha256(PARSER_PATH) != PINNED_PARSER_SHA256:
        raise InvalidEvidence("repository Aider parser does not match pinned SHA-256")
    spec = importlib.util.spec_from_file_location("diamond_pinned_aider_parser", PARSER_PATH)
    if spec is None or spec.loader is None:
        raise InvalidEvidence("could not load pinned Aider parser")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse_response(response: Path) -> tuple[dict[str, Any], dict[str, str]]:
    module = parser_module()
    try:
        parsed = module.parse_whole_file_response(response.read_text(errors="replace"), sorted(AUTHORIZED))
    except Exception as exc:
        return {"format_valid": False, "parsed_files": [], "parser_error": str(exc)}, {}
    files = dict(parsed.files)
    return {"format_valid": bool(parsed.format_valid), "parsed_files": sorted(files), "parser_error": None}, files


def changed_files(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(name for name in set(before) | set(after) if before.get(name) != after.get(name))


def require_fields(value: dict[str, Any], fields: dict[str, type], label: str) -> None:
    for name, expected in fields.items():
        if not isinstance(value.get(name), expected):
            raise InvalidEvidence(f"{label} field missing or wrongly typed: {name}")


def verify_8a_aider_response_parse(parse_result: dict[str, Any], parsed: dict[str, str]) -> dict[str, Any]:
    passed = parse_result["format_valid"] and bool(parsed) and set(parsed).issubset(AUTHORIZED)
    return kernel("8A", "verify_8a_aider_response_parse", passed, "response parsed as a strict Aider whole-file edit" if passed else "response was empty, malformed, or recoverably invalid", {**parse_result, "parser_source_sha256": PINNED_PARSER_SHA256})


def verify_8b_authorized_file_scope(parse_result: dict[str, Any], parsed: dict[str, str], changed: list[str], after_root: Path) -> dict[str, Any]:
    parsed_names = sorted(parsed)
    content_matches = {name: (after_root / name).is_file() and not (after_root / name).is_symlink() and (after_root / name).read_text() == content for name, content in parsed.items()}
    passed = parse_result["format_valid"] and bool(changed) and changed == parsed_names and set(changed).issubset(AUTHORIZED) and all(content_matches.values())
    return kernel("8B", "verify_8b_authorized_file_scope", passed, "actual changes and post-edit contents exactly matched authorized parsed files" if passed else "parsed names or contents differed from the authenticated post-edit tree", {"parsed_files": parsed_names, "changed_files": changed, "authorized_files": sorted(AUTHORIZED), "content_matches": content_matches})


def verify_8c_response_quality_counters(harness: dict[str, Any]) -> dict[str, Any]:
    counters = harness.get("response_counters")
    compiler = harness.get("compiler_result")
    if not isinstance(counters, dict) or not isinstance(compiler, dict):
        raise InvalidEvidence("harness counters or compiler result is missing")
    names = ["num_malformed_responses", "syntax_errors", "indentation_errors", "lazy_comments"]
    for name in names:
        if not isinstance(counters.get(name), int) or counters[name] < 0:
            raise InvalidEvidence(f"invalid response counter: {name}")
    if not isinstance(compiler.get("status"), str) or not isinstance(compiler.get("returncode"), int):
        raise InvalidEvidence("compiler result schema is invalid")
    passed = all(counters[name] == 0 for name in names) and compiler["status"] == "passed" and compiler["returncode"] == 0
    return kernel("8C", "verify_8c_response_quality_counters", passed, "response counters were clean and candidate compiled" if passed else "response event or candidate compile failure was recorded", {"response_counters": counters, "compiler_result": compiler})


def verify_8d_evaluation_completion(harness: dict[str, Any]) -> dict[str, Any]:
    evaluation = harness.get("evaluation")
    if not isinstance(evaluation, dict):
        raise InvalidEvidence("evaluation timing receipt is missing")
    require_fields(evaluation, {"status": str, "elapsed_seconds": (int, float), "timeout_seconds": (int, float), "test_timeouts": int}, "evaluation")
    infrastructure_error = evaluation.get("infrastructure_error")
    if infrastructure_error not in (None, False, ""):
        raise InvalidEvidence("evaluation records an infrastructure error")
    if evaluation["elapsed_seconds"] < 0 or evaluation["timeout_seconds"] <= 0 or evaluation["test_timeouts"] < 0:
        raise InvalidEvidence("evaluation timing values are invalid")
    passed = evaluation["status"] == "complete" and evaluation["elapsed_seconds"] <= evaluation["timeout_seconds"] and evaluation["test_timeouts"] == 0
    return kernel("8D", "verify_8d_evaluation_completion", passed, "evaluation completed within its limit" if passed else "candidate evaluation timed out, crashed, or remained incomplete", evaluation)


def verify_8e_receipt_integrity(bundle: Path, manifest: dict[str, Any], response: Path, task_manifest_path: Path, task: dict[str, Any], harness: dict[str, Any], parse_result: dict[str, Any], changed: list[str], before_digest: str, after_digest: str) -> dict[str, Any]:
    require_fields(task, {"task_id": str, "source_revision": str, "editable_files": list, "required_benchmark_files": list}, "task manifest")
    if task["task_id"] != TASK_ID or set(task["editable_files"]) != AUTHORIZED:
        raise InvalidEvidence("task manifest identity or editable-file set is invalid")
    require_fields(harness, {"run_id": str, "model": str, "attempt": int, "response_sha256": str, "task_manifest_sha256": str, "before_tree_sha256": str, "after_tree_sha256": str, "parser_source_sha256": str, "parser_result": dict, "changed_files": list, "logs": dict}, "harness receipt")
    bindings = {
        "response": harness["response_sha256"] == sha256(response),
        "task_manifest": harness["task_manifest_sha256"] == sha256(task_manifest_path),
        "before_tree": harness["before_tree_sha256"] == before_digest,
        "after_tree": harness["after_tree_sha256"] == after_digest,
        "parser_source": harness["parser_source_sha256"] == PINNED_PARSER_SHA256 == manifest.get("parser_source_sha256"),
        "parser_result": harness["parser_result"] == parse_result,
        "changed_files": sorted(harness["changed_files"]) == changed,
    }
    logs: dict[str, str] = {}
    for name in ("configure", "build_test"):
        path = resolve_file(bundle, harness["logs"].get(name), f"logs.{name}")
        if path.stat().st_size == 0:
            raise InvalidEvidence(f"required log is empty: {name}")
        logs[name] = sha256(path)
    if not all(bindings.values()):
        raise InvalidEvidence(f"harness receipt binding contradiction: {json.dumps(bindings, sort_keys=True)}")
    return kernel("8E", "verify_8e_receipt_integrity", True, "task, parser, response, trees, logs, and receipt are fully bound", {"bindings": bindings, "logs": logs, "run_id": harness["run_id"], "model": harness["model"], "attempt": harness["attempt"]})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    bundle_absolute = args.bundle_dir.absolute()
    output_absolute = args.output_dir.absolute()
    if any(path.is_symlink() for path in (bundle_absolute, *bundle_absolute.parents)):
        print(json.dumps({"overall_status": "INVALID", "reason": "bundle path must not contain symlinks"}))
        return 2
    if args.output_dir.exists() or any(path.is_symlink() for path in (output_absolute, *output_absolute.parents)):
        print(json.dumps({"overall_status": "INVALID", "reason": "output path must be new and contain no symlinks"}))
        return 2
    bundle = args.bundle_dir.resolve()
    output = args.output_dir.resolve()
    if output == bundle or bundle in output.parents:
        print(json.dumps({"overall_status": "INVALID", "reason": "output directory must be outside the evidence bundle"}))
        return 2
    args.output_dir.mkdir(parents=True)
    receipt: dict[str, Any] = {"schema_version": 1, "task_id": TASK_ID, "contract_variant": "pristine-original-v1", "policy_id": POLICY_ID, "policy_name": "response_harness_integrity", "verifier_source_sha256": sha256(Path(__file__))}
    started = time.time()
    try:
        if not bundle.is_dir() or bundle.is_symlink():
            raise InvalidEvidence("bundle directory is missing or unsafe")
        manifest_path = bundle / "integrity_bundle.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise InvalidEvidence("integrity_bundle.json is missing or unsafe")
        manifest = load_json(manifest_path)
        if manifest.get("schema_version") != 1 or manifest.get("task_id") != TASK_ID or manifest.get("parser_source_sha256") != PINNED_PARSER_SHA256:
            raise InvalidEvidence("integrity bundle identity or parser binding is invalid")
        response = resolve_file(bundle, manifest.get("response"), "response")
        task_path = resolve_file(bundle, manifest.get("task_manifest"), "task_manifest")
        harness_path = resolve_file(bundle, manifest.get("harness_receipt"), "harness_receipt")
        _, before, before_digest = resolve_tree(bundle, manifest.get("before_tree"), "before_tree")
        after_root, after, after_digest = resolve_tree(bundle, manifest.get("after_tree"), "after_tree")
        task = load_json(task_path)
        harness = load_json(harness_path)
        parse_result, parsed = parse_response(response)
        changed = changed_files(before, after)
        kernels = [verify_8a_aider_response_parse(parse_result, parsed), verify_8b_authorized_file_scope(parse_result, parsed, changed, after_root), verify_8c_response_quality_counters(harness), verify_8d_evaluation_completion(harness), verify_8e_receipt_integrity(bundle, manifest, response, task_path, task, harness, parse_result, changed, before_digest, after_digest)]
        receipt.update({"integrity_manifest_sha256": sha256(manifest_path), "kernels": kernels, "applicable_kernel_count": 5, "kernel_sum": sum(item["score"] for item in kernels), "overall_status": "pass" if all(item["score"] == 1 for item in kernels) else "fail"})
        exit_code = 0 if receipt["overall_status"] == "pass" else 1
    except InvalidEvidence as exc:
        receipt.update({"overall_status": "INVALID", "reason": str(exc)})
        exit_code = 2
    receipt["started_at"] = started
    if isinstance(receipt.get("kernels"), list):
        applicable = [item for item in receipt["kernels"] if item.get("applicable", True)]
        receipt["passed_kernel_count"] = sum(item.get("score") == 1 for item in applicable)
        receipt["failed_kernel_count"] = sum(item.get("score") == -1 for item in applicable)
    receipt["duration_seconds"] = round(time.time() - started, 6)
    (output / "verification_receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
