"""Evidence-backed 45-check reward policy for Aider C++ GRPO.

The policy deliberately separates response/static checks from checks produced by
the sandboxed C++ harness.  A missing or unsafe downstream stage contributes
failed checks; verifier infrastructure failures are raised and never converted
to model reward.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path, PurePath
import re
from typing import Mapping

from .parser import (
    AiderResponseError,
    FENCE_RE,
    ParsedAiderResponse,
    TERMINAL_STOP_RE,
    _looks_like_file_target,
    _normalize_label,
    _preceding_line,
)
from .schema import (
    AiderPolyglotTask,
    WEIGHTED45_CHECK_IDS,
    WEIGHTED45_HARNESS_CHECK_IDS,
    WEIGHTED45_TIER_CHECKS,
)


WEIGHTED45_TIER_WEIGHTS: dict[str, float] = {
    "forbidden_file_bypass": 1.00,
    "clarification_no_file": 0.92,
    "fatal_parse_failure": 0.85,
    "wrong_file_label": 0.75,
    "duplicate_file": 0.70,
    "compilation": 0.55,
    "runtime": 0.12,
    "hidden_tests": 0.80,
    "full_pass": 0.85,
}
WEIGHTED45_TOTAL_WEIGHT = 6.54
WEIGHTED45_POLICY_VERSION = "weighted45-v1"
STATIC_CHECK_IDS = WEIGHTED45_CHECK_IDS - WEIGHTED45_HARNESS_CHECK_IDS

SYSTEM_CALL_RE = re.compile(
    r"\b(?:system|popen|fork|vfork|exec(?:l|le|lp|v|ve|vp|vpe)|posix_spawn|kill|raise|_Exit|_exit|"
    r"exit|quick_exit|abort|terminate)\s*\("
)
PRIVILEGE_RE = re.compile(
    r"\b(?:setuid|seteuid|setgid|setegid|setresuid|setresgid|capset|chown|chmod|"
    r"fchmod|mount|unshare|setns|ptrace|prctl)\s*\("
)
RESTRICTED_PATH_RE = re.compile(
    r"(?:^|[\"'\s/])(?:\.grader|CMakeLists\.txt|/proc|/sys|/dev|/run/secrets)|"
    r"(?:_test\.(?:cpp|cc|h)\b)",
    re.IGNORECASE | re.MULTILINE,
)
PROCESS_EXEC_RE = re.compile(
    r"\b(?:system|popen|fork|vfork|exec(?:l|le|lp|v|ve|vp|vpe)|posix_spawn)\s*\(|"
    r"\b(?:bash|sh|zsh|python|perl|ruby)\s+-[a-z]",
    re.IGNORECASE,
)
SPOOF_RE = re.compile(r"GLM47_AIDER_(?:PASS|WEIGHTED45|SUITE)", re.IGNORECASE)
BYPASS_RE = re.compile(
    r"#\s*(?:define|undef)\s+(?:main|return|if|for|while|switch)\b|"
    r"\b(?:__asm__|__asm|asm)\b"
)
SYMLINK_RE = re.compile(r"\b(?:symlink|readlink|realpath)\s*\(")
CLARIFICATION_RE = re.compile(
    r"\b(?:clarif(?:y|ication)|could you provide|please provide|need more information)\b",
    re.IGNORECASE,
)
CPP_DEFINITION_RE = re.compile(
    r"\b(?:class|struct|enum(?:\s+class)?)\s+([A-Za-z_]\w*)|"
    r"\b([A-Za-z_]\w*)\s*\([^;{}]*\)\s*(?:const\s*)?\{"
)
CPP_API_RE = re.compile(
    r"\b(?:class|struct|enum(?:\s+class)?|namespace)\s+([A-Za-z_]\w*)|"
    r"\b([A-Za-z_]\w*)\s*\([^;{}]*\)\s*(?:const\s*)?(?:;|\{)"
)
CPP_KEYWORDS = {
    "if",
    "for",
    "while",
    "switch",
    "catch",
    "return",
    "sizeof",
    "static_cast",
    "dynamic_cast",
    "reinterpret_cast",
    "const_cast",
}
VALID_PREPROCESSOR_RE = re.compile(
    r"^\s*#\s*(?:include|define|undef|if|ifdef|ifndef|elif|else|endif|pragma|line|"
    r"error|warning)\b"
)


@dataclass(frozen=True)
class Weighted45Score:
    """Complete score and auditable intermediate values for all 45 checks."""

    checks: dict[str, bool]
    evidence: dict[str, str]
    tier_pass_counts: dict[str, int]
    raw_tier_rewards: dict[str, float]
    weighted_tier_rewards: dict[str, float]
    numerator: float
    total_weight: float
    normalized_reward: float
    normalized_percentage: float

    def to_record(self) -> dict[str, object]:
        return {
            "policy_version": WEIGHTED45_POLICY_VERSION,
            "checks": dict(self.checks),
            "evidence": dict(self.evidence),
            "tier_pass_counts": dict(self.tier_pass_counts),
            "raw_tier_rewards": dict(self.raw_tier_rewards),
            "weighted_tier_rewards": dict(self.weighted_tier_rewards),
            "numerator": self.numerator,
            "total_weight": self.total_weight,
            "normalized_reward": self.normalized_reward,
            "normalized_percentage": self.normalized_percentage,
        }


@dataclass(frozen=True)
class _ResponseFence:
    raw_label: str
    normalized_label: str
    exact_label: bool
    code: str
    target: str | None


def score_weighted45(
    checks: Mapping[str, bool], evidence: Mapping[str, str] | None = None
) -> Weighted45Score:
    """Apply ``(0.3*N - 0.5)*W`` to every tier and normalize by 6.54."""

    observed = set(checks)
    if observed != WEIGHTED45_CHECK_IDS:
        missing = sorted(WEIGHTED45_CHECK_IDS - observed)
        extra = sorted(observed - WEIGHTED45_CHECK_IDS)
        raise ValueError(f"weighted45 check contract mismatch: missing={missing} extra={extra}")
    if any(not isinstance(value, bool) for value in checks.values()):
        raise TypeError("weighted45 outcomes must be booleans")
    supplied_evidence = dict(evidence or {})
    unknown_evidence = set(supplied_evidence) - WEIGHTED45_CHECK_IDS
    if unknown_evidence:
        raise ValueError(f"weighted45 evidence has unknown checks: {sorted(unknown_evidence)}")

    pass_counts: dict[str, int] = {}
    raw_rewards: dict[str, float] = {}
    weighted_rewards: dict[str, float] = {}
    for tier, check_ids in WEIGHTED45_TIER_CHECKS.items():
        passed = sum(bool(checks[check_id]) for check_id in check_ids)
        raw = 0.3 * passed - 0.5
        weighted = raw * WEIGHTED45_TIER_WEIGHTS[tier]
        pass_counts[tier] = passed
        raw_rewards[tier] = round(raw, 10)
        weighted_rewards[tier] = round(weighted, 10)

    numerator = math.fsum(weighted_rewards.values())
    normalized = numerator / WEIGHTED45_TOTAL_WEIGHT
    if not -1.0 <= normalized <= 1.0:
        raise ValueError(f"weighted45 normalized reward escaped [-1, 1]: {normalized}")
    return Weighted45Score(
        checks=dict(checks),
        evidence=supplied_evidence,
        tier_pass_counts=pass_counts,
        raw_tier_rewards=raw_rewards,
        weighted_tier_rewards=weighted_rewards,
        numerator=round(numerator, 10),
        total_weight=WEIGHTED45_TOTAL_WEIGHT,
        normalized_reward=round(normalized, 6),
        normalized_percentage=round(normalized * 100.0, 4),
    )


def evaluate_response_checks(
    task: AiderPolyglotTask,
    exercise_dir: Path,
    response: str,
    *,
    parsed: ParsedAiderResponse | None,
    parse_error: AiderResponseError | None,
) -> tuple[dict[str, bool], dict[str, str]]:
    """Evaluate the 25 response/static checks regardless of parse success."""

    del parse_error  # The checks are derived from the response, not an error bucket.
    clean_response = TERMINAL_STOP_RE.sub("", response)
    fences = _inspect_fences(clean_response, task.editable_files)
    code = "\n".join(fence.code for fence in fences) or clean_response
    labels = [fence.normalized_label for fence in fences if fence.normalized_label]
    targets = [fence.target for fence in fences if fence.target is not None]
    parsed_files = parsed.files if parsed is not None else {}
    parsed_ok = parsed is not None and bool(parsed_files)
    allowed = set(task.editable_files)
    unsafe_labels = [
        label
        for label in labels
        if _looks_like_file_target(label)
        and label not in allowed
        and PurePath(label).name not in allowed
    ]
    exact_targets = [
        fence.target
        for fence in fences
        if fence.target is not None and fence.exact_label and fence.normalized_label in allowed
    ]
    target_counts = {target: targets.count(target) for target in set(targets)}
    normalized_counts = {label: labels.count(label) for label in set(labels)}
    content_hashes = [hashlib.sha256(fence.code.encode()).hexdigest() for fence in fences]
    definitions = _definition_names(parsed_files)
    required_symbols, required_namespaces = _required_api(exercise_dir, task.editable_files)
    candidate_text = "\n".join(parsed_files.values())

    checks = {
        # Forbidden file / bypass
        "F1": SYSTEM_CALL_RE.search(code) is None,
        "F2": PRIVILEGE_RE.search(code) is None,
        "F3": RESTRICTED_PATH_RE.search(code) is None,
        "F4": PROCESS_EXEC_RE.search(code) is None,
        "F5": not unsafe_labels
        and SPOOF_RE.search(code) is None
        and BYPASS_RE.search(code) is None,
        # Clarification / no file
        "C1": parsed_ok,
        "C2": parsed_ok and set(parsed_files) == allowed,
        "C3": parsed_ok and all(_substantive(contents) for contents in parsed_files.values()),
        "C4": parsed_ok
        and not unsafe_labels
        and SYMLINK_RE.search(code) is None
        and all(_safe_relative_label(label) for label in labels),
        "C5": parsed_ok and CLARIFICATION_RE.search(clean_response) is None,
        # Fatal parse failure
        "P1": bool(fences) and all(_lexically_balanced(fence.code) for fence in fences),
        "P2": _valid_text_encoding(clean_response),
        "P3": clean_response.count("```") == 2 * len(fences) and bool(fences),
        "P4": all(_preprocessor_lexically_valid(fence.code) for fence in fences),
        "P5": parsed_ok,
        # Wrong file label
        "L1": parsed_ok and len(exact_targets) == len(fences) and bool(fences),
        "L2": parsed_ok and _symbols_preserved(candidate_text, required_symbols),
        "L3": parsed_ok
        and bool(parsed.format_valid)
        and _symbols_preserved(candidate_text, required_namespaces),
        "L4": parsed_ok
        and len(targets) == len(fences)
        and all(count == 1 for count in target_counts.values()),
        "L5": parsed_ok and set(targets) == allowed and not unsafe_labels,
        # Duplicate file
        "D1": all(count == 1 for count in target_counts.values()),
        "D2": len(content_hashes) == len(set(content_hashes)),
        "D3": all(count == 1 for count in normalized_counts.values()),
        "D4": len(definitions) == len(set(definitions)),
        "D5": len({label.casefold() for label in labels}) == len(labels),
    }
    if set(checks) != STATIC_CHECK_IDS:
        raise AssertionError("internal weighted45 static check set is incomplete")

    evidence = {
        "F1": "no forbidden system-call primitive" if checks["F1"] else "system-call primitive",
        "F2": "no privilege primitive" if checks["F2"] else "privilege primitive",
        "F3": "no restricted path reference" if checks["F3"] else "restricted path reference",
        "F4": "no process-spawn path" if checks["F4"] else "process-spawn path",
        "F5": "no escape/spoof label" if checks["F5"] else "escape or spoof label",
        "C1": f"parsed_files={len(parsed_files)}",
        "C2": f"required={sorted(allowed)} supplied={sorted(parsed_files)}",
        "C3": "all supplied files substantive" if checks["C3"] else "missing/empty file",
        "C4": "workspace-relative dependencies" if checks["C4"] else "unsafe dependency/label",
        "C5": "implementation payload" if checks["C5"] else "clarification/no payload",
        "P1": f"complete_fences={len(fences)} lexical_balance={checks['P1']}",
        "P2": f"valid_utf8_no_nul={checks['P2']}",
        "P3": f"fence_tokens={clean_response.count('```')}",
        "P4": f"preprocessor_lexical_valid={checks['P4']}",
        "P5": f"whole_file_parse={checks['P5']}",
        "L1": f"exact_labels={len(exact_targets)}/{len(fences)}",
        "L2": f"required_api_symbols={sorted(required_symbols)}",
        "L3": f"required_namespaces={sorted(required_namespaces)}",
        "L4": f"target_counts={target_counts}",
        "L5": f"manifest_targets={sorted(allowed)} observed={sorted(targets)}",
        "D1": f"canonical_target_counts={target_counts}",
        "D2": f"content_blocks={len(content_hashes)} unique={len(set(content_hashes))}",
        "D3": f"normalized_label_counts={normalized_counts}",
        "D4": f"definitions={definitions}",
        "D5": f"labels={labels}",
    }
    return checks, evidence


def failed_harness_checks(reason: str) -> tuple[dict[str, bool], dict[str, str]]:
    """Represent safely skipped downstream work without manufacturing passes."""

    checks = {check_id: False for check_id in WEIGHTED45_HARNESS_CHECK_IDS}
    evidence = {check_id: reason for check_id in WEIGHTED45_HARNESS_CHECK_IDS}
    return checks, evidence


def _inspect_fences(response: str, editable_files: list[str]) -> list[_ResponseFence]:
    allowed = set(editable_files)
    inspected: list[_ResponseFence] = []
    for match in FENCE_RE.finditer(response):
        raw_label = _preceding_line(response, match.start())
        normalized, exact = _normalize_label(raw_label)
        target: str | None = None
        if normalized in allowed:
            target = normalized
        elif normalized and PurePath(normalized).name in allowed:
            target = PurePath(normalized).name
            exact = False
        inspected.append(
            _ResponseFence(
                raw_label=raw_label,
                normalized_label=normalized,
                exact_label=exact,
                code=match.group("code"),
                target=target,
            )
        )
    return inspected


def _safe_relative_label(label: str) -> bool:
    path = PurePath(label)
    return bool(label) and not path.is_absolute() and ".." not in path.parts


def _substantive(contents: str) -> bool:
    without_comments = re.sub(r"/\*.*?\*/|//[^\n]*", "", contents, flags=re.DOTALL)
    return bool(re.search(r"[A-Za-z_]", without_comments))


def _valid_text_encoding(text: str) -> bool:
    try:
        encoded = text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return b"\x00" not in encoded


def _lexically_balanced(source: str) -> bool:
    """Cheap lexical gate; the strict compiler provides the authoritative syntax check."""

    without_literals = re.sub(
        r'R"[^()\\\s]{0,16}\(.*?\)[^()\\\s]{0,16}"|"(?:\\.|[^"\\])*"|'
        r"'(?:\\.|[^'\\])*'|/\*.*?\*/|//[^\n]*",
        "",
        source,
        flags=re.DOTALL,
    )
    pairs = {"(": ")", "[": "]", "{": "}"}
    stack: list[str] = []
    for character in without_literals:
        if character in pairs:
            stack.append(pairs[character])
        elif character in pairs.values():
            if not stack or stack.pop() != character:
                return False
    return not stack


def _preprocessor_lexically_valid(source: str) -> bool:
    directives = [line for line in source.splitlines() if line.lstrip().startswith("#")]
    return all(VALID_PREPROCESSOR_RE.match(line) is not None for line in directives) and not (
        source.rstrip().endswith("\\")
    )


def _definition_names(files: Mapping[str, str]) -> list[str]:
    names: list[str] = []
    for contents in files.values():
        contents = re.sub(r"/\*.*?\*/|//[^\n]*", "", contents, flags=re.DOTALL)
        for match in CPP_DEFINITION_RE.finditer(contents):
            declaration_name = match.group(1)
            function_name = match.group(2)
            if declaration_name and declaration_name not in CPP_KEYWORDS:
                names.append(f"declaration:{declaration_name}")
            elif function_name and function_name not in CPP_KEYWORDS:
                signature = re.sub(r"\s+", " ", match.group(0).rsplit("{", 1)[0]).strip()
                names.append(f"function:{signature}")
    return names


def _required_api(exercise_dir: Path, editable_files: list[str]) -> tuple[set[str], set[str]]:
    symbols: set[str] = set()
    namespaces: set[str] = set()
    for name in editable_files:
        path = exercise_dir / name
        if not path.is_file() or path.suffix not in {".h", ".hpp"}:
            continue
        source = path.read_text(encoding="utf-8")
        for match in CPP_API_RE.finditer(source):
            symbol = match.group(1) or match.group(2)
            if not symbol or symbol in CPP_KEYWORDS:
                continue
            if source[match.start() :].lstrip().startswith("namespace"):
                namespaces.add(symbol)
            else:
                symbols.add(symbol)
    return symbols, namespaces


def _symbols_preserved(candidate: str, symbols: set[str]) -> bool:
    return all(re.search(rf"\b{re.escape(symbol)}\b", candidate) for symbol in symbols)
