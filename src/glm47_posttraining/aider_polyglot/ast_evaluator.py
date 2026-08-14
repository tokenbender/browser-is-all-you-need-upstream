"""C++17 AST quality evaluator for Aider Polyglot reward shaping.

The evaluator is intentionally small and deterministic.  It uses libclang for
AST traversal when available and keeps narrow text checks for properties that
are easier to express directly, such as sanitizer output and obvious raw
allocation primitives.
"""

from __future__ import annotations

import math
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Mapping


AST17_CHECK_WEIGHTS: dict[str, float] = {
    "raii": 0.30,
    "encapsulation": 0.25,
    "const_correctness": 0.20,
    "density": 0.15,
    "sanitizer": 0.10,
}
_CHECK_DENOMINATOR = sum(abs(value) for value in AST17_CHECK_WEIGHTS.values())
_LIBCLANG_RESOURCE_DIR_ENV = "GLM47_LIBCLANG_RESOURCE_DIR"

_RAW_NEW_RE = re.compile(r"\bnew\s+(?!\()")
_RAW_DELETE_RE = re.compile(r"\bdelete(?:\s*\[\s*\])?\s+")
_SMART_PTR_RE = re.compile(r"\bstd::(?:unique_ptr|shared_ptr|weak_ptr|make_unique|make_shared)\b")
_MUTABLE_GLOBAL_STATIC_RE = re.compile(
    r"(?m)^\s*(?:static\s+)?(?!const\b)(?:[A-Za-z_][\w:<>,\s*&]+\s+)"
    r"[A-Za-z_]\w*\s*(?:=|\{)"
)
_LARGE_BY_VALUE_RE = re.compile(
    r"\b(?:std::(?:string|vector|map|unordered_map|set|unordered_set|deque|list)|"
    r"[A-Z][A-Za-z_0-9]*(?:<[^;{}()]*>)?)\s+[A-Za-z_]\w*\s*(?:,|\))"
)
_CONST_REF_RE = re.compile(
    r"\b(?:const\s+[A-Za-z_:][\w:<>,\s]*\s*&|[A-Za-z_:][\w:<>,\s]*\s+const\s*&|"
    r"std::string_view)\b"
)
_CONST_MEMBER_RE = re.compile(r"\)\s*const\s*(?:noexcept\s*)?(?:override\s*)?(?:\{|;)")
_SANITIZER_ERROR_RE = re.compile(
    r"(addresssanitizer|undefinedbehaviorsanitizer|leaksanitizer|"
    r"runtime error:|heap-buffer-overflow|stack-buffer-overflow|use-after-free)",
    re.IGNORECASE,
)
_EMPTY_STATEMENT_RE = re.compile(r"(?m)^\s*;\s*$")


@dataclass(frozen=True)
class AST17Evaluation:
    """Detailed result for the five-check C++17 AST rubric."""

    score: float
    checks: dict[str, float]
    node_count: int
    line_count: int
    diagnostics: tuple[str, ...] = ()
    clang_available: bool = False
    sanitizer_signal_detected: bool = False


def validate_libclang_runtime(
    *, raise_on_error: bool = True, require_clang18: bool = False
) -> bool:
    """Verify that Python clang bindings and libclang can parse C++17."""

    try:
        from clang import cindex  # type: ignore

        _configure_libclang(cindex)
        index = cindex.Index.create()
        with TemporaryDirectory(prefix="glm47-libclang-preflight-") as temp_value:
            source = Path(temp_value) / "probe.cpp"
            source.write_text(
                "#include <memory>\nint answer(){auto p=std::make_unique<int>(1);return *p;}\n",
                encoding="utf-8",
            )
            unit = index.parse(
                str(source),
                args=["-std=c++17", "-xc++", *_libclang_resource_args()],
                options=cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD,
            )
            fatal = [
                str(diagnostic)
                for diagnostic in unit.diagnostics
                if diagnostic.severity >= cindex.Diagnostic.Error
            ]
            if fatal:
                raise RuntimeError("; ".join(fatal))
        if require_clang18 and not _clang18_binary_available():
            raise RuntimeError("clang-18 binary is required but was not found")
        return True
    except Exception as exc:
        if raise_on_error:
            raise RuntimeError(f"libclang C++17 runtime check failed: {exc}") from exc
        return False


def compute_ast17_score(
    source: str | Mapping[str, str],
    *,
    sanitizer_report: str | None = None,
    support_files: Mapping[str, str] | None = None,
    return_details: bool = True,
) -> AST17Evaluation | float:
    """Return S_AST17 in [-1.0, +1.0] for the five C++17 quality checks."""

    candidate_files = _normalize_source_files(source)
    support = dict(support_files or {})
    combined = "\n".join(candidate_files.values())
    line_count = _active_line_count(combined)
    diagnostics: tuple[str, ...] = ()
    node_count = 0
    clang_available = False

    try:
        node_count, diagnostics = _parse_node_count(candidate_files, support)
        clang_available = True
    except Exception as exc:
        diagnostics = (f"clang_parse_unavailable: {type(exc).__name__}: {exc}",)
        node_count = _fallback_node_count(combined)

    checks = {
        "raii": _check_raii(combined),
        "encapsulation": _check_encapsulation(combined),
        "const_correctness": _check_const_correctness(combined),
        "density": _check_density(combined, node_count=node_count, line_count=line_count),
        "sanitizer": _check_sanitizer(sanitizer_report),
    }
    score = sum(AST17_CHECK_WEIGHTS[name] * checks[name] for name in AST17_CHECK_WEIGHTS)
    score = max(-1.0, min(1.0, score / _CHECK_DENOMINATOR))
    result = AST17Evaluation(
        score=score,
        checks=checks,
        node_count=node_count,
        line_count=line_count,
        diagnostics=diagnostics,
        clang_available=clang_available,
        sanitizer_signal_detected=checks["sanitizer"] < 0.0,
    )
    return result if return_details else result.score


def _configure_libclang(cindex) -> None:
    configured = os.environ.get("LIBCLANG_PATH")
    if configured:
        path = Path(configured)
        if path.is_file():
            cindex.Config.set_library_file(str(path))
        elif path.is_dir():
            cindex.Config.set_library_path(str(path))


def _libclang_resource_args() -> list[str]:
    """Return a validated Clang resource directory without poisoning CUDA JIT."""

    configured = os.environ.get(_LIBCLANG_RESOURCE_DIR_ENV, "").strip()
    if not configured:
        return []
    resource_dir = Path(configured)
    if not resource_dir.is_absolute():
        raise RuntimeError(f"{_LIBCLANG_RESOURCE_DIR_ENV} must be an absolute path")
    if not resource_dir.is_dir():
        raise RuntimeError(
            f"{_LIBCLANG_RESOURCE_DIR_ENV} is not a directory: {resource_dir}"
        )
    builtin_header = resource_dir / "include" / "stddef.h"
    if not builtin_header.is_file():
        raise RuntimeError(
            f"{_LIBCLANG_RESOURCE_DIR_ENV} does not contain include/stddef.h: "
            f"{resource_dir}"
        )
    return [f"-resource-dir={resource_dir}"]


def _clang18_binary_available() -> bool:
    try:
        completed = subprocess.run(
            ["clang-18", "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0 and "clang version 18" in completed.stdout.lower()


def _normalize_source_files(source: str | Mapping[str, str]) -> dict[str, str]:
    if isinstance(source, str):
        return {"candidate.cpp": source}
    return {str(name): str(contents) for name, contents in source.items()}


def _parse_node_count(
    candidate_files: Mapping[str, str],
    support_files: Mapping[str, str],
) -> tuple[int, tuple[str, ...]]:
    from clang import cindex  # type: ignore

    _configure_libclang(cindex)
    with TemporaryDirectory(prefix="glm47-ast17-") as temp_value:
        root = Path(temp_value)
        for files in (support_files, candidate_files):
            for name, contents in files.items():
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(contents, encoding="utf-8")
        parse_target = _first_cpp_file(root, candidate_files) or next(iter(candidate_files))
        index = cindex.Index.create()
        unit = index.parse(
            str(root / parse_target),
            args=[
                "-std=c++17",
                "-I",
                str(root),
                "-xc++",
                *_libclang_resource_args(),
            ],
            options=cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD,
        )
        diagnostics = tuple(str(diagnostic) for diagnostic in unit.diagnostics)
        return sum(1 for _cursor in unit.cursor.walk_preorder()), diagnostics


def _first_cpp_file(root: Path, files: Mapping[str, str]) -> str | None:
    for name in files:
        if Path(name).suffix in {".cpp", ".cc", ".cxx"} and (root / name).exists():
            return name
    return None


def _active_line_count(source: str) -> int:
    return sum(1 for line in source.splitlines() if line.strip())


def _fallback_node_count(source: str) -> int:
    tokens = re.findall(r"[A-Za-z_]\w*|[{}();,]", source)
    return max(1, len(tokens))


def _check_raii(source: str) -> float:
    raw_new = bool(_RAW_NEW_RE.search(source))
    raw_delete = bool(_RAW_DELETE_RE.search(source))
    if raw_new or raw_delete:
        return -1.0
    return 1.0 if _SMART_PTR_RE.search(source) or "std::" in source or source.strip() else 0.0


def _check_encapsulation(source: str) -> float:
    if _MUTABLE_GLOBAL_STATIC_RE.search(_remove_class_bodies(source)):
        return -1.0
    public_field = re.search(r"public\s*:\s*(?:[^{};]+\s+)+[A-Za-z_]\w*\s*;", source)
    private_or_protected = re.search(r"\b(?:private|protected)\s*:", source)
    class_seen = re.search(r"\b(?:class|struct)\s+[A-Za-z_]\w*", source)
    if public_field:
        return -1.0
    if private_or_protected or not class_seen:
        return 1.0
    return 0.0


def _remove_class_bodies(source: str) -> str:
    return re.sub(r"\b(?:class|struct)\s+\w+[^{}]*\{.*?\};", "", source, flags=re.DOTALL)


def _check_const_correctness(source: str) -> float:
    if _LARGE_BY_VALUE_RE.search(source) and not _CONST_REF_RE.search(source):
        return -1.0
    if _CONST_REF_RE.search(source) or _CONST_MEMBER_RE.search(source):
        return 1.0
    return 0.0


def _check_density(source: str, *, node_count: int, line_count: int) -> float:
    if line_count <= 0:
        return 0.0
    empty_ratio = len(_EMPTY_STATEMENT_RE.findall(source)) / max(1, line_count)
    ratio = node_count / max(1, line_count)
    if empty_ratio > 0.20:
        return -1.0
    if 1.0 <= ratio <= 35.0:
        return 1.0
    distance = min(abs(ratio - 1.0), abs(ratio - 35.0))
    return max(-1.0, 1.0 - math.sqrt(distance) / 4.0)


def _check_sanitizer(report: str | None) -> float:
    if report and _SANITIZER_ERROR_RE.search(report):
        return -1.0
    return 1.0


__all__ = [
    "AST17_CHECK_WEIGHTS",
    "AST17Evaluation",
    "compute_ast17_score",
    "validate_libclang_runtime",
]
