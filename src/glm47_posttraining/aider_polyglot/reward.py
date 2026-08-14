"""Pass@1-aligned reward for Aider-style shadow tasks and official evaluation."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path, PurePath
import re
from typing import Callable

from glm47_posttraining.cpp_perf.sandbox import SandboxInfrastructureError

from .ast_evaluator import AST17Evaluation, compute_ast17_score
from .harness import (
    CandidatePolicyError,
    run_aider_tests,
    run_shadow_hybrid45_tests,
    run_shadow_weighted45_tests,
)
from .hybrid45 import (
    derive_hybrid45_observation,
    evaluate_hybrid45_response_checks,
    score_hybrid45,
)
from .mef45 import MEF45Receipt, project_mef45
from .parser import AiderResponseError, ParsedAiderResponse, parse_whole_file_response
from .policy45 import (
    Weighted45Score,
    evaluate_response_checks,
    failed_harness_checks,
    score_weighted45,
)
from .schema import (
    AiderPolyglotTask,
    AiderTestResult,
    HYBRID45_MEF_POLICY_VERSION,
    HYBRID45_POLICY_VERSION,
    Hybrid45Receipt,
    WEIGHTED45_HARNESS_CHECK_IDS,
)


Runner = Callable[[Path, dict[str, str]], AiderTestResult]
FORBIDDEN_VIOLATION_REASON = "forbidden_file_or_primitive_violation"
CLARIFICATION_OR_NO_FILE_REASON = "clarification_or_no_file_output"
FATAL_PARSE_REASON = "fatal_parse_failure"
DUPLICATE_FILE_REASON = "duplicate_file"
WRONG_FILE_LABEL_REASON = "wrong_file_label"
COMPILATION_FAILURE_REASON = "compilation_failure"
COMPILATION_FAILURE_SYNTAX_REASON = "compilation_failure_syntax"
COMPILATION_FAILURE_MISSING_SYMBOL_REASON = "compilation_failure_missing_symbol"
COMPILATION_FAILURE_MISSING_INCLUDE_OR_TYPE_REASON = "compilation_failure_missing_include_or_type"
COMPILATION_FAILURE_API_MISMATCH_REASON = "compilation_failure_api_mismatch"
COMPILATION_FAILURE_LINKER_REASON = "compilation_failure_linker"
COMPILATION_FAILURE_WARNING_REASON = "compilation_failure_warning"
SANITIZER_ERROR_REASON = "sanitizer_error"
CANDIDATE_TIMEOUT_REASON = "candidate_timeout"
INFRASTRUCTURE_FAULT_REASON = "infrastructure_fault"
PARTIAL_TEST_PASS_REASON = "partial_test_pass"
RUNTIME_ZERO_PASS_REASON = "runtime_zero_pass"
FORBIDDEN_REWARD = -1.0
CLARIFICATION_OR_NO_FILE_REWARD = -0.92
FATAL_PARSE_REWARD = -0.85
DUPLICATE_FILE_REWARD = -0.70
WRONG_FILE_LABEL_REWARD = -0.75
COMPILATION_FAILURE_REWARD = -0.5
COMPILATION_FAILURE_SYNTAX_REWARD = -0.55
COMPILATION_FAILURE_MISSING_SYMBOL_REWARD = -0.50
COMPILATION_FAILURE_MISSING_INCLUDE_OR_TYPE_REWARD = -0.45
COMPILATION_FAILURE_API_MISMATCH_REWARD = -0.42
COMPILATION_FAILURE_LINKER_REWARD = -0.38
COMPILATION_FAILURE_WARNING_REWARD = -0.32
SANITIZER_ERROR_REWARD = -0.5
CANDIDATE_TIMEOUT_REWARD = -0.5
INFRASTRUCTURE_MASK_REWARD = 0.0
TEST_EXECUTION_FLOOR = -0.20
TEST_EXECUTION_CEILING = 1.00
PROTECTED_NAMES = {"CMakeLists.txt"}
PROTECTED_SUFFIXES = ("_test.cpp", "_test.cc", "_test.h", ".cmake")
SANITIZER_ERROR_MARKERS = (
    "addresssanitizer",
    "undefinedbehaviorsanitizer",
    "leaksanitizer",
    "runtime error:",
    "heap-buffer-overflow",
    "stack-buffer-overflow",
    "use-after-free",
)
COMPILE_WARNING_MARKERS = (
    "-werror",
    "warnings being treated as errors",
    "warning:",
    "unused variable",
    "unused parameter",
    "sign-compare",
    "reorder",
)
COMPILE_LINKER_MARKERS = (
    "undefined reference",
    "multiple definition",
    "ld returned",
    "collect2:",
    "duplicate symbol",
)
COMPILE_API_MISMATCH_MARKERS = (
    "no matching function",
    "candidate expects",
    "too few arguments",
    "too many arguments",
    "invalid conversion",
    "cannot convert",
    "ambiguous",
    "discard qualifiers",
    "passing",
)
COMPILE_MISSING_INCLUDE_OR_TYPE_MARKERS = (
    "no such file or directory",
    "has not been declared",
    "was not declared in this scope",
    "does not name a type",
    "unknown type name",
    "incomplete type",
)
COMPILE_MISSING_SYMBOL_MARKERS = (
    "not declared",
    "not a member",
    "no member named",
    "use of undeclared identifier",
)
COMPILE_SYNTAX_MARKERS = (
    "expected",
    "stray",
    "unterminated",
    "parse error",
    "invalid declarator",
    "expected initializer",
)
CPP_STRUCTURE_RE = re.compile(
    r"\b(?:class|struct|enum|template|std::|auto|constexpr|const|return|for|while|if)\b"
)
RAW_NEW_RE = re.compile(r"\bnew\s+(?!\()")
RAW_DELETE_RE = re.compile(r"\bdelete(?:\s*\[\s*\])?\s+")
MUTABLE_GLOBAL_RE = re.compile(
    r"(?m)^\s*(?:static\s+)?(?!const\b)(?:[A-Za-z_][\w:<>,\s*&]+\s+)"
    r"[A-Za-z_]\w*\s*(?:=|\{)"
)
CONST_REF_RE = re.compile(r"\b(?:const\s+[A-Za-z_:][\w:<>,\s]*\s*&|std::string_view)\b")


@dataclass(frozen=True)
class AiderRewardBreakdown:
    reward: float
    reason: str
    parsed: ParsedAiderResponse | None = None
    harness: AiderTestResult | None = None
    infrastructure_error: bool = False
    infrastructure_detail: str | None = None


@dataclass(frozen=True)
class ProductionAiderRewardBreakdown(AiderRewardBreakdown):
    """Production Aider reward with AST17/style/bloat telemetry."""

    s_aider: float = 0.0
    s_ast17: float = 0.0
    s_style: float = 0.0
    anti_bloat: float = 0.0
    line_count: int = 0
    ast17_checks: dict[str, float] | None = None


@dataclass(frozen=True)
class Weighted45AiderRewardBreakdown(ProductionAiderRewardBreakdown):
    """Production breakdown carrying every weighted45 outcome and intermediate."""

    weighted45: Weighted45Score | None = None


@dataclass(frozen=True)
class Hybrid45AiderRewardBreakdown(ProductionAiderRewardBreakdown):
    """Production breakdown carrying the exact Hybrid45 V2 receipt."""

    hybrid45: Hybrid45Receipt | None = None


@dataclass(frozen=True)
class MEF45AiderRewardBreakdown(Hybrid45AiderRewardBreakdown):
    """Breakdown carrying V2 diagnostics and the R7 MEF projection."""

    mef45: MEF45Receipt | None = None


def compute_aider_reward(
    task: AiderPolyglotTask,
    exercise_dir: Path,
    model_output: str,
    *,
    runner: Runner | None = None,
) -> AiderRewardBreakdown:
    """Score correctness first and use formatting only as a small tie-breaker."""

    try:
        parsed = parse_whole_file_response(model_output, task.editable_files)
    except AiderResponseError as exc:
        reward = -1.0 if exc.reason == "forbidden_file" else -0.8
        return AiderRewardBreakdown(reward=reward, reason=exc.reason)

    try:
        harness = (runner or run_aider_tests)(exercise_dir, parsed.files)
    except CandidatePolicyError:
        return AiderRewardBreakdown(
            reward=-1.0,
            reason="forbidden_runtime_primitive",
            parsed=parsed,
        )

    if harness.status == "infrastructure_error":
        raise SandboxInfrastructureError(
            harness.logs.get("error", "Aider verifier reported an infrastructure error")
        )

    semantic = {
        "compile_failed": -0.5,
        "candidate_timeout": -0.5,
    }.get(harness.status)
    if semantic is None:
        semantic = 1.0 if harness.all_tests_pass else 0.6 * harness.fraction_tests_passed

    format_penalty = 0.0 if parsed.format_valid else 0.1
    reward = max(-1.0, min(1.0, semantic - format_penalty))
    reason = "passed" if harness.all_tests_pass else harness.status
    if not parsed.format_valid:
        reason = f"recoverable_format_{reason}"
    return AiderRewardBreakdown(reward=reward, reason=reason, parsed=parsed, harness=harness)


def compute_production_aider_reward(
    task: AiderPolyglotTask,
    exercise_dir: Path,
    model_output: str,
    *,
    runner: Runner | None = None,
) -> ProductionAiderRewardBreakdown:
    """Production reward behind the remote Aider parser/harness contract.

    Endpoint policy:
    - forbidden file/runtime primitive: -1.0
    - no-file/clarification output: -0.92
    - fatal parse failure: -0.85
    - duplicate/wrong file label: -0.70/-0.75
    - compile failure: diagnostic-shaped -0.55..-0.30
    - timeout/sanitizer failure: -0.5
    - infrastructure fault: 0.0 with ``infrastructure_error=True``
    - compiled test execution: continuous ``-0.20 + 1.20*S_Aider``
    - runtime zero-pass: -0.20
    - partial tests: proportional test reward in (-0.20, 1.00)
    - full pass: 1.00; AST/style/bloat remain diagnostic telemetry
    """

    try:
        parsed = parse_whole_file_response(model_output, task.editable_files)
    except AiderResponseError as exc:
        reward, reason = _parse_failure_reward(exc, model_output)
        return ProductionAiderRewardBreakdown(
            reward=reward,
            reason=reason,
        )

    try:
        harness = (runner or run_aider_tests)(exercise_dir, parsed.files)
    except CandidatePolicyError:
        return ProductionAiderRewardBreakdown(
            reward=FORBIDDEN_REWARD,
            reason=FORBIDDEN_VIOLATION_REASON,
            parsed=parsed,
        )
    except SandboxInfrastructureError as exc:
        return ProductionAiderRewardBreakdown(
            reward=INFRASTRUCTURE_MASK_REWARD,
            reason=INFRASTRUCTURE_FAULT_REASON,
            parsed=parsed,
            infrastructure_error=True,
            infrastructure_detail=str(exc)[-2000:],
            ast17_checks={"error": 0.0},
        )

    if harness.status == "infrastructure_error":
        return ProductionAiderRewardBreakdown(
            reward=INFRASTRUCTURE_MASK_REWARD,
            reason=INFRASTRUCTURE_FAULT_REASON,
            parsed=parsed,
            harness=harness,
            infrastructure_error=True,
            infrastructure_detail=_combined_harness_logs(harness)[-2000:],
        )

    if harness.status == "compile_failed":
        reward, reason = _compile_failure_reward(harness, parsed, task)
        return ProductionAiderRewardBreakdown(
            reward=reward,
            reason=_format_sensitive_reason(parsed, reason),
            parsed=parsed,
            harness=harness,
            s_ast17=0.0,
            s_style=_cpp_quality_score(parsed.files),
        )
    if harness.status == "candidate_timeout":
        return ProductionAiderRewardBreakdown(
            reward=CANDIDATE_TIMEOUT_REWARD,
            reason=CANDIDATE_TIMEOUT_REASON,
            parsed=parsed,
            harness=harness,
        )
    if harness.status == "sanitizer_error" or _harness_has_sanitizer_error(harness):
        return ProductionAiderRewardBreakdown(
            reward=SANITIZER_ERROR_REWARD,
            reason=SANITIZER_ERROR_REASON,
            parsed=parsed,
            harness=harness,
        )

    s_aider = max(0.0, min(1.0, harness.fraction_tests_passed))
    cpp_quality = _cpp_quality_score(parsed.files)
    test_reward = _continuous_test_reward(harness)
    if not harness.all_tests_pass:
        reason = (
            RUNTIME_ZERO_PASS_REASON
            if harness.tests_passed <= 0
            else PARTIAL_TEST_PASS_REASON
        )
        return ProductionAiderRewardBreakdown(
            reward=test_reward,
            reason=_format_sensitive_reason(parsed, reason),
            parsed=parsed,
            harness=harness,
            s_aider=s_aider,
            s_style=cpp_quality,
        )

    line_count = _candidate_line_count(parsed.files)
    ast_eval = compute_ast17_score(
        parsed.files,
        sanitizer_report=_combined_harness_logs(harness),
        return_details=True,
    )
    if isinstance(ast_eval, AST17Evaluation):
        s_ast17 = ast_eval.score
        ast_checks = ast_eval.checks
    else:
        s_ast17 = float(ast_eval)
        ast_checks = {}
    s_style = cpp_quality
    anti_bloat = min(0.08, 0.02 * math.sqrt(max(0, line_count - 50)))
    return ProductionAiderRewardBreakdown(
        reward=test_reward,
        reason=_format_sensitive_reason(parsed, "correct"),
        parsed=parsed,
        harness=harness,
        s_aider=s_aider,
        s_ast17=s_ast17,
        s_style=s_style,
        anti_bloat=anti_bloat,
        line_count=line_count,
        ast17_checks=ast_checks,
    )


def compute_weighted45_aider_reward(
    task: AiderPolyglotTask,
    exercise_dir: Path,
    model_output: str,
    *,
    runner: Runner | None = None,
) -> Weighted45AiderRewardBreakdown:
    """Evaluate all nine tiers and all 45 checks without outcome buckets.

    Unsafe or unparsable responses still receive all 45 boolean outcomes, but
    unsafe code is not executed.  A sandbox/verifier infrastructure fault is the
    only masked outcome and is rejected by the Miles bridge before optimization.
    """

    parsed: ParsedAiderResponse | None = None
    parse_error: AiderResponseError | None = None
    try:
        parsed = parse_whole_file_response(model_output, task.editable_files)
    except AiderResponseError as exc:
        parse_error = exc

    static_checks, static_evidence = evaluate_response_checks(
        task,
        exercise_dir,
        model_output,
        parsed=parsed,
        parse_error=parse_error,
    )
    harness: AiderTestResult | None = None
    policy_violation = False
    if parsed is None:
        harness_checks, harness_evidence = failed_harness_checks(
            "not executed: response did not yield a safe editable file"
        )
    else:
        try:
            selected_runner = runner
            if selected_runner is None:
                if task.harness_kind != "shadow_cpp17":
                    raise SandboxInfrastructureError(
                        "weighted45 requires the shadow_cpp17 hidden-grader contract"
                    )
                selected_runner = run_shadow_weighted45_tests
            harness = selected_runner(exercise_dir, parsed.files)
        except CandidatePolicyError:
            policy_violation = True
            harness_checks, harness_evidence = failed_harness_checks(
                "not executed: forbidden runtime/verifier-bypass primitive"
            )
        except SandboxInfrastructureError as exc:
            return Weighted45AiderRewardBreakdown(
                reward=INFRASTRUCTURE_MASK_REWARD,
                reason=INFRASTRUCTURE_FAULT_REASON,
                parsed=parsed,
                infrastructure_detail=str(exc)[-2000:],
                infrastructure_error=True,
                ast17_checks={"error": 0.0},
            )
        else:
            if harness.status == "infrastructure_error":
                return Weighted45AiderRewardBreakdown(
                    reward=INFRASTRUCTURE_MASK_REWARD,
                    reason=INFRASTRUCTURE_FAULT_REASON,
                    parsed=parsed,
                    harness=harness,
                    infrastructure_error=True,
                    infrastructure_detail=_combined_harness_logs(harness)[-2000:],
                )
            if set(harness.weighted45_checks) != WEIGHTED45_HARNESS_CHECK_IDS:
                raise SandboxInfrastructureError(
                    "weighted45 harness did not return the exact 20 K/R/H/A outcomes"
                )
            harness_checks = dict(harness.weighted45_checks)
            harness_evidence = dict(harness.weighted45_evidence)

    all_checks = {**static_checks, **harness_checks}
    all_evidence = {**static_evidence, **harness_evidence}
    weighted45 = score_weighted45(all_checks, all_evidence)
    reason = _weighted45_reason(
        parsed=parsed,
        parse_error=parse_error,
        response=model_output,
        harness=harness,
        policy_violation=policy_violation,
    )
    s_aider = sum(all_checks[f"H{index}"] for index in range(1, 6)) / 5.0
    line_count = _candidate_line_count(parsed.files) if parsed else 0
    return Weighted45AiderRewardBreakdown(
        reward=weighted45.normalized_reward,
        reason=reason,
        parsed=parsed,
        harness=harness,
        s_aider=s_aider,
        s_style=_cpp_quality_score(parsed.files) if parsed else 0.0,
        line_count=line_count,
        weighted45=weighted45,
    )


def compute_hybrid45_aider_reward(
    task: AiderPolyglotTask,
    exercise_dir: Path,
    model_output: str,
    *,
    runner: Runner | None = None,
) -> Hybrid45AiderRewardBreakdown:
    """Evaluate the separately versioned observation-aware V2 reward."""

    if task.reward_contract != HYBRID45_POLICY_VERSION:
        return Hybrid45AiderRewardBreakdown(
            reward=INFRASTRUCTURE_MASK_REWARD,
            reason=INFRASTRUCTURE_FAULT_REASON,
            infrastructure_error=True,
            infrastructure_detail=(
                f"task reward_contract={task.reward_contract!r} does not bind "
                f"{HYBRID45_POLICY_VERSION}"
            ),
        )

    parsed: ParsedAiderResponse | None = None
    parse_error: AiderResponseError | None = None
    try:
        parsed = parse_whole_file_response(model_output, task.editable_files)
    except AiderResponseError as exc:
        parse_error = exc

    static_checks, static_evidence = evaluate_hybrid45_response_checks(
        task,
        exercise_dir,
        model_output,
        parsed=parsed,
        parse_error=parse_error,
    )
    harness: AiderTestResult | None = None
    policy_violation = any(
        not static_checks[f"F{index}"] for index in range(1, 6)
    )
    complete_payload = static_checks["C2"] and static_checks["P5"] and static_checks["L5"]
    if parsed is None or policy_violation or not complete_payload:
        reason = (
            "not executed: forbidden runtime/verifier-bypass primitive"
            if policy_violation
            else "not executed: complete safe editable-file payload unavailable"
        )
        harness_checks, harness_evidence = failed_harness_checks(reason)
    else:
        try:
            selected_runner = runner
            if selected_runner is None:
                if task.harness_kind != "shadow_cpp17":
                    raise SandboxInfrastructureError(
                        "hybrid45 requires the shadow_cpp17 hidden-grader contract"
                    )
                selected_runner = run_shadow_hybrid45_tests
            harness = selected_runner(exercise_dir, parsed.files)
        except CandidatePolicyError:
            policy_violation = True
            harness_checks, harness_evidence = failed_harness_checks(
                "not executed: forbidden runtime/verifier-bypass primitive"
            )
        except SandboxInfrastructureError as exc:
            return Hybrid45AiderRewardBreakdown(
                reward=INFRASTRUCTURE_MASK_REWARD,
                reason=INFRASTRUCTURE_FAULT_REASON,
                parsed=parsed,
                infrastructure_detail=str(exc)[-2000:],
                infrastructure_error=True,
                ast17_checks={"error": 0.0},
            )
        else:
            if harness.status == "infrastructure_error":
                return Hybrid45AiderRewardBreakdown(
                    reward=INFRASTRUCTURE_MASK_REWARD,
                    reason=INFRASTRUCTURE_FAULT_REASON,
                    parsed=parsed,
                    harness=harness,
                    infrastructure_error=True,
                    infrastructure_detail=_combined_harness_logs(harness)[-2000:],
                )
            if set(harness.weighted45_checks) != WEIGHTED45_HARNESS_CHECK_IDS:
                return Hybrid45AiderRewardBreakdown(
                    reward=INFRASTRUCTURE_MASK_REWARD,
                    reason=INFRASTRUCTURE_FAULT_REASON,
                    parsed=parsed,
                    harness=harness,
                    infrastructure_error=True,
                    infrastructure_detail=(
                        "hybrid45 harness did not return the exact 20 K/R/H/A outcomes"
                    ),
                )
            harness_checks = dict(harness.weighted45_checks)
            harness_evidence = dict(harness.weighted45_evidence)

    all_checks = {**static_checks, **harness_checks}
    all_evidence = {**static_evidence, **harness_evidence}
    observed, applicable, compact_evidence = derive_hybrid45_observation(
        all_checks, all_evidence
    )
    reason = _weighted45_reason(
        parsed=parsed,
        parse_error=parse_error,
        response=model_output,
        harness=harness,
        policy_violation=policy_violation,
    )
    hybrid45 = score_hybrid45(
        all_checks,
        compact_evidence,
        observed,
        applicable,
        failure_mechanism=_hybrid45_failure_mechanism(reason),
    )
    if hybrid45.optimizer_score is None:
        return Hybrid45AiderRewardBreakdown(
            reward=INFRASTRUCTURE_MASK_REWARD,
            reason=INFRASTRUCTURE_FAULT_REASON,
            parsed=parsed,
            harness=harness,
            infrastructure_error=True,
            infrastructure_detail="hybrid45 scorer masked the optimizer score",
        )
    return Hybrid45AiderRewardBreakdown(
        reward=hybrid45.optimizer_score,
        reason=reason,
        parsed=parsed,
        harness=harness,
        s_aider=hybrid45.hidden_partitions_passed / 5.0,
        s_style=_cpp_quality_score(parsed.files) if parsed else 0.0,
        line_count=_candidate_line_count(parsed.files) if parsed else 0,
        hybrid45=hybrid45,
    )


def _mef_curriculum_role(task: AiderPolyglotTask) -> str:
    prefix = "curriculum-role-"
    roles = [tag.removeprefix(prefix) for tag in task.tags if tag.startswith(prefix)]
    allowed = {"ordinary", "repair", "calibration", "monitor"}
    if len(roles) != 1 or roles[0] not in allowed:
        raise ValueError(
            f"MEF45 task must bind exactly one curriculum role tag: {task.task_id}"
        )
    return roles[0]


def compute_hybrid45_mef_aider_reward(
    task: AiderPolyglotTask,
    exercise_dir: Path,
    model_output: str,
    *,
    runner: Runner | None = None,
) -> MEF45AiderRewardBreakdown:
    """Run the exact V2 verifier and apply the separately versioned MEF scalar."""

    if task.reward_contract != HYBRID45_MEF_POLICY_VERSION:
        return MEF45AiderRewardBreakdown(
            reward=INFRASTRUCTURE_MASK_REWARD,
            reason=INFRASTRUCTURE_FAULT_REASON,
            infrastructure_error=True,
            infrastructure_detail=(
                f"task reward_contract={task.reward_contract!r} does not bind "
                f"{HYBRID45_MEF_POLICY_VERSION}"
            ),
        )
    base_task = task.model_copy(update={"reward_contract": HYBRID45_POLICY_VERSION})
    base = compute_hybrid45_aider_reward(
        base_task,
        exercise_dir,
        model_output,
        runner=runner,
    )
    if base.infrastructure_error or base.hybrid45 is None:
        return MEF45AiderRewardBreakdown(
            reward=INFRASTRUCTURE_MASK_REWARD,
            reason=INFRASTRUCTURE_FAULT_REASON,
            parsed=base.parsed,
            harness=base.harness,
            infrastructure_error=True,
            infrastructure_detail=base.infrastructure_detail or "MEF45 base receipt unavailable",
            hybrid45=base.hybrid45,
        )
    try:
        projection = project_mef45(base.hybrid45, _mef_curriculum_role(task))
    except Exception as exc:
        return MEF45AiderRewardBreakdown(
            reward=INFRASTRUCTURE_MASK_REWARD,
            reason=INFRASTRUCTURE_FAULT_REASON,
            parsed=base.parsed,
            harness=base.harness,
            infrastructure_error=True,
            infrastructure_detail=f"MEF45 projection failed: {type(exc).__name__}: {exc}",
            hybrid45=base.hybrid45,
        )
    return MEF45AiderRewardBreakdown(
        reward=projection.optimizer_score,
        reason=base.reason,
        parsed=base.parsed,
        harness=base.harness,
        s_aider=base.s_aider,
        s_style=base.s_style,
        line_count=base.line_count,
        hybrid45=base.hybrid45,
        mef45=projection,
    )


def _hybrid45_failure_mechanism(reason: str) -> str | None:
    return {
        FORBIDDEN_VIOLATION_REASON: "protected_scope_escape_bypass_or_spoofing",
        CLARIFICATION_OR_NO_FILE_REASON: "no_file_payload",
        FATAL_PARSE_REASON: "fatal_parse",
        DUPLICATE_FILE_REASON: "duplicate_file",
        WRONG_FILE_LABEL_REASON: "wrong_file_label",
        COMPILATION_FAILURE_SYNTAX_REASON: "candidate_syntax_failure",
        COMPILATION_FAILURE_MISSING_SYMBOL_REASON: "public_symbol_missing",
        COMPILATION_FAILURE_MISSING_INCLUDE_OR_TYPE_REASON: "missing_include_or_type",
        COMPILATION_FAILURE_API_MISMATCH_REASON: "public_api_signature_mismatch",
        COMPILATION_FAILURE_LINKER_REASON: "linkage_failure",
        COMPILATION_FAILURE_WARNING_REASON: "warning_clean_compile_failure",
        COMPILATION_FAILURE_REASON: "compilation_failure",
        CANDIDATE_TIMEOUT_REASON: "candidate_inner_timeout",
        SANITIZER_ERROR_REASON: "sanitizer_failure",
        RUNTIME_ZERO_PASS_REASON: "hidden_semantic_failure",
        PARTIAL_TEST_PASS_REASON: "partial_hidden_semantics",
    }.get(reason.removeprefix("recoverable_format_"))


def _weighted45_reason(
    *,
    parsed: ParsedAiderResponse | None,
    parse_error: AiderResponseError | None,
    response: str,
    harness: AiderTestResult | None,
    policy_violation: bool,
) -> str:
    if policy_violation:
        return FORBIDDEN_VIOLATION_REASON
    if parse_error is not None:
        _legacy_reward, reason = _parse_failure_reward(parse_error, response)
        return reason
    if harness is None:
        return FATAL_PARSE_REASON
    if harness.all_tests_pass:
        return _format_sensitive_reason(parsed, "correct") if parsed else "correct"
    if harness.status == "compile_failed":
        _legacy_reward, reason = _classify_compile_failure(harness)
        return _format_sensitive_reason(parsed, reason) if parsed else reason
    if harness.status == "candidate_timeout":
        return CANDIDATE_TIMEOUT_REASON
    return (
        _format_sensitive_reason(parsed, PARTIAL_TEST_PASS_REASON)
        if parsed
        else PARTIAL_TEST_PASS_REASON
    )


def _continuous_test_reward(harness: AiderTestResult) -> float:
    """Map executed test progress monotonically onto [-0.20, 1.00].

    Parse and compilation outcomes have their own negative progress bands. Once
    the candidate can execute tests, correctness alone determines its reward;
    formatting, AST, style, and bloat remain telemetry and cannot move a
    candidate across a test-case boundary.
    """

    if harness.tests_total <= 0:
        raise SandboxInfrastructureError(
            "compiled Aider candidate did not report a positive test count"
        )
    if harness.tests_passed > harness.tests_total:
        raise SandboxInfrastructureError(
            "compiled Aider candidate reported more passing tests than total tests"
        )
    fraction = harness.tests_passed / harness.tests_total
    reward = TEST_EXECUTION_FLOOR + (
        TEST_EXECUTION_CEILING - TEST_EXECUTION_FLOOR
    ) * fraction
    return round(max(-1.0, min(1.0, reward)), 4)


def _parse_failure_reward(exc: AiderResponseError, response: str) -> tuple[float, str]:
    if exc.reason == "forbidden_file":
        target = _extract_target_from_error(exc)
        if _is_protected_or_escape_target(target):
            return FORBIDDEN_REWARD, FORBIDDEN_VIOLATION_REASON
        return WRONG_FILE_LABEL_REWARD, WRONG_FILE_LABEL_REASON
    if exc.reason == "duplicate_file":
        return DUPLICATE_FILE_REWARD, DUPLICATE_FILE_REASON
    if exc.reason in {"invalid_encoding", "response_too_large"}:
        return FATAL_PARSE_REWARD, FATAL_PARSE_REASON
    if _has_no_usable_file_output(response):
        return CLARIFICATION_OR_NO_FILE_REWARD, CLARIFICATION_OR_NO_FILE_REASON
    return FATAL_PARSE_REWARD, FATAL_PARSE_REASON


def _extract_target_from_error(exc: AiderResponseError) -> str:
    marker = "response targets non-editable file:"
    message = str(exc)
    if marker not in message:
        return ""
    return message.split(marker, 1)[1].strip()


def _is_protected_or_escape_target(target: str) -> bool:
    if not target:
        return True
    path = PurePath(target)
    if path.is_absolute() or ".." in path.parts:
        return True
    return target in PROTECTED_NAMES or target.endswith(PROTECTED_SUFFIXES)


def _has_no_usable_file_output(response: str) -> bool:
    stripped = response.strip().lower()
    if "```" not in response:
        return True
    clarification_markers = (
        "clarify",
        "clarification",
        "could you provide",
        "please provide",
        "i need more",
        "need more information",
    )
    return bool(stripped) and any(marker in stripped for marker in clarification_markers)


def _compile_failure_reward(
    harness: AiderTestResult, parsed: ParsedAiderResponse, task: AiderPolyglotTask
) -> tuple[float, str]:
    base_reward, reason = _classify_compile_failure(harness)
    if reason == COMPILATION_FAILURE_SYNTAX_REASON:
        return base_reward, reason
    reward = base_reward + _compile_format_adjustment(parsed) + 0.05 * _mechanism_score(task, parsed)
    return round(max(-0.65, min(-0.30, reward)), 4), reason


def _classify_compile_failure(harness: AiderTestResult) -> tuple[float, str]:
    logs = _combined_harness_logs(harness).lower()
    if _contains_any(logs, COMPILE_LINKER_MARKERS):
        return COMPILATION_FAILURE_LINKER_REWARD, COMPILATION_FAILURE_LINKER_REASON
    if _contains_any(logs, COMPILE_API_MISMATCH_MARKERS):
        return COMPILATION_FAILURE_API_MISMATCH_REWARD, COMPILATION_FAILURE_API_MISMATCH_REASON
    if _contains_any(logs, COMPILE_MISSING_INCLUDE_OR_TYPE_MARKERS):
        return (
            COMPILATION_FAILURE_MISSING_INCLUDE_OR_TYPE_REWARD,
            COMPILATION_FAILURE_MISSING_INCLUDE_OR_TYPE_REASON,
        )
    if _contains_any(logs, COMPILE_MISSING_SYMBOL_MARKERS):
        return COMPILATION_FAILURE_MISSING_SYMBOL_REWARD, COMPILATION_FAILURE_MISSING_SYMBOL_REASON
    if _contains_any(logs, COMPILE_SYNTAX_MARKERS):
        return COMPILATION_FAILURE_SYNTAX_REWARD, COMPILATION_FAILURE_SYNTAX_REASON
    if _contains_any(logs, COMPILE_WARNING_MARKERS):
        return COMPILATION_FAILURE_WARNING_REWARD, COMPILATION_FAILURE_WARNING_REASON
    return COMPILATION_FAILURE_REWARD, COMPILATION_FAILURE_REASON


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _compile_format_adjustment(parsed: ParsedAiderResponse) -> float:
    return 0.03 if parsed.format_valid else -0.05


def _format_sensitive_reason(parsed: ParsedAiderResponse, reason: str) -> str:
    return reason if parsed.format_valid else f"recoverable_format_{reason}"


def _mechanism_score(task: AiderPolyglotTask, parsed: ParsedAiderResponse) -> float:
    combined = "\n".join(parsed.files.values())
    expected_files = set(task.editable_files)
    observed_files = set(parsed.files)
    checks = [
        bool(observed_files),
        expected_files.issubset(observed_files),
        bool(CPP_STRUCTURE_RE.search(combined)),
        _candidate_line_count(parsed.files) >= 1,
    ]
    return sum(checks) / len(checks)


def _cpp_quality_score(files: dict[str, str]) -> float:
    combined = "\n".join(files.values())
    line_count = _candidate_line_count(files)
    checks = [
        "using namespace std" not in combined,
        not RAW_NEW_RE.search(combined) and not RAW_DELETE_RE.search(combined),
        not MUTABLE_GLOBAL_RE.search(_remove_class_bodies(combined)),
        bool(CONST_REF_RE.search(combined)) or line_count <= 30,
    ]
    return sum(checks) / len(checks)


def _remove_class_bodies(source: str) -> str:
    return re.sub(r"\b(?:class|struct)\s+\w+[^{}]*\{.*?\};", "", source, flags=re.DOTALL)


def _candidate_line_count(files: dict[str, str]) -> int:
    return sum(1 for contents in files.values() for line in contents.splitlines() if line.strip())


def _combined_harness_logs(harness: AiderTestResult) -> str:
    return "\n".join(str(value) for value in harness.logs.values())


def _harness_has_sanitizer_error(harness: AiderTestResult) -> bool:
    logs = _combined_harness_logs(harness).lower()
    return any(marker in logs for marker in SANITIZER_ERROR_MARKERS)
