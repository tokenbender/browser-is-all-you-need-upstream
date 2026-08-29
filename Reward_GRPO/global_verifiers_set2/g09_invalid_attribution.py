"""G09: attribute verifier failures without changing candidate semantics."""

from __future__ import annotations

import errno as errno_module
import re
from typing import Any, Iterable

from receipt import PolicyReceipt, policy

_LOG_LIMIT = 4096


def _walk(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _command_facts(receipt: PolicyReceipt) -> dict[str, Any]:
    for value in _walk(receipt.facts):
        if isinstance(value.get("command"), list) and "returncode" in value:
            return value
    return {}


def _errno(command: dict[str, Any], reason: str) -> dict[str, Any] | None:
    text = "\n".join(str(command.get(key) or "") for key in ("launch_error", "stderr"))
    markers = {"EACCES": errno_module.EACCES, "Permission denied": errno_module.EACCES,
               "ENOENT": errno_module.ENOENT, "No such file or directory": errno_module.ENOENT}
    for marker, number in markers.items():
        if marker in text or marker in reason:
            return {"name": errno_module.errorcode[number], "number": number}
    match = re.search(r"\[Errno\s+(\d+)\]", text)
    if match:
        number = int(match.group(1))
        return {"name": errno_module.errorcode.get(number, "UNKNOWN"), "number": number}
    return None


def _bounded_log(command: dict[str, Any]) -> dict[str, Any]:
    stderr, stdout = str(command.get("stderr") or ""), str(command.get("stdout") or "")
    combined = stderr if stderr else stdout
    return {"text": combined[-_LOG_LIMIT:], "source": "stderr" if stderr else "stdout",
            "truncated": len(combined) > _LOG_LIMIT, "limit_bytes": _LOG_LIMIT}


def verify(receipts: list[PolicyReceipt]) -> PolicyReceipt:
    """Return one attribution record without converting candidate FAIL to INVALID."""

    origin = next((item for item in receipts if item.status == "INVALID"), None)
    classification = "INVALID"
    if origin is None:
        origin = next((item for item in receipts if item.status == "FAIL"), None)
        classification = "FAIL" if origin is not None else "PASS"
    if origin is None:
        return policy("G09", "PASS", "NO_FAILURE_TO_ATTRIBUTE", classification="PASS",
                      originating_policy=None, reason_code=None,
                      infrastructure_classification="NONE", main_error_log=None,
                      command=None, returncode=None, errno=None)
    command = _command_facts(origin)
    facts = {
        "classification": classification,
        "originating_policy": origin.policy,
        "originating_status": origin.status,
        "reason_code": origin.reason,
        "infrastructure_classification": (
            "INFRASTRUCTURE_OR_CONTRACT" if classification == "INVALID" else "CANDIDATE"
        ),
        "main_error_log": _bounded_log(command),
        "command": command.get("command"),
        "returncode": command.get("returncode"),
        "errno": _errno(command, origin.reason),
        "timed_out": bool(command.get("timed_out", False)),
        "launch_error_kind": command.get("launch_error_kind"),
    }
    if classification == "INVALID":
        return policy("G09", "INVALID", origin.reason, **facts)
    return policy("G09", "PASS", "CANDIDATE_FAILURE_ATTRIBUTED", **facts)
