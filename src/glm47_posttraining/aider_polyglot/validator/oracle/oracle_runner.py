"""Execute canonical reference solutions through the exact Weighted45 harness."""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import time
from collections.abc import Callable, Mapping
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory

from glm47_posttraining.cpp_perf.sandbox import sandbox_backend

from ...harness import run_shadow_weighted45_tests
from ...parser import AiderResponseError, parse_whole_file_response
from ...policy45 import WEIGHTED45_CHECK_IDS
from ...reward import compute_weighted45_aider_reward
from ...schema import AiderPolyglotTask, AiderTestResult
from .oracle_cache import OracleReceiptCache, oracle_cache_key
from .oracle_receipt import (
    OracleCertificationReceipt,
    OracleEnvironment,
    OracleInputBinding,
    OracleRuleResult,
    OracleRunReceipt,
    OracleValidationConfig,
    SHA256_ZERO,
    canonical_sha256,
    compute_certification_sha256,
)
from .oracle_rules import oracle_rule


HarnessRunner = Callable[[Path, Mapping[str, str], str, str], AiderTestResult]


class OracleCertificationError(ValueError):
    """A task failed one or more mandatory oracle rules."""

    def __init__(self, receipt: OracleCertificationReceipt) -> None:
        self.receipt = receipt
        super().__init__(
            f"oracle certification rejected {receipt.task_id}: "
            f"failed_rules={list(receipt.failed_rule_ids)}"
        )


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_sha256(root: Path, names: list[str]) -> str:
    digest = hashlib.sha256()
    for name in sorted(names):
        relative = name.encode("utf-8")
        data = (root / name).read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _rule_result(
    rule_id: str,
    passed: bool,
    *,
    observed: str,
    expected: str,
    evidence: str,
) -> OracleRuleResult:
    definition = oracle_rule(rule_id)
    return OracleRuleResult(
        rule_id=rule_id,
        rule_version=definition.version,
        passed=passed,
        severity=definition.severity,
        observed=observed,
        expected=expected,
        evidence=evidence,
        remediation=definition.remediation,
    )


def load_reference_solution(
    exercise: str | Path, editable_files: list[str]
) -> tuple[dict[str, str], tuple[OracleRuleResult, ...]]:
    """Load an exact, private reference package and return auditable rule outcomes."""

    source = Path(exercise)
    reference = source / ".reference"
    directory_ok = reference.is_dir() and not reference.is_symlink()
    rules = [
        _rule_result(
            "ORC-001",
            directory_ok,
            observed=str(reference) if reference.exists() else "missing",
            expected="real non-symlink .reference directory",
            evidence=f"is_dir={reference.is_dir()} is_symlink={reference.is_symlink()}",
        )
    ]
    if not directory_ok:
        for rule_id in ("ORC-002", "ORC-003", "ORC-004"):
            rules.append(
                _rule_result(
                    rule_id,
                    False,
                    observed="not evaluated",
                    expected=oracle_rule(rule_id).description,
                    evidence="blocked by ORC-001",
                )
            )
        return {}, tuple(rules)

    actual = {
        path.relative_to(reference).as_posix()
        for path in reference.rglob("*")
        if path.is_file()
    }
    expected = set(editable_files)
    exact_files = actual == expected
    rules.append(
        _rule_result(
            "ORC-002",
            exact_files,
            observed=f"files={sorted(actual)}",
            expected=f"files={sorted(expected)}",
            evidence=(
                f"missing={sorted(expected - actual)} extra={sorted(actual - expected)}"
            ),
        )
    )
    regular = exact_files and all(
        (reference / name).is_file()
        and not (reference / name).is_symlink()
        and (reference / name).resolve().parent == reference.resolve()
        for name in editable_files
    )
    rules.append(
        _rule_result(
            "ORC-003",
            regular,
            observed=f"regular_direct_children={regular}",
            expected="all reference files are regular direct children",
            evidence=f"reference_root={reference.resolve()}",
        )
    )
    files: dict[str, str] = {}
    response_ok = regular
    response_evidence = "blocked by ORC-002/ORC-003"
    if regular:
        try:
            files = {
                name: (reference / name).read_text(encoding="utf-8")
                for name in editable_files
            }
            response = render_reference_response(files)
            parsed = parse_whole_file_response(response, editable_files)
            response_ok = parsed.format_valid and parsed.files == {
                name: contents.rstrip() + "\n" for name, contents in files.items()
            }
            response_evidence = (
                f"format_valid={parsed.format_valid} parsed={sorted(parsed.files)} "
                f"bytes={len(response.encode('utf-8'))}"
            )
        except (UnicodeError, AiderResponseError, OSError) as exc:
            response_ok = False
            response_evidence = f"{type(exc).__name__}: {exc}"
    rules.append(
        _rule_result(
            "ORC-004",
            response_ok,
            observed=f"whole_file_response_valid={response_ok}",
            expected="exact parse of every editable reference file",
            evidence=response_evidence,
        )
    )
    return files if response_ok else {}, tuple(rules)


def render_reference_response(files: Mapping[str, str]) -> str:
    return "".join(
        f"{name}\n```cpp\n{contents.rstrip()}\n```\n" for name, contents in files.items()
    )


def _compiler_version() -> str:
    try:
        completed = subprocess.run(
            ["c++", "--version"], check=False, capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"unavailable:{type(exc).__name__}"
    first_line = (completed.stdout or completed.stderr or "unknown").splitlines()
    return first_line[0] if first_line else "unknown"


@lru_cache(maxsize=1)
def _environment() -> OracleEnvironment:
    return OracleEnvironment(
        python_version=platform.python_version(),
        platform=platform.platform(),
        compiler=_compiler_version(),
        sandbox_backend=sandbox_backend(),
        sandbox_unshare_net=os.environ.get("GLM47_CPP_SANDBOX_UNSHARE_NET", "1"),
    )


def _default_harness_runner(
    exercise: Path,
    files: Mapping[str, str],
    standard: str,
    hidden_test_sha256: str,
) -> AiderTestResult:
    return run_shadow_weighted45_tests(
        exercise,
        files,
        expected_test_sha256=hidden_test_sha256,
        cpp_standard=standard,
        optimize=True,
        hidden_werror=True,
    )


def _run_signature(run: OracleRunReceipt) -> tuple[object, ...]:
    return (
        run.reward,
        run.normalized_percentage,
        run.reason,
        run.infrastructure_error,
        run.infrastructure_detail,
        run.harness_status,
        run.tests_passed,
        run.tests_total,
        run.checks_sha256,
    )


def certify_task_oracle(
    task: AiderPolyglotTask,
    source_exercise: str | Path,
    hidden_test_file: str,
    *,
    config: OracleValidationConfig | None = None,
    cache: OracleReceiptCache | None = None,
    harness_runner: HarnessRunner | None = None,
) -> OracleCertificationReceipt:
    """Certify one task by running its private reference through all 45 checks."""

    selected_config = config or OracleValidationConfig()
    exercise = Path(source_exercise)
    reference_files, reference_rules = load_reference_solution(exercise, task.editable_files)
    hidden_path = exercise / hidden_test_file
    hidden_observed = _sha256_path(hidden_path) if hidden_path.is_file() else SHA256_ZERO
    hidden_expected = task.hidden_test_sha256 or SHA256_ZERO
    hidden_ok = hidden_observed == hidden_expected and hidden_observed != SHA256_ZERO
    hidden_rule = _rule_result(
        "ORC-005",
        hidden_ok,
        observed=hidden_observed,
        expected=hidden_expected,
        evidence=f"hidden_test={hidden_path}",
    )
    starter_hash = (
        _tree_sha256(exercise, task.editable_files)
        if all((exercise / name).is_file() for name in task.editable_files)
        else SHA256_ZERO
    )
    reference_hash = (
        _tree_sha256(exercise / ".reference", task.editable_files)
        if reference_files
        else SHA256_ZERO
    )
    input_binding = OracleInputBinding(
        task_descriptor_sha256=canonical_sha256(task.model_dump(mode="json")),
        starter_tree_sha256=starter_hash,
        reference_tree_sha256=reference_hash,
        hidden_test_sha256=hidden_observed,
        source_prompt_sha256=task.source_prompt_sha256,
    )
    environment = _environment()

    # Cache lookup is fail-closed and bound to the full task/config/environment tuple.
    provisional = OracleCertificationReceipt(
        task_id=task.task_id,
        status="rejected",
        config=selected_config,
        config_sha256=selected_config.config_sha256,
        input_binding=input_binding,
        environment=environment,
        runs=(),
        rules=(
            *reference_rules,
            hidden_rule,
            *(
                _rule_result(
                    rule_id,
                    False,
                    observed="not evaluated",
                    expected=oracle_rule(rule_id).description,
                    evidence="provisional cache key",
                )
                for rule_id in ("ORC-010", "ORC-011", "ORC-012", "ORC-013", "ORC-014", "ORC-015", "ORC-016")
            ),
        ),
        certification_sha256=SHA256_ZERO,
    )
    if cache is not None:
        cached = cache.load(oracle_cache_key(provisional), task_id=task.task_id)
        if cached is not None:
            return cached

    runs: list[OracleRunReceipt] = []
    can_execute = bool(reference_files) and hidden_ok
    if can_execute:
        with TemporaryDirectory(prefix=f"oracle_{task.exercise}_") as temporary:
            workspace = Path(temporary)
            (workspace / ".grader").mkdir(parents=True)
            for name in task.editable_files:
                shutil.copy2(exercise / name, workspace / name)
            shutil.copy2(hidden_path, workspace / ".grader" / "test.cpp")
            response = render_reference_response(reference_files)
            selected_runner = harness_runner or _default_harness_runner
            for standard in selected_config.standards:
                for run_index in range(1, selected_config.runs_per_standard + 1):
                    started = time.perf_counter()

                    def runner(path: Path, files: dict[str, str]) -> AiderTestResult:
                        return selected_runner(path, files, standard, hidden_expected)

                    breakdown = compute_weighted45_aider_reward(
                        task, workspace, response, runner=runner
                    )
                    elapsed_ms = max(0, round((time.perf_counter() - started) * 1000))
                    weighted = breakdown.weighted45
                    checks = dict(weighted.checks) if weighted is not None else {}
                    harness = breakdown.harness
                    runs.append(
                        OracleRunReceipt(
                            standard=standard,
                            run_index=run_index,
                            reward=breakdown.reward,
                            normalized_percentage=(
                                weighted.normalized_percentage if weighted is not None else 0.0
                            ),
                            reason=breakdown.reason,
                            infrastructure_detail=breakdown.infrastructure_detail,
                            infrastructure_error=breakdown.infrastructure_error,
                            harness_status=harness.status if harness is not None else None,
                            tests_passed=harness.tests_passed if harness is not None else 0,
                            tests_total=harness.tests_total if harness is not None else 0,
                            checks=checks,
                            checks_sha256=canonical_sha256(dict(sorted(checks.items()))),
                            duration_ms=elapsed_ms,
                        )
                    )

    expected_run_count = len(selected_config.standards) * selected_config.runs_per_standard
    no_infrastructure = len(runs) == expected_run_count and all(
        not run.infrastructure_error for run in runs
    )
    exact_receipts = len(runs) == expected_run_count and all(
        set(run.checks) == WEIGHTED45_CHECK_IDS
        and all(isinstance(value, bool) for value in run.checks.values())
        for run in runs
    )
    perfect_rewards = len(runs) == expected_run_count and all(
        run.reward == selected_config.expected_reward for run in runs
    )
    all_checks = exact_receipts and all(all(run.checks.values()) for run in runs)
    sanitizers = exact_receipts and all(
        run.checks.get("A2") is True and run.checks.get("A4") is True for run in runs
    )
    deterministic = len(runs) == expected_run_count
    per_standard_signatures: dict[str, set[tuple[object, ...]]] = {}
    for run in runs:
        per_standard_signatures.setdefault(run.standard, set()).add(_run_signature(run))
    deterministic = deterministic and all(
        len(per_standard_signatures.get(standard, set())) == 1
        for standard in selected_config.standards
    )
    matrix_passed = (
        {run.standard for run in runs} == set(selected_config.standards)
        and perfect_rewards
        and all_checks
    )
    execution_rules = (
        _rule_result(
            "ORC-010",
            no_infrastructure,
            observed=f"runs={len(runs)} infrastructure_faults={sum(run.infrastructure_error for run in runs)}",
            expected=f"{expected_run_count} runs and zero infrastructure faults",
            evidence="; ".join(
                f"{run.standard}#{run.run_index}:{run.reason}"
                + (
                    f":{run.infrastructure_detail}"
                    if run.infrastructure_detail
                    else ""
                )
                for run in runs
            ),
        ),
        _rule_result(
            "ORC-011",
            exact_receipts,
            observed=f"exact_receipts={sum(set(run.checks) == WEIGHTED45_CHECK_IDS for run in runs)}",
            expected=f"{expected_run_count} exact 45-check receipts",
            evidence="; ".join(f"{run.standard}#{run.run_index}:{len(run.checks)}" for run in runs),
        ),
        _rule_result(
            "ORC-012",
            perfect_rewards,
            observed=f"rewards={[run.reward for run in runs]}",
            expected=f"{[selected_config.expected_reward] * expected_run_count}",
            evidence=f"policy={selected_config.policy_version}",
        ),
        _rule_result(
            "ORC-013",
            all_checks,
            observed=f"all_checks_pass={all_checks}",
            expected="all 45 checks true on every run",
            evidence="; ".join(
                f"{run.standard}#{run.run_index}:"
                f"{sorted(check for check, passed in run.checks.items() if not passed)}"
                for run in runs
            ),
        ),
        _rule_result(
            "ORC-014",
            sanitizers,
            observed=f"sanitizer_matrix_pass={sanitizers}",
            expected="A2 and A4 true on every run",
            evidence="; ".join(
                f"{run.standard}#{run.run_index}:A2={run.checks.get('A2')} A4={run.checks.get('A4')}"
                for run in runs
            ),
        ),
        _rule_result(
            "ORC-015",
            deterministic,
            observed=f"signature_counts={dict((key, len(value)) for key, value in per_standard_signatures.items())}",
            expected="one identical outcome signature per standard across at least three runs",
            evidence=f"runs_per_standard={selected_config.runs_per_standard}",
        ),
        _rule_result(
            "ORC-016",
            matrix_passed,
            observed=f"standards={sorted({run.standard for run in runs})}",
            expected=f"standards={list(selected_config.standards)} all perfect",
            evidence=f"perfect_rewards={perfect_rewards} all_checks={all_checks}",
        ),
    )
    rules = (*reference_rules, hidden_rule, *execution_rules)
    status = "certified" if all(rule.passed for rule in rules) else "rejected"
    receipt = OracleCertificationReceipt(
        task_id=task.task_id,
        status=status,
        config=selected_config,
        config_sha256=selected_config.config_sha256,
        input_binding=input_binding,
        environment=environment,
        runs=tuple(runs),
        rules=rules,
        certification_sha256=SHA256_ZERO,
    )
    receipt = receipt.model_copy(
        update={"certification_sha256": compute_certification_sha256(receipt)}
    )
    if cache is not None and receipt.status == "certified":
        cache.store(receipt)
    return receipt


def require_certified_oracle(receipt: OracleCertificationReceipt) -> None:
    if receipt.status != "certified":
        raise OracleCertificationError(receipt)


__all__ = [
    "HarnessRunner",
    "OracleCertificationError",
    "certify_task_oracle",
    "load_reference_solution",
    "render_reference_response",
    "require_certified_oracle",
]
