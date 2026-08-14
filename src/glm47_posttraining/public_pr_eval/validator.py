"""Static validator for public-PR repository-evaluation contracts.

This validator intentionally checks only serialization, prompt/content quality,
scope safety, environment reproducibility, and evaluator-asset integrity. It is
answer-blind and does not replace task-specific executable oracle replay.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .mechanism_contract import mechanism_contract_findings


SCHEMA_VERSION = "public-pr-repo-eval-v2"
CLASSIFICATION = "public_pr_regression_diagnostic_only"
RESPONSE_PROTOCOL = "aider_whole_workspace_edit"
DIFF_RESPONSE_PROTOCOL = "aider_diff_workspace_edit"
ALLOWED_EDIT_PROTOCOLS = {
    "whole": RESPONSE_PROTOCOL,
    "diff": DIFF_RESPONSE_PROTOCOL,
}
EXACT_FEEDBACK = (
    "Compiler or tests failed. No private test names, output, expected values, "
    "or evaluator internals are disclosed. Review the task contract and your current "
    "production-file changes, then make one final correction."
)
COMPILER_FEEDBACK_MODE = "first_editable_compiler_diagnostic_v1"
COMPILER_FEEDBACK_DISCLOSURE = (
    "first_editable_compiler_diagnostic_no_private_details"
)
BASELINE_REPAIR_PROMPT_PROFILE = "baseline_preserving_compiler_repair_v1"
BASELINE_REPAIR_SECTION = "# Baseline-preserving compile-safety delta"
BASELINE_REPAIR_INSTRUCTION_IDS = tuple(f"B{index:02d}" for index in range(1, 9))
COMPACT_REPAIR_PROMPT_PROFILE = "compact_baseline_compiler_repair_bestof4_v2"
COMPACT_REPAIR_SECTION = "# Final patch audit"
COMPACT_REPAIR_INSTRUCTION_IDS = tuple(f"C{index:02d}" for index in range(1, 11))
PRIORITIZED_REPAIR_PROMPT_PROFILE = "failure_prioritized_intern_guide_bestof4_v3"
PRIORITIZED_REPAIR_SECTION = "# Priority-ordered final checks"
PRIORITIZED_REPAIR_INSTRUCTION_IDS = tuple(
    f"P{index:02d}" for index in range(1, 9)
)
PRIORITIZED_REPAIR_PARENT_PROMPT_SHA256 = (
    "c2e80dccbd50d0c9e1e38ba06a4c021821ac82fb16ba500ac0358a4fe5e9ced5"
)
FINAL_CLEANUP_REPAIR_PROMPT_PROFILE = (
    "failure_prioritized_final_cleanup_bestof4_v4"
)
FINAL_CLEANUP_REPAIR_PARENT_PROMPT_SHA256 = (
    "edb3c99880aae430bad5c9e92ae6e9bbb0f805b9be9b2eca3b1464311fa8a41d"
)
FINAL_CLEANUP_REPAIR_SUFFIX = """# Final mandatory cleanup

Confirm every `fmt_safe_duration_cast` caller has been migrated to
`fmt_duration_cast`, then delete the complete legacy helper block. The
`fmt_safe_duration_cast` identifier must not remain in `include/fmt/chrono.h`.
Preserve all adjacent functions, braces, and unrelated preprocessor directives.
"""
FIRST_DEMO_BASELINE_PROMPT_SHA256 = (
    "443e4fe72cc4960881d2718821e7f4cf3cb00100080f0b64677b1d02025fdf77"
)
FIRST_DEMO_BASELINE_PRESERVED_MECHANISMS = (
    "fmt-duration-cast-helper",
    "same-arithmetic-dispatch",
    "safe-cast-placement",
    "templated-gmtime",
    "localtime-to-time-t",
    "fractional-seconds-casts",
    "remove-old-safe-helper",
    "chrono-formatter-cast",
)
BASELINE_REPAIR_REQUIRED_SHAPES = (
    "safe_duration_cast::safe_duration_cast<To>(from, ec)",
    "template <typename Duration>\nstd::time_t to_time_t(",
    "do_format(gmtime(val), ctx, &subsecs)",
    "format(gmtime(val), ctx)",
    "localtime(val)",
)
COMPACT_REPAIR_REQUIRED_SHAPES = (
    "safe_duration_cast::safe_duration_cast<To>(from, ec)",
    "template <typename Duration>\nstd::time_t to_time_t(",
    "detail::to_time_t(time_point)",
    "do_format(gmtime(val), ctx, &subsecs)",
    "format(gmtime(val), ctx)",
    "localtime(val)",
)
PRIORITIZED_REPAIR_REQUIRED_SHAPES = (
    "d - fmt_duration_cast<std::chrono::seconds>(d)",
    "safe_duration_cast::safe_duration_cast<To>(from, ec)",
    "template <typename Duration>\nstd::time_t to_time_t(",
    "template <typename Duration>\ninline std::tm gmtime(",
    "detail::to_time_t(time_point)",
    "detail::fmt_duration_cast<Duration>(",
    "do_format(gmtime(val), ctx, &subsecs)",
    "format(localtime(val), ctx)",
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
IMAGE_RE = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$")
TASK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{7,119}$")
REQUIRED_PROMPT_SECTIONS = (
    "# Objective",
    "# Failure reproduction",
    "# Required behavior",
    "# Compatibility and invariants",
    "# Editable scope",
    "# Validation expectations",
    "# Response contract",
)
REQUIRED_WORKFLOW_SECTION = "# Mandatory repository-edit workflow"
REQUIRED_TASK_AUDIT_SECTION = "# Task-specific implementation self-audit"
REQUIRED_WORKFLOW_INSTRUCTION_IDS = tuple(f"W{index:02d}" for index in range(1, 39))
FORBIDDEN_MODEL_INPUT_MARKERS = (
    "github.com/",
    "pull/",
    "issues/",
    "reference_commit",
    "reference patch",
    "hidden_validation",
    "private_probes",
)
REQUIRED_WARNING_FLAGS = {"-Wall", "-Wextra", "-Werror"}


@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "message": self.message,
        }


def canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_bytes().splitlines(), 1):
        if not raw.strip():
            raise ValueError(f"blank physical line {line_number}")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid UTF-8/JSON on line {line_number}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"line {line_number} is not a JSON object")
        rows.append(value)
    if not rows:
        raise ValueError("evaluation JSONL is empty")
    return rows


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _strings(value: Any) -> list[str]:
    return (
        value
        if isinstance(value, list) and all(isinstance(item, str) for item in value)
        else []
    )


def _safe_relative(path: str) -> bool:
    value = PurePosixPath(path)
    return (
        bool(path)
        and not value.is_absolute()
        and ".." not in value.parts
        and not any(part in {"", "."} for part in value.parts)
    )


def _add(findings: list[Finding], condition: bool, rule: str, message: str) -> None:
    if not condition:
        findings.append(Finding(rule, "critical", message))


def _validate_prompt(row: dict[str, Any], findings: list[Finding]) -> str:
    model_input = _object(row.get("model_input"))
    messages = model_input.get("messages")
    valid_messages = (
        isinstance(messages, list)
        and len(messages) == 1
        and isinstance(messages[0], dict)
        and messages[0].get("role") == "user"
        and isinstance(messages[0].get("content"), str)
    )
    _add(
        findings,
        valid_messages,
        "PPR-PROMPT-001",
        "model_input must contain one user message",
    )
    prompt = messages[0]["content"] if valid_messages else ""
    output = _object(row.get("output_contract"))
    edit_format = str(output.get("edit_format", ""))
    maximum_prompt_length = 18_000 if edit_format == "diff" else 12_000
    _add(
        findings,
        1_400 <= len(prompt) <= maximum_prompt_length,
        "PPR-PROMPT-002",
        "prompt must be detailed but bounded for its edit protocol "
        f"(1,400-{maximum_prompt_length:,} characters)",
    )
    positions = [prompt.find(section) for section in REQUIRED_PROMPT_SECTIONS]
    _add(
        findings,
        all(position >= 0 for position in positions) and positions == sorted(positions),
        "PPR-PROMPT-003",
        "prompt is missing required ordered sections",
    )
    lowered = prompt.lower()
    leaks = [marker for marker in FORBIDDEN_MODEL_INPUT_MARKERS if marker in lowered]
    _add(
        findings,
        not leaks,
        "PPR-PROMPT-004",
        f"model prompt leaks evaluator provenance: {leaks}",
    )
    _add(
        findings,
        "only" in lowered and "modify" in lowered and "do not modify tests" in lowered,
        "PPR-PROMPT-005",
        "prompt must state the exact production-file boundary and protect tests",
    )
    _add(
        findings,
        "hardcod" in lowered and "public api" in lowered,
        "PPR-PROMPT-006",
        "prompt must prohibit example-specific hardcoding and preserve public APIs",
    )
    prompt_profile = _object(row.get("prompt_contract")).get("profile")
    if prompt_profile in {
        BASELINE_REPAIR_PROMPT_PROFILE,
        COMPACT_REPAIR_PROMPT_PROFILE,
        PRIORITIZED_REPAIR_PROMPT_PROFILE,
        FINAL_CLEANUP_REPAIR_PROMPT_PROFILE,
    }:
        if prompt_profile == BASELINE_REPAIR_PROMPT_PROFILE:
            instruction_ids = BASELINE_REPAIR_INSTRUCTION_IDS
            section = BASELINE_REPAIR_SECTION
            marker_prefix = "B"
            required_shapes = BASELINE_REPAIR_REQUIRED_SHAPES
        elif prompt_profile == COMPACT_REPAIR_PROMPT_PROFILE:
            instruction_ids = COMPACT_REPAIR_INSTRUCTION_IDS
            section = COMPACT_REPAIR_SECTION
            marker_prefix = "C"
            required_shapes = COMPACT_REPAIR_REQUIRED_SHAPES
        else:
            instruction_ids = PRIORITIZED_REPAIR_INSTRUCTION_IDS
            section = PRIORITIZED_REPAIR_SECTION
            marker_prefix = "P"
            required_shapes = PRIORITIZED_REPAIR_REQUIRED_SHAPES
        missing_baseline_ids = [
            instruction_id
            for instruction_id in instruction_ids
            if f"[{instruction_id}]" not in prompt
        ]
        _add(
            findings,
            section in prompt and not missing_baseline_ids,
            "PPR-PROMPT-008",
            "baseline-preserving prompt is missing its compile-safety section or IDs: "
            f"{missing_baseline_ids}",
        )
        baseline_markers = re.findall(rf"\[{marker_prefix}\d{{2}}\]", prompt)
        _add(
            findings,
            len(baseline_markers) == len(instruction_ids)
            and len(set(baseline_markers)) == len(instruction_ids),
            "PPR-PROMPT-009",
            "each baseline-preserving compile-safety instruction must appear exactly once",
        )
        _add(
            findings,
            REQUIRED_WORKFLOW_SECTION not in prompt
            and REQUIRED_TASK_AUDIT_SECTION not in prompt
            and not re.findall(r"\[W\d{2}\]|\[F\d{2}\]", prompt),
            "PPR-PROMPT-010",
            "compiler-repair prompt must not reintroduce the generic W/F instruction blocks",
        )
        contract = _object(row.get("prompt_contract"))
        lineage_ok = (
            contract.get("baseline_prompt_sha256")
            == FIRST_DEMO_BASELINE_PROMPT_SHA256
            and tuple(contract.get("preserved_baseline_mechanisms", ()))
            == FIRST_DEMO_BASELINE_PRESERVED_MECHANISMS
        )
        if prompt_profile == COMPACT_REPAIR_PROMPT_PROFILE:
            lineage_ok = lineage_ok and contract.get("handoff_prompt_sha256") == (
                "b3997db3f5148890b879db2807c9a3c8de6f5be0552954cef529d8110c86ed25"
            )
        elif prompt_profile == PRIORITIZED_REPAIR_PROMPT_PROFILE:
            lineage_ok = lineage_ok and contract.get("parent_prompt_sha256") == (
                PRIORITIZED_REPAIR_PARENT_PROMPT_SHA256
            )
        elif prompt_profile == FINAL_CLEANUP_REPAIR_PROMPT_PROFILE:
            lineage_ok = lineage_ok and contract.get("parent_prompt_sha256") == (
                FINAL_CLEANUP_REPAIR_PARENT_PROMPT_SHA256
            )
        _add(
            findings,
            lineage_ok,
            "PPR-PROMPT-011",
            "compiler-repair prompt must bind the exact first-prompt lineage and preserved mechanisms",
        )
        _add(
            findings,
            all(shape in prompt for shape in required_shapes)
            and "Demo baseline scoring" not in prompt,
            "PPR-PROMPT-012",
            "compiler-repair prompt must retain concrete baseline shapes without score-optimization language",
        )
        if prompt_profile == FINAL_CLEANUP_REPAIR_PROMPT_PROFILE:
            _add(
                findings,
                prompt.endswith(FINAL_CLEANUP_REPAIR_SUFFIX),
                "PPR-PROMPT-013",
                "final-cleanup prompt must end with the exact mandatory legacy-helper removal gate",
            )
    else:
        missing_workflow_ids = [
            instruction_id
            for instruction_id in REQUIRED_WORKFLOW_INSTRUCTION_IDS
            if f"[{instruction_id}]" not in prompt
        ]
        _add(
            findings,
            REQUIRED_WORKFLOW_SECTION in prompt and not missing_workflow_ids,
            "PPR-PROMPT-008",
            "prompt is missing the mandatory repository-edit workflow or instruction IDs: "
            f"{missing_workflow_ids}",
        )
        workflow_markers = re.findall(r"\[W\d{2}\]", prompt)
        _add(
            findings,
            len(workflow_markers) == len(REQUIRED_WORKFLOW_INSTRUCTION_IDS)
            and len(set(workflow_markers)) == len(REQUIRED_WORKFLOW_INSTRUCTION_IDS),
            "PPR-PROMPT-009",
            "each mandatory workflow instruction must appear exactly once",
        )
        _add(
            findings,
            REQUIRED_TASK_AUDIT_SECTION in prompt,
            "PPR-PROMPT-010",
            "prompt must contain a task-specific implementation self-audit",
        )
    _add(
        findings,
        model_input.get("network_access") == "disabled"
        and model_input.get("response_protocol")
        == ALLOWED_EDIT_PROTOCOLS.get(edit_format),
        "PPR-PROMPT-007",
        "model network and response protocol are not frozen",
    )
    return prompt


def _validate_scope(
    row: dict[str, Any], prompt: str, findings: list[Finding]
) -> list[str]:
    scope = _object(row.get("scope"))
    editable = _strings(scope.get("editable_files"))
    _add(
        findings,
        scope.get("mode") == "exact_allowlist"
        and scope.get("reject_unlisted_changes") is True
        and scope.get("require_production_change") is True,
        "PPR-SCOPE-001",
        "scope must fail closed as an exact repository-wide allowlist",
    )
    _add(
        findings,
        len(editable) == 1 and all(_safe_relative(path) for path in editable),
        "PPR-SCOPE-002",
        "exactly one safe editable production file is required",
    )
    _add(
        findings,
        all(path in prompt for path in editable),
        "PPR-SCOPE-003",
        "every editable file must be named exactly in the model prompt",
    )
    _add(
        findings,
        scope.get("protected_policy") == "all_repository_paths_except_editable_files",
        "PPR-SCOPE-004",
        "all non-editable repository paths must be protected implicitly",
    )
    return editable


def _validate_environment(row: dict[str, Any], findings: list[Finding]) -> None:
    environment = _object(row.get("environment"))
    toolchain = _object(environment.get("toolchain"))
    resources = _object(environment.get("resource_limits"))
    image = environment.get("image")
    _add(
        findings,
        isinstance(image, str) and IMAGE_RE.fullmatch(image) is not None,
        "PPR-ENV-001",
        "runtime image must be pinned by sha256 digest",
    )
    _add(
        findings,
        environment.get("platform") == "linux/amd64"
        and environment.get("runtime_network") == "disabled"
        and environment.get("provisioning_network") == "image_build_only",
        "PPR-ENV-002",
        "platform and build/runtime network boundary must be explicit",
    )
    _add(
        findings,
        toolchain.get("cc") == "gcc-13"
        and toolchain.get("cxx") == "g++-13"
        and toolchain.get("cmake") == "3.27.9"
        and toolchain.get("generator") == "Unix Makefiles",
        "PPR-ENV-003",
        "GCC 13 and CMake 3.27.9 toolchain must be frozen",
    )
    _add(
        findings,
        environment.get("dependencies") == "prefetched_and_digest_bound_in_image",
        "PPR-ENV-004",
        "dependencies must be prefetched and immutable before network isolation",
    )
    _add(
        findings,
        all(
            isinstance(resources.get(key), int) and resources[key] > 0
            for key in (
                "cpu_cores",
                "memory_mib",
                "disk_mib",
                "command_timeout_seconds",
            )
        ),
        "PPR-ENV-005",
        "positive CPU, memory, disk, and command timeout limits are required",
    )


def _validate_commands(commands: Any, findings: list[Finding], prefix: str) -> None:
    valid = isinstance(commands, list) and bool(commands)
    if valid:
        for command in commands:
            valid = (
                isinstance(command, dict)
                and isinstance(command.get("name"), str)
                and isinstance(command.get("argv"), list)
                and bool(command["argv"])
                and all(isinstance(arg, str) and arg for arg in command["argv"])
                and isinstance(command.get("timeout_seconds"), int)
                and command["timeout_seconds"] > 0
            )
            if not valid:
                break
    _add(
        findings,
        valid,
        f"{prefix}-001",
        "commands must be nonempty argv arrays with timeouts",
    )


def _validate_hidden(
    row: dict[str, Any], repo_root: Path, findings: list[Finding]
) -> None:
    hidden = _object(row.get("hidden_validation"))
    overlay = _object(hidden.get("overlay"))
    paths = _strings(overlay.get("include_paths"))
    _add(
        findings,
        overlay.get("source") == "reference_commit_diff"
        and bool(paths)
        and all(_safe_relative(path) for path in paths)
        and SHA256_RE.fullmatch(str(overlay.get("patch_sha256", ""))) is not None
        and SHA256_RE.fullmatch(str(overlay.get("file_manifest_sha256", "")))
        is not None,
        "PPR-HIDDEN-001",
        "hidden overlay needs safe paths plus patch and per-file manifest digests",
    )
    probe = _object(hidden.get("independent_probe"))
    probe_path = repo_root / str(probe.get("path", ""))
    probe_safe = _safe_relative(str(probe.get("path", "")))
    probe_hash = str(probe.get("sha256", ""))
    _add(
        findings,
        probe_safe
        and probe_path.is_file()
        and SHA256_RE.fullmatch(probe_hash) is not None
        and sha256_path(probe_path) == probe_hash,
        "PPR-HIDDEN-002",
        "independent probe is missing or its digest does not match",
    )
    if probe_path.is_file():
        source = probe_path.read_text(encoding="utf-8")
        _add(
            findings,
            ("int main(" in source or "TEST_CASE(" in source)
            and "#include" in source
            and not any(
                token in source for token in ("std::system(", "popen(", "fork(")
            ),
            "PPR-HIDDEN-003",
            "private probe must be a self-contained C++ program without process escapes",
        )
    _validate_commands(hidden.get("build_commands"), findings, "PPR-BUILD")
    _validate_commands(hidden.get("probe_commands"), findings, "PPR-PROBE")
    command_args = {
        arg
        for command in hidden.get("probe_commands", [])
        if isinstance(command, dict)
        for arg in command.get("argv", [])
        if isinstance(arg, str)
    }
    _add(
        findings,
        REQUIRED_WARNING_FLAGS.issubset(command_args),
        "PPR-HIDDEN-004",
        "independent probe compile must be warning-clean",
    )
    behaviors = _strings(hidden.get("required_behaviors"))
    _add(
        findings,
        len(behaviors) >= 6 and len(set(behaviors)) == len(behaviors),
        "PPR-HIDDEN-005",
        "at least six distinct behavioral assertions are required",
    )
    _add(
        findings,
        hidden.get("base_oracle") == "must_fail"
        and hidden.get("reference_oracle") == "must_pass"
        and hidden.get("plausible_wrong_oracle") == "must_fail",
        "PPR-HIDDEN-006",
        "base/reference/plausible-wrong oracle expectations must be explicit",
    )
    mutation = _object(hidden.get("plausible_wrong_mutation_spec"))
    _add(
        findings,
        _safe_relative(str(mutation.get("path", "")))
        and isinstance(mutation.get("old"), str)
        and bool(mutation["old"])
        and isinstance(mutation.get("new"), str)
        and mutation.get("new") != mutation.get("old")
        and isinstance(mutation.get("expected_replacements"), int)
        and mutation["expected_replacements"] > 0,
        "PPR-HIDDEN-007",
        "a deterministic evaluator-only plausible-wrong mutation is required",
    )

    for rule_id, message in mechanism_contract_findings(row, repo_root):
        findings.append(Finding(rule_id, "critical", message))


def _validate_run_policy(row: dict[str, Any], findings: list[Finding]) -> None:
    policy = _object(row.get("run_policy"))
    attempts = policy.get("attempts")
    seeds = policy.get("seeds")
    single_candidate = seeds == [1701] and "candidate_count" not in policy
    best_of_four = (
        seeds == [1701, 1702, 1703, 1704]
        and policy.get("candidate_count") == 4
        and policy.get("candidate_isolation") == "fresh_prepared_repository_copy"
        and policy.get("candidate_selection")
        == "first_executable_pass_else_furthest_executable_stage"
        and policy.get("stop_on_first_executable_pass") is True
    )
    _add(
        findings,
        attempts in {1, 2}
        and (single_candidate or best_of_four)
        and policy.get("temperature") == 0.7
        and policy.get("top_p") == 1.0
        and policy.get("max_completion_tokens") == 32768
        and policy.get("thinking_mode") in {"disabled", "enabled"},
        "PPR-RUN-001",
        "attempt count, seed, decoding, token limit, and thinking mode must match an approved contract",
    )
    status_feedback_ok = (
        policy.get("attempt_2_feedback") == EXACT_FEEDBACK
        and policy.get("feedback_disclosure") == "status_only_no_private_details"
    )
    compiler_feedback_ok = (
        policy.get("attempt_2_feedback_mode") == COMPILER_FEEDBACK_MODE
        and policy.get("feedback_disclosure") == COMPILER_FEEDBACK_DISCLOSURE
        and policy.get("repair_temperature") == 0.2
        and "attempt_2_feedback" not in policy
    )
    _add(
        findings,
        (status_feedback_ok or compiler_feedback_ok)
        if attempts == 2
        else "attempt_2_feedback" not in policy
        and "attempt_2_feedback_mode" not in policy,
        "PPR-RUN-002",
        "attempt-two feedback must use an approved disclosure contract and be absent for single-turn runs",
    )


def validate_row(row: dict[str, Any], repo_root: Path) -> list[Finding]:
    findings: list[Finding] = []
    task_id = row.get("task_id")
    _add(
        findings,
        row.get("schema_version") == SCHEMA_VERSION,
        "PPR-SCHEMA-001",
        f"schema_version must be {SCHEMA_VERSION}",
    )
    _add(
        findings,
        isinstance(task_id, str) and TASK_ID_RE.fullmatch(task_id) is not None,
        "PPR-SCHEMA-002",
        "task_id is missing or unsafe",
    )
    _add(
        findings,
        row.get("classification") == CLASSIFICATION,
        "PPR-SCHEMA-003",
        "public tasks must remain diagnostic eval-only",
    )
    prompt = _validate_prompt(row, findings)
    _validate_scope(row, prompt, findings)
    repository = _object(row.get("repository"))
    _add(
        findings,
        isinstance(repository.get("url"), str)
        and repository["url"].startswith("https://github.com/")
        and repository["url"].endswith(".git")
        and COMMIT_RE.fullmatch(str(repository.get("base_commit", ""))) is not None
        and COMMIT_RE.fullmatch(str(repository.get("reference_commit", ""))) is not None
        and repository.get("base_commit") != repository.get("reference_commit")
        and repository.get("reference_visibility") == "evaluator_only",
        "PPR-REPO-001",
        "repository URL and distinct pinned base/reference commits are required",
    )
    _validate_environment(row, findings)
    _validate_hidden(row, repo_root, findings)
    _validate_run_policy(row, findings)
    output = _object(row.get("output_contract"))
    _add(
        findings,
        output.get("kind") == "workspace_edit"
        and output.get("edit_format") in ALLOWED_EDIT_PROTOCOLS
        and output.get("candidate_diff_source") == "git_diff_against_evaluator_baseline"
        and output.get("malformed_response") == "attempt_failure",
        "PPR-OUTPUT-001",
        "workspace-edit parsing and candidate diff semantics must be frozen",
    )
    integrity = _object(row.get("integrity"))
    _add(
        findings,
        integrity.get("model_prompt_sha256") == sha256_bytes(prompt.encode("utf-8"))
        and SHA256_RE.fullmatch(str(integrity.get("reference_patch_sha256", "")))
        is not None,
        "PPR-INTEGRITY-001",
        "model prompt or evaluator-only reference-patch digest is invalid",
    )
    provenance = _object(row.get("provenance"))
    _add(
        findings,
        isinstance(provenance.get("upstream_pr_url"), str)
        and provenance["upstream_pr_url"].startswith("https://github.com/")
        and provenance.get("contamination_risk")
        == "public_patch_possible_pretraining_overlap"
        and provenance.get("training_eligibility") == "forbidden",
        "PPR-PROVENANCE-001",
        "public provenance and no-training boundary must be explicit",
    )
    return findings


def validate_contract_file(path: Path, repo_root: Path) -> dict[str, Any]:
    rows = load_jsonl(path)
    catalog = []
    seen_ids: set[str] = set()
    seen_prompts: set[str] = set()
    corpus_findings: list[Finding] = []
    for index, row in enumerate(rows, 1):
        findings = validate_row(row, repo_root)
        task_id = str(row.get("task_id", f"line-{index}"))
        prompt_hash = _object(row.get("integrity")).get("model_prompt_sha256")
        if task_id in seen_ids:
            corpus_findings.append(
                Finding("PPR-CORPUS-001", "critical", f"duplicate task_id: {task_id}")
            )
        if isinstance(prompt_hash, str) and prompt_hash in seen_prompts:
            corpus_findings.append(
                Finding("PPR-CORPUS-002", "critical", f"duplicate prompt: {task_id}")
            )
        seen_ids.add(task_id)
        if isinstance(prompt_hash, str):
            seen_prompts.add(prompt_hash)
        catalog.append(
            {
                "line": index,
                "task_id": task_id,
                "status": "PASS" if not findings else "FAIL",
                "findings": [finding.as_dict() for finding in findings],
            }
        )
    failed = sum(item["status"] == "FAIL" for item in catalog)
    decision = "PASS" if failed == 0 and not corpus_findings else "FAIL"
    return {
        "schema_version": "public-pr-repo-eval-static-validation-v1",
        "decision": decision,
        "scope": "format_prompt_content_code_quality_only",
        "task_jsonl": str(path.resolve()),
        "task_jsonl_sha256": sha256_path(path),
        "row_count": len(rows),
        "unique_task_count": len(seen_ids),
        "passed_rows": len(rows) - failed,
        "failed_rows": failed,
        "catalog": catalog,
        "corpus_findings": [finding.as_dict() for finding in corpus_findings],
        "limitations": [
            "does not execute task-specific builds or hidden tests",
            "does not inspect or score model responses",
            "does not establish clean generalization because patches are public",
        ],
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite validation report: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json(report))


def finding_ids(report: dict[str, Any]) -> Iterable[str]:
    for item in report.get("catalog", []):
        for finding in item.get("findings", []):
            yield str(finding.get("rule_id"))
    for finding in report.get("corpus_findings", []):
        yield str(finding.get("rule_id"))
