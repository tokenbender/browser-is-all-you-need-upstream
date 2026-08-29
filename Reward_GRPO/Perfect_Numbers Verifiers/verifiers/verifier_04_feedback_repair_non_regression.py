
from __future__ import annotations

import argparse
import difflib
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

sys.dont_write_bytecode = True

from verifier_01_exact_public_api import KernelReceipt
from verifier_01_exact_public_api import PreflightError
from verifier_01_exact_public_api import _combined_digest
from verifier_01_exact_public_api import _fail
from verifier_01_exact_public_api import _pass
from verifier_01_exact_public_api import _sha256


TASK_ID = "perfect-numbers"
POLICY_ID = "PN-E04"
OFFICIAL_TEST_SHA256 = "fa206f8feaa1f8aa63986db34fc96458b30ab0325c0855fd6659ab7cbcb50be3"
AUTHORIZED_FILES = ("perfect_numbers.h", "perfect_numbers.cpp")
TEST_UUIDS = frozenset(
    {
        "163e8e86-7bfd-4ee2-bd68-d083dc3381a3",
        "169a7854-0431-4ae0-9815-c3b6d967436d",
        "ee3627c4-7b36-4245-ba7c-8727d585f402",
        "80ef7cf8-9ea8-49b9-8b2d-d9cb3db3ed7e",
        "3e300e0d-1a12-4f11-8c48-d1027165ab60",
        "ec7792e6-8786-449c-b005-ce6dd89a772b",
        "e610fdc7-2b6e-43c3-a51c-b70fb37413ba",
        "0beb7f66-753a-443f-8075-ad7fbd9018f3",
        "1c802e45-b4c6-4962-93d7-1cad245821ef",
        "47dd569f-9e5a-4a11-9a47-a4e91c8c28aa",
        "a696dec8-6147-4d68-afad-d38de5476a56",
        "72445cee-660c-4d75-8506-6c40089dc302",
        "2d72ce2c-6802-49ac-8ece-c790ba3dae13",
    }
)
ALLOWED_DIAGNOSTICS = frozenset(
    {
        "PN-E01-API",
        "PN-E02-ONE",
        "PN-E03-ZERO-NO-THROW",
        "PN-E03-ZERO-WRONG-TYPE",
        "PN-E03-NEGATIVE-NO-THROW",
        "PN-E03-NEGATIVE-WRONG-TYPE",
    }
)
STAGE_ORDER = {"response": 0, "compile": 1, "link": 2, "test": 3, "complete": 4}


@dataclass(frozen=True)
class BundleContext:
    bundle_dir: Path
    output_dir: Path
    manifest: dict[str, Any]
    file_hashes: dict[str, str]
    turn_1: dict[str, Any]
    turn_2: dict[str, Any]
    changed_files: tuple[str, ...]
    diff_sha256: str


def _json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PreflightError(f"invalid JSON artifact {path.name}: {error}") from error
    if not isinstance(value, dict):
        raise PreflightError(f"JSON artifact is not an object: {path.name}")
    return value


def _canonical_diff(bundle_dir: Path) -> tuple[str, tuple[str, ...]]:
    chunks: list[str] = []
    changed: list[str] = []
    for filename in AUTHORIZED_FILES:
        before_path = bundle_dir / "turn_1" / "source" / filename
        after_path = bundle_dir / "turn_2" / "source" / filename
        before = before_path.read_text(encoding="utf-8")
        after = after_path.read_text(encoding="utf-8")
        if before == after:
            continue
        changed.append(filename)
        chunks.extend(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"turn_1/{filename}",
                tofile=f"turn_2/{filename}",
            )
        )
    return "".join(chunks), tuple(changed)


def _validate_response_receipt(bundle_dir: Path, turn: str) -> None:
    response_path = bundle_dir / turn / "response.txt"
    receipt = _json_object(bundle_dir / turn / "response_receipt.json")
    if receipt.get("status") != "completed":
        raise PreflightError(f"{turn} response did not complete")
    if receipt.get("response_sha256") != _sha256(response_path):
        raise PreflightError(f"{turn} response receipt hash mismatch")
    if response_path.stat().st_size == 0:
        raise PreflightError(f"{turn} response is empty")


def _derive_diagnostics(stdout: str, stderr: str) -> set[str]:
    text = f"{stdout}\n{stderr}"
    lowered = text.lower()
    derived = {diagnostic for diagnostic in ALLOWED_DIAGNOSTICS if diagnostic in text}
    if "error:" in lowered and "classification" in lowered and "not a member" in lowered:
        derived.add("PN-E01-API")
    if ("classify(1)" in lowered or "edge case (no factors other than itself)" in lowered) and "failed" in lowered:
        derived.add("PN-E02-ONE")
    if "classify(0)" in lowered:
        if "no exception" in lowered:
            derived.add("PN-E03-ZERO-NO-THROW")
        elif "unexpected exception" in lowered or "wrong exception" in lowered or "invalid_argument" in lowered:
            derived.add("PN-E03-ZERO-WRONG-TYPE")
    if "classify(-1)" in lowered or "negative integer is rejected" in lowered:
        if "no exception" in lowered:
            derived.add("PN-E03-NEGATIVE-NO-THROW")
        elif "unexpected exception" in lowered or "wrong exception" in lowered or "invalid_argument" in lowered:
            derived.add("PN-E03-NEGATIVE-WRONG-TYPE")
    return derived


def _validate_evaluation_receipt(bundle_dir: Path, turn: str) -> dict[str, Any]:
    receipt = _json_object(bundle_dir / turn / "evaluation_receipt.json")
    if receipt.get("task_id") != TASK_ID:
        raise PreflightError(f"{turn} evaluation task identity mismatch")
    if receipt.get("official_test_sha256") != OFFICIAL_TEST_SHA256:
        raise PreflightError(f"{turn} official test hash mismatch")
    source_dir = bundle_dir / turn / "source"
    if receipt.get("candidate_source_sha256") != _combined_digest(source_dir, AUTHORIZED_FILES):
        raise PreflightError(f"{turn} evaluation source binding mismatch")
    stdout_path = bundle_dir / turn / "evaluation.stdout.log"
    stderr_path = bundle_dir / turn / "evaluation.stderr.log"
    if receipt.get("stdout_sha256") != _sha256(stdout_path):
        raise PreflightError(f"{turn} stdout binding mismatch")
    if receipt.get("stderr_sha256") != _sha256(stderr_path):
        raise PreflightError(f"{turn} stderr binding mismatch")
    diagnostics = receipt.get("diagnostics")
    if not isinstance(diagnostics, list) or any(not isinstance(item, str) for item in diagnostics):
        raise PreflightError(f"{turn} diagnostics are malformed")
    if len(diagnostics) != len(set(diagnostics)) or not set(diagnostics).issubset(ALLOWED_DIAGNOSTICS):
        raise PreflightError(f"{turn} diagnostics contain duplicates or unsupported IDs")
    stdout = stdout_path.read_text(encoding="utf-8")
    stderr = stderr_path.read_text(encoding="utf-8")
    if set(diagnostics) != _derive_diagnostics(stdout, stderr):
        raise PreflightError(f"{turn} diagnostic IDs disagree with raw evaluation logs")
    test_results = receipt.get("test_results")
    if not isinstance(test_results, dict) or set(test_results) != TEST_UUIDS:
        raise PreflightError(f"{turn} per-test UUID set is incomplete")
    if any(value not in {"pass", "fail", "blocked"} for value in test_results.values()):
        raise PreflightError(f"{turn} contains an invalid per-test outcome")
    passed = sum(value == "pass" for value in test_results.values())
    failed = sum(value == "fail" for value in test_results.values())
    selected = passed + failed
    if receipt.get("passed_tests") != passed or receipt.get("failed_tests") != failed or receipt.get("selected_tests") != selected:
        raise PreflightError(f"{turn} test counters disagree with per-test outcomes")
    stage = receipt.get("stage")
    if stage not in STAGE_ORDER:
        raise PreflightError(f"{turn} stage is invalid")
    for name in ("build_succeeded", "evaluation_completed", "timed_out"):
        if not isinstance(receipt.get(name), bool):
            raise PreflightError(f"{turn} field is not boolean: {name}")
    return receipt


def _prepare(args: argparse.Namespace) -> BundleContext:
    bundle_input = args.bundle_dir
    output_input = args.output_dir
    bundle_dir = bundle_input.resolve()
    if output_input.is_symlink():
        raise PreflightError("output directory must not be a symlink")
    output_dir = output_input.resolve()
    if bundle_input.is_symlink():
        raise PreflightError("bundle directory must not be a symlink")
    if not bundle_dir.is_dir():
        raise PreflightError("bundle directory does not exist")
    if output_dir == bundle_dir or output_dir.is_relative_to(bundle_dir):
        raise PreflightError("output directory must be outside the bundle directory")
    if output_dir.exists() and (not output_dir.is_dir() or any(output_dir.iterdir())):
        raise PreflightError("output directory must be new or empty")
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = bundle_dir / "manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise PreflightError("manifest.json is missing or symlinked")
    manifest = _json_object(manifest_path)
    if manifest.get("schema_version") != 1 or manifest.get("task_id") != TASK_ID:
        raise PreflightError("bundle schema or task identity mismatch")
    if manifest.get("official_test_sha256") != OFFICIAL_TEST_SHA256:
        raise PreflightError("bundle official test hash mismatch")
    if manifest.get("authorized_files") != list(AUTHORIZED_FILES):
        raise PreflightError("bundle authorized-file contract mismatch")
    declared_files = manifest.get("files")
    if not isinstance(declared_files, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in declared_files.items()):
        raise PreflightError("manifest file bindings are malformed")
    actual_files: set[str] = set()
    for path in bundle_dir.rglob("*"):
        if path == manifest_path:
            continue
        if path.is_symlink():
            raise PreflightError(f"bundle contains symlink: {path.relative_to(bundle_dir)}")
        if path.is_file():
            actual_files.add(path.relative_to(bundle_dir).as_posix())
    if actual_files != set(declared_files):
        raise PreflightError("manifest file set does not match bundle files")
    observed_hashes: dict[str, str] = {}
    for relative, expected in declared_files.items():
        path = bundle_dir / relative
        if not path.is_file() or path.is_symlink():
            raise PreflightError(f"declared bundle file is missing or symlinked: {relative}")
        observed = _sha256(path)
        observed_hashes[relative] = observed
        if observed != expected:
            raise PreflightError(f"bundle file hash mismatch: {relative}")
    generated_feedback = (bundle_dir / "generated_feedback.txt").read_bytes()
    delivered_feedback = (bundle_dir / "delivered_feedback.txt").read_bytes()
    if not generated_feedback or generated_feedback != delivered_feedback:
        raise PreflightError("generated and delivered feedback are empty or differ")
    for turn in ("turn_1", "turn_2"):
        source_dir = bundle_dir / turn / "source"
        if not source_dir.is_dir() or source_dir.is_symlink():
            raise PreflightError(f"source snapshot directory is missing or symlinked: {turn}")
        observed_sources = {
            path.name
            for path in source_dir.iterdir()
            if path.is_file() or path.is_symlink()
        }
        if observed_sources != set(AUTHORIZED_FILES):
            raise PreflightError(f"source snapshot contains missing or unauthorized files: {turn}")
        for filename in AUTHORIZED_FILES:
            source_path = bundle_dir / turn / "source" / filename
            if not source_path.is_file() or source_path.is_symlink():
                raise PreflightError(f"source snapshot is missing or symlinked: {turn}/{filename}")
        _validate_response_receipt(bundle_dir, turn)
    turn_1 = _validate_evaluation_receipt(bundle_dir, "turn_1")
    turn_2 = _validate_evaluation_receipt(bundle_dir, "turn_2")
    expected_diff, changed_files = _canonical_diff(bundle_dir)
    observed_diff_path = bundle_dir / "turn_2" / "turn_2.diff"
    if observed_diff_path.read_text(encoding="utf-8") != expected_diff:
        raise PreflightError("turn_2.diff does not match authenticated source snapshots")
    return BundleContext(
        bundle_dir=bundle_dir,
        output_dir=output_dir,
        manifest=manifest,
        file_hashes=observed_hashes,
        turn_1=turn_1,
        turn_2=turn_2,
        changed_files=changed_files,
        diff_sha256=_sha256(observed_diff_path),
    )


def _full_pass(receipt: dict[str, Any]) -> bool:
    return (
        receipt.get("stage") == "complete"
        and receipt.get("selected_tests") == 13
        and receipt.get("passed_tests") == 13
        and receipt.get("failed_tests") == 0
        and all(value == "pass" for value in receipt.get("test_results", {}).values())
        and receipt.get("timed_out") is False
        and receipt.get("build_succeeded") is True
        and receipt.get("evaluation_completed") is True
    )


def verify_e04_a_targeted_edit(ctx: BundleContext) -> KernelReceipt:
    turn_1_diagnostics = set(ctx.turn_1["diagnostics"])
    required: set[str] = set()
    if "PN-E01-API" in turn_1_diagnostics:
        required.add("perfect_numbers.h")
    if "PN-E02-ONE" in turn_1_diagnostics or any(item.startswith("PN-E03-") for item in turn_1_diagnostics):
        required.add("perfect_numbers.cpp")
    facts = {"turn_1_diagnostics": sorted(turn_1_diagnostics), "required_files": sorted(required), "changed_files": list(ctx.changed_files)}
    artifacts = {"turn_2_diff": ctx.diff_sha256}
    if not turn_1_diagnostics:
        return _fail("E04-A", "turn 1 has no supported repair diagnostic", [], facts)
    if not ctx.changed_files or not required.issubset(ctx.changed_files):
        return _fail("E04-A", "turn 2 did not change every diagnostic-mapped source file", [], facts)
    return _pass("E04-A", "turn 2 changed every diagnostic-mapped source file", [], facts, artifacts)


def verify_e04_b_diagnostic_elimination(ctx: BundleContext) -> KernelReceipt:
    turn_1_diagnostics = set(ctx.turn_1["diagnostics"])
    turn_2_diagnostics = set(ctx.turn_2["diagnostics"])
    remaining = turn_1_diagnostics & turn_2_diagnostics
    facts = {
        "turn_1_diagnostics": sorted(turn_1_diagnostics),
        "turn_2_diagnostics": sorted(turn_2_diagnostics),
        "remaining_diagnostics": sorted(remaining),
    }
    if not turn_1_diagnostics or remaining:
        return _fail("E04-B", "turn 2 did not eliminate every turn-1 diagnostic", [], facts)
    return _pass("E04-B", "turn 2 eliminated every turn-1 diagnostic", [], facts, {})


def verify_e04_c_no_regression(ctx: BundleContext) -> KernelReceipt:
    turn_1_passed = {key for key, value in ctx.turn_1["test_results"].items() if value == "pass"}
    turn_2_passed = {key for key, value in ctx.turn_2["test_results"].items() if value == "pass"}
    regressed = turn_1_passed - turn_2_passed
    stage_regressed = STAGE_ORDER[ctx.turn_2["stage"]] < STAGE_ORDER[ctx.turn_1["stage"]]
    facts = {
        "turn_1_passed": sorted(turn_1_passed),
        "turn_2_passed": sorted(turn_2_passed),
        "regressed_tests": sorted(regressed),
        "turn_1_stage": ctx.turn_1["stage"],
        "turn_2_stage": ctx.turn_2["stage"],
        "stage_regressed": stage_regressed,
    }
    if regressed or stage_regressed:
        return _fail("E04-C", "turn 2 regressed a passing test or evaluation stage", [], facts)
    return _pass("E04-C", "turn 2 preserved every passing test and evaluation stage", [], facts, {})


def verify_e04_d_full_repair(ctx: BundleContext) -> KernelReceipt:
    turn_1_pass = _full_pass(ctx.turn_1)
    turn_2_pass = _full_pass(ctx.turn_2)
    facts = {
        "turn_1_full_pass": turn_1_pass,
        "turn_2_full_pass": turn_2_pass,
        "turn_2_selected_tests": ctx.turn_2["selected_tests"],
        "turn_2_passed_tests": ctx.turn_2["passed_tests"],
        "turn_2_failed_tests": ctx.turn_2["failed_tests"],
    }
    if not (turn_1_pass or turn_2_pass):
        return _fail("E04-D", "trajectory did not reach an authenticated 13/13 pass", [], facts)
    return _pass("E04-D", "trajectory reached an authenticated 13/13 pass", [], facts, {})


def _write_receipt(
    output_dir: Path,
    results: list[KernelReceipt],
    preflight_error: str | None,
    file_hashes: dict[str, str],
    excluded_conditions: list[dict[str, str]],
) -> dict[str, Any]:
    excluded = bool(excluded_conditions) and not results and preflight_error is None
    invalid = preflight_error is not None or any(result.kernel is None for result in results)
    kernel_sum = None if invalid else sum(result.kernel or 0 for result in results)
    status = "invalid" if invalid else "excluded" if excluded else "pass" if all(result.kernel == 1 for result in results) else "fail"
    payload: dict[str, Any] = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "policy_id": POLICY_ID,
        "status": status,
        "preflight_error": preflight_error,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "verifier_source_sha256": _sha256(Path(__file__).resolve()),
        "verifier_dependency_sha256": {
            "verifier_01_exact_public_api.py": _sha256(Path(__file__).resolve().with_name("verifier_01_exact_public_api.py"))
        },
        "bundle_file_sha256": file_hashes,
        "kernel_results": [asdict(result) for result in results],
        "passed_count": sum(result.kernel == 1 for result in results),
        "failed_count": sum(result.kernel == -1 for result in results),
        "invalid_count": sum(result.kernel is None for result in results),
        "kernel_sum": kernel_sum,
        "maximum_kernel_sum": 4,
        "excluded_conditions": excluded_conditions,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "verification_receipt.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    output_dir = args.output_dir.resolve()
    try:
        ctx = _prepare(args)
    except (OSError, UnicodeError, PreflightError) as error:
        bundle_dir = args.bundle_dir.resolve()
        unsafe_output = (
            args.output_dir.is_symlink()
            or output_dir == bundle_dir
            or output_dir.is_relative_to(bundle_dir)
        )
        if unsafe_output or (output_dir.exists() and output_dir.is_dir() and any(output_dir.iterdir())):
            print(f"INVALID: {error}", file=sys.stderr)
            return 2
        payload = _write_receipt(output_dir, [], str(error), {}, [])
        print(json.dumps({"status": payload["status"], "receipt": str(output_dir / "verification_receipt.json")}))
        return 2
    if _full_pass(ctx.turn_1):
        exclusions = [{"condition": "PN-E04", "reason": "not_applicable_turn_1_already_passed"}]
        payload = _write_receipt(ctx.output_dir, [], None, ctx.file_hashes, exclusions)
        print(json.dumps({"status": payload["status"], "kernel_sum": payload["kernel_sum"], "receipt": str(ctx.output_dir / "verification_receipt.json")}))
        return 0
    checks: tuple[Callable[[BundleContext], KernelReceipt], ...] = (
        verify_e04_a_targeted_edit,
        verify_e04_b_diagnostic_elimination,
        verify_e04_c_no_regression,
        verify_e04_d_full_repair,
    )
    results = [check(ctx) for check in checks]
    payload = _write_receipt(ctx.output_dir, results, None, ctx.file_hashes, [])
    print(json.dumps({"status": payload["status"], "kernel_sum": payload["kernel_sum"], "receipt": str(ctx.output_dir / "verification_receipt.json")}))
    return 0 if payload["status"] in {"pass", "excluded"} else 2 if payload["status"] == "invalid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
