"""Safely overlay an Aider whole-file response on an immutable starter tree."""

from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Iterable

FENCE = re.compile(
    r"^```(?P<language>[^\n]*)\n(?P<code>.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL
)
TERMINAL_STOP = re.compile(
    r"(?:[ \t\r\n]*(?:<\|endoftext\|>|<\|user\|>|<\|observation\|>))+$"
)
RECOVERABLE_LABEL = re.compile(
    r"^(?:#{1,6}\s+|[-*]\s+)?`{0,2}(?P<label>[^`]+?)`{0,2}:?$"
)
PROTECTED_NAMES = {"CMakeLists.txt"}
PROTECTED_SUFFIXES = ("_test.cpp", "_test.cc", "_test.h", ".cmake")
MAX_RESPONSE_BYTES = 1024 * 1024
THINKING_END = "</think>"


@dataclass(frozen=True)
class Reconstruction:
    root: Path
    returned_files: list[str]
    inherited_files: list[str]
    candidate_sha256: str
    format_valid: bool


class ReconstructionError(ValueError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def _safe(relative: str) -> bool:
    path = PurePath(relative)
    return (
        bool(relative)
        and not path.is_absolute()
        and ".." not in path.parts
        and "." not in path.parts
        and str(path) == relative
    )


def _regular_files(root: Path) -> set[str]:
    files: set[str] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ReconstructionError("UNSAFE_CANDIDATE", str(path.relative_to(root)))
        if path.is_file():
            files.add(path.relative_to(root).as_posix())
    return files


def tree_sha256(root: Path, files: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for name in sorted(files):
        data = (root / name).read_bytes()
        digest.update(name.encode() + b"\0" + data + b"\0")
    return digest.hexdigest()


def _preceding_line(text: str, offset: int) -> str:
    prefix = text[:offset].rstrip("\r\n")
    return prefix.splitlines()[-1].strip() if prefix else ""


def _normalize_label(label_line: str) -> tuple[str, bool]:
    exact = label_line.strip()
    match = RECOVERABLE_LABEL.fullmatch(exact)
    normalized = match.group("label").strip() if match else exact
    return normalized, normalized == exact


def _looks_like_file_target(label: str) -> bool:
    if not label or " " in label:
        return False
    path = PurePath(label)
    return (
        path.is_absolute()
        or ".." in path.parts
        or len(path.parts) > 1
        or label in PROTECTED_NAMES
        or label.endswith(PROTECTED_SUFFIXES)
        or "." in label
    )


def reconstruct(
    starter: Path, output: Path, editable_files: list[str], *, response: str | None = None,
    supplied_dir: Path | None = None, finish_reason: str | None = None,
) -> Reconstruction:
    if response is not None and supplied_dir is not None:
        raise ReconstructionError("INVALID_INPUT", "choose response or supplied_dir")
    allowed = set(editable_files)
    if not allowed or any(not _safe(name) for name in allowed):
        raise ReconstructionError("INVALID_MANIFEST", "unsafe editable-file contract")
    shutil.copytree(starter, output, symlinks=False)
    returned: dict[str, bytes] = {}
    format_valid = True
    if response is not None:
        if len(response.encode("utf-8")) > MAX_RESPONSE_BYTES:
            raise ReconstructionError("RESPONSE_TOO_LARGE", "response exceeds safe byte limit")
        if THINKING_END in response:
            response = response.rsplit(THINKING_END, 1)[1].lstrip()
        response = TERMINAL_STOP.sub("", response)
        fence_count = 0
        for match in FENCE.finditer(response):
            fence_count += 1
            label, exact = _normalize_label(_preceding_line(response, match.start()))
            name = PurePath(label).as_posix()
            if name in allowed and _safe(name):
                target = name
            elif _safe(name) and PurePath(name).name in allowed:
                target = PurePath(name).name
                exact = False
            elif _looks_like_file_target(name):
                raise ReconstructionError("UNAUTHORIZED_FILE", label)
            else:
                format_valid = False
                continue
            if target in returned:
                raise ReconstructionError("DUPLICATE_FILE", target)
            language = match.group("language").strip().lower()
            if language not in {"", "cpp", "c++", "cc", "hpp", "h"} or not exact:
                format_valid = False
            returned[target] = (match.group("code").rstrip() + "\n").encode()
        if not returned:
            reason = "TRUNCATED" if finish_reason == "length" else "INVALID_FORMAT"
            raise ReconstructionError(reason, "no complete editable file was returned")
        if response.count("```") % 2:
            reason = "TRUNCATED" if finish_reason == "length" else "INCOMPLETE_FENCE"
            raise ReconstructionError(reason, "response contains an incomplete code fence")
        if fence_count == 0:
            raise ReconstructionError("INVALID_FORMAT", "response contains no complete code fence")
    elif supplied_dir is not None:
        supplied = _regular_files(supplied_dir)
        unauthorized = sorted(supplied - allowed)
        if unauthorized:
            raise ReconstructionError("UNAUTHORIZED_FILE", unauthorized[0])
        for name in allowed:
            source = supplied_dir / name
            if source.is_file() and not source.is_symlink():
                returned[name] = source.read_bytes()
    else:
        raise ReconstructionError("INVALID_INPUT", "candidate input is absent")
    for name, data in returned.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    inherited = sorted(allowed - set(returned))
    return Reconstruction(
        output, sorted(returned), inherited, tree_sha256(output, allowed), format_valid
    )
