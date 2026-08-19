# Allergies verifier policy E05: feedback repair closure.
import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


POLICY_ID = "E05"
POLICY_NAME = "feedback_repair_closure"
TASK_ID = "local-aider-cpp/allergies"
REQUIRED_ARTIFACTS = {
    "turn_1_response": "turn_1/response.txt",
    "turn_1_allergies_h": "turn_1/source/allergies.h",
    "turn_1_allergies_cpp": "turn_1/source/allergies.cpp",
    "turn_1_score_receipt": "turn_1/score_receipt.json",
    "generated_feedback": "turn_1/generated_feedback.txt",
    "delivered_feedback": "turn_2/delivered_feedback.txt",
    "turn_2_response": "turn_2/response.txt",
    "turn_2_allergies_h": "turn_2/source/allergies.h",
    "turn_2_allergies_cpp": "turn_2/source/allergies.cpp",
    "turn_2_score_receipt": "turn_2/score_receipt.json",
    "turn_2_source_diff": "turn_2/source.diff",
}


class InvalidEvidence(RuntimeError):
    pass


@dataclass
class KernelResult:
    kernel: str
    result: str
    score: int | None
    evidence: dict[str, Any]
    reason: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verifier_hash() -> str:
    return _sha256(Path(__file__).resolve())


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _path_has_symlink(path: Path) -> bool:
    absolute = path.absolute()
    cursor = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        cursor /= part
        if cursor.is_symlink():
            return True
    return False


def _prepare_output(bundle_dir: Path, output_dir: Path) -> Path:
    if _path_has_symlink(output_dir):
        raise InvalidEvidence("output path must not contain a symlink")
    bundle = bundle_dir.resolve()
    output = output_dir.resolve()
    if output == bundle or _is_within(output, bundle):
        raise InvalidEvidence("output directory must be outside the trajectory bundle")
    if output.exists():
        if not output.is_dir() or output.is_symlink():
            raise InvalidEvidence("output path must be a real directory")
        if any(output.iterdir()):
            raise InvalidEvidence("output directory must be empty")
    else:
        output.mkdir(parents=True)
    return output


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InvalidEvidence(f"cannot read valid JSON from {path.name}: {error}") from error
    if not isinstance(value, dict):
        raise InvalidEvidence(f"{path.name} must contain a JSON object")
    return value


def _safe_artifact(bundle: Path, relative_path: Any) -> Path:
    if not isinstance(relative_path, str) or not relative_path:
        raise InvalidEvidence("artifact path must be a non-empty string")
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise InvalidEvidence(f"unsafe artifact path: {relative_path}")
    cursor = bundle
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise InvalidEvidence(f"symlink is not allowed: {relative_path}")
    resolved = (bundle / relative).resolve()
    if not _is_within(resolved, bundle):
        raise InvalidEvidence(f"artifact escapes bundle: {relative_path}")
    if not resolved.is_file() or resolved.is_symlink():
        raise InvalidEvidence(f"artifact is not a regular file: {relative_path}")
    return resolved


def _task_matches(receipt: dict[str, Any]) -> bool:
    identity = receipt.get("task_id", receipt.get("task"))
    return identity in {TASK_ID, "allergies"}


def _bind_receipt(receipt: dict[str, Any], header: Path, implementation: Path, label: str) -> None:
    candidate_files = receipt.get("candidate_files")
    if not isinstance(candidate_files, list):
        raise InvalidEvidence(f"{label} receipt lacks candidate_files")
    recorded: dict[str, str] = {}
    for entry in candidate_files:
        if not isinstance(entry, dict):
            raise InvalidEvidence(f"{label} candidate_files entry is not an object")
        path = entry.get("path")
        digest = entry.get("sha256")
        if path in {"allergies.h", "allergies.cpp"} and isinstance(digest, str):
            recorded[path] = digest
    expected = {"allergies.h": _sha256(header), "allergies.cpp": _sha256(implementation)}
    if recorded != expected:
        raise InvalidEvidence(f"{label} receipt candidate hashes do not match its source snapshot")
    output = _receipt_output(receipt)
    output_hash = receipt.get("output_sha256")
    if not isinstance(output_hash, str) or hashlib.sha256(output.encode()).hexdigest() != output_hash:
        raise InvalidEvidence(f"{label} receipt output hash is missing or incorrect")


def _receipt_output(receipt: dict[str, Any]) -> str:
    for key in ("output", "combined_output", "stderr", "stdout"):
        value = receipt.get(key)
        if isinstance(value, str):
            return value
    nested = receipt.get("result")
    if isinstance(nested, dict):
        for key in ("output", "combined_output", "stderr", "stdout"):
            value = nested.get(key)
            if isinstance(value, str):
                return value
    raise InvalidEvidence("score receipt does not contain textual evaluation output")


def _receipt_returncode(receipt: dict[str, Any]) -> int:
    for container in (receipt, receipt.get("result")):
        if isinstance(container, dict):
            for key in ("returncode", "return_code", "exit_code"):
                value = container.get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    return value
    raise InvalidEvidence("score receipt does not contain an integer return code")


def _receipt_status(receipt: dict[str, Any]) -> str:
    for container in (receipt, receipt.get("result")):
        if isinstance(container, dict):
            value = container.get("status")
            if isinstance(value, str) and value:
                return value.lower()
    raise InvalidEvidence("score receipt does not contain a status")


def _diagnostic_present(output: str) -> bool:
    lowered = output.lower()
    parameter_error = re.search(
        r"cannot initialize (?:a )?parameter of type.+(?:char\s*\[|const char|basic_string)",
        lowered,
        flags=re.DOTALL,
    )
    return "is_allergic_to" in lowered and parameter_error is not None


def _kernel_invalid(kernel: str, reason: str) -> KernelResult:
    return KernelResult(kernel, "INVALID", None, {}, reason)


def verify_5a_bundle_integrity(context: dict[str, Any]) -> KernelResult:
    bundle = context["bundle"]
    manifest = context["manifest"]
    if manifest.get("schema_version") != 1:
        raise InvalidEvidence("manifest schema_version must be 1")
    if manifest.get("task_id") != TASK_ID:
        raise InvalidEvidence(f"manifest task_id must be {TASK_ID}")
    if manifest.get("trajectory_kind") != "two_turn":
        raise InvalidEvidence("trajectory_kind must be two_turn")
    entries = manifest.get("artifacts")
    if not isinstance(entries, dict):
        raise InvalidEvidence("manifest artifacts must be an object")
    paths: dict[str, Path] = {}
    hashes: dict[str, str] = {}
    for key, expected_path in REQUIRED_ARTIFACTS.items():
        entry = entries.get(key)
        if not isinstance(entry, dict):
            raise InvalidEvidence(f"missing artifact entry: {key}")
        relative_path = entry.get("path")
        expected_hash = entry.get("sha256")
        if relative_path != expected_path:
            raise InvalidEvidence(f"artifact {key} must use path {expected_path}")
        if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            raise InvalidEvidence(f"artifact {key} has an invalid SHA-256 value")
        path = _safe_artifact(bundle, relative_path)
        actual_hash = _sha256(path)
        if actual_hash != expected_hash:
            raise InvalidEvidence(f"artifact hash mismatch: {key}")
        paths[key] = path
        hashes[key] = actual_hash
    turn_1_receipt = _read_json(paths["turn_1_score_receipt"])
    turn_2_receipt = _read_json(paths["turn_2_score_receipt"])
    if not _task_matches(turn_1_receipt) or not _task_matches(turn_2_receipt):
        raise InvalidEvidence("score receipt task identity does not match Allergies")
    _bind_receipt(turn_1_receipt, paths["turn_1_allergies_h"], paths["turn_1_allergies_cpp"], "turn one")
    _bind_receipt(turn_2_receipt, paths["turn_2_allergies_h"], paths["turn_2_allergies_cpp"], "turn two")
    context["paths"] = paths
    context["artifact_hashes"] = hashes
    context["turn_1_receipt"] = turn_1_receipt
    context["turn_2_receipt"] = turn_2_receipt
    return KernelResult(
        "5A",
        "PASS",
        1,
        {"artifact_count": len(paths), "artifact_hashes": hashes},
        "bundle paths, hashes, and task identities are authenticated",
    )


def verify_5b_feedback_binding(context: dict[str, Any]) -> KernelResult:
    paths = context["paths"]
    generated = paths["generated_feedback"].read_bytes()
    delivered = paths["delivered_feedback"].read_bytes()
    if not generated:
        raise InvalidEvidence("generated feedback is empty")
    if generated != delivered:
        raise InvalidEvidence("generated and delivered feedback differ")
    return KernelResult(
        "5B",
        "PASS",
        1,
        {"feedback_sha256": _sha256(paths["generated_feedback"]), "byte_count": len(generated)},
        "the delivered feedback is byte-identical to the generated feedback",
    )


def verify_5c_reported_diagnostic_removed(context: dict[str, Any]) -> KernelResult:
    turn_1_output = _receipt_output(context["turn_1_receipt"])
    turn_2_output = _receipt_output(context["turn_2_receipt"])
    if not _diagnostic_present(turn_1_output):
        raise InvalidEvidence("turn-one receipt lacks the policy's authenticated parameter-type diagnostic")
    if _diagnostic_present(turn_2_output):
        return KernelResult(
            "5C",
            "FAIL",
            -1,
            {"diagnostic": "api.is_allergic_to.parameter_type", "present_in_turn_2": True},
            "the reported string-parameter diagnostic remains after feedback",
        )
    return KernelResult(
        "5C",
        "PASS",
        1,
        {"diagnostic": "api.is_allergic_to.parameter_type", "present_in_turn_2": False},
        "the reported string-parameter diagnostic is absent from turn two",
    )


def verify_5d_official_consumer_compile(context: dict[str, Any]) -> KernelResult:
    receipt = context["turn_2_receipt"]
    returncode = _receipt_returncode(receipt)
    output = _receipt_output(receipt)
    compile_markers = re.compile(
        r"(?:^|\n).*(?:error:|undefined reference|linker command failed|ld: error|make(?:\[\d+\])?: \*\*\*)",
        flags=re.IGNORECASE,
    )
    has_marker = compile_markers.search(output) is not None
    if returncode != 0 or has_marker:
        return KernelResult(
            "5D",
            "FAIL",
            -1,
            {"returncode": returncode, "compile_or_link_error_marker": has_marker},
            "turn two did not produce a clean official consumer build and run",
        )
    return KernelResult(
        "5D",
        "PASS",
        1,
        {"returncode": returncode, "compile_or_link_error_marker": False},
        "turn two completed without compile or link failure",
    )


def verify_5e_complete_suite_closure(context: dict[str, Any]) -> KernelResult:
    receipt = context["turn_2_receipt"]
    status = _receipt_status(receipt)
    returncode = _receipt_returncode(receipt)
    output = _receipt_output(receipt)
    summary = "All tests passed (50 assertions in 50 test cases)"
    if status in {"passed", "pass", "success", "completed"} and returncode == 0 and summary in output:
        return KernelResult(
            "5E",
            "PASS",
            1,
            {"status": status, "returncode": returncode, "summary": summary},
            "turn two closes the repair with all 50 official assertions passing",
        )
    if status in {"failed", "fail", "error", "completed"} or returncode != 0:
        return KernelResult(
            "5E",
            "FAIL",
            -1,
            {"status": status, "returncode": returncode, "summary_present": summary in output},
            "turn two does not close the repair with the complete official suite",
        )
    raise InvalidEvidence("turn-two receipt has an unrecognized completion status")


def _overall(kernels: list[KernelResult]) -> tuple[str, dict[str, int], int | None]:
    counts = {
        "passed": sum(item.result == "PASS" for item in kernels),
        "failed": sum(item.result == "FAIL" for item in kernels),
        "invalid": sum(item.result == "INVALID" for item in kernels),
    }
    if counts["invalid"]:
        return "INVALID", counts, None
    kernel_sum = sum(item.score or 0 for item in kernels)
    return ("PASS" if counts["failed"] == 0 else "FAIL"), counts, kernel_sum


def _write_receipt(output: Path, payload: dict[str, Any]) -> None:
    (output / "verification_receipt.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _base_receipt(bundle: Path, manifest_hash: str | None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "policy_id": POLICY_ID,
        "policy_name": POLICY_NAME,
        "task_id": TASK_ID,
        "kernel_model": {"pass": 1, "fail": -1, "invalid": None},
        "verifier_sha256": _verifier_hash(),
        "bundle": str(bundle),
        "manifest_sha256": manifest_hash,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    bundle = args.bundle_dir.resolve()
    try:
        if not bundle.is_dir() or bundle.is_symlink():
            raise InvalidEvidence("bundle directory must be a real directory")
        output = _prepare_output(bundle, args.output_dir)
    except InvalidEvidence as error:
        print(f"INVALID: {error}", file=sys.stderr)
        return 2
    manifest_path = bundle / "manifest.json"
    manifest_hash: str | None = None
    try:
        if not manifest_path.is_file() or manifest_path.is_symlink():
            raise InvalidEvidence("manifest.json must be a regular file")
        manifest_hash = _sha256(manifest_path)
        manifest = _read_json(manifest_path)
        if manifest.get("trajectory_kind") == "single_turn":
            receipt = _base_receipt(bundle, manifest_hash)
            receipt.update(
                {
                    "overall_status": "NOT_APPLICABLE",
                    "reason": "single-turn trajectories contain no feedback repair event",
                    "counts": {"passed": 0, "failed": 0, "invalid": 0},
                    "kernel_sum": None,
                    "kernels": [],
                }
            )
            _write_receipt(output, receipt)
            return 0
        context: dict[str, Any] = {"bundle": bundle, "manifest": manifest}
        first = verify_5a_bundle_integrity(context)
        kernels = [first]
        for kernel, function in (
            ("5B", verify_5b_feedback_binding),
            ("5C", verify_5c_reported_diagnostic_removed),
            ("5D", verify_5d_official_consumer_compile),
            ("5E", verify_5e_complete_suite_closure),
        ):
            try:
                kernels.append(function(context))
            except InvalidEvidence as error:
                kernels.append(_kernel_invalid(kernel, str(error)))
    except InvalidEvidence as error:
        kernels = [_kernel_invalid("5A", str(error))]
        kernels.extend(
            _kernel_invalid(kernel, "blocked because bundle integrity is invalid")
            for kernel in ("5B", "5C", "5D", "5E")
        )
        context = {}
    overall, counts, kernel_sum = _overall(kernels)
    receipt = _base_receipt(bundle, manifest_hash)
    receipt.update(
        {
            "overall_status": overall,
            "counts": counts,
            "kernel_sum": kernel_sum,
            "artifact_hashes": context.get("artifact_hashes", {}),
            "kernels": [asdict(item) for item in kernels],
        }
    )
    _write_receipt(output, receipt)
    return {"PASS": 0, "FAIL": 1, "INVALID": 2}[overall]


if __name__ == "__main__":
    raise SystemExit(main())
