"""Safe parser for Aider's whole-file response format."""

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
RECOVERABLE_LABEL_RE = re.compile(r"^(?:#{1,6}\s+|[-*]\s+)?`{0,2}(?P<label>[^`]+?)`{0,2}:?$")
PROTECTED_NAMES = {"CMakeLists.txt"}
PROTECTED_SUFFIXES = ("_test.cpp", "_test.cc", "_test.h", ".cmake")
MAX_RESPONSE_BYTES = 1024 * 1024
THINKING_END_MARKER = "</think>"


class AiderResponseError(ValueError):
    """The response cannot be safely applied to the exercise."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class Glm47ResponseSegments:
    """Consumer-visible response segments for GLM thinking-mode output."""

    final_answer: str
    thinking_boundary_applied: bool


def _validate_response_text(response: str) -> None:
    try:
        response_bytes = response.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise AiderResponseError(
            "invalid_encoding", "response is not valid UTF-8 text"
        ) from exc
    if len(response_bytes) > MAX_RESPONSE_BYTES:
        raise AiderResponseError("response_too_large", "response exceeds the safe byte limit")


def segment_glm47_response(response: str) -> Glm47ResponseSegments:
    """Expose only the final answer after GLM's thinking terminator.

    The complete raw response is validated before segmentation so a malformed
    or oversized thinking prefix cannot bypass the response contract. Without
    a terminator, the full response remains visible for non-thinking output.
    """

    _validate_response_text(response)
    _thinking, marker, final_answer = response.partition(THINKING_END_MARKER)
    if not marker:
        return Glm47ResponseSegments(
            final_answer=response,
            thinking_boundary_applied=False,
        )
    return Glm47ResponseSegments(
        final_answer=final_answer,
        thinking_boundary_applied=True,
    )


@dataclass(frozen=True)
class ParsedAiderResponse:
    files: dict[str, str]
    format_valid: bool


def parse_whole_file_response(response: str, editable_files: Iterable[str]) -> ParsedAiderResponse:
    """Extract complete files while rejecting any non-editable target.

    Mirrors Aider's whole-file coder: fences without a usable filename label are
    normally skipped (recoverable format penalty), and a path-prefixed label whose
    basename is editable maps to that basename. A single otherwise-unlabelled code
    fence is recoverable only when its target is unambiguous: either there is one
    editable file, or there is one editable source file and its code includes an
    exact declared editable header. Space-free file-like labels outside the
    editable set stay fatal — that is the tamper boundary.
    """

    _validate_response_text(response)

    # GLM-4.7's pinned generation config treats these chat-control tokens as
    # terminal EOS ids. Miles deliberately retains the stop token in decoded
    # rollout text, so it can be glued directly to Aider's closing fence (for
    # example, ```<|user|>). Remove terminal EOS markers before parsing; an
    # identical string inside file contents is left untouched.
    response = TERMINAL_STOP_RE.sub("", response)

    allowed = set(editable_files)
    parsed: dict[str, str] = {}
    format_valid = True
    fence_count = 0
    unlabelled_fences: list[re.Match[str]] = []

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
            raise AiderResponseError(
                "forbidden_file", f"response targets non-editable file: {normalized}"
            )
        else:
            format_valid = False
            if not normalized and language in {"", "cpp", "c++", "cc", "hpp", "h"}:
                unlabelled_fences.append(match)
            continue

        if target in parsed:
            raise AiderResponseError(
                "duplicate_file", f"response contains duplicate file: {target}"
            )
        if language not in {"", "cpp", "c++", "cc", "hpp", "h"}:
            format_valid = False
        if not exact:
            format_valid = False
        parsed[target] = match.group("code").rstrip() + "\n"

    if not parsed and fence_count == 1 and len(unlabelled_fences) == 1:
        code = unlabelled_fences[0].group("code")
        target = _infer_unlabelled_target(code, allowed)
        if target is not None:
            parsed[target] = code.rstrip() + "\n"
            format_valid = False

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
    match = RECOVERABLE_LABEL_RE.fullmatch(exact)
    normalized = match.group("label").strip() if match else exact
    return normalized, normalized == exact


def _looks_like_file_target(label: str) -> bool:
    if not label or " " in label:
        return False
    path = PurePath(label)
    if path.is_absolute() or ".." in path.parts or len(path.parts) > 1:
        return True
    return label in PROTECTED_NAMES or label.endswith(PROTECTED_SUFFIXES) or "." in label


def _infer_unlabelled_target(code: str, allowed: set[str]) -> str | None:
    if len(allowed) == 1:
        return next(iter(allowed))

    source_files = sorted(
        name for name in allowed if PurePath(name).suffix.lower() in {".cpp", ".cc", ".cxx"}
    )
    header_files = sorted(
        name for name in allowed if PurePath(name).suffix.lower() in {".h", ".hh", ".hpp", ".hxx"}
    )
    if len(source_files) != 1 or not header_files:
        return None
    for header in header_files:
        include = re.compile(
            rf'^\s*#\s*include\s*["<]{re.escape(header)}[">]\s*$', re.MULTILINE
        )
        if include.search(code):
            return source_files[0]
    return None
