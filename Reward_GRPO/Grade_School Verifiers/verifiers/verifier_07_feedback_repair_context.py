# Policy 7 verifier: authenticate Grade School two-turn response health, feedback delivery, targeted repair, diagnostic reduction, and final success.
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from _grade_school_common import KernelReceipt, bundle_parser, excluded, failed, finalize_receipt, invalid, load_bound_bytes, load_bound_json, output_preflight_failed, passed, prepare_output, safe_relative, sha256


PHASE_ORDER = {"configure": 0, "compile": 1, "link": 2, "tests": 3, "pass": 4}


@dataclass(frozen=True)
class TrajectoryContext:
    bundle_dir: Path
    output_dir: Path
    manifest: dict[str, Any]


def _turn(ctx: TrajectoryContext, number: int) -> dict[str, Any]:
    turns = ctx.manifest.get("turns")
    if not isinstance(turns, list):
        raise ValueError("turns must be a list")
    matches = [item for item in turns if isinstance(item, dict) and item.get("turn") == number]
    if len(matches) != 1:
        raise ValueError(f"manifest must contain exactly one turn {number}")
    return matches[0]


def _evaluation(ctx: TrajectoryContext, number: int) -> dict[str, Any]:
    return load_bound_json(ctx.bundle_dir, _turn(ctx, number)["evaluation_receipt"])


def _turn_one_passed(ctx: TrajectoryContext) -> bool:
    evaluation = _evaluation(ctx, 1)
    return evaluation.get("passed") is True and evaluation.get("official_test_count") == 8 and evaluation.get("passed_test_count") == 8 and evaluation.get("timed_out") is False


def verify_7a_first_response_health(ctx: TrajectoryContext) -> KernelReceipt:
    turn = _turn(ctx, 1)
    response = load_bound_bytes(ctx.bundle_dir, turn["response"])
    receipt = load_bound_json(ctx.bundle_dir, turn["response_receipt"])
    facts = {"status": receipt.get("status"), "num_error_outputs": receipt.get("num_error_outputs"), "num_exhausted_context_windows": receipt.get("num_exhausted_context_windows"), "response_sha256": turn["response"]["sha256"]}
    healthy = receipt.get("status") == "completed" and receipt.get("num_error_outputs") == 0 and receipt.get("num_exhausted_context_windows") == 0 and bool(response.strip())
    return passed("7A", "turn 1 response was healthy", facts=facts) if healthy else failed("7A", "turn 1 response health failed", facts=facts)


def verify_7b_feedback_delivery(ctx: TrajectoryContext) -> KernelReceipt:
    if _turn_one_passed(ctx):
        return excluded("7B", "turn 1 already passed")
    first = _turn(ctx, 1)
    second = _turn(ctx, 2)
    generated = load_bound_bytes(ctx.bundle_dir, first["generated_feedback"])
    delivered = load_bound_bytes(ctx.bundle_dir, second["delivered_feedback"])
    facts = {"generated_sha256": first["generated_feedback"]["sha256"], "delivered_sha256": second["delivered_feedback"]["sha256"], "nonempty": bool(generated)}
    if generated and generated == delivered:
        return passed("7B", "feedback was delivered byte-for-byte", facts=facts)
    return failed("7B", "feedback was missing or altered", facts=facts)


def verify_7c_targeted_repair(ctx: TrajectoryContext) -> KernelReceipt:
    if _turn_one_passed(ctx):
        return excluded("7C", "turn 1 already passed")
    first = _turn(ctx, 1)
    second = _turn(ctx, 2)
    evaluation = load_bound_json(ctx.bundle_dir, first["evaluation_receipt"])
    diff = load_bound_bytes(ctx.bundle_dir, second["edit_diff"]).decode("utf-8", errors="replace")
    first_source = load_bound_bytes(ctx.bundle_dir, first["source_snapshot"])
    second_source = load_bound_bytes(ctx.bundle_dir, second["source_snapshot"])
    diagnostics = evaluation.get("diagnostics")
    if not isinstance(diagnostics, list):
        raise ValueError("turn-1 diagnostics must be a list")
    matched: list[str] = []
    for diagnostic in diagnostics:
        if not isinstance(diagnostic, dict):
            raise ValueError("diagnostic must be an object")
        files = diagnostic.get("target_files")
        tokens = diagnostic.get("target_tokens")
        if not isinstance(files, list) or not isinstance(tokens, list):
            raise ValueError("diagnostic targets must be lists")
        if any((f"+++ b/{name}" in diff or f"+++ {name}" in diff) for name in files if isinstance(name, str)) and any(token in diff for token in tokens if isinstance(token, str)):
            matched.append(str(diagnostic.get("id")))
    facts = {"source_changed": first_source != second_source, "matched_diagnostic_ids": matched, "diff_sha256": second["edit_diff"]["sha256"]}
    if first_source != second_source and matched:
        return passed("7C", "turn 2 targeted a reported diagnostic", facts=facts)
    return failed("7C", "turn 2 was absent or unrelated to reported diagnostics", facts=facts)


def verify_7d_diagnostic_reduction(ctx: TrajectoryContext) -> KernelReceipt:
    if _turn_one_passed(ctx):
        return excluded("7D", "turn 1 already passed")
    first = _evaluation(ctx, 1)
    second = _evaluation(ctx, 2)
    first_diagnostics = first.get("diagnostics")
    second_diagnostics = second.get("diagnostics")
    if not isinstance(first_diagnostics, list) or not isinstance(second_diagnostics, list):
        raise ValueError("diagnostics must be lists")
    first_ids = {str(item["id"]) for item in first_diagnostics if isinstance(item, dict) and "id" in item}
    second_ids = {str(item["id"]) for item in second_diagnostics if isinstance(item, dict) and "id" in item}
    first_phase = first.get("phase")
    second_phase = second.get("phase")
    if first_phase not in PHASE_ORDER or second_phase not in PHASE_ORDER:
        raise ValueError("unknown evaluation phase")
    remaining = first_ids & second_ids
    improved = len(remaining) < len(first_ids) and PHASE_ORDER[second_phase] >= PHASE_ORDER[first_phase]
    facts = {"turn_1_ids": sorted(first_ids), "turn_2_ids": sorted(second_ids), "remaining_turn_1_ids": sorted(remaining), "turn_1_phase": first_phase, "turn_2_phase": second_phase}
    return passed("7D", "diagnostics decreased without phase regression", facts=facts) if improved else failed("7D", "diagnostics did not decrease or evaluation regressed", facts=facts)


def verify_7e_pass_within_two_turns(ctx: TrajectoryContext) -> KernelReceipt:
    observations: list[dict[str, Any]] = []
    for number in (1, 2):
        try:
            evaluation = _evaluation(ctx, number)
        except (KeyError, ValueError):
            if number == 2 and _turn_one_passed(ctx):
                continue
            raise
        complete = evaluation.get("task_id") == "grade-school" and evaluation.get("official_test_count") == 8 and evaluation.get("passed_test_count") == 8 and evaluation.get("passed") is True and evaluation.get("timed_out") is False
        observations.append({"turn": number, "complete_pass": complete, "phase": evaluation.get("phase")})
        if complete:
            return passed("7E", f"turn {number} achieved an authenticated 8/8 pass", facts={"turns": observations})
    return failed("7E", "no authenticated 8/8 pass occurred within two turns", facts={"turns": observations})


def _build_context(bundle_dir: Path, output_dir: Path) -> tuple[TrajectoryContext | None, str]:
    try:
        root = bundle_dir.resolve(strict=True)
        if not root.is_dir() or root.is_symlink():
            return None, "bundle is not a real directory"
        ready, message = prepare_output(output_dir, root)
        if not ready:
            return None, message
        manifest_path = root / "trajectory_bundle.json"
        if not manifest_path.is_file() or manifest_path.is_symlink():
            return None, "trajectory_bundle.json is missing or unsafe"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or manifest.get("schema_version") != 1 or manifest.get("task_id") != "grade-school" or manifest.get("turn_limit") != 2:
            return None, "trajectory manifest identity is invalid"
        return TrajectoryContext(root, output_dir.resolve(), manifest), "ready"
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return None, f"trajectory preflight failed: {error}"


def main() -> int:
    parser = bundle_parser("Feedback Repair and Two-Turn Progress")
    args = parser.parse_args()
    context, error = _build_context(args.bundle_dir, args.output_dir)
    if context is None:
        if output_preflight_failed(error):
            return 2
        return finalize_receipt(args.output_dir, "7", "Feedback Repair and Two-Turn Progress", [], Path(__file__), preflight_error=error)
    kernels: list[KernelReceipt] = []
    for function in [verify_7a_first_response_health, verify_7b_feedback_delivery, verify_7c_targeted_repair, verify_7d_diagnostic_reduction, verify_7e_pass_within_two_turns]:
        try:
            kernels.append(function(context))
        except (OSError, KeyError, ValueError, json.JSONDecodeError) as error_value:
            kernel_id = function.__name__.split("_")[1].upper()
            kernels.append(invalid(kernel_id, f"trajectory evidence is invalid: {error_value}"))
    extra = {"bundle_manifest_sha256": sha256(context.bundle_dir / "trajectory_bundle.json")}
    return finalize_receipt(args.output_dir, "7", "Feedback Repair and Two-Turn Progress", kernels, Path(__file__), extra=extra)


if __name__ == "__main__":
    sys.exit(main())
