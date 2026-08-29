
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


ARTIFACT_FIELDS = (
    "response",
    "response_receipt",
    "source_snapshot",
    "evaluation_receipt",
    "generated_feedback",
    "delivered_feedback",
    "edit_diff",
)
REQUIRED_TURN_FIELDS = (
    "response",
    "response_receipt",
    "source_snapshot",
    "evaluation_receipt",
)
PHASE_RANK = {"configure": 0, "compile": 1, "link": 2, "tests": 3, "pass": 4}
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


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


def _turn(ctx: VerifierContext, number: int) -> dict[str, Any] | None:
    for value in ctx.manifest.get("turns", []):
        if isinstance(value, dict) and value.get("turn") == number:
            return value
    return None


def _artifact(ctx: VerifierContext, turn: dict[str, Any], field_name: str) -> tuple[Path, str]:
    reference = turn.get(field_name)
    if not isinstance(reference, dict):
        raise EvidenceError(f"{field_name} reference is absent")
    relative = reference.get("path")
    expected = reference.get("sha256")
    if not isinstance(relative, str) or not relative or not isinstance(expected, str):
        raise EvidenceError(f"{field_name} reference is malformed")
    if SHA256_PATTERN.fullmatch(expected) is None:
        raise EvidenceError(f"{field_name} SHA-256 is malformed")
    posix = PurePosixPath(relative)
    if posix.is_absolute() or ".." in posix.parts or "." in posix.parts:
        raise EvidenceError(f"{field_name} path is unsafe")
    raw = ctx.bundle_dir.joinpath(*posix.parts)
    resolved = raw.resolve()
    if resolved == ctx.bundle_dir or ctx.bundle_dir not in resolved.parents:
        raise EvidenceError(f"{field_name} path escapes the bundle")
    cursor = raw
    while cursor != ctx.bundle_dir:
        if cursor.is_symlink():
            raise EvidenceError(f"{field_name} path uses a symlink")
        cursor = cursor.parent
    if not raw.is_file():
        raise EvidenceError(f"{field_name} artifact is missing")
    observed = _sha256(raw)
    if observed != expected:
        raise EvidenceError(f"{field_name} SHA-256 mismatch")
    return raw, observed


def _json_artifact(ctx: VerifierContext, turn: dict[str, Any], field_name: str) -> tuple[dict[str, Any], Path, str]:
    path, digest = _artifact(ctx, turn, field_name)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EvidenceError(f"{field_name} is not valid JSON: {error}") from error
    if not isinstance(value, dict):
        raise EvidenceError(f"{field_name} must contain a JSON object")
    return value, path, digest


def _response_receipt(ctx: VerifierContext, turn: dict[str, Any]) -> tuple[dict[str, Any], Path, str]:
    receipt, path, digest = _json_artifact(ctx, turn, "response_receipt")
    status = receipt.get("status")
    error_outputs = receipt.get("num_error_outputs")
    exhausted = receipt.get("num_exhausted_context_windows")
    if status not in {"completed", "model_error", "context_exhausted"}:
        raise EvidenceError("response status is invalid")
    if not _is_int(error_outputs) or error_outputs < 0:
        raise EvidenceError("num_error_outputs must be a nonnegative integer")
    if not _is_int(exhausted) or exhausted < 0:
        raise EvidenceError("num_exhausted_context_windows must be a nonnegative integer")
    return receipt, path, digest


def _evaluation_receipt(ctx: VerifierContext, turn: dict[str, Any]) -> tuple[dict[str, Any], Path, str]:
    receipt, path, digest = _json_artifact(ctx, turn, "evaluation_receipt")
    if receipt.get("task_id") != "bank-account":
        raise EvidenceError("evaluation task identity is not bank-account")
    phase = receipt.get("phase")
    selected = receipt.get("official_test_count")
    passed_count = receipt.get("passed_test_count")
    passed = receipt.get("passed")
    timed_out = receipt.get("timed_out")
    diagnostics = receipt.get("diagnostics")
    if phase not in PHASE_RANK:
        raise EvidenceError("evaluation phase is invalid")
    if not _is_int(selected) or selected < 0:
        raise EvidenceError("official_test_count must be a nonnegative integer")
    if not _is_int(passed_count) or passed_count < 0 or passed_count > selected:
        raise EvidenceError("passed_test_count is invalid")
    if not isinstance(passed, bool) or not isinstance(timed_out, bool):
        raise EvidenceError("evaluation status fields must be boolean")
    if not isinstance(diagnostics, list):
        raise EvidenceError("diagnostics must be a list")
    for diagnostic in diagnostics:
        if not isinstance(diagnostic, dict) or not isinstance(diagnostic.get("id"), str) or not diagnostic["id"]:
            raise EvidenceError("each diagnostic requires a stable id")
        files = diagnostic.get("target_files")
        tokens = diagnostic.get("target_tokens")
        if not isinstance(files, list) or not files or not all(isinstance(item, str) and item for item in files):
            raise EvidenceError("each diagnostic requires target_files")
        if not isinstance(tokens, list) or not tokens or not all(isinstance(item, str) and item for item in tokens):
            raise EvidenceError("each diagnostic requires target_tokens")
    full_pass = phase == "pass" and selected == 17 and passed_count == 17 and passed and not timed_out
    if passed != full_pass:
        raise EvidenceError("evaluation pass fields are contradictory")
    if full_pass and diagnostics:
        raise EvidenceError("a complete pass cannot retain active diagnostics")
    return receipt, path, digest


def _pass(kernel_id: str, summary: str, facts: dict[str, Any], artifacts: dict[str, str]) -> KernelReceipt:
    return KernelReceipt(kernel_id, 1, "pass", summary, facts, artifacts)


def _fail(kernel_id: str, summary: str, facts: dict[str, Any] | None = None, artifacts: dict[str, str] | None = None) -> KernelReceipt:
    return KernelReceipt(kernel_id, -1, "fail", summary, facts or {}, artifacts or {})


def _invalid(kernel_id: str, summary: str, facts: dict[str, Any] | None = None) -> KernelReceipt:
    return KernelReceipt(kernel_id, None, "invalid", summary, facts or {}, {})


def _is_full_pass(receipt: dict[str, Any]) -> bool:
    return (
        receipt.get("phase") == "pass"
        and receipt.get("official_test_count") == 17
        and receipt.get("passed_test_count") == 17
        and receipt.get("passed") is True
        and receipt.get("timed_out") is False
    )


def _preflight(ctx: VerifierContext) -> tuple[bool, str, dict[str, Any]]:
    if ctx.manifest_error is not None:
        return False, ctx.manifest_error, {}
    manifest = ctx.manifest
    if manifest.get("schema_version") != 1:
        return False, "unsupported trajectory schema", {}
    if manifest.get("task_id") != "bank-account":
        return False, "bundle task identity is not bank-account", {}
    if manifest.get("turn_limit") != 2:
        return False, "turn_limit must be exactly 2", {}
    turns = manifest.get("turns")
    if not isinstance(turns, list) or len(turns) not in {1, 2}:
        return False, "bundle must contain one or two turns", {}
    expected_numbers = list(range(1, len(turns) + 1))
    if any(not isinstance(turn, dict) for turn in turns) or [turn.get("turn") for turn in turns] != expected_numbers:
        return False, "turns must be ordered as 1 and optional 2", {}
    artifacts: dict[str, str] = {}
    try:
        for turn in turns:
            for field_name in REQUIRED_TURN_FIELDS:
                if field_name not in turn:
                    raise EvidenceError(f"turn {turn['turn']} lacks {field_name}")
            for field_name in ARTIFACT_FIELDS:
                if field_name in turn:
                    path, digest = _artifact(ctx, turn, field_name)
                    artifacts[f"turn{turn['turn']}.{field_name}:{path.relative_to(ctx.bundle_dir).as_posix()}"] = digest
        _response_receipt(ctx, turns[0])
        _evaluation_receipt(ctx, turns[0])
        if len(turns) == 2:
            _response_receipt(ctx, turns[1])
            _evaluation_receipt(ctx, turns[1])
    except EvidenceError as error:
        return False, str(error), {"authenticated_artifacts": artifacts}
    return True, "trajectory bundle and declared artifacts authenticated", {"authenticated_artifacts": artifacts}


def verify_7a_first_response_health(ctx: VerifierContext) -> KernelReceipt:
    turn = _turn(ctx, 1)
    if turn is None:
        return _invalid("7A", "turn 1 is unavailable")
    try:
        response_path, response_digest = _artifact(ctx, turn, "response")
        receipt, receipt_path, receipt_digest = _response_receipt(ctx, turn)
        response_text = response_path.read_text(encoding="utf-8", errors="replace")
    except (EvidenceError, OSError) as error:
        return _invalid("7A", str(error))
    facts = {
        "response_status": receipt["status"],
        "response_bytes": response_path.stat().st_size,
        "num_error_outputs": receipt["num_error_outputs"],
        "num_exhausted_context_windows": receipt["num_exhausted_context_windows"],
    }
    artifacts = {response_path.name: response_digest, receipt_path.name: receipt_digest}
    passed = (
        receipt["status"] == "completed"
        and receipt["num_error_outputs"] == 0
        and receipt["num_exhausted_context_windows"] == 0
        and bool(response_text.strip())
    )
    if passed:
        return _pass("7A", "first response completed without model or context error", facts, artifacts)
    return _fail("7A", "first response had a model/context error or no completed content", facts, artifacts)


def verify_7b_feedback_delivery(ctx: VerifierContext) -> KernelReceipt:
    first = _turn(ctx, 1)
    second = _turn(ctx, 2)
    if first is None:
        return _invalid("7B", "turn 1 is unavailable")
    if "generated_feedback" not in first or second is None or "delivered_feedback" not in second:
        return _fail("7B", "generated feedback was not delivered to a second turn")
    try:
        generated_path, generated_digest = _artifact(ctx, first, "generated_feedback")
        delivered_path, delivered_digest = _artifact(ctx, second, "delivered_feedback")
        generated = generated_path.read_bytes()
        delivered = delivered_path.read_bytes()
    except (EvidenceError, OSError) as error:
        return _invalid("7B", str(error))
    facts = {
        "generated_bytes": len(generated),
        "delivered_bytes": len(delivered),
        "byte_identical": generated == delivered,
    }
    artifacts = {"generated_feedback": generated_digest, "delivered_feedback": delivered_digest}
    if generated and generated == delivered:
        return _pass("7B", "turn 2 received the exact nonempty evaluator feedback", facts, artifacts)
    return _fail("7B", "turn 2 feedback was empty or differed from evaluator output", facts, artifacts)


def _diff_blocks(text: str) -> tuple[dict[str, str], int]:
    blocks: dict[str, list[str]] = {}
    current: str | None = None
    changed_lines = 0
    for line in text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            current = parts[3][2:] if len(parts) >= 4 and parts[3].startswith("b/") else None
            if current is not None:
                blocks.setdefault(current, []).append(line)
            continue
        if line.startswith("+++ "):
            value = line[4:].split("\t", 1)[0]
            if value != "/dev/null":
                current = value[2:] if value.startswith("b/") else value
                blocks.setdefault(current, []).append(line)
            continue
        if current is not None:
            blocks.setdefault(current, []).append(line)
            if (line.startswith("+") and not line.startswith("+++")) or (line.startswith("-") and not line.startswith("---")):
                changed_lines += 1
    return {name: "\n".join(lines) for name, lines in blocks.items()}, changed_lines


def _file_matches(observed: str, expected: str) -> bool:
    observed_path = PurePosixPath(observed)
    expected_path = PurePosixPath(expected)
    return observed_path == expected_path or observed_path.name == expected_path.name


def verify_7c_targeted_repair(ctx: VerifierContext) -> KernelReceipt:
    first = _turn(ctx, 1)
    second = _turn(ctx, 2)
    if first is None:
        return _invalid("7C", "turn 1 is unavailable")
    if second is None or "edit_diff" not in second:
        return _fail("7C", "no second-turn edit diff was recorded")
    try:
        first_eval, first_eval_path, first_eval_digest = _evaluation_receipt(ctx, first)
        first_source, first_source_digest = _artifact(ctx, first, "source_snapshot")
        second_source, second_source_digest = _artifact(ctx, second, "source_snapshot")
        diff_path, diff_digest = _artifact(ctx, second, "edit_diff")
        diff_text = diff_path.read_text(encoding="utf-8", errors="replace")
    except (EvidenceError, OSError) as error:
        return _invalid("7C", str(error))
    blocks, changed_lines = _diff_blocks(diff_text)
    targeted: list[str] = []
    for diagnostic in first_eval["diagnostics"]:
        matched = False
        for observed_file, block in blocks.items():
            file_ok = any(_file_matches(observed_file, expected) for expected in diagnostic["target_files"])
            token_ok = any(token in block for token in diagnostic["target_tokens"])
            if file_ok and token_ok:
                matched = True
                break
        if matched:
            targeted.append(diagnostic["id"])
    facts = {
        "changed_file_count": len(blocks),
        "changed_line_count": changed_lines,
        "source_snapshot_changed": first_source_digest != second_source_digest,
        "targeted_diagnostic_ids": targeted,
        "turn1_diagnostic_count": len(first_eval["diagnostics"]),
    }
    artifacts = {
        first_eval_path.name: first_eval_digest,
        f"turn1_source:{first_source.name}": first_source_digest,
        f"turn2_source:{second_source.name}": second_source_digest,
        diff_path.name: diff_digest,
    }
    passed = changed_lines > 0 and first_source_digest != second_source_digest and bool(targeted)
    if passed:
        return _pass("7C", "second edit touched a file and token named by turn-1 diagnostics", facts, artifacts)
    return _fail("7C", "second edit did not target an authenticated failing region", facts, artifacts)


def verify_7d_diagnostic_reduction(ctx: VerifierContext) -> KernelReceipt:
    first = _turn(ctx, 1)
    second = _turn(ctx, 2)
    if first is None:
        return _invalid("7D", "turn 1 is unavailable")
    if second is None:
        return _fail("7D", "no second evaluation exists")
    try:
        first_eval, first_path, first_digest = _evaluation_receipt(ctx, first)
        second_eval, second_path, second_digest = _evaluation_receipt(ctx, second)
    except EvidenceError as error:
        return _invalid("7D", str(error))
    first_counts = Counter(item["id"] for item in first_eval["diagnostics"])
    second_counts = Counter(item["id"] for item in second_eval["diagnostics"])
    first_total = sum(first_counts.values())
    remaining = sum(min(count, second_counts[diagnostic_id]) for diagnostic_id, count in first_counts.items())
    phase_not_regressed = PHASE_RANK[second_eval["phase"]] >= PHASE_RANK[first_eval["phase"]]
    facts = {
        "turn1_phase": first_eval["phase"],
        "turn2_phase": second_eval["phase"],
        "turn1_targeted_diagnostic_occurrences": first_total,
        "turn2_remaining_occurrences": remaining,
        "phase_not_regressed": phase_not_regressed,
    }
    artifacts = {"turn1_evaluation": first_digest, "turn2_evaluation": second_digest}
    passed = first_total > 0 and remaining < first_total and phase_not_regressed
    if passed:
        return _pass("7D", "reported diagnostics were reduced without evaluation-stage regression", facts, artifacts)
    return _fail("7D", "reported diagnostics persisted or evaluation moved backward", facts, artifacts)


def verify_7e_pass_within_two_turns(ctx: VerifierContext) -> KernelReceipt:
    evaluated: list[dict[str, Any]] = []
    artifacts: dict[str, str] = {}
    for number in (1, 2):
        turn = _turn(ctx, number)
        if turn is None:
            continue
        try:
            receipt, path, digest = _evaluation_receipt(ctx, turn)
        except EvidenceError as error:
            return _invalid("7E", str(error))
        evaluated.append({
            "turn": number,
            "phase": receipt["phase"],
            "selected": receipt["official_test_count"],
            "passed_count": receipt["passed_test_count"],
            "passed": receipt["passed"],
            "timed_out": receipt["timed_out"],
        })
        artifacts[f"turn{number}_evaluation:{path.name}"] = digest
        if _is_full_pass(receipt):
            return _pass("7E", f"all 17 official tests passed on turn {number}", {"passing_turn": number, "evaluations": evaluated}, artifacts)
    return _fail("7E", "no complete 17/17 pass occurred within two turns", {"evaluations": evaluated}, artifacts)


def verify_policy_7(ctx: VerifierContext) -> dict[str, Any]:
    preflight_ok, preflight_summary, preflight_facts = _preflight(ctx)
    if not preflight_ok:
        results = [_invalid(kernel_id, preflight_summary, preflight_facts) for kernel_id in ("7A", "7B", "7C", "7D", "7E")]
        applicable = ["7A", "7B", "7C", "7D", "7E"]
        excluded: dict[str, Any] = {}
    else:
        first = _turn(ctx, 1)
        if first is None:
            results = [_invalid(kernel_id, "turn 1 is unavailable") for kernel_id in ("7A", "7B", "7C", "7D", "7E")]
            applicable = ["7A", "7B", "7C", "7D", "7E"]
            excluded = {}
        else:
            try:
                first_eval, _, _ = _evaluation_receipt(ctx, first)
            except EvidenceError as error:
                results = [_invalid(kernel_id, str(error)) for kernel_id in ("7A", "7B", "7C", "7D", "7E")]
                applicable = ["7A", "7B", "7C", "7D", "7E"]
                excluded = {}
            else:
                if _is_full_pass(first_eval):
                    results = [verify_7a_first_response_health(ctx), verify_7e_pass_within_two_turns(ctx)]
                    applicable = ["7A", "7E"]
                    excluded = {
                        kernel_id: {
                            "status": "not_applicable",
                            "reason": "not_needed_first_turn_pass",
                            "included_in_kernel_sum": False,
                        }
                        for kernel_id in ("7B", "7C", "7D")
                    }
                else:
                    results = [
                        verify_7a_first_response_health(ctx),
                        verify_7b_feedback_delivery(ctx),
                        verify_7c_targeted_repair(ctx),
                        verify_7d_diagnostic_reduction(ctx),
                        verify_7e_pass_within_two_turns(ctx),
                    ]
                    applicable = ["7A", "7B", "7C", "7D", "7E"]
                    excluded = {}
    invalid = any(result.kernel is None for result in results)
    full_pass = len(applicable)
    kernel_sum = None if invalid else sum(result.kernel for result in results if result.kernel is not None)
    status = "invalid" if invalid else "pass" if kernel_sum == full_pass else "fail"
    return {
        "schema_version": 1,
        "policy_id": "bank-account-policy-07-feedback-repair-context-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "kernel_model": {"pass": 1, "fail": -1, "infrastructure": "INVALID"},
        "kernel_sum": kernel_sum,
        "kernel_range": [-full_pass, full_pass],
        "full_pass_required": full_pass,
        "applicable_kernel_ids": applicable,
        "excluded_conditions": excluded,
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
        raise ValueError("output directory must be outside the trajectory bundle")
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
    manifest_path = bundle_dir / "trajectory_bundle.json"
    manifest: dict[str, Any] = {}
    manifest_sha256: str | None = None
    manifest_error: str | None = None
    try:
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise EvidenceError("trajectory_bundle.json is missing or is a symlink")
        manifest_sha256 = _sha256(manifest_path)
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise EvidenceError("trajectory_bundle.json must contain an object")
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
    receipt = verify_policy_7(ctx)
    receipt_path = output_dir / "verification_receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: receipt[key] for key in ("status", "kernel_sum", "passed_kernels", "failed_kernels")}, sort_keys=True))
    print(receipt_path)
    return 0 if receipt["status"] == "pass" else 2 if receipt["status"] == "invalid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
