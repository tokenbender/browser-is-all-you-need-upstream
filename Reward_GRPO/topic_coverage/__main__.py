"""CPU-only audit CLI. No training entry point or reward registration."""

from __future__ import annotations

import argparse
from pathlib import Path

from Reward_GRPO.generalized_cpp_grpo import DEFAULT_REGISTRY, _reconstruct
from Reward_GRPO.topic_coverage.controls import controls
from Reward_GRPO.topic_coverage.runner import (
    AuditSession, candidate_sources, plain_directory, reference_sources, control_sources,
    write_json,
)
from Reward_GRPO.topic_coverage.specs import TOPICS


def control_matches(record: dict, control) -> bool:
    if record["status"] != control.expected:
        return False
    candidate = record.get("candidate", {})
    if control.kind == "semantic":
        if candidate.get("build", {}).get("returncode") != 0:
            return False  # A semantic mutant must fail behavior, not accidentally compilation.
        groups = {item["group"]: item for item in candidate["groups"]}
        return groups[control.required_failed_group]["status"] == "fail"
    if control.kind == "diagnostic":
        return any(item.get("warning") for item in candidate.get("diagnostics", []))
    if control.kind == "build":
        return candidate.get("reason") == "build_failure"
    return True


def validate(args: argparse.Namespace) -> int:
    root = plain_directory(args.output)
    fixture_root = DEFAULT_REGISTRY.parent / "multi_env_fixtures"
    if root == fixture_root or fixture_root in root.parents:
        raise ValueError("validation output must be outside all finalized fixtures")
    if root.exists():
        raise ValueError("validation output must be a new directory")
    root.mkdir(parents=True)
    entries = []
    for task in TOPICS:
        with AuditSession(task, root / task, registry_path=args.registry, compiler=args.compiler,
                          include_diagnostics=True, allow_local_execution=True) as session:
            sources = control_sources(session.binding, task)
            reference = session.audit(sources, "reference_replay")
            entries.append({"task_id": task, "control": "reference_replay", "kind": "positive",
                            "status": reference["status"], "matched": reference["status"] == "pass"})
            print(f"{task}: reference {reference['status']}", flush=True)
            for control in controls(task, sources):
                record = session.audit(control.sources, control.name)
                matched = control_matches(record, control)
                entries.append({"task_id": task, "control": control.name, "kind": control.kind,
                                "status": record["status"], "matched": matched})
                print(f"{task}: {control.name} {record['status']} expected={control.expected} matched={matched}",
                      flush=True)
    summary = {
        "schema_version": 1, "audit_only": True, "changes_grpo_reward": False,
        "status": "pass" if all(item["matched"] for item in entries) else "fail",
        "tasks": len(TOPICS), "controls": len(entries), "matched": sum(item["matched"] for item in entries),
        "semantic_mutants": sum(item["kind"] == "semantic" for item in entries),
        "semantic_mutants_rejected": sum(item["kind"] == "semantic" and item["matched"] for item in entries),
        "entries": entries,
    }
    if args.compare_generalized:
        with AuditSession("allergies", root / "incremental-allergies", registry_path=args.registry,
                          compiler=args.compiler, allow_local_execution=True) as session:
            control = next(item for item in controls(
                "allergies", reference_sources(session.binding)
            ) if item.name == "high_bit_alias")
            extra = session.audit(control.sources)
            baseline = session.compare_generalized(control.sources)
            gain = baseline.get("reason") == "pass" and extra["status"] == "fail"
            summary["incremental_coverage"] = {
                "control": control.name, "generalized_status": baseline.get("reason"),
                "topic_status": extra["status"], "additional_fault_detected": gain,
            }
            if not gain:
                summary["status"] = "fail"
    write_json(root / "validation.json", summary)
    print(f"Validation: {summary['status']} ({summary['matched']}/{summary['controls']}); {root / 'validation.json'}")
    return 0 if summary["status"] == "pass" else 1


def check(args: argparse.Namespace) -> int:
    if args.candidate_dir:
        candidate = plain_directory(args.candidate_dir)
        output = plain_directory(args.output)
        if output == candidate or candidate in output.parents:
            raise ValueError("output must be outside the candidate directory")
    with AuditSession(
        args.task, args.output, registry_path=args.registry, compiler=args.compiler,
        include_diagnostics=args.include_diagnostics, allow_local_execution=True,
    ) as session:
        if args.reference:
            sources = reference_sources(session.binding)
        elif args.response_file:
            response = args.response_file.read_text(encoding="utf-8")
            reconstructed = session.work / "reconstructed"
            _reconstruct(session.binding, response, reconstructed)
            sources = candidate_sources(args.task, reconstructed)
        else:
            directory = plain_directory(args.candidate_dir)
            if session.output == directory or directory in session.output.parents:
                raise ValueError("output must be outside the candidate directory")
            sources = candidate_sources(args.task, directory)
        result = session.audit(sources)
        if args.with_generalized:
            # Original reward returned unchanged, in a separate side-by-side receipt.
            session.compare_generalized(sources, raw_response=response if args.response_file else None)
        print(f"{args.task}: topic audit {result['status']}; {session.output / 'candidate.json'}")
        return {"pass": 0, "fail": 1, "invalid": 2}[result["status"]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "validate"):
        command = sub.add_parser(name)
        command.add_argument("--output", type=Path, required=True)
        command.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
        command.add_argument("--compiler", default="g++")
        command.add_argument("--allow-local-execution", action="store_true",
                             help="Acknowledge CPU execution of reviewed code; not a security sandbox.")
        if name == "validate":
            command.add_argument("--compare-generalized", action="store_true",
                                 help="Also prove one incremental fault detection against the live baseline.")
        if name == "check":
            command.add_argument("--task", choices=tuple(TOPICS), required=True)
            source = command.add_mutually_exclusive_group(required=True)
            source.add_argument("--candidate-dir", type=Path)
            source.add_argument("--response-file", type=Path)
            source.add_argument("--reference", action="store_true")
            command.add_argument("--include-diagnostics", action="store_true")
            command.add_argument("--with-generalized", action="store_true")
    args = parser.parse_args()
    if not args.allow_local_execution:
        parser.error("--allow-local-execution is required; this backend is not hostile-code isolation")
    try:
        return validate(args) if args.command == "validate" else check(args)
    except (OSError, ValueError) as error:
        parser.exit(2, f"Audit configuration/input error: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
