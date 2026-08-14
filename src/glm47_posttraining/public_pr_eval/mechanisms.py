"""Structure-aware mechanism checks for the fmt chrono public-PR diagnostic.

These checks deliberately do not decide whether a candidate is correct.  They
establish declaration scope and call-site shape after C++ tokenization.  The
runner combines them with compiler and focused executable evidence before a
mechanism can be reported as verified.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


FMT_MECHANISM_IDS = (
    "fmt-duration-cast-helper",
    "same-arithmetic-dispatch",
    "safe-cast-placement",
    "to-time-t-helper",
    "templated-gmtime",
    "localtime-to-time-t",
    "fractional-seconds-casts",
    "remove-old-safe-helper",
    "milliseconds-casts",
    "chrono-formatter-cast",
    "time-point-root-fix",
    "local-time-root-fix",
)


_TOKEN_RE = re.compile(
    r"""
    //[^\n]*
    |/\*.*?\*/
    |R\"[^\s(\\]{0,16}\(.*?\)[^\s\"\\]{0,16}\"
    |\"(?:\\.|[^\"\\])*\"
    |'(?:\\.|[^'\\])*'
    |[A-Za-z_]\w*
    |::|->|&&|\|\||==|!=|<=|>=|<<|>>
    |[^\s]
    """,
    re.DOTALL | re.VERBOSE,
)


@dataclass(frozen=True)
class _Token:
    value: str
    start: int
    end: int


def _tokens(source: str) -> list[_Token]:
    result: list[_Token] = []
    for match in _TOKEN_RE.finditer(source):
        value = match.group(0)
        if value.startswith("//") or value.startswith("/*"):
            continue
        result.append(_Token(value, match.start(), match.end()))
    return result


def _values(tokens: list[_Token]) -> list[str]:
    return [token.value for token in tokens]


def _find_sequence(values: list[str], sequence: tuple[str, ...]) -> list[int]:
    width = len(sequence)
    return [
        index
        for index in range(0, len(values) - width + 1)
        if tuple(values[index : index + width]) == sequence
    ]


def _matching_brace(values: list[str], opening: int) -> int | None:
    depth = 0
    for index in range(opening, len(values)):
        if values[index] == "{":
            depth += 1
        elif values[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


def _spans_for_namespace(values: list[str], name: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for start in _find_sequence(values, ("namespace", name, "{")):
        end = _matching_brace(values, start + 2)
        if end is not None:
            spans.append((start, end))
    return spans


def _inside(index: int, spans: list[tuple[int, int]]) -> bool:
    return any(start < index < end for start, end in spans)


def _definition_span(
    values: list[str], anchor: tuple[str, ...], *, occurrence: int = 0
) -> tuple[int, int] | None:
    starts = _find_sequence(values, anchor)
    if occurrence >= len(starts):
        return None
    start = starts[occurrence]
    if anchor[-1] == "{":
        opening = start + len(anchor) - 1
    else:
        try:
            opening = values.index("{", start + len(anchor))
        except ValueError:
            return None
    end = _matching_brace(values, opening)
    return (start, end) if end is not None else None


def _contains(values: list[str], sequence: tuple[str, ...]) -> bool:
    return bool(_find_sequence(values, sequence))


def _slice(values: list[str], span: tuple[int, int] | None) -> list[str]:
    return [] if span is None else values[span[0] : span[1] + 1]


def _balanced_preprocessor(source: str) -> bool:
    stack: list[str] = []
    for raw in source.splitlines():
        match = re.match(r"\s*#\s*(if|ifdef|ifndef|elif|else|endif)\b", raw)
        if match is None:
            continue
        directive = match.group(1)
        if directive in {"if", "ifdef", "ifndef"}:
            stack.append(directive)
        elif directive in {"elif", "else"}:
            if not stack:
                return False
        elif not stack:
            return False
        else:
            stack.pop()
    return not stack


def _result(
    verifier_id: str, passed: bool, evidence: list[str], failures: list[str]
) -> dict[str, Any]:
    return {
        "verifier_id": verifier_id,
        "status": "valid" if passed else "invalid",
        "evidence": evidence,
        "failures": failures,
    }


def evaluate_fmt_structure(path: Path) -> list[dict[str, Any]]:
    """Return twelve token/scope checks for ``include/fmt/chrono.h``."""

    source = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    tokens = _tokens(source)
    values = _values(tokens)
    detail_spans = _spans_for_namespace(values, "detail")
    safe_spans = _spans_for_namespace(values, "safe_duration_cast")
    preprocessor_ok = _balanced_preprocessor(source)

    trait_positions = _find_sequence(
        values, ("struct", "is_same_arithmetic_type")
    )
    cast_definitions = _find_sequence(values, ("To", "fmt_duration_cast", "("))
    cast_in_detail = [position for position in cast_definitions if _inside(position, detail_spans)]
    safe_end = max((end for _, end in safe_spans), default=-1)
    first_cast = min(cast_in_detail, default=-1)

    to_time_positions = _find_sequence(
        values, ("std", "::", "time_t", "to_time_t", "(")
    )
    to_time_in_detail = [
        position for position in to_time_positions if _inside(position, detail_spans)
    ]
    to_time_span = _definition_span(
        values,
        (
            "template",
            "<",
            "typename",
            "Duration",
            ">",
            "std",
            "::",
            "time_t",
            "to_time_t",
            "(",
        ),
    )
    gmtime_span = _definition_span(
        values,
        (
            "template",
            "<",
            "typename",
            "Duration",
            ">",
            "inline",
            "std",
            "::",
            "tm",
            "gmtime",
            "(",
        ),
    )
    localtime_span = _definition_span(
        values,
        (
            "template",
            "<",
            "typename",
            "Duration",
            ">",
            "inline",
            "auto",
            "localtime",
            "(",
        ),
    )
    fractional_span = _definition_span(
        values, ("void", "write_fractional_seconds", "(")
    )
    milliseconds_span = _definition_span(
        values,
        (
            "inline",
            "std",
            "::",
            "chrono",
            "::",
            "duration",
            "<",
            "Rep",
            ",",
            "std",
            "::",
            "milli",
            ">",
            "get_milliseconds",
            "(",
        ),
    )
    chrono_formatter_span = _definition_span(values, ("struct", "chrono_formatter", "{"))
    system_formatter_span = _definition_span(
        values,
        (
            "struct",
            "formatter",
            "<",
            "std",
            "::",
            "chrono",
            "::",
            "time_point",
            "<",
            "std",
            "::",
            "chrono",
            "::",
            "system_clock",
        ),
    )
    local_formatter_span = _definition_span(
        values,
        (
            "struct",
            "formatter",
            "<",
            "std",
            "::",
            "chrono",
            "::",
            "local_time",
        ),
    )

    trait_values = _slice(
        values,
        (
            trait_positions[0],
            _matching_brace(values, values.index("{", trait_positions[0])),
        )
        if trait_positions
        else None,
    )
    to_time_values = _slice(values, to_time_span)
    gmtime_values = _slice(values, gmtime_span)
    localtime_values = _slice(values, localtime_span)
    fractional_values = _slice(values, fractional_span)
    milliseconds_values = _slice(values, milliseconds_span)
    chrono_formatter_values = _slice(values, chrono_formatter_span)
    system_formatter_values = _slice(values, system_formatter_span)
    local_formatter_values = _slice(values, local_formatter_span)

    checks: dict[str, tuple[bool, list[str], list[str]]] = {}
    checks["fmt-duration-cast-helper"] = (
        len(cast_in_detail) == 2
        and _contains(values, ("safe_duration_cast", "::", "safe_duration_cast", "<", "To", ">"))
        and _contains(values, ("FMT_THROW", "(", "format_error", "(", '"cannot format duration"')),
        ["two fmt_duration_cast definitions resolve inside namespace detail"],
        ["missing two scoped overload definitions or checked-error path"],
    )
    checks["same-arithmetic-dispatch"] = (
        bool(trait_positions)
        and _inside(trait_positions[0], detail_spans)
        and _contains(
            trait_values,
            ("std", "::", "is_integral", "<", "Rep1", ">", "::", "value"),
        )
        and _contains(
            trait_values,
            ("std", "::", "is_integral", "<", "Rep2", ">", "::", "value"),
        )
        and _contains(
            trait_values,
            (
                "std",
                "::",
                "is_floating_point",
                "<",
                "Rep1",
                ">",
                "::",
                "value",
            ),
        )
        and _contains(
            trait_values,
            (
                "std",
                "::",
                "is_floating_point",
                "<",
                "Rep2",
                ">",
                "::",
                "value",
            ),
        ),
        ["arithmetic-category trait is scoped inside namespace detail"],
        ["trait scope or integral/floating category predicate is incomplete"],
    )
    checks["safe-cast-placement"] = (
        preprocessor_ok
        and len(cast_in_detail) == 2
        and safe_end >= 0
        and first_cast > safe_end,
        ["preprocessor is balanced and helper follows safe_duration_cast definition"],
        ["unbalanced directives or helper appears before its dependency/outside detail"],
    )
    checks["to-time-t-helper"] = (
        len(to_time_in_detail) == 1
        and bool(to_time_values)
        and _contains(
            to_time_values, ("time_point", ".", "time_since_epoch", "(", ")")
        )
        and _contains(
            to_time_values,
            (
                "fmt_duration_cast",
                "<",
                "std",
                "::",
                "chrono",
                "::",
                "duration",
                "<",
                "std",
                "::",
                "time_t",
                ">>",
            ),
        ),
        ["one to_time_t template resolves inside namespace detail"],
        ["to_time_t scope or direct epoch-duration conversion is missing"],
    )
    checks["templated-gmtime"] = (
        bool(gmtime_values)
        and _contains(gmtime_values, ("time_point", "<", "std", "::", "chrono", "::", "system_clock", ",", "Duration", ">"))
        and _contains(gmtime_values, ("detail", "::", "to_time_t", "(", "time_point", ")")),
        ["gmtime is templated on Duration and delegates directly to detail::to_time_t"],
        ["generic system-clock gmtime overload is missing or narrows indirectly"],
    )
    checks["localtime-to-time-t"] = (
        bool(localtime_values)
        and _contains(localtime_values, ("detail", "::", "to_time_t", "(", "std", "::", "chrono", "::", "current_zone", "(", ")", "->", "to_sys", "(", "time", ")", ")"))
        and not _contains(localtime_values, ("system_clock", "::", "to_time_t")),
        ["feature-gated localtime overload delegates through detail::to_time_t"],
        ["localtime overload is missing or retains native system-clock narrowing"],
    )
    checks["fractional-seconds-casts"] = (
        _contains(fractional_values, ("d", "-", "fmt_duration_cast", "<", "std", "::", "chrono", "::", "seconds", ">", "(", "d", ")"))
        and _contains(fractional_values, ("fmt_duration_cast", "<", "subsecond_precision", ">", "(", "fractional", ")", ".", "count", "(", ")")),
        ["write_fractional_seconds routes whole and fractional conversions through the helper"],
        ["one or both scoped fractional conversion sites are missing"],
    )
    checks["remove-old-safe-helper"] = (
        "fmt_safe_duration_cast" not in values,
        ["legacy fmt_safe_duration_cast identifier is absent from tokenized source"],
        ["legacy fmt_safe_duration_cast identifier remains after tokenization"],
    )
    checks["milliseconds-casts"] = (
        _contains(milliseconds_values, ("fmt_duration_cast", "<", "CommonSecondsType", ">"))
        and _contains(milliseconds_values, ("fmt_duration_cast", "<", "std", "::", "chrono", "::", "seconds", ">"))
        and _contains(milliseconds_values, ("fmt_duration_cast", "<", "std", "::", "chrono", "::", "milliseconds", ">")),
        ["get_milliseconds routes safe and fallback remainder paths through fmt_duration_cast"],
        ["get_milliseconds does not contain all required helper-routed conversions"],
    )
    checks["chrono-formatter-cast"] = (
        _contains(chrono_formatter_values, ("s", "=", "fmt_duration_cast", "<", "seconds", ">"))
        and "fmt_safe_duration_cast" not in chrono_formatter_values,
        ["chrono_formatter seconds state uses the unified helper"],
        ["chrono_formatter retains a legacy/raw split conversion"],
    )
    checks["time-point-root-fix"] = (
        system_formatter_values.count("gmtime") >= 2
        and _contains(system_formatter_values, ("gmtime", "(", "val", ")"))
        and not _contains(system_formatter_values, ("time_point_cast", "<", "std", "::", "chrono", "::", "seconds", ">")),
        ["system-clock formatter calls gmtime(val) without calendar-path time_point_cast"],
        ["system-clock formatter root path is missing or still narrows before gmtime"],
    )
    checks["local-time-root-fix"] = (
        local_formatter_values.count("localtime") >= 2
        and _contains(local_formatter_values, ("localtime", "(", "val", ")"))
        and not _contains(local_formatter_values, ("time_point_cast", "<", "std", "::", "chrono", "::", "seconds", ">")),
        ["local-time formatter calls localtime(val) without calendar-path time_point_cast"],
        ["local-time formatter root path is missing or still narrows before localtime"],
    )

    return [
        _result(verifier_id, *checks[verifier_id]) for verifier_id in FMT_MECHANISM_IDS
    ]


STRUCTURE_VERIFIERS: dict[str, Callable[[Path], list[dict[str, Any]]]] = {
    "fmt-chrono-structure-v1": evaluate_fmt_structure,
}


def run_structure_verifier(verifier_id: str, path: Path) -> list[dict[str, Any]]:
    try:
        verifier = STRUCTURE_VERIFIERS[verifier_id]
    except KeyError as exc:
        raise ValueError(f"unknown structure verifier: {verifier_id}") from exc
    return verifier(path)
