"""Preparation, oracle replay, and Aider execution for public-PR evaluations."""

from __future__ import annotations

import copy
import difflib
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Iterable

from .mechanism_scoring import (
    build_compile_gate_ready,
    structure_summary,
    textual_hint_summary,
    verified_mechanism_summary,
)
from .validator import (
    COMPILER_FEEDBACK_MODE,
    EXACT_FEEDBACK,
    canonical_json,
    load_jsonl,
    sha256_bytes,
    sha256_path,
)


BASELINE_TAG = "public-pr-evaluator-baseline-v2"
PRIVATE_DIR = ".public-pr-eval-private"
BUILD_DIR = "build-public-pr-eval"
DEPENDENCY_DIR = ".public-pr-eval-deps"

PR_DIAGNOSTIC_CONTEXT = {
    "fmtlib-fmt-large-time-point-overflow-v2": {
        "defect": "chrono formatting narrowed a wider custom-duration time point through the native system_clock duration, allowing signed overflow before calendar conversion",
        "reference_mechanism": "the upstream patch adds generic checked duration conversion and converts system-clock time points directly to time_t without first narrowing to system_clock::duration",
    },
    "catch2-reset-assertion-disposition-v2": {
        "defect": "transient assertion result disposition survived CHECKED_ELSE completion and contaminated later uncaught-exception reporting",
        "reference_mechanism": "the upstream patch resets the saved result disposition only after the current assertion reaction has consumed it, across every relevant completion path",
    },
    "simdjson-preserve-underflow-signed-zero-v2": {
        "defect": "zero-producing number-parser paths discarded the sign of negative values that underflowed beyond the representable subnormal range",
        "reference_mechanism": "the upstream patch applies the parsed sign when producing zero for both zero-significand and exponent-underflow paths",
    },
}


class EvaluationError(RuntimeError):
    """Raised when an evaluation integrity or execution gate fails."""


def _progress(message: str) -> None:
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    print(f"[{timestamp}] [public-pr-eval] {message}", flush=True)


def _heartbeat(done: threading.Event, argv: list[str], cwd: Path) -> None:
    started = time.monotonic()
    while not done.wait(30):
        elapsed = int(time.monotonic() - started)
        _progress(
            f"still running after {elapsed}s: {argv[0]} "
            f"(cwd={cwd.name or cwd})"
        )


def _run(
    argv: list[str],
    *,
    cwd: Path,
    timeout: int,
    env: dict[str, str] | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    done = threading.Event()
    heartbeat = threading.Thread(
        target=_heartbeat, args=(done, argv, cwd), daemon=True
    )
    heartbeat.start()
    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
    finally:
        done.set()
        heartbeat.join(timeout=1)
    if check and result.returncode != 0:
        raise EvaluationError(
            f"command failed ({result.returncode}): {argv!r}\n{result.stdout[-4000:]}"
        )
    return result


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return _run(["git", *args], cwd=cwd, timeout=600, check=check)


def _task_by_id(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        task_id = str(row["task_id"])
        if task_id in result:
            raise EvaluationError(f"duplicate task_id: {task_id}")
        result[task_id] = row
    return result


def _overlay_patch(repo: Path, row: dict[str, Any], *, production: bool) -> bytes:
    repository = row["repository"]
    if production:
        paths = row["scope"]["editable_files"]
    else:
        paths = row["hidden_validation"]["overlay"]["include_paths"]
    command = [
        "git",
        "diff",
        "--binary",
        repository["base_commit"],
        repository["reference_commit"],
        "--",
        *paths,
    ]
    result = subprocess.run(command, cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise EvaluationError(result.stderr.decode("utf-8", errors="replace"))
    return result.stdout


def _overlay_file_manifest(repo: Path, row: dict[str, Any]) -> bytes:
    repository = row["repository"]
    overlay = row["hidden_validation"]["overlay"]
    changed = _git(
        repo,
        "diff",
        "--name-only",
        repository["base_commit"],
        repository["reference_commit"],
        "--",
        *overlay["include_paths"],
    ).stdout.splitlines()
    files: dict[str, str] = {}
    for path in changed:
        payload = subprocess.check_output(
            ["git", "show", f"{repository['reference_commit']}:{path}"], cwd=repo
        )
        files[path] = sha256_bytes(payload)
    return canonical_json({"files": files})


def _expand_argv(argv: list[str], repo: Path, probe: Path) -> list[str]:
    binary = repo / PRIVATE_DIR / "probe-bin"
    replacements = {
        "{private_probe}": str(probe),
        "{private_probe_binary}": str(binary),
        "{mechanism_probe}": str(repo / PRIVATE_DIR / "mechanism-probe.cpp"),
        "{repository}": str(repo),
    }
    return [replacements.get(value, value) for value in argv]


def run_command_specs(
    repo: Path,
    specs: list[dict[str, Any]],
    *,
    probe: Path,
    log_dir: Path,
    environment: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    log_dir.mkdir(parents=True, exist_ok=True)
    receipts = []
    for index, spec in enumerate(specs, 1):
        argv = _expand_argv(list(spec["argv"]), repo, probe)
        _progress(
            f"command {index}/{len(specs)} start: {spec['name']} "
            f"(task={repo.name})"
        )
        started = time.monotonic()
        try:
            result = _run(
                argv,
                cwd=repo,
                timeout=int(spec["timeout_seconds"]),
                env=environment,
            )
            timed_out = False
            output = result.stdout
            returncode = result.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            output = (exc.stdout or "") + (exc.stderr or "")
            returncode = 124
        except OSError as exc:
            timed_out = False
            output = f"{type(exc).__name__}: {exc}\n"
            returncode = 127
        log_path = log_dir / f"{index:02d}-{spec['name']}.log"
        log_path.write_text(output, encoding="utf-8", errors="replace")
        receipts.append(
            {
                "name": spec["name"],
                "argv": argv,
                "returncode": returncode,
                "timed_out": timed_out,
                "duration_seconds": round(time.monotonic() - started, 6),
                "log_path": str(log_path),
                "log_sha256": sha256_path(log_path),
            }
        )
        _progress(
            f"command {index}/{len(specs)} done: {spec['name']} "
            f"rc={returncode} elapsed={receipts[-1]['duration_seconds']}s"
        )
        if returncode != 0 and not bool(spec.get("continue_on_failure")):
            break
    return receipts


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json(value))


ACTIONABLE_COMPILER_MARKERS = ("error:", "fatal error:", "warning:")
SOURCE_LOCATION_RE = re.compile(r"(?:^|\s)([^\s:]+\.(?:h|hpp|cc|cpp)):\d+(?::\d+)?:")


def compiler_feedback_for_attempt(
    score: dict[str, Any], editable_files: list[str]
) -> str:
    """Return only the first diagnostic rooted in an editable production file."""

    failed = next(
        (
            command
            for command in (
                *score.get("build_commands", []),
                *score.get("mechanism_commands", []),
            )
            if int(command.get("returncode", 0)) != 0
        ),
        None,
    )
    if failed is None:
        return EXACT_FEEDBACK
    log_path = Path(str(failed.get("log_path", "")))
    if not log_path.is_file():
        return EXACT_FEEDBACK
    allowed = tuple(editable_files)
    allowed_names = tuple(Path(path).name for path in allowed)
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    start = None
    for index, raw in enumerate(lines):
        lowered = raw.lower()
        if not any(marker in lowered for marker in ACTIONABLE_COMPILER_MARKERS):
            continue
        if any(path in raw for path in allowed) or any(
            name in raw for name in allowed_names
        ):
            start = index
            break
    if start is None:
        return EXACT_FEEDBACK

    selected: list[str] = []
    for raw in lines[start : start + 8]:
        lowered = raw.lower()
        if any(
            marker in lowered
            for marker in (
                PRIVATE_DIR.lower(),
                "private_probe",
                "hidden test",
                "expected output",
                "test/",
                "tests/",
            )
        ):
            break
        locations = SOURCE_LOCATION_RE.findall(raw)
        if locations and not all(
            any(path in location or Path(path).name == Path(location).name for path in allowed)
            for location in locations
        ):
            break
        line = raw.strip()
        for path in (*allowed, *allowed_names):
            position = line.find(path)
            if position >= 0:
                line = line[position:]
                break
        if line:
            selected.append(line[:800])
    if not selected:
        return EXACT_FEEDBACK
    return (
        "Compilation failed.\n\n"
        "First actionable diagnostic from the editable production file:\n"
        + "\n".join(selected)
        + "\n\nRepair the existing patch in include/fmt/chrono.h only. "
        "Resolve this first diagnostic before later cascades; preserve every existing "
        "preprocessor branch, namespace boundary, fallback overload, and the complete "
        "baseline implementation plan. Do not edit tests or any other file."
    )


def _failed_command(score: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    for stage, key in (("build", "build_commands"), ("mechanism", "mechanism_commands"), ("probe", "probe_commands")):
        for command in score.get(key, []):
            if command.get("returncode") != 0:
                return stage, command
    return "none", None


def _failure_class(score: dict[str, Any]) -> str:
    if score["passed"]:
        return "none"
    if not score["scope_passed"]:
        return "no_production_change" if not score["changed_paths"] else "scope_violation"
    stage, command = _failed_command(score)
    if command is None:
        return "evaluator_incomplete"
    name = str(command["name"]).lower()
    if stage == "probe":
        return "independent_probe_compile_failure" if "compile" in name else "independent_probe_runtime_failure"
    if stage == "mechanism":
        return "mechanism_compile_failure" if "compile" in name else "mechanism_probe_failure"
    if "configure" in name:
        return "configure_failure"
    if "build" in name or "compile" in name:
        return "compile_or_link_failure"
    return "regression_test_failure"


def _git_blob(repo: Path, revision: str, path: str) -> bytes:
    return subprocess.check_output(["git", "show", f"{revision}:{path}"], cwd=repo)


def _evaluate_solution_checklist(row: dict[str, Any], repo: Path) -> list[dict[str, Any]]:
    checklist = row.get("diagnostic_checklist", [])
    if not isinstance(checklist, list):
        return []
    results: list[dict[str, Any]] = []
    for item in checklist:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", ""))
        candidate_path = repo / path
        source = (
            candidate_path.read_text(encoding="utf-8", errors="replace")
            if candidate_path.is_file()
            else ""
        )
        required = [str(pattern) for pattern in item.get("required_substrings", [])]
        forbidden = [str(pattern) for pattern in item.get("forbidden_substrings", [])]
        present_required = [pattern for pattern in required if pattern in source]
        missing_required = [pattern for pattern in required if pattern not in source]
        present_forbidden = [pattern for pattern in forbidden if pattern in source]
        ordered = [str(pattern) for pattern in item.get("ordered_substrings", [])]
        cursor = 0
        missing_ordered: list[str] = []
        for pattern in ordered:
            found = source.find(pattern, cursor)
            if found < 0:
                missing_ordered.append(pattern)
            else:
                cursor = found + len(pattern)
        order_passed = not missing_ordered
        status = (
            "present"
            if not missing_required and not present_forbidden and order_passed
            else "partial"
            if present_required or len(missing_required) < len(required) or (ordered and not order_passed)
            else "missing"
        )
        results.append(
            {
                "id": str(item.get("id", "")),
                "verifier_id": str(item.get("verifier_id", "")),
                "change": str(item.get("change", "")),
                "purpose": str(item.get("purpose", "")),
                "path": path,
                "status": status,
                "required_count": len(required),
                "present_required_count": len(present_required),
                "missing_required_substrings": missing_required,
                "forbidden_count": len(forbidden),
                "present_forbidden_substrings": present_forbidden,
                "ordered_count": len(ordered),
                "order_passed": order_passed,
                "missing_ordered_substrings": missing_ordered,
            }
        )
    return results


def _demo_baseline_summary(
    row: dict[str, Any],
    score: dict[str, Any],
    files: list[dict[str, Any]],
    checklist: list[dict[str, Any]],
) -> dict[str, Any]:
    textual_hints = textual_hint_summary(checklist)
    minimum_file_similarity = (
        min(float(item.get("line_similarity_ratio", 0.0)) for item in files)
        if files
        else 0.0
    )
    executable_passed = bool(score.get("passed"))
    if executable_passed:
        reason = "executable_oracle_passed"
    else:
        verified = score.get("verified_mechanisms", {})
        reason = (
            str(verified.get("reason"))
            if verified.get("status") == "unavailable"
            else "executable_oracle_failed"
        )
    return {
        "schema_version": "public-pr-demo-baseline-v2",
        "passed": executable_passed,
        "reason": reason,
        "executable_oracle_passed": executable_passed,
        "textual_hints": textual_hints,
        "structural_mechanisms": score.get(
            "structural_mechanisms", {"status": "not_configured"}
        ),
        "verified_mechanisms": score.get(
            "verified_mechanisms", {"status": "not_configured"}
        ),
        "minimum_observed_line_similarity_ratio": round(minimum_file_similarity, 6),
        "interpretation_limit": (
            "textual hints, structural checks, and reference similarity are diagnostic; "
            "only the executable oracle can pass the candidate"
        ),
    }


def _line_comparison(candidate: bytes, reference: bytes) -> dict[str, Any]:
    candidate_text = candidate.decode("utf-8", errors="replace")
    reference_text = reference.decode("utf-8", errors="replace")
    candidate_lines = candidate_text.splitlines()
    reference_lines = reference_text.splitlines()
    matcher = difflib.SequenceMatcher(None, candidate_lines, reference_lines, autojunk=False)
    candidate_only = 0
    reference_only = 0
    for opcode, i1, i2, j1, j2 in matcher.get_opcodes():
        if opcode in {"delete", "replace"}:
            candidate_only += i2 - i1
        if opcode in {"insert", "replace"}:
            reference_only += j2 - j1
    return {
        "candidate_sha256": sha256_bytes(candidate),
        "reference_sha256": sha256_bytes(reference),
        "exact_reference_match": candidate == reference,
        "candidate_line_count": len(candidate_lines),
        "reference_line_count": len(reference_lines),
        "candidate_only_or_changed_lines": candidate_only,
        "missing_or_changed_reference_lines": reference_only,
        "line_similarity_ratio": round(matcher.ratio(), 6),
        "unified_diff": "\n".join(
            difflib.unified_diff(
                candidate_text.splitlines(),
                reference_text.splitlines(),
                fromfile="candidate",
                tofile="upstream-reference",
                lineterm="",
            )
        )
        + "\n",
    }


def write_attempt_diagnostics(
    row: dict[str, Any],
    repo: Path,
    score: dict[str, Any],
    output_dir: Path,
    *,
    aider_returncode: int,
) -> dict[str, Any]:
    """Compare a scored candidate with the evaluator-only upstream production patch."""
    output_dir.mkdir(parents=True, exist_ok=False)
    editable_files = row["scope"]["editable_files"]
    candidate_patch = _git(
        repo, "diff", "--binary", BASELINE_TAG, "--", *editable_files
    ).stdout
    reference_patch = _overlay_patch(repo, row, production=True)
    (output_dir / "candidate-production.patch").write_text(candidate_patch, encoding="utf-8")
    (output_dir / "upstream-reference.patch").write_bytes(reference_patch)

    files: list[dict[str, Any]] = []
    comparison_root = output_dir / "candidate-vs-reference"
    comparison_root.mkdir()
    for path in editable_files:
        candidate_path = repo / path
        candidate = candidate_path.read_bytes() if candidate_path.is_file() else b""
        reference = _git_blob(repo, row["repository"]["reference_commit"], path)
        comparison = _line_comparison(candidate, reference)
        diff_name = path.replace("/", "__") + ".diff"
        (comparison_root / diff_name).write_text(
            comparison.pop("unified_diff"), encoding="utf-8"
        )
        comparison.update({"path": path, "diff_path": str(comparison_root / diff_name)})
        files.append(comparison)
    checklist = _evaluate_solution_checklist(row, repo)
    demo_baseline = _demo_baseline_summary(row, score, files, checklist)

    stage, failed = _failed_command(score)
    failure_excerpt = ""
    if failed is not None:
        failed_log = Path(failed["log_path"])
        if failed_log.is_file():
            failure_excerpt = failed_log.read_text(
                encoding="utf-8", errors="replace"
            )[-8000:]
    excerpt_path = output_dir / "failure-log-tail.txt"
    excerpt_path.write_text(failure_excerpt, encoding="utf-8")
    exact_reference = bool(files) and all(item["exact_reference_match"] for item in files)
    failure_class = _failure_class(score)
    if not score["passed"] and exact_reference:
        failure_class = "evaluator_inconsistency_reference_failed"
    context = PR_DIAGNOSTIC_CONTEXT.get(
        row["task_id"], {"defect": "unknown", "reference_mechanism": "unknown"}
    )
    receipt = {
        "schema_version": "public-pr-model-attempt-diagnostics-v2",
        "classification": "public_pr_regression_diagnostic_only",
        "task_id": row["task_id"],
        "passed": score["passed"],
        "aider_returncode": aider_returncode,
        "failure_class": failure_class,
        "failed_stage": stage,
        "failed_command": failed,
        "changed_paths": score["changed_paths"],
        "exact_upstream_reference_match": exact_reference,
        "candidate_patch_sha256": sha256_bytes(candidate_patch.encode("utf-8")),
        "upstream_reference_patch_sha256": sha256_bytes(reference_patch),
        "files": files,
        "solution_checklist": checklist,
        "demo_baseline": demo_baseline,
        "upstream_defect": context["defect"],
        "upstream_reference_mechanism": context["reference_mechanism"],
        "required_behaviors": row["hidden_validation"]["required_behaviors"],
        "failure_log_tail_path": str(excerpt_path),
        "interpretation_limit": "executable oracle result is authoritative; textual similarity to the public upstream patch is diagnostic only",
    }
    _write_json(output_dir / "diagnostics.json", receipt)

    command_summary = (
        "none"
        if failed is None
        else f"{failed['name']} (return code {failed['returncode']})"
    )
    file_rows = "\n".join(
        f"| `{item['path']}` | {item['exact_reference_match']} | "
        f"{item['line_similarity_ratio']:.6f} | {item['candidate_only_or_changed_lines']} | "
        f"{item['missing_or_changed_reference_lines']} |"
        for item in files
    )
    checklist_rows = "\n".join(
        f"| `{item['id']}` | {item['status']} | {item['present_required_count']}/"
        f"{item['required_count']} | {len(item['present_forbidden_substrings'])}/"
        f"{item['forbidden_count']} | {item['purpose']} |"
        for item in checklist
    )
    hints = demo_baseline["textual_hints"]
    structural = demo_baseline["structural_mechanisms"]
    verified = demo_baseline["verified_mechanisms"]
    structural_line = (
        f"{structural.get('valid', 0)}/{structural.get('total', 0)} "
        f"structure checks valid (diagnostic only)"
        if structural.get("status") == "complete"
        else str(structural.get("status", "not_configured"))
    )
    if verified.get("status") == "unavailable":
        verified_line = (
            "UNAVAILABLE — " + str(verified.get("reason", "compile_gate_failed"))
        )
    elif verified.get("status") in {"complete", "incomplete"}:
        verified_line = (
            f"{verified.get('verified', 0)}/{verified.get('applicable_total', 0)} "
            f"applicable mechanisms verified; "
            f"{verified.get('platform_gated', 0)} platform-gated/unverified"
        )
    else:
        verified_line = str(verified.get("status", "not_configured"))
    checklist_section = (
        "\n## Mechanism evidence\n\n"
        f"- Textual hints: `{hints['present']}/{hints['total']}` present "
        f"(diagnostic only; partial `{hints['partial']}`, missing `{hints['missing']}`).\n"
        f"- Structurally valid: `{structural_line}`.\n"
        f"- Executable verified: `{verified_line}`.\n"
        f"- Final result: **{'PASS' if score['passed'] else 'FAIL'}**.\n\n"
        "### Textual hint checklist\n\n"
        "| Check | Hint status | Required substrings | Forbidden substrings present | Purpose |\n"
        "| --- | --- | ---: | ---: | --- |\n"
        f"{checklist_rows}\n"
        if checklist
        else ""
    )
    markdown = f"""# Attempt diagnosis: {row['task_id']}

- Oracle result: **{'PASS' if score['passed'] else 'FAIL'}**
- Failure class: `{failure_class}`
- Aider return code: `{aider_returncode}`
- First failed evaluator command: `{command_summary}`
- Exact upstream production match: `{exact_reference}`
- Final result: **{'PASS' if demo_baseline['passed'] else 'FAIL'}** (`{demo_baseline['reason']}`)

## Upstream defect and correction

Defect: {context['defect']}.

Reference mechanism: {context['reference_mechanism']}.

## Candidate versus upstream production files

| File | Exact | Line similarity | Candidate-only/changed | Missing/changed reference |
| --- | ---: | ---: | ---: | ---: |
{file_rows}
{checklist_section}
The executable build, regression tests, and independent probe determine correctness. Patch
similarity is only a diagnostic aid: a different implementation can pass, while a visually
similar implementation can still fail an edge case.

## Why this attempt failed

The first deterministic failure occurred in `{command_summary}`. The complete command log is
preserved by the score receipt, its final 8,000 characters are in `failure-log-tail.txt`, and
the exact candidate-to-reference differences are under `candidate-vs-reference/`. If the
failure class is `evaluator_inconsistency_reference_failed`, stop and repair the evaluator;
do not attribute that result to the model.
"""
    (output_dir / "diagnostics.md").write_text(markdown, encoding="utf-8")
    return receipt


def write_suite_diagnostics(output_root: Path, receipts: list[dict[str, Any]]) -> None:
    lines = [
        "# Public-PR model evaluation diagnosis",
        "",
        "These tasks are public-patch diagnostics and are not clean generalization evidence.",
        "Executable oracle results are authoritative; upstream patch similarity is diagnostic.",
        "",
        "| Task | Pass@1 | Pass@2 | Textual hints (diagnostic) | "
        "Structural (diagnostic) | Executable verified | Final failure class | "
        "Exact upstream patch |",
        "| --- | ---: | ---: | ---: | ---: | --- | --- | ---: |",
    ]
    for receipt in receipts:
        final = receipt["attempts"][-1]["diagnostics"]
        baseline = final.get("demo_baseline", {})
        hints = baseline.get("textual_hints", {})
        structure = baseline.get("structural_mechanisms", {})
        verified = baseline.get("verified_mechanisms", {})
        hints_cell = (
            f"{hints.get('present', 0)}/{hints.get('total', 0)}"
            if hints.get("status") == "diagnostic_only"
            else "not configured"
        )
        structure_cell = (
            f"{structure.get('valid', 0)}/{structure.get('total', 0)}"
            if structure.get("status") == "complete"
            else str(structure.get("status", "not configured"))
        )
        if verified.get("status") == "unavailable":
            verified_cell = (
                "UNAVAILABLE — "
                + str(verified.get("reason", "compile_gate_failed"))
            )
        elif verified.get("status") in {"complete", "incomplete"}:
            verified_cell = (
                f"{verified.get('verified', 0)}/"
                f"{verified.get('applicable_total', 0)} applicable; "
                f"{verified.get('platform_gated', 0)} gated"
            )
        else:
            verified_cell = str(verified.get("status", "not configured"))
        lines.append(
            f"| `{receipt['task_id']}` | {receipt['pass_at_1']} | "
            f"{receipt['pass_at_2']} | {hints_cell} | {structure_cell} | "
            f"{verified_cell} | `{final['failure_class']}` | "
            f"{final['exact_upstream_reference_match']} |"
        )
    lines.extend(
        [
            "",
            "Each task directory contains the candidate patch, evaluator-only upstream patch,",
            "candidate-to-reference diff, failed-command log tail, and machine-readable receipt",
            "for every attempted response.",
            "",
        ]
    )
    (output_root / "diagnostic-report.md").write_text("\n".join(lines), encoding="utf-8")


def _tree_manifest(root: Path) -> bytes:
    files = {
        path.relative_to(root).as_posix(): sha256_path(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
    return canonical_json({"files": files})


def prepare_task(
    row: dict[str, Any],
    *,
    destination: Path,
    repo_root: Path,
    receipt_dir: Path,
) -> dict[str, Any]:
    if destination.exists():
        raise FileExistsError(f"refusing to reuse prepared task path: {destination}")
    repository = row["repository"]
    _progress(f"prepare {row['task_id']}: clone pinned repository")
    _run(
        ["git", "clone", "--no-checkout", repository["url"], str(destination)],
        cwd=destination.parent,
        timeout=1800,
        check=True,
    )
    _git(destination, "checkout", "--detach", repository["base_commit"])
    _git(destination, "cat-file", "-e", f"{repository['reference_commit']}^{{commit}}")

    overlay_patch = _overlay_patch(destination, row, production=False)
    overlay = row["hidden_validation"]["overlay"]
    if sha256_bytes(overlay_patch) != overlay["patch_sha256"]:
        raise EvaluationError(f"hidden overlay patch digest mismatch: {row['task_id']}")
    file_manifest = _overlay_file_manifest(destination, row)
    if sha256_bytes(file_manifest) != overlay["file_manifest_sha256"]:
        raise EvaluationError(f"hidden overlay file manifest mismatch: {row['task_id']}")
    apply_result = subprocess.run(
        ["git", "apply", "--whitespace=nowarn", "-"],
        cwd=destination,
        input=overlay_patch,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if apply_result.returncode != 0:
        raise EvaluationError(apply_result.stderr.decode("utf-8", errors="replace"))
    _progress(f"prepare {row['task_id']}: hidden overlay digest verified")

    probe_binding = row["hidden_validation"]["independent_probe"]
    source_probe = repo_root / probe_binding["path"]
    if not source_probe.is_file() or sha256_path(source_probe) != probe_binding["sha256"]:
        raise EvaluationError(f"private probe digest mismatch: {row['task_id']}")
    private_dir = destination / PRIVATE_DIR
    private_dir.mkdir(parents=True, exist_ok=False)
    probe = private_dir / "probe.cpp"
    shutil.copy2(source_probe, probe)
    mechanism_probe_sha256 = None
    mechanism_config = row["hidden_validation"].get("mechanism_verification")
    if isinstance(mechanism_config, dict):
        mechanism_binding = mechanism_config.get("probe", {})
        source_mechanism_probe = repo_root / str(mechanism_binding.get("path", ""))
        expected_mechanism_sha256 = str(mechanism_binding.get("sha256", ""))
        if (
            not source_mechanism_probe.is_file()
            or sha256_path(source_mechanism_probe) != expected_mechanism_sha256
        ):
            raise EvaluationError(
                f"mechanism probe digest mismatch: {row['task_id']}"
            )
        mechanism_probe = private_dir / "mechanism-probe.cpp"
        shutil.copy2(source_mechanism_probe, mechanism_probe)
        mechanism_probe_sha256 = sha256_path(mechanism_probe)
    with (destination / ".git" / "info" / "exclude").open(
        "a", encoding="utf-8"
    ) as exclude:
        exclude.write(
            f"/{BUILD_DIR}/\n/{DEPENDENCY_DIR}/\n/{PRIVATE_DIR}/probe-bin\n"
            f"/{PRIVATE_DIR}/mechanism-probe-*\n"
        )

    _git(destination, "config", "user.name", "Public PR Evaluator")
    _git(destination, "config", "user.email", "public-pr-eval@invalid")
    _git(destination, "add", "-A")
    commit_env = os.environ.copy()
    commit_env.update(
        {
            "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z",
            "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z",
        }
    )
    _run(
        ["git", "commit", "-m", "materialize evaluator-only hidden overlay"],
        cwd=destination,
        timeout=600,
        env=commit_env,
        check=True,
    )
    baseline_commit = _git(destination, "rev-parse", "HEAD").stdout.strip()
    _git(destination, "tag", BASELINE_TAG, baseline_commit)

    provision_env = os.environ.copy()
    provision_env.update({"CC": "gcc-13", "CXX": "g++-13", "TZ": "UTC", "LC_ALL": "C.UTF-8"})
    provision = run_command_specs(
        destination,
        row["hidden_validation"].get("provision_commands", []),
        probe=probe,
        log_dir=receipt_dir / row["task_id"] / "provision",
        environment=provision_env,
    )
    if provision and provision[-1]["returncode"] != 0:
        raise EvaluationError(f"dependency provisioning failed: {row['task_id']}")
    dependency_root = destination / DEPENDENCY_DIR
    dependency_manifest = (
        _tree_manifest(dependency_root)
        if dependency_root.is_dir()
        else canonical_json({"files": {}})
    )
    build_root = destination / BUILD_DIR
    if build_root.exists():
        shutil.rmtree(build_root)
    receipt = {
        "schema_version": "public-pr-repo-preparation-v2",
        "task_id": row["task_id"],
        "status": "prepared",
        "repository_url": repository["url"],
        "base_commit": repository["base_commit"],
        "reference_commit": repository["reference_commit"],
        "evaluator_baseline_commit": baseline_commit,
        "overlay_patch_sha256": sha256_bytes(overlay_patch),
        "overlay_file_manifest_sha256": sha256_bytes(file_manifest),
        "private_probe_sha256": sha256_path(probe),
        "mechanism_probe_sha256": mechanism_probe_sha256,
        "dependency_file_manifest_sha256": sha256_bytes(dependency_manifest),
        "provision_commands": provision,
    }
    _write_json(receipt_dir / row["task_id"] / "preparation.json", receipt)
    _progress(f"prepare {row['task_id']}: complete")
    return receipt


def prepare_all(jsonl: Path, destination: Path, repo_root: Path) -> dict[str, Any]:
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite preparation root: {destination}")
    destination.mkdir(parents=True, exist_ok=False)
    tasks_root = destination / "tasks"
    receipts_root = destination / "receipts"
    tasks_root.mkdir()
    rows = load_jsonl(jsonl)
    _progress(f"suite preparation start: {len(rows)} tasks")
    receipts = []
    for row in rows:
        receipts.append(
            prepare_task(
                row,
                destination=tasks_root / row["task_id"],
                repo_root=repo_root,
                receipt_dir=receipts_root,
            )
        )
    manifest = {
        "schema_version": "public-pr-repo-prepared-suite-v2",
        "status": "prepared",
        "task_jsonl": str(jsonl.resolve()),
        "task_jsonl_sha256": sha256_path(jsonl),
        "task_count": len(receipts),
        "tasks": receipts,
    }
    _write_json(destination / "prepared-suite.json", manifest)
    _progress("suite preparation complete")
    return manifest


def changed_paths(repo: Path) -> list[str]:
    baseline = _git(repo, "rev-parse", BASELINE_TAG).stdout.strip()
    committed = _git(repo, "diff", "--name-only", "--no-renames", baseline, "HEAD").stdout.splitlines()
    working = _git(repo, "diff", "--name-only", "--no-renames", "HEAD").stdout.splitlines()
    staged = _git(repo, "diff", "--cached", "--name-only", "--no-renames", "HEAD").stdout.splitlines()
    untracked = _git(repo, "ls-files", "--others", "--exclude-standard").stdout.splitlines()
    return sorted(set(committed + working + staged + untracked))


def score_candidate(
    row: dict[str, Any],
    repo: Path,
    output_dir: Path,
    *,
    require_change: bool = True,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=False)
    observed = changed_paths(repo)
    allowed = sorted(row["scope"]["editable_files"])
    scope_passed = not (set(observed) - set(allowed)) and (
        bool(observed) if require_change else True
    )
    _progress(
        f"score {row['task_id']}: scope={'pass' if scope_passed else 'fail'} "
        f"changed={observed}"
    )
    probe = repo / PRIVATE_DIR / "probe.cpp"
    environment = os.environ.copy()
    environment.update(
        {
            "CC": "gcc-13",
            "CXX": "g++-13",
            "TZ": "UTC",
            "LC_ALL": "C.UTF-8",
            "FETCHCONTENT_FULLY_DISCONNECTED": "ON",
        }
    )
    hidden = row["hidden_validation"]
    mechanism_config = hidden.get("mechanism_verification")
    build_receipts: list[dict[str, Any]] = []
    probe_receipts: list[dict[str, Any]] = []
    mechanism_receipts: list[dict[str, Any]] = []
    if scope_passed:
        build_receipts = run_command_specs(
            repo,
            hidden["build_commands"],
            probe=probe,
            log_dir=output_dir / "build",
            environment=environment,
        )
        if isinstance(mechanism_config, dict) and build_compile_gate_ready(
            mechanism_config, build_receipts
        ):
            mechanism_receipts = run_command_specs(
                repo,
                mechanism_config.get("commands", []),
                probe=probe,
                log_dir=output_dir / "mechanisms",
                environment=environment,
            )
        if build_receipts and build_receipts[-1]["returncode"] == 0:
            probe_receipts = run_command_specs(
                repo,
                hidden["probe_commands"],
                probe=probe,
                log_dir=output_dir / "probe",
                environment=environment,
            )
    build_passed = bool(build_receipts) and build_receipts[-1]["returncode"] == 0
    probe_passed = bool(probe_receipts) and probe_receipts[-1]["returncode"] == 0
    structure = structure_summary(row, repo)
    verified = verified_mechanism_summary(
        row,
        scope_passed=scope_passed,
        build_receipts=build_receipts,
        mechanism_receipts=mechanism_receipts,
        structure=structure,
    )
    checklist = _evaluate_solution_checklist(row, repo)
    textual_hints = textual_hint_summary(checklist)
    mechanism_required = bool(
        isinstance(mechanism_config, dict)
        and mechanism_config.get("required_for_pass") is True
    )
    mechanism_gate_passed = not mechanism_required or verified.get("status") == "complete"
    passed = scope_passed and build_passed and probe_passed and mechanism_gate_passed
    receipt = {
        "schema_version": "public-pr-repo-candidate-score-v3",
        "task_id": row["task_id"],
        "passed": passed,
        "final_result": "PASS" if passed else "FAIL",
        "scope_passed": scope_passed,
        "allowed_paths": allowed,
        "changed_paths": observed,
        "build_passed": build_passed,
        "probe_passed": probe_passed,
        "mechanism_gate_required": mechanism_required,
        "mechanism_gate_passed": mechanism_gate_passed,
        "textual_hints": textual_hints,
        "structural_mechanisms": structure,
        "verified_mechanisms": verified,
        "build_commands": build_receipts,
        "probe_commands": probe_receipts,
        "mechanism_commands": mechanism_receipts,
    }
    _write_json(output_dir / "score.json", receipt)
    _progress(
        f"score {row['task_id']}: {'PASS' if passed else 'FAIL'} "
        f"build={build_passed} probe={probe_passed} "
        f"mechanisms={verified.get('status')}"
    )
    return receipt


def _copy_prepared(source: Path, destination: Path) -> None:
    if destination.exists():
        raise FileExistsError(destination)
    shutil.copytree(source, destination, symlinks=True)


def _apply_production_reference(row: dict[str, Any], repo: Path) -> None:
    patch = _overlay_patch(repo, row, production=True)
    if sha256_bytes(patch) != row["integrity"]["reference_patch_sha256"]:
        raise EvaluationError(f"reference production patch digest mismatch: {row['task_id']}")
    result = subprocess.run(
        ["git", "apply", "--whitespace=nowarn", "-"],
        cwd=repo,
        input=patch,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise EvaluationError(result.stderr.decode("utf-8", errors="replace"))


def _apply_mutation(row: dict[str, Any], repo: Path) -> None:
    mutation = row["hidden_validation"].get("plausible_wrong_mutation_spec")
    if not isinstance(mutation, dict):
        raise EvaluationError(f"missing plausible-wrong mutation spec: {row['task_id']}")
    path = repo / mutation["path"]
    source = path.read_text(encoding="utf-8")
    old = mutation["old"]
    expected = int(mutation["expected_replacements"])
    observed = source.count(old)
    if observed != expected:
        raise EvaluationError(
            f"mutation precondition mismatch for {row['task_id']}: {observed} != {expected}"
        )
    path.write_text(source.replace(old, mutation["new"]), encoding="utf-8")


def verify_oracles(
    jsonl: Path,
    prepared_root: Path,
    output_root: Path,
) -> dict[str, Any]:
    if output_root.exists():
        raise FileExistsError(output_root)
    output_root.mkdir(parents=True)
    rows = load_jsonl(jsonl)
    _progress(f"oracle replay start: {len(rows)} tasks x 3 controls")
    catalog = []
    for row in rows:
        task_id = row["task_id"]
        source = prepared_root / "tasks" / task_id
        task_output = output_root / task_id
        controls = {}
        for control in ("base", "reference", "plausible-wrong"):
            _progress(f"oracle {task_id}: {control} start")
            candidate = task_output / f"{control}-repo"
            _copy_prepared(source, candidate)
            if control != "base":
                _apply_production_reference(row, candidate)
            if control == "plausible-wrong":
                _apply_mutation(row, candidate)
            controls[control] = score_candidate(
                row,
                candidate,
                task_output / f"{control}-score",
                require_change=False,
            )
            _progress(
                f"oracle {task_id}: {control} "
                f"{'PASS' if controls[control]['passed'] else 'FAIL'}"
            )
        passed = (
            controls["base"]["passed"] is False
            and controls["reference"]["passed"] is True
            and controls["plausible-wrong"]["passed"] is False
        )
        catalog.append({"task_id": task_id, "passed": passed, "controls": controls})
    receipt = {
        "schema_version": "public-pr-repo-oracle-replay-v2",
        "decision": "PASS" if all(item["passed"] for item in catalog) else "FAIL",
        "task_jsonl_sha256": sha256_path(jsonl),
        "task_count": len(catalog),
        "catalog": catalog,
    }
    _write_json(output_root / "oracle-replay.json", receipt)
    _progress(f"oracle replay complete: {receipt['decision']}")
    return receipt


def _aider_command(
    *,
    aider_python: str,
    model: str,
    settings: Path,
    message: Path,
    history: Path,
    editable_files: list[str],
    restore: bool,
    edit_format: str = "whole",
    auto_lint: bool = True,
    auto_test: bool = False,
) -> list[str]:
    command = [
        aider_python,
        "-m",
        "aider",
        "--model",
        f"openai/{model}",
        "--edit-format",
        edit_format,
        "--model-settings-file",
        str(settings),
        "--message-file",
        str(message),
        "--chat-history-file",
        str(history),
        "--yes-always",
        "--no-auto-commits",
        "--no-dirty-commits",
        "--no-gitignore",
        "--no-check-update",
        "--no-stream",
        "--map-tokens",
        "0",
    ]
    if not auto_lint:
        command.append("--no-auto-lint")
    if not auto_test:
        command.append("--no-auto-test")
    if restore:
        command.append("--restore-chat-history")
    return [*command, *editable_files]


MODEL_CALL_MARKER_RE = re.compile(r"(?m)^Tokens:\s+[^\n]*sent,[^\n]*received\.?$")


def observed_aider_model_calls(output: str) -> int | None:
    count = len(MODEL_CALL_MARKER_RE.findall(output))
    return count if count else None


def evaluate_task_with_aider(
    row: dict[str, Any],
    *,
    prepared_repo: Path,
    output_dir: Path,
    aider_python: str,
    model: str,
    model_settings: Path,
    api_base: str,
    api_key: str,
    repair_model_settings: Path | None = None,
) -> dict[str, Any]:
    if output_dir.exists():
        raise FileExistsError(output_dir)
    output_dir.mkdir(parents=True)
    repo = output_dir / "repository"
    _copy_prepared(prepared_repo, repo)
    history = output_dir / "chat-history.md"
    prompt = output_dir / "attempt-1-message.txt"
    prompt.write_text(row["model_input"]["messages"][0]["content"], encoding="utf-8")
    attempt_count = int(row.get("run_policy", {}).get("attempts", 2))
    if attempt_count not in {1, 2}:
        raise EvaluationError(f"unsupported attempt count for {row['task_id']}: {attempt_count}")
    feedback = output_dir / "attempt-2-message.txt"
    feedback_mode = str(row.get("run_policy", {}).get("attempt_2_feedback_mode", "status_only"))
    if attempt_count >= 2 and feedback_mode != COMPILER_FEEDBACK_MODE:
        feedback.write_text(EXACT_FEEDBACK + "\n", encoding="utf-8")
    harness = row.get("harness_instructions", {})
    aider_auto_lint = bool(harness.get("aider_auto_lint", True))
    aider_auto_test = bool(harness.get("aider_auto_test", False))
    environment = os.environ.copy()
    environment.update(
        {
            "OPENAI_API_BASE": api_base,
            "OPENAI_API_KEY": api_key,
            "TZ": "UTC",
            "LC_ALL": "C.UTF-8",
        }
    )
    attempts = []
    for attempt in range(1, attempt_count + 1):
        _progress(f"model task {row['task_id']}: attempt {attempt} inference start")
        message = prompt if attempt == 1 else feedback
        edit_format = str(row.get("output_contract", {}).get("edit_format", "whole"))
        if edit_format not in {"whole", "diff"}:
            raise EvaluationError(f"unsupported edit format for {row['task_id']}: {edit_format}")
        attempt_settings = (
            repair_model_settings
            if attempt == 2 and repair_model_settings is not None
            else model_settings
        )
        command = _aider_command(
            aider_python=aider_python,
            model=model,
            settings=attempt_settings,
            message=message,
            history=history,
            editable_files=row["scope"]["editable_files"],
            restore=attempt == 2,
            edit_format=edit_format,
            auto_lint=aider_auto_lint,
            auto_test=aider_auto_test,
        )
        inference = _run(command, cwd=repo, timeout=3600, env=environment)
        _progress(
            f"model task {row['task_id']}: attempt {attempt} inference done "
            f"rc={inference.returncode}"
        )
        log_path = output_dir / f"attempt-{attempt}-aider.log"
        log_path.write_text(inference.stdout, encoding="utf-8", errors="replace")
        score = score_candidate(row, repo, output_dir / f"attempt-{attempt}-score")
        diagnostics = write_attempt_diagnostics(
            row,
            repo,
            score,
            output_dir / f"attempt-{attempt}-diagnostics",
            aider_returncode=inference.returncode,
        )
        attempts.append(
            {
                "attempt": attempt,
                "aider_returncode": inference.returncode,
                "observed_aider_model_calls": observed_aider_model_calls(
                    inference.stdout
                ),
                "aider_log_sha256": sha256_path(log_path),
                "model_settings_sha256": sha256_path(attempt_settings),
                "score": score,
                "diagnostics": diagnostics,
            }
        )
        if score["passed"]:
            break
        if attempt == 1 and attempt_count >= 2 and feedback_mode == COMPILER_FEEDBACK_MODE:
            feedback.write_text(
                compiler_feedback_for_attempt(score, row["scope"]["editable_files"]) + "\n",
                encoding="utf-8",
            )
    receipt = {
        "schema_version": "public-pr-repo-model-task-v2",
        "task_id": row["task_id"],
        "model": model,
        "seed": row["run_policy"]["seeds"][0],
        "temperature": row["run_policy"]["temperature"],
        "top_p": row["run_policy"]["top_p"],
        "edit_format": str(row.get("output_contract", {}).get("edit_format", "whole")),
        "attempt_count": attempt_count,
        "attempt_2_feedback_mode": feedback_mode if attempt_count >= 2 else None,
        "attempt_2_feedback_sha256": (
            sha256_path(feedback) if attempt_count >= 2 and feedback.is_file() else None
        ),
        "repair_temperature": row.get("run_policy", {}).get("repair_temperature"),
        "aider_auto_lint": aider_auto_lint,
        "aider_auto_test": aider_auto_test,
        "pass_at_1": attempts[0]["score"]["passed"],
        "pass_at_2": any(item["score"]["passed"] for item in attempts),
        "attempts": attempts,
        "final_changed_paths": changed_paths(repo),
    }
    _write_json(output_dir / "task-receipt.json", receipt)
    _progress(
        f"model task {row['task_id']}: complete "
        f"pass@1={receipt['pass_at_1']} pass@2={receipt['pass_at_2']}"
    )
    return receipt


def _candidate_rank(receipt: dict[str, Any]) -> tuple[int, ...]:
    final = receipt["attempts"][-1]["score"]
    commands = [
        *final.get("build_commands", []),
        *final.get("mechanism_commands", []),
        *final.get("probe_commands", []),
    ]
    completed = sum(int(item.get("returncode", 1) == 0) for item in commands)
    verified = int(final.get("verified_mechanisms", {}).get("verified", 0))
    executable_gates = sum(
        int(bool(final.get(name)))
        for name in ("build_passed", "probe_passed", "mechanism_gate_passed")
    )
    return (
        int(bool(final.get("passed"))),
        executable_gates,
        verified,
        int(bool(final.get("probe_passed"))),
        int(bool(final.get("build_passed"))),
        int(bool(final.get("scope_passed"))),
        completed,
    )


def evaluate_task_best_of_n(
    row: dict[str, Any],
    *,
    prepared_repo: Path,
    output_dir: Path,
    aider_python: str,
    model: str,
    model_settings_by_seed: dict[int, Path],
    api_base: str,
    api_key: str,
    repair_model_settings_by_seed: dict[int, Path],
) -> dict[str, Any]:
    if output_dir.exists():
        raise FileExistsError(output_dir)
    output_dir.mkdir(parents=True)
    policy = row["run_policy"]
    seeds = [int(seed) for seed in policy["seeds"]]
    requested = int(policy["candidate_count"])
    if requested != len(seeds):
        raise EvaluationError("candidate_count must equal the number of candidate seeds")

    candidates: list[dict[str, Any]] = []
    for candidate_number, seed in enumerate(seeds, 1):
        if seed not in model_settings_by_seed or seed not in repair_model_settings_by_seed:
            raise EvaluationError(f"missing model settings for candidate seed {seed}")
        candidate_row = copy.deepcopy(row)
        candidate_row["run_policy"]["seeds"] = [seed]
        candidate_dir = output_dir / f"candidate-{candidate_number:02d}-seed-{seed}"
        _progress(
            f"model task {row['task_id']}: isolated candidate "
            f"{candidate_number}/{requested} seed={seed}"
        )
        receipt = evaluate_task_with_aider(
            candidate_row,
            prepared_repo=prepared_repo,
            output_dir=candidate_dir,
            aider_python=aider_python,
            model=model,
            model_settings=model_settings_by_seed[seed],
            api_base=api_base,
            api_key=api_key,
            repair_model_settings=repair_model_settings_by_seed[seed],
        )
        candidates.append(
            {
                "candidate_number": candidate_number,
                "seed": seed,
                "artifact_directory": candidate_dir.name,
                "receipt": receipt,
            }
        )
        if receipt["pass_at_2"] and policy["stop_on_first_executable_pass"]:
            break

    selected = max(
        candidates,
        key=lambda item: (_candidate_rank(item["receipt"]), -item["candidate_number"]),
    )
    selected_receipt = selected["receipt"]
    any_initial = any(item["receipt"]["pass_at_1"] for item in candidates)
    any_final = any(item["receipt"]["pass_at_2"] for item in candidates)
    aggregate = {
        "schema_version": "public-pr-repo-model-task-best-of-n-v1",
        "task_id": row["task_id"],
        "model": model,
        "candidate_count_requested": requested,
        "candidate_count_executed": len(candidates),
        "candidate_seeds_requested": seeds,
        "candidate_isolation": policy["candidate_isolation"],
        "candidate_selection": policy["candidate_selection"],
        "stop_on_first_executable_pass": policy["stop_on_first_executable_pass"],
        "selected_candidate_number": selected["candidate_number"],
        "selected_candidate_seed": selected["seed"],
        "selection_basis": (
            "first_executable_pass"
            if any_final
            else "furthest_executable_stage"
        ),
        "pass_at_1": any_initial,
        "pass_at_2": any_final,
        "attempts": selected_receipt["attempts"],
        "final_changed_paths": selected_receipt["final_changed_paths"],
        "candidates": candidates,
    }
    _write_json(output_dir / "task-receipt.json", aggregate)
    _progress(
        f"model task {row['task_id']}: best-of-{requested} complete "
        f"initial_success={any_initial} final_success={any_final} "
        f"selected=candidate-{selected['candidate_number']:02d}"
    )
    return aggregate


def evaluate_suite_with_aider(
    jsonl: Path,
    prepared_root: Path,
    output_root: Path,
    *,
    aider_python: str,
    model: str,
    model_settings: Path,
    api_base: str,
    api_key: str,
    repair_model_settings: Path | None = None,
    model_settings_by_seed: dict[int, Path] | None = None,
    repair_model_settings_by_seed: dict[int, Path] | None = None,
) -> dict[str, Any]:
    if output_root.exists():
        raise FileExistsError(output_root)
    output_root.mkdir(parents=True)
    receipts = []
    rows = load_jsonl(jsonl)
    _progress(f"model suite start: {len(rows)} tasks")
    for index, row in enumerate(rows, 1):
        _progress(f"model suite task {index}/{len(rows)}: {row['task_id']}")
        candidate_count = int(row.get("run_policy", {}).get("candidate_count", 1))
        if candidate_count > 1:
            if model_settings_by_seed is None or repair_model_settings_by_seed is None:
                raise EvaluationError("best-of-N evaluation requires per-seed model settings")
            receipt = evaluate_task_best_of_n(
                row,
                prepared_repo=prepared_root / "tasks" / row["task_id"],
                output_dir=output_root / row["task_id"],
                aider_python=aider_python,
                model=model,
                model_settings_by_seed=model_settings_by_seed,
                api_base=api_base,
                api_key=api_key,
                repair_model_settings_by_seed=repair_model_settings_by_seed,
            )
        else:
            receipt = evaluate_task_with_aider(
                row,
                prepared_repo=prepared_root / "tasks" / row["task_id"],
                output_dir=output_root / row["task_id"],
                aider_python=aider_python,
                model=model,
                model_settings=model_settings,
                api_base=api_base,
                api_key=api_key,
                repair_model_settings=repair_model_settings,
            )
        receipts.append(receipt)
    receipt = {
        "schema_version": "public-pr-repo-model-suite-v2",
        "model": model,
        "task_jsonl_sha256": sha256_path(jsonl),
        "task_count": len(receipts),
        "pass_at_1": sum(item["pass_at_1"] for item in receipts),
        "pass_at_2": sum(item["pass_at_2"] for item in receipts),
        "tasks": receipts,
    }
    _write_json(output_root / "suite-receipt.json", receipt)
    write_suite_diagnostics(output_root, receipts)
    _progress(
        f"model suite complete: pass@1={receipt['pass_at_1']}/{len(receipts)} "
        f"pass@2={receipt['pass_at_2']}/{len(receipts)}"
    )
    return receipt


def temporary_copy(source: Path) -> tuple[tempfile.TemporaryDirectory[str], Path]:
    temporary = tempfile.TemporaryDirectory(prefix="public-pr-eval-")
    destination = Path(temporary.name) / source.name
    _copy_prepared(source, destination)
    return temporary, destination
