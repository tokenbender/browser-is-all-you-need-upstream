

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable


FENCE_RE = re.compile(
    r"^```(?P<language>[^\n]*)\n(?P<code>.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL
)
TERMINAL_STOP_RE = re.compile(
    r"(?:[ \t\r\n]*(?:<\|endoftext\|>|<\|user\|>|<\|observation\|>))+$"
)
LABEL_PREFIX_RE = re.compile(r"^(?:#{1,6}\s+|[-+*]\s+)")
MARKDOWN_WRAPPERS = ("**", "__", "``", "`", "*", "_")
PROTECTED_NAMES = {"CMakeLists.txt"}
PROTECTED_SUFFIXES = ("_test.cpp", "_test.cc", "_test.h", ".cmake")
MAX_RESPONSE_BYTES = 1024 * 1024
THINKING_END = "</think>"


class AiderResponseError(ValueError):


    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class ParsedAiderResponse:
    files: dict[str, str]
    format_valid: bool


def parse_whole_file_response(
    response: str,
    editable_files: Iterable[str],
    *,
    recover_boundary_errors: bool = False,
) -> ParsedAiderResponse:








    if len(response.encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise AiderResponseError("response_too_large", "response exceeds the safe byte limit")





    if THINKING_END in response:
        response = response.rsplit(THINKING_END, 1)[1].lstrip()






    response = TERMINAL_STOP_RE.sub("", response)

    allowed = set(editable_files)
    parsed: dict[str, str] = {}
    format_valid = True
    fence_count = 0
    first_boundary_error: AiderResponseError | None = None

    for match in FENCE_RE.finditer(response):
        fence_count += 1
        label_line = _preceding_line(response, match.start())
        normalized, exact = _normalize_label(label_line)
        language = match.group("language").strip().lower()

        if normalized in allowed:
            target = normalized
        elif normalized and PurePath(normalized).name in allowed:
            target, exact = PurePath(normalized).name, False
        elif _looks_like_file_target(normalized):
            error = AiderResponseError(
                "forbidden_file", f"response targets non-editable file: {normalized}"
            )
            if not recover_boundary_errors:
                raise error
            first_boundary_error = first_boundary_error or error
            format_valid = False
            continue
        else:
            format_valid = False
            continue

        if target in parsed:
            error = AiderResponseError(
                "duplicate_file", f"response contains duplicate file: {target}"
            )
            if not recover_boundary_errors:
                raise error
            first_boundary_error = first_boundary_error or error
            format_valid = False
        if language not in {"", "cpp", "c++", "cc", "hpp", "h"}:
            format_valid = False
        if not exact:
            format_valid = False
        parsed[target] = match.group("code").rstrip() + "\n"

    if not parsed and first_boundary_error is not None:
        raise first_boundary_error
    if fence_count == 0 or not parsed:
        raise AiderResponseError("invalid_format", "response contains no complete editable files")
    return ParsedAiderResponse(files=parsed, format_valid=format_valid)


def _preceding_line(text: str, offset: int) -> str:
    prefix = text[:offset].rstrip("\r\n")
    if not prefix:
        return ""
    return prefix.splitlines()[-1].strip()


def _normalize_label(label_line: str) -> tuple[str, bool]:
    exact = label_line.strip()
    normalized = LABEL_PREFIX_RE.sub("", exact, count=1).strip()
    if normalized.endswith(":"):
        normalized = normalized[:-1].rstrip()
    for wrapper in MARKDOWN_WRAPPERS:
        if (
            normalized.startswith(wrapper)
            and normalized.endswith(wrapper)
            and len(normalized) > 2 * len(wrapper)
        ):
            normalized = normalized[len(wrapper):-len(wrapper)].strip()
            if normalized.endswith(":"):
                normalized = normalized[:-1].rstrip()
            break
    return normalized, normalized == exact


def _looks_like_file_target(label: str) -> bool:
    if not label or " " in label:
        return False
    path = PurePath(label)
    if path.is_absolute() or ".." in path.parts or len(path.parts) > 1:
        return True
    return label in PROTECTED_NAMES or label.endswith(PROTECTED_SUFFIXES) or "." in label
