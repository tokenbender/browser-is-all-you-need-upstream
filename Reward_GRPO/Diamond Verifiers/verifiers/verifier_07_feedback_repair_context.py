# Policy 7 verifier: authenticate Diamond feedback delivery, targeted repair, diagnostic reduction, and success within two turns.
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Any


TASK_ID = "diamond"
POLICY_ID = "07"
PHASES = {"format-or-apply": 0, "compile": 1, "link": 2, "tests": 3, "pass": 4}
AUTHORIZED = {"diamond.cpp", "diamond.h"}


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


def resolve_ref(bundle: Path, reference: Any, label: str) -> Path:
    if not isinstance(reference, dict) or not isinstance(reference.get("path"), str) or not isinstance(reference.get("sha256"), str):
        raise InvalidEvidence(f"invalid artifact reference: {label}")
    relative = Path(reference["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise InvalidEvidence(f"unsafe relative artifact path: {label}")
    reject_symlink_components(bundle, relative, label)
    unresolved = bundle / relative
    if unresolved.is_symlink():
        raise InvalidEvidence(f"symlink evidence is forbidden: {label}")
    path = unresolved.resolve()
    try:
        path.relative_to(bundle)
    except ValueError as exc:
        raise InvalidEvidence(f"artifact escapes bundle: {label}") from exc
    if not path.is_file():
        raise InvalidEvidence(f"missing or unsafe artifact: {label}")
    actual = sha256(path)
    if actual != reference["sha256"]:
        raise InvalidEvidence(f"artifact hash mismatch: {label}")
    return path


def kernel(kernel_id: str, function: str, passed: bool, summary: str, facts: dict[str, Any]) -> dict[str, Any]:
    return {"kernel_id": kernel_id, "verifier_function": function, "status": "pass" if passed else "fail", "score": 1 if passed else -1, "applicable": True, "summary": summary, "facts": facts}


def excluded(kernel_id: str, function: str) -> dict[str, Any]:
    return {"kernel_id": kernel_id, "verifier_function": function, "status": "excluded", "score": None, "applicable": False, "exclusion_reason": "not_needed_first_turn_pass"}


def validate_response_receipt(receipt: dict[str, Any], label: str) -> None:
    required = {"status": str, "num_error_outputs": int, "num_exhausted_context_windows": int}
    for name, expected in required.items():
        if not isinstance(receipt.get(name), expected):
            raise InvalidEvidence(f"{label} response receipt field is missing or wrongly typed: {name}")
    if receipt["num_error_outputs"] < 0 or receipt["num_exhausted_context_windows"] < 0:
        raise InvalidEvidence(f"{label} response counters must be nonnegative")


def validate_evaluation(receipt: dict[str, Any], label: str) -> None:
    required = {"task_id": str, "phase": str, "official_test_count": int, "passed_test_count": int, "passed": bool, "timed_out": bool, "diagnostics": list}
    for name, expected in required.items():
        if not isinstance(receipt.get(name), expected):
            raise InvalidEvidence(f"{label} evaluation field is missing or wrongly typed: {name}")
    if receipt["task_id"] != TASK_ID or receipt["phase"] not in PHASES:
        raise InvalidEvidence(f"{label} evaluation identity or phase is invalid")
    for diagnostic in receipt["diagnostics"]:
        if not isinstance(diagnostic, dict) or not isinstance(diagnostic.get("id"), str) or not isinstance(diagnostic.get("target_file"), list) or not isinstance(diagnostic.get("target_token"), list):
            raise InvalidEvidence(f"{label} diagnostic schema is invalid")


def verified_turns(bundle: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    if manifest.get("schema_version") != 1 or manifest.get("task_id") != TASK_ID or manifest.get("turn_limit") != 2:
        raise InvalidEvidence("trajectory manifest identity or turn limit is invalid")
    entries = manifest.get("turns")
    if not isinstance(entries, list) or not entries or len(entries) > 2:
        raise InvalidEvidence("trajectory must contain one or two turns")
    turns: list[dict[str, Any]] = []
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict) or entry.get("turn") != index:
            raise InvalidEvidence("trajectory turns must be ordered and contiguous")
        resolved: dict[str, Any] = {"turn": index}
        names = ["response", "response_receipt", "source_snapshot", "evaluation_receipt"]
        if index == 1:
            names.append("generated_feedback")
        else:
            names.extend(["delivered_feedback", "edit_diff"])
        for name in names:
            resolved[name] = resolve_ref(bundle, entry.get(name), f"turn{index}.{name}")
        resolved["response_receipt_json"] = load_json(resolved["response_receipt"])
        resolved["evaluation_json"] = load_json(resolved["evaluation_receipt"])
        validate_response_receipt(resolved["response_receipt_json"], f"turn{index}")
        validate_evaluation(resolved["evaluation_json"], f"turn{index}")
        turns.append(resolved)
    if not turns[0]["evaluation_json"]["passed"] and len(turns) != 2:
        raise InvalidEvidence("failed turn one requires complete turn-two evidence")
    return turns


def verify_7a_first_response_health(turns: list[dict[str, Any]]) -> dict[str, Any]:
    response = turns[0]["response"].read_text(errors="replace")
    receipt = turns[0]["response_receipt_json"]
    passed = bool(response.strip()) and receipt["status"] == "completed" and receipt["num_error_outputs"] == 0 and receipt["num_exhausted_context_windows"] == 0
    return kernel("7A", "verify_7a_first_response_health", passed, "first response completed cleanly" if passed else "first response was empty, errored, or exhausted", {"response_sha256": sha256(turns[0]["response"]), "response_nonempty": bool(response.strip()), **receipt})


def verify_7b_feedback_delivery(turns: list[dict[str, Any]]) -> dict[str, Any]:
    generated = turns[0]["generated_feedback"].read_bytes()
    delivered = turns[1]["delivered_feedback"].read_bytes()
    passed = bool(generated) and generated == delivered
    return kernel("7B", "verify_7b_feedback_delivery", passed, "feedback was delivered byte-for-byte" if passed else "feedback was absent or changed", {"generated_sha256": hashlib.sha256(generated).hexdigest(), "delivered_sha256": hashlib.sha256(delivered).hexdigest(), "generated_bytes": len(generated), "delivered_bytes": len(delivered)})


def diff_blocks(text: str) -> dict[str, str]:
    blocks: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("+++ "):
            raw = line[4:].strip()
            raw = raw[2:] if raw.startswith("b/") else raw
            name = Path(raw).name
            current = name if name in AUTHORIZED else None
            if current:
                blocks.setdefault(current, []).append(line)
        elif current is not None:
            blocks[current].append(line)
    return {name: "\n".join(lines) for name, lines in blocks.items()}


def verify_7c_targeted_repair(turns: list[dict[str, Any]]) -> dict[str, Any]:
    diff_text = turns[1]["edit_diff"].read_text(errors="replace")
    blocks = diff_blocks(diff_text)
    diagnostics = turns[0]["evaluation_json"]["diagnostics"]
    matched: list[dict[str, str]] = []
    for diagnostic in diagnostics:
        for target_file in diagnostic["target_file"]:
            name = Path(str(target_file)).name
            block = blocks.get(name, "")
            for token in diagnostic["target_token"]:
                if isinstance(token, str) and token and token in block:
                    matched.append({"diagnostic_id": diagnostic["id"], "file": name, "token": token})
    edit_lines = [line for line in diff_text.splitlines() if (line.startswith("+") or line.startswith("-")) and not line.startswith("+++") and not line.startswith("---")]
    snapshots_differ = sha256(turns[0]["source_snapshot"]) != sha256(turns[1]["source_snapshot"])
    passed = bool(blocks) and bool(edit_lines) and snapshots_differ and bool(matched)
    return kernel("7C", "verify_7c_targeted_repair", passed, "turn-two edit targeted an authenticated diagnostic" if passed else "turn-two edit was absent or unrelated", {"changed_files": sorted(blocks), "edit_line_count": len(edit_lines), "source_snapshots_differ": snapshots_differ, "matches": matched})


def verify_7d_diagnostic_reduction(turns: list[dict[str, Any]]) -> dict[str, Any]:
    first = turns[0]["evaluation_json"]
    second = turns[1]["evaluation_json"]
    first_ids = {item["id"] for item in first["diagnostics"]}
    second_ids = {item["id"] for item in second["diagnostics"]}
    remaining = first_ids & second_ids
    phase_progress = PHASES[second["phase"]] >= PHASES[first["phase"]]
    reduced = bool(first_ids) and len(remaining) < len(first_ids)
    passed = reduced and phase_progress
    return kernel("7D", "verify_7d_diagnostic_reduction", passed, "diagnostics decreased without phase regression" if passed else "repair did not reduce diagnostics or regressed", {"turn1_ids": sorted(first_ids), "turn2_ids": sorted(second_ids), "remaining_turn1_ids": sorted(remaining), "turn1_phase": first["phase"], "turn2_phase": second["phase"], "phase_progress": phase_progress})


def verify_7e_pass_within_two_turns(turns: list[dict[str, Any]]) -> dict[str, Any]:
    earliest: int | None = None
    evaluations = []
    for turn in turns:
        value = turn["evaluation_json"]
        complete = value["official_test_count"] == 5 and value["passed_test_count"] == 5 and value["passed"] and not value["timed_out"] and value["phase"] == "pass"
        evaluations.append({"turn": turn["turn"], "official_test_count": value["official_test_count"], "passed_test_count": value["passed_test_count"], "passed": value["passed"], "timed_out": value["timed_out"], "phase": value["phase"]})
        if complete and earliest is None:
            earliest = turn["turn"]
    passed = earliest is not None
    return kernel("7E", "verify_7e_pass_within_two_turns", passed, "Diamond passed within two turns" if passed else "no authenticated 5/5 pass within two turns", {"earliest_pass_turn": earliest, "evaluations": evaluations})


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
    receipt: dict[str, Any] = {"schema_version": 1, "task_id": TASK_ID, "contract_variant": "pristine-original-v1", "policy_id": POLICY_ID, "policy_name": "feedback_repair_context", "verifier_source_sha256": sha256(Path(__file__))}
    started = time.time()
    try:
        if not bundle.is_dir() or bundle.is_symlink():
            raise InvalidEvidence("bundle directory is missing or unsafe")
        manifest_path = bundle / "trajectory_bundle.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise InvalidEvidence("trajectory_bundle.json is missing or unsafe")
        manifest = load_json(manifest_path)
        turns = verified_turns(bundle, manifest)
        first_pass = turns[0]["evaluation_json"]["passed"]
        kernels = [verify_7a_first_response_health(turns)]
        if first_pass:
            kernels.extend([excluded("7B", "verify_7b_feedback_delivery"), excluded("7C", "verify_7c_targeted_repair"), excluded("7D", "verify_7d_diagnostic_reduction")])
        else:
            kernels.extend([verify_7b_feedback_delivery(turns), verify_7c_targeted_repair(turns), verify_7d_diagnostic_reduction(turns)])
        kernels.append(verify_7e_pass_within_two_turns(turns))
        applicable = [item for item in kernels if item["applicable"]]
        receipt.update({"trajectory_manifest_sha256": sha256(manifest_path), "kernels": kernels, "applicable_kernel_count": len(applicable), "excluded_kernels": [item["kernel_id"] for item in kernels if not item["applicable"]], "kernel_sum": sum(item["score"] for item in applicable), "overall_status": "pass" if all(item["score"] == 1 for item in applicable) else "fail"})
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
