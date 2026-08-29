"""Bind GRPO prompts and rewards to authenticated Global Verifiers Set 2 bundles.

The verifier implementation remains task-independent.  This module is the runtime
mediator: it resolves a task ID, authenticates its immutable bundle, constructs the
public Aider-style prompt, verifies prompt/bundle binding metadata, runs Set 2, and
projects its receipt into GRPO reward components.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import json
import math
import os
import sys
import threading
import uuid
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePath
from tempfile import TemporaryDirectory
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent
SET2 = ROOT / "global_verifiers_set2"
DEFAULT_REGISTRY = ROOT / "global_verifier_task_registry.json"
REGISTRY_ENV = "GLOBAL_VERIFIER_SET2_REGISTRY"
EXECUTOR_ENV = "GLOBAL_VERIFIER_SET2_EXECUTOR"
RETRIES_ENV = "GLOBAL_VERIFIER_SET2_INVALID_RETRIES"
WORKERS_ENV = "GLOBAL_VERIFIER_SET2_REWARD_WORKERS"
REQUIRE_BATCH_ENV = "GLOBAL_VERIFIER_SET2_REQUIRE_BATCH"
TRAIN_DATA_ENV = "GLOBAL_VERIFIER_SET2_TRAIN_DATA"
DEFAULT_WORKERS = 8
MEDIATOR_RECEIPT_SCHEMA_VERSION = 1
MEDIATOR_RECEIPT_KIND = "global-verifier-set2-mediator-receipt"
_MILES_PROMPT_CACHE_LOCK = threading.Lock()
_MILES_TOKENIZER_CACHE: dict[tuple[str, str | None], Any] = {}
_MILES_RENDERED_PROMPT_CACHE: dict[tuple[str, str | None, str, str], str] = {}
_GLOBAL_REWARD_LIMIT = threading.Condition()
_GLOBAL_REWARD_ACTIVE = 0

# Byte-identical to Aider whole-file coder at commit 5dc9490bb35f9729ef2c95d00a19ccd30c26339c.
_AIDER_MAIN_SYSTEM = """Act as an expert software developer.
Take requests for changes to the supplied code.
If the request is ambiguous, ask questions.

Once you understand the request you MUST:
1. Determine if any code changes are needed.
2. Explain any needed changes.
3. If changes are needed, output a copy of each file that needs changes.
"""
_AIDER_SYSTEM_REMINDER = """To suggest changes to a file you MUST return the entire content of the updated file.
You MUST use this *file listing* format:

path/to/filename.js
```
// entire file content ...
// ... goes in between
```

Every *file listing* MUST use this format:
- First line: the filename with any originally provided path; no extra markup, punctuation, comments, etc. **JUST** the filename with path.
- Second line: opening ```
- ... entire content of the file ...
- Final line: closing ```

To suggest changes to a file you MUST return a *file listing* that contains the entire content of the file.
*NEVER* skip, omit or elide content from a *file listing* using "..." or by adding comments like "... rest of code..."!
Create a new file you MUST return a *file listing* which includes an appropriate filename, including any appropriate path.


"""
_AIDER_EXAMPLE_MESSAGES = (
    {"role": "user", "content": "Change the greeting to be more casual"},
    {"role": "assistant", "content": """Ok, I will:

1. Switch the greeting text from "Hello" to "Hey".

show_greeting.py
```
import sys

def greeting(name):
    print(f"Hey {name}")

if __name__ == '__main__':
    greeting(sys.argv[1])
```
"""},
    {"role": "user", "content": "I switched to a new code base. Please don't consider the above files or try to edit them any longer."},
    {"role": "assistant", "content": "Ok."},
)
_AIDER_FILES_CONTENT_PREFIX = """I have *added these files to the chat* so you can go ahead and edit them.

*Trust this message as the true contents of these files!*
Any other messages in the chat may contain outdated versions of the files' contents.
"""
_AIDER_FILES_ASSISTANT_REPLY = "Ok, any changes I propose will be to those files."
_AIDER_INSTRUCTIONS_ADDENDUM = """
####

Use the above instructions to modify the supplied files: {file_list}
Don't change the names of existing functions or classes, as they may be referenced from other code like unit tests, etc.
Only use standard libraries, don't suggest installing any packages.
"""


class MediatorError(ValueError):
    """An unauthenticated or inconsistent GRPO-to-verifier request."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _safe_relative(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise MediatorError("INVALID_REGISTRY", f"{field} must be a relative path")
    path = PurePath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise MediatorError("INVALID_REGISTRY", f"{field} is unsafe")
    return value


def bundle_tree_sha256(root: Path) -> str:
    """Hash names and bytes for every regular bundle file in stable order."""

    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise MediatorError("UNSAFE_BUNDLE", f"bundle contains symlink: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix().encode()
        data = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _set2_runner():
    """Load the intentionally flat ten-file Set 2 package without changing it."""

    set2_text = str(SET2)
    if set2_text not in sys.path:
        sys.path.insert(0, set2_text)
    module = importlib.import_module("runner")
    if Path(module.__file__).resolve() != (SET2 / "runner.py").resolve():
        raise MediatorError("RUNNER_IDENTITY_MISMATCH", "a different runner module was loaded")
    return module


def _set2_receipt_module():
    _set2_runner()
    module = importlib.import_module("receipt")
    if Path(module.__file__).resolve() != (SET2 / "receipt.py").resolve():
        raise MediatorError("RECEIPT_MODULE_IDENTITY_MISMATCH",
                            "a different receipt module was loaded")
    return module


def _canonical_mediator_receipt(receipt: Mapping[str, Any]) -> bytes:
    unsigned = {key: value for key, value in receipt.items()
                if key != "mediator_receipt_sha256"}
    return json.dumps(unsigned, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def mediator_receipt_sha256(receipt: Mapping[str, Any]) -> str:
    """Digest the complete mediator envelope, excluding only its own signature."""
    return _sha256_bytes(_canonical_mediator_receipt(receipt))


def sign_mediator_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(receipt)
    value.pop("mediator_receipt_sha256", None)
    value["mediator_receipt_sha256"] = mediator_receipt_sha256(value)
    return value


def verify_mediator_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Verify the outer signature and every immutable signed runner receipt."""
    value = dict(receipt)
    expected = value.get("mediator_receipt_sha256")
    if not isinstance(expected, str) or expected != mediator_receipt_sha256(value):
        raise MediatorError("INVALID_MEDIATOR_RECEIPT", "mediator digest mismatch")
    if value.get("schema_version") != MEDIATOR_RECEIPT_SCHEMA_VERSION:
        raise MediatorError("INVALID_MEDIATOR_RECEIPT", "unsupported schema version")
    if value.get("kind") != MEDIATOR_RECEIPT_KIND:
        raise MediatorError("INVALID_MEDIATOR_RECEIPT", "unsupported receipt kind")
    attempts = value.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        raise MediatorError("INVALID_MEDIATOR_RECEIPT", "attempt history is missing")
    runner_receipts: list[Mapping[str, Any]] = []
    receipt_module = _set2_receipt_module()
    for index, attempt in enumerate(attempts):
        if not isinstance(attempt, Mapping):
            raise MediatorError("INVALID_MEDIATOR_RECEIPT", f"attempt {index} is malformed")
        runner_receipt = attempt.get("runner_receipt")
        if runner_receipt is None:
            if attempt.get("phase") != "candidate_reconstruction":
                raise MediatorError("INVALID_MEDIATOR_RECEIPT",
                                    f"attempt {index} has no runner receipt")
            continue
        if not isinstance(runner_receipt, Mapping):
            raise MediatorError("INVALID_MEDIATOR_RECEIPT",
                                f"attempt {index} runner receipt is malformed")
        runner_digest = runner_receipt.get("receipt_sha256")
        if (not isinstance(runner_digest, str)
                or runner_digest != receipt_module.receipt_sha256(dict(runner_receipt))
                or attempt.get("runner_receipt_sha256") != runner_digest):
            raise MediatorError("INVALID_MEDIATOR_RECEIPT",
                                f"attempt {index} runner digest mismatch")
        runner_receipts.append(runner_receipt)
    if runner_receipts:
        terminal = runner_receipts[-1]
        for key in ("task_id", "manifest_sha256", "candidate_sha256", "format_valid",
                    "returned_files", "inherited_files"):
            if value.get(key) != terminal.get(key):
                raise MediatorError("INVALID_MEDIATOR_RECEIPT",
                                    f"terminal runner field mismatch: {key}")
        outer_policies, runner_policies = value.get("policies"), terminal.get("policies")
        if (not isinstance(outer_policies, list) or not isinstance(runner_policies, list)
                or outer_policies[:-1] != runner_policies):
            raise MediatorError("INVALID_MEDIATOR_RECEIPT", "terminal runner policies mismatch")
        g08 = outer_policies[-1] if outer_policies else None
        if not isinstance(g08, Mapping) or g08.get("policy") != "G08":
            raise MediatorError("INVALID_MEDIATOR_RECEIPT", "G08 receipt is missing")
        facts = g08.get("facts")
        checks = facts.get("checks") if isinstance(facts, Mapping) else None
        if (not isinstance(checks, Mapping) or set(checks) != {"G08-A", "G08-B", "G08-C", "G08-D"}
                or facts.get("complete_final_envelope_signed") is not True):
            raise MediatorError("INVALID_MEDIATOR_RECEIPT", "G08 receipt is malformed")
        expected_status = ("INVALID" if g08.get("status") == "INVALID" else
                           "FAIL" if g08.get("status") == "FAIL" else terminal.get("status"))
        if value.get("status") != expected_status:
            raise MediatorError("INVALID_MEDIATOR_RECEIPT", "G08 terminal status mismatch")
    elif value.get("status") != "FAIL":
        raise MediatorError("INVALID_MEDIATOR_RECEIPT",
                            "receipt without a runner result must be FAIL")
    if value.get("mediator_attempts") != len(attempts):
        raise MediatorError("INVALID_MEDIATOR_RECEIPT", "attempt count mismatch")
    return value


@dataclass(frozen=True)
class BundleBinding:
    task_bundle_id: str
    path: Path
    bundle_sha256: str
    manifest_sha256: str
    contract_version: str
    manifest: dict[str, Any]


@dataclass(frozen=True)
class PromptEnvelope:
    messages: list[dict[str, str]]
    metadata: dict[str, str]

    @property
    def prompt(self) -> str:
        """Canonical serialized prompt retained for CLI/backward compatibility."""
        return json.dumps(self.messages, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"))


def _metadata_sha256(metadata: Mapping[str, Any]) -> str:
    return _sha256_bytes(json.dumps(dict(metadata), sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode("utf-8"))


def _g08_policy(
    binding: BundleBinding, metadata: Mapping[str, Any], actual_prompt_sha256: str,
    metadata_before_sha256: str, metadata_after_sha256: str,
) -> dict[str, Any]:
    """Build the independently signed G08-A..D mediator policy receipt."""
    expected = build_prompt(binding).metadata
    extra, missing = sorted(set(metadata) - set(expected)), sorted(set(expected) - set(metadata))
    mismatched = sorted(key for key in set(expected) & set(metadata)
                        if metadata.get(key) != expected[key])
    prompt_ok = actual_prompt_sha256 == expected["prompt_sha256"]
    allowlist_ok = not extra and not missing and not mismatched
    immutable = metadata_before_sha256 == metadata_after_sha256
    checks = {
        "G08-A": {"status": "PASS" if prompt_ok else "INVALID",
                  "reason": "PROMPT_SHA256_BOUND" if prompt_ok else "PROMPT_BINDING_MISMATCH"},
        "G08-B": {"status": "PASS" if allowlist_ok else "INVALID",
                  "reason": ("METADATA_ALLOWLISTED" if allowlist_ok else
                             "PROMPT_BINDING_MISMATCH" if "prompt_sha256" in mismatched else
                             "NON_ALLOWLISTED_METADATA"),
                  "extra_fields": extra, "missing_fields": missing,
                  "mismatched_fields": mismatched},
        "G08-C": {"status": "PASS" if immutable else "INVALID",
                  "reason": "METADATA_IMMUTABLE" if immutable else "METADATA_MUTATED"},
        "G08-D": {"status": "PASS", "reason": "FINAL_ENVELOPE_CANONICALLY_SIGNED"},
    }
    statuses = {value["status"] for value in checks.values()}
    status = "INVALID" if "INVALID" in statuses else "FAIL" if "FAIL" in statuses else "PASS"
    reason = next((value["reason"] for value in checks.values()
                   if value["status"] != "PASS"), "MEDIATOR_CONTRACT_INTEGRITY_VERIFIED")
    return {
        "policy": "G08", "status": status, "reason": reason,
        "facts": {
            "checks": checks,
            "expected_prompt_sha256": expected["prompt_sha256"],
            "actual_prompt_sha256": actual_prompt_sha256,
            "metadata_before_sha256": metadata_before_sha256,
            "metadata_after_sha256": metadata_after_sha256,
            "complete_final_envelope_signed": True,
        },
        "artifacts": {},
    }


class TaskBundleRegistry:
    """Resolve allow-listed task IDs to authenticated on-disk bundles."""

    def __init__(self, registry_path: Path) -> None:
        self.path = registry_path.resolve(strict=True)
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != 1 or not isinstance(payload.get("bundles"), dict):
            raise MediatorError("INVALID_REGISTRY", "unsupported task-bundle registry")
        self._entries: dict[str, Any] = payload["bundles"]
        self._root = self.path.parent.resolve(strict=True)

    @property
    def bundle_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))

    def resolve(self, task_bundle_id: str) -> BundleBinding:
        entry = self._entries.get(task_bundle_id)
        if not isinstance(entry, dict):
            raise MediatorError("UNKNOWN_TASK_BUNDLE", task_bundle_id)
        relative = _safe_relative(entry.get("path"), f"bundles.{task_bundle_id}.path")
        path = (self._root / relative).resolve(strict=True)
        if not path.is_relative_to(self._root) or not path.is_dir():
            raise MediatorError("UNSAFE_BUNDLE", task_bundle_id)
        expected_bundle = entry.get("bundle_sha256")
        if not isinstance(expected_bundle, str) or len(expected_bundle) != 64:
            raise MediatorError("INVALID_REGISTRY", "bundle_sha256 is malformed")
        actual_bundle = bundle_tree_sha256(path)
        if actual_bundle != expected_bundle:
            raise MediatorError("BUNDLE_HASH_MISMATCH", task_bundle_id)
        runner = _set2_runner()
        try:
            manifest, manifest_sha = runner.load_bundle(path)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise MediatorError("INVALID_TASK_BUNDLE", str(error)) from error
        if manifest["task_id"] != task_bundle_id:
            raise MediatorError("BUNDLE_IDENTITY_MISMATCH", task_bundle_id)
        expected_manifest = entry.get("manifest_sha256")
        if expected_manifest is not None and expected_manifest != manifest_sha:
            raise MediatorError("MANIFEST_HASH_MISMATCH", task_bundle_id)
        return BundleBinding(task_bundle_id, path, actual_bundle, manifest_sha,
                             str(manifest["contract_version"]), manifest)


def _public_starter_files(binding: BundleBinding) -> list[str]:
    configured = binding.manifest.get("prompt", {}).get("public_starter_files")
    if configured is None:
        configured = sorted(
            path.relative_to(binding.path / "starter").as_posix()
            for path in (binding.path / "starter").rglob("*") if path.is_file()
        )
    if not isinstance(configured, list) or not configured:
        raise MediatorError("INVALID_PROMPT_CONTRACT", "no public starter files")
    result: list[str] = []
    for index, value in enumerate(configured):
        relative = _safe_relative(value, f"public_starter_files[{index}]")
        path = binding.path / "starter" / relative
        if not path.is_file() or path.is_symlink():
            raise MediatorError("INVALID_PROMPT_CONTRACT", f"missing starter file: {relative}")
        result.append(relative)
    return result


def build_prompt(binding: BundleBinding) -> PromptEnvelope:
    """Construct the pinned eight-message Aider whole-file prompt."""

    instructions = (binding.path / "instructions.md").read_text(encoding="utf-8")
    editable = _public_starter_files(binding)
    files_content = _AIDER_FILES_CONTENT_PREFIX
    for name in editable:
        content = (binding.path / "starter" / name).read_text(encoding="utf-8")
        files_content += f"\n{name}\n```\n{content}```\n"
    request = (
        instructions
        + _AIDER_INSTRUCTIONS_ADDENDUM.format(file_list=" ".join(editable))
        + "\n\n"
        + _AIDER_SYSTEM_REMINDER
    )
    messages = [
        {"role": "system", "content": _AIDER_MAIN_SYSTEM + "\n" + _AIDER_SYSTEM_REMINDER},
        *(dict(message) for message in _AIDER_EXAMPLE_MESSAGES),
        {"role": "user", "content": files_content},
        {"role": "assistant", "content": _AIDER_FILES_ASSISTANT_REPLY},
        {"role": "user", "content": request},
    ]
    canonical = json.dumps(messages, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":")).encode()
    metadata = {
        "task_bundle_id": binding.task_bundle_id,
        "bundle_sha256": binding.bundle_sha256,
        "manifest_sha256": binding.manifest_sha256,
        "contract_version": binding.contract_version,
        "prompt_kind": str(binding.manifest.get("prompt", {}).get("kind", "aider-whole-file")),
        "prompt_sha256": _sha256_bytes(canonical),
    }
    return PromptEnvelope(messages, metadata)


def prepare_dataset_row(row: Mapping[str, Any], registry: TaskBundleRegistry) -> dict[str, Any]:
    """Bind a dataset row to the canonical Aider prompt and authenticated bundle."""

    result = dict(row)
    metadata = dict(result.get("metadata") or {})
    task_bundle_id = metadata.get("task_bundle_id") or result.get("task_bundle_id")
    if not isinstance(task_bundle_id, str):
        raise MediatorError("MISSING_TASK_BUNDLE_ID", "dataset row lacks task_bundle_id")
    envelope = build_prompt(registry.resolve(task_bundle_id))
    result["prompt"] = [dict(message) for message in envelope.messages]
    if "messages" in result:
        result["messages"] = [dict(message) for message in envelope.messages]
    metadata.update(envelope.metadata)
    result["metadata"] = metadata
    result.pop("task_bundle_id", None)
    return result


def _policy_map(receipt: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(item.get("policy")): item
        for item in receipt.get("policies", [])
        if isinstance(item, Mapping)
    }


def _invalid_reason(receipt: Mapping[str, Any]) -> str:
    return next(
        (str(item.get("reason")) for item in receipt.get("policies", [])
         if isinstance(item, Mapping) and item.get("status") == "INVALID"),
        "verifier_invalid",
    )


def _validated_reward_projection(manifest: Mapping[str, Any]) -> dict[str, Any] | None:
    value = manifest.get("reward_projection")
    if value is None:
        return None
    if not isinstance(value, Mapping) or value.get("kind") != "staged-g04-bipolar-v1":
        raise MediatorError("INVALID_REWARD_PROJECTION", "unsupported reward projection")
    fields = (
        "pass", "format_fail", "g01_fail", "g02_fail", "g03_fail",
        "g04_scale", "g04_offset",
    )
    normalized: dict[str, Any] = {"kind": value["kind"]}
    for field in fields:
        number = value.get(field)
        if not isinstance(number, (int, float)) or isinstance(number, bool):
            raise MediatorError("INVALID_REWARD_PROJECTION", f"{field} must be numeric")
        normalized[field] = float(number)
        if not math.isfinite(normalized[field]) or abs(normalized[field]) > 4.0:
            raise MediatorError("INVALID_REWARD_PROJECTION", f"{field} is out of bounds")
    return normalized


def receipt_to_reward(receipt: Mapping[str, Any], *, format_valid: bool = True) -> dict[str, Any]:
    """Project signed generic gate facts without flattening authenticated partial tests."""

    status = receipt.get("status")
    projection = receipt.get("reward_projection")
    projection_kind = (
        projection.get("kind")
        if isinstance(projection, Mapping)
        else "binary-correctness-v1"
    )
    if status == "INVALID":
        return {"valid": False, "retry": True, "reward": 0.0,
                "include_in_normalization": False, "include_in_loss": False,
                "projection_kind": projection_kind, "stage": "invalid",
                "correctness": None, "format": None, "build": None,
                "api": None, "tests": None}
    policies = _policy_map(receipt)
    g04_facts = policies.get("G04", {}).get("facts", {})
    tests = float(g04_facts.get("score", 0.0)) if isinstance(g04_facts, Mapping) else 0.0
    tests = max(0.0, min(1.0, tests))
    components = {
        "correctness": float(status == "PASS"),
        "format": float(format_valid),
        "build": float(policies.get("G02", {}).get("status") == "PASS"),
        "api": float(policies.get("G03", {}).get("status") == "PASS"),
        "tests": tests,
    }
    reward = components["correctness"]
    stage = "binary"
    if isinstance(projection, Mapping) and projection_kind == "staged-g04-bipolar-v1":
        if status == "PASS":
            reward, stage = float(projection["pass"]), "pass"
        elif not format_valid:
            reward, stage = float(projection["format_fail"]), "format"
        elif policies.get("G01", {}).get("status") != "PASS":
            reward, stage = float(projection["g01_fail"]), "integrity"
        elif policies.get("G02", {}).get("status") != "PASS":
            reward, stage = float(projection["g02_fail"]), "build"
        elif policies.get("G03", {}).get("status") != "PASS":
            reward, stage = float(projection["g03_fail"]), "api"
        else:
            reward = float(projection["g04_scale"]) * tests + float(projection["g04_offset"])
            stage = "functional"
    return {"valid": True, "retry": False, "reward": reward,
            "include_in_normalization": True, "include_in_loss": True,
            "projection_kind": projection_kind, "stage": stage, **components}


def _worker_identity() -> str:
    return f"{os.getpid()}:{threading.current_thread().name}:{threading.get_ident()}"


def _default_retry_token(
    binding: BundleBinding, response: str | None, candidate: Path | None,
) -> str:
    candidate_identity = (
        _sha256_bytes(response.encode("utf-8"))
        if response is not None
        else _sha256_bytes(str(candidate).encode("utf-8"))
    )
    payload = {
        "task_bundle_id": binding.task_bundle_id,
        "bundle_sha256": binding.bundle_sha256,
        "candidate_identity": candidate_identity,
    }
    return _sha256_bytes(json.dumps(payload, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8"))


def _mediator_envelope(
    binding: BundleBinding, attempts: list[dict[str, Any]], *,
    retry_token: str, exhausted: bool, terminal: Mapping[str, Any] | None,
    reconstruction_reason: str | None = None,
    metadata: Mapping[str, Any], actual_prompt_sha256: str,
    metadata_before_sha256: str, metadata_after_sha256: str,
) -> dict[str, Any]:
    terminal_fields = {
        "status": "FAIL",
        "task_id": binding.task_bundle_id,
        "manifest_sha256": binding.manifest_sha256,
        "candidate_sha256": None,
        "format_valid": False,
        "returned_files": [],
        "inherited_files": [],
        "policies": [],
    }
    if terminal is not None:
        terminal_fields.update({
            key: terminal[key]
            for key in ("status", "task_id", "manifest_sha256", "candidate_sha256",
                        "format_valid", "returned_files", "inherited_files", "policies")
        })
    g08 = _g08_policy(binding, metadata, actual_prompt_sha256,
                      metadata_before_sha256, metadata_after_sha256)
    terminal_fields["policies"] = [*terminal_fields["policies"], g08]
    if g08["status"] in {"FAIL", "INVALID"}:
        terminal_fields["status"] = g08["status"]
    envelope: dict[str, Any] = {
        "schema_version": MEDIATOR_RECEIPT_SCHEMA_VERSION,
        "kind": MEDIATOR_RECEIPT_KIND,
        **terminal_fields,
        "bundle_sha256": binding.bundle_sha256,
        "contract_version": binding.contract_version,
        "reward_projection": _validated_reward_projection(binding.manifest),
        "attempts": attempts,
        "mediator_attempts": len(attempts),
        "invalid_retry_exhausted": exhausted,
        "retry": {
            "token": retry_token,
            "attempts": len(attempts),
            "exhausted": exhausted,
            "worker_identities": [attempt["worker_identity"] for attempt in attempts],
        },
    }
    if reconstruction_reason is not None:
        envelope["reason"] = reconstruction_reason
    signed = sign_mediator_receipt(envelope)
    return verify_mediator_receipt(signed)


def _evaluate(
    binding: BundleBinding, *, response: str | None = None, candidate: Path | None = None,
    finish_reason: str | None = None, executor: str = "docker", invalid_retries: int = 1,
    retry_token: str | None = None, attempt_offset: int = 0,
    retry_limit: int | None = None, metadata: Mapping[str, Any] | None = None,
    actual_prompt_sha256: str | None = None,
) -> dict[str, Any]:
    if executor not in {"docker", "host"}:
        raise MediatorError("INVALID_EXECUTOR", executor)
    if (response is None) == (candidate is None):
        raise MediatorError("INVALID_CANDIDATE_INPUT", "choose response or candidate")
    runner = _set2_runner()
    reconstruction_module = importlib.import_module("candidate_reconstruction")
    receipt_module = _set2_receipt_module()
    candidate_path = candidate.resolve(strict=True) if candidate is not None else None
    prompt_envelope = build_prompt(binding)
    metadata_value = metadata if metadata is not None else prompt_envelope.metadata
    prompt_sha = actual_prompt_sha256 or prompt_envelope.metadata["prompt_sha256"]
    metadata_before = _metadata_sha256(metadata_value)
    token = retry_token or _default_retry_token(binding, response, candidate_path)
    attempts: list[dict[str, Any]] = []
    terminal: Mapping[str, Any] | None = None
    for local_attempt in range(max(0, invalid_retries) + 1):
        attempt_number = attempt_offset + local_attempt + 1
        execution = {
            "attempt": attempt_number,
            "queue_attempt": attempt_number,
            "retry_token": token,
            "worker_identity": _worker_identity(),
            "execution_id": uuid.uuid4().hex,
        }
        with TemporaryDirectory(prefix="gv2-grpo-mediator-") as temporary:
            output = Path(temporary) / "receipt"
            args = argparse.Namespace(bundle=binding.path, candidate=candidate_path,
                                      response=response, finish_reason=finish_reason,
                                      output=output, executor=executor, full=False)
            try:
                produced = runner.run(args)
            except reconstruction_module.ReconstructionError as error:
                attempts.append({
                    **execution,
                    "phase": "candidate_reconstruction",
                    "reason": error.reason,
                    "runner_receipt": None,
                    "runner_receipt_sha256": None,
                })
                return _mediator_envelope(
                    binding, attempts, retry_token=token, exhausted=False, terminal=None,
                    reconstruction_reason=error.reason, metadata=metadata_value,
                    actual_prompt_sha256=prompt_sha, metadata_before_sha256=metadata_before,
                    metadata_after_sha256=_metadata_sha256(metadata_value),
                )
            receipt_path = output / "verification_receipt.json"
            try:
                value = receipt_module.read_verified(receipt_path)
            except (OSError, ValueError, json.JSONDecodeError) as error:
                raise MediatorError("INVALID_VERIFIER_RECEIPT", str(error)) from error
            unsigned = {key: item for key, item in value.items() if key != "receipt_sha256"}
            if unsigned != produced.payload():
                raise MediatorError("RECEIPT_PAYLOAD_MISMATCH", binding.task_bundle_id)
            identities = {
                "schema_version": 2,
                "task_id": binding.task_bundle_id,
                "manifest_sha256": binding.manifest_sha256,
            }
            for key, expected in identities.items():
                if value.get(key) != expected:
                    raise MediatorError("RECEIPT_IDENTITY_MISMATCH", key)
            attempts.append({
                **execution,
                "phase": "set2_runner",
                "runner_receipt_sha256": value["receipt_sha256"],
                "runner_receipt": value,
            })
            terminal = value
            if value.get("status") != "INVALID":
                break
    exhausted = bool(
        terminal is not None
        and terminal.get("status") == "INVALID"
        and (retry_limit is None or attempt_offset + max(0, invalid_retries) >= retry_limit)
    )
    return _mediator_envelope(
        binding, attempts, retry_token=token, exhausted=exhausted, terminal=terminal,
        metadata=metadata_value, actual_prompt_sha256=prompt_sha,
        metadata_before_sha256=metadata_before,
        metadata_after_sha256=_metadata_sha256(metadata_value),
    )


def evaluate_response(
    binding: BundleBinding, response: str, *, finish_reason: str | None = None,
    executor: str = "docker", invalid_retries: int = 1, retry_token: str | None = None,
    attempt_offset: int = 0, retry_limit: int | None = None,
    metadata: Mapping[str, Any] | None = None, actual_prompt_sha256: str | None = None,
) -> dict[str, Any]:
    return _evaluate(
        binding, response=response, finish_reason=finish_reason, executor=executor,
        invalid_retries=invalid_retries, retry_token=retry_token,
        attempt_offset=attempt_offset, retry_limit=retry_limit,
        metadata=metadata, actual_prompt_sha256=actual_prompt_sha256,
    )


def evaluate_candidate(
    binding: BundleBinding, candidate: Path, *, executor: str = "docker",
    invalid_retries: int = 1, retry_token: str | None = None, attempt_offset: int = 0,
    retry_limit: int | None = None,
) -> dict[str, Any]:
    """Replay an authenticated editable-file snapshot without weakening live binding."""

    return _evaluate(
        binding, candidate=candidate, executor=executor, invalid_retries=invalid_retries,
        retry_token=retry_token, attempt_offset=attempt_offset, retry_limit=retry_limit,
    )


def _sample_value(sample: Any, name: str, default: Any = None) -> Any:
    if isinstance(sample, Mapping):
        return sample.get(name, default)
    return getattr(sample, name, default)


def _sample_metadata(sample: Any) -> dict[str, Any]:
    value = _sample_value(sample, "metadata", {})
    return dict(value) if isinstance(value, Mapping) else {}


def _sample_response(sample: Any) -> str:
    for name in ("response", "completion", "output"):
        value = _sample_value(sample, name)
        if isinstance(value, str):
            return value
    return ""


def _sample_finish_reason(sample: Any) -> str | None:
    """Map Miles generation status to the reconstruction finish reason."""

    value = _sample_value(sample, "finish_reason")
    if isinstance(value, str) and value:
        return value
    status = _sample_value(sample, "status")
    status_value = getattr(status, "value", status)
    if status_value == "truncated":
        return "length"
    return None


def _canonical_messages_sha256(messages: list[Mapping[str, Any]]) -> str:
    normalized = [
        {"role": message["role"], "content": message["content"]}
        for message in messages
    ]
    canonical = json.dumps(
        normalized, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return _sha256_bytes(canonical)


def _render_messages_for_miles(runtime_args: Any, messages: list[Mapping[str, Any]]) -> str:
    """Render with the same pinned Miles path that transformed ``Sample.prompt``."""

    if runtime_args is None or not getattr(runtime_args, "apply_chat_template", False):
        raise MediatorError(
            "RENDERED_PROMPT_BINDING_UNAVAILABLE",
            "Miles runtime arguments with --apply-chat-template are required",
        )
    checkpoint = getattr(runtime_args, "hf_checkpoint", None)
    if not isinstance(checkpoint, str) or not checkpoint:
        raise MediatorError("RENDERED_PROMPT_BINDING_UNAVAILABLE", "hf_checkpoint is missing")
    template_path = getattr(runtime_args, "chat_template_path", None)
    if template_path is not None and not isinstance(template_path, str):
        raise MediatorError("RENDERED_PROMPT_BINDING_UNAVAILABLE", "chat_template_path is invalid")
    raw_kwargs = getattr(runtime_args, "apply_chat_template_kwargs", None) or {}
    if not isinstance(raw_kwargs, Mapping):
        raise MediatorError(
            "RENDERED_PROMPT_BINDING_UNAVAILABLE",
            "apply_chat_template_kwargs must be a mapping",
        )
    kwargs = dict(raw_kwargs)
    messages_json = json.dumps(
        list(messages), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    kwargs_json = json.dumps(kwargs, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    cache_key = (checkpoint, template_path, kwargs_json, messages_json)
    with _MILES_PROMPT_CACHE_LOCK:
        cached = _MILES_RENDERED_PROMPT_CACHE.get(cache_key)
        if cached is not None:
            return cached
        try:
            from miles.utils import chat_template_utils
            from miles.utils.processing_utils import load_tokenizer
        except Exception as error:
            raise MediatorError(
                "RENDERED_PROMPT_BINDING_UNAVAILABLE",
                f"Miles prompt renderer import failed: {error}",
            ) from error
        tokenizer_key = (checkpoint, template_path)
        tokenizer = _MILES_TOKENIZER_CACHE.get(tokenizer_key)
        if tokenizer is None:
            tokenizer = load_tokenizer(
                checkpoint,
                chat_template_path=template_path,
                trust_remote_code=True,
            )
            _MILES_TOKENIZER_CACHE[tokenizer_key] = tokenizer
        rendered = chat_template_utils.apply_chat_template(
            list(messages),
            tokenizer=tokenizer,
            tools=None,
            tokenize=False,
            add_generation_prompt=True,
            **kwargs,
        )
        if not isinstance(rendered, str):
            raise MediatorError(
                "RENDERED_PROMPT_BINDING_UNAVAILABLE",
                "Miles chat template did not return text",
            )
        _MILES_RENDERED_PROMPT_CACHE[cache_key] = rendered
        return rendered


def _sample_prompt_sha256(
    sample: Any, *, expected_messages: list[Mapping[str, Any]], runtime_args: Any = None,
) -> str:
    value = _sample_value(sample, "prompt")
    if value is None:
        value = _sample_value(sample, "messages")
    if value is None:
        raise MediatorError(
            "MISSING_ROLLOUT_PROMPT",
            "live scoring requires the actual prompt or messages used for generation",
        )
    if isinstance(value, str):
        expected_rendered = _render_messages_for_miles(runtime_args, expected_messages)
        if value != expected_rendered:
            raise MediatorError(
                "PROMPT_BINDING_MISMATCH",
                "rendered rollout prompt bytes",
            )
        return _canonical_messages_sha256(expected_messages)
    if not isinstance(value, list) or not all(
        isinstance(message, Mapping)
        and isinstance(message.get("role"), str)
        and isinstance(message.get("content"), str)
        for message in value
    ):
        raise MediatorError(
            "INVALID_ROLLOUT_PROMPT",
            "prompt must be canonical role/content messages or exact Miles-rendered text",
        )
    return _canonical_messages_sha256(value)


def _sample_retry_token(
    sample: Any, binding: BundleBinding, prompt_sha256: str, response: str,
) -> str:
    metadata = _sample_metadata(sample)
    payload = {
        "rollout_id": _sample_value(sample, "rollout_id"),
        "problem_id": _sample_value(sample, "problem_id", metadata.get("problem_id")),
        "task_bundle_id": binding.task_bundle_id,
        "bundle_sha256": binding.bundle_sha256,
        "prompt_sha256": prompt_sha256,
        "response_sha256": _sha256_bytes(response.encode("utf-8")),
    }
    return _sha256_bytes(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode("utf-8"))


def _invalid_score_record(
    sample: Any, reason: str, *, exception: str, retry_token: str | None = None,
    retry_attempt: int = 0,
) -> dict[str, Any]:
    components = {
        "valid": False,
        "retry": False,
        "reward": 0.0,
        "include_in_normalization": False,
        "include_in_loss": False,
        "correctness": None,
        "format": None,
        "build": None,
        "api": None,
        "tests": None,
    }
    metadata = _sample_metadata(sample)
    return {
        "score": 0.0,
        "reward": 0.0,
        "valid": False,
        "infrastructure_error": True,
        "include_in_normalization": False,
        "include_in_loss": False,
        "retry": False,
        "retry_requested": False,
        "retry_exhausted": False,
        "retry_token": retry_token,
        "retry_attempt": retry_attempt,
        "reason": reason,
        "exception": exception,
        "reward_components": components,
        "rollout_id": _sample_value(sample, "rollout_id"),
        "problem_id": _sample_value(sample, "problem_id", metadata.get("problem_id")),
    }


def score_sample(
    sample: Any, registry: TaskBundleRegistry, *, executor: str, invalid_retries: int,
    retry_token: str | None = None, retry_attempt: int = 0,
    retry_limit: int | None = None, runtime_args: Any = None,
) -> dict[str, Any]:
    metadata = _sample_metadata(sample)
    try:
        task_bundle_id = metadata.get("task_bundle_id")
        if not isinstance(task_bundle_id, str):
            raise MediatorError("MISSING_TASK_BUNDLE_ID", "rollout lacks task_bundle_id")
        binding = registry.resolve(task_bundle_id)
        envelope = build_prompt(binding)
        actual_prompt_sha = _sample_prompt_sha256(
            sample, expected_messages=envelope.messages, runtime_args=runtime_args,
        )
        response = _sample_response(sample)
        token = retry_token or _sample_retry_token(
            sample, binding, envelope.metadata["prompt_sha256"], response,
        )
        global_retry_limit = max(0, invalid_retries) if retry_limit is None else max(0, retry_limit)
        receipt = evaluate_response(
            binding, response,
            finish_reason=_sample_finish_reason(sample),
            executor=executor,
            invalid_retries=invalid_retries,
            retry_token=token,
            attempt_offset=retry_attempt,
            retry_limit=global_retry_limit,
            metadata=metadata, actual_prompt_sha256=actual_prompt_sha,
        )
        verify_mediator_receipt(receipt)
        projection = receipt_to_reward(receipt, format_valid=receipt.get("format_valid", True))
        retry_intrinsic = bool(projection["retry"])
        retry_exhausted = bool(receipt.get("invalid_retry_exhausted"))
        retry_requested = retry_intrinsic and not retry_exhausted
        worker_identities = receipt.get("retry", {}).get("worker_identities", [])
        return {
            "score": projection["reward"],
            "reward": projection["reward"],
            "valid": projection["valid"],
            "infrastructure_error": not projection["valid"],
            "include_in_normalization": projection["include_in_normalization"],
            "include_in_loss": projection["include_in_loss"],
            "retry": retry_intrinsic,
            "retry_requested": retry_requested,
            "retry_exhausted": retry_exhausted,
            "retry_token": token,
            "retry_attempt": retry_attempt,
            "worker_identity": worker_identities[-1] if worker_identities else None,
            "reason": (
                _invalid_reason(receipt)
                if not projection["valid"]
                else str(receipt.get("reason", receipt["status"])).lower()
            ),
            "task_bundle_id": task_bundle_id,
            "bundle_sha256": binding.bundle_sha256,
            "manifest_sha256": binding.manifest_sha256,
            "prompt_sha256": envelope.metadata["prompt_sha256"],
            "reward_components": projection,
            "verifier_receipt": receipt,
            "rollout_id": _sample_value(sample, "rollout_id"),
            "problem_id": _sample_value(sample, "problem_id", metadata.get("problem_id")),
        }
    except MediatorError as error:
        return _invalid_score_record(
            sample, error.reason, exception=str(error), retry_token=retry_token,
            retry_attempt=retry_attempt,
        )
    except Exception as error:  # protects remote reward workers
        return _invalid_score_record(
            sample, "MEDIATOR_EXCEPTION",
            exception=f"{type(error).__name__}: {error}",
            retry_token=retry_token,
            retry_attempt=retry_attempt,
        )


def _settings() -> tuple[TaskBundleRegistry, str, int]:
    registry = TaskBundleRegistry(Path(os.environ.get(REGISTRY_ENV, DEFAULT_REGISTRY)))
    executor = os.environ.get(EXECUTOR_ENV, "docker")
    retries = int(os.environ.get(RETRIES_ENV, "1"))
    return registry, executor, max(0, retries)


def neutralize_infrastructure_scores(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Give INVALID records zero group-normalized advantage without hiding audited reward."""

    groups: dict[tuple[Any, Any], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[(record.get("rollout_id"), record.get("problem_id"))].append(record)
    for group in groups.values():
        invalid = [record for record in group if record.get("infrastructure_error")]
        if not invalid:
            continue
        valid_scores = [float(record.get("score") or 0.0) for record in group
                        if not record.get("infrastructure_error")]
        anchor = sum(valid_scores) / len(valid_scores) if valid_scores else 0.0
        for record in invalid:
            record["score"] = anchor
            record["score_neutralized"] = True
    return records


def _reward_post_process_groups(args: Any, samples: list[Any]) -> list[list[int]]:
    group_indices = [_sample_value(sample, "group_index") for sample in samples]
    if samples and all(value is not None for value in group_indices):
        groups: dict[int, list[int]] = {}
        for index, value in enumerate(group_indices):
            groups.setdefault(int(value), []).append(index)
        return list(groups.values())
    expected = int(getattr(args, "n_samples_per_prompt", 0) or 0) * int(
        getattr(args, "rollout_batch_size", 0) or 0
    )
    fanout = int(getattr(args, "n_samples_per_prompt", 0) or 0)
    if fanout > 0 and expected == len(samples):
        return [
            list(range(start, start + fanout))
            for start in range(0, len(samples), fanout)
        ]
    raise RuntimeError(
        "Set 2 reward post-processing requires Miles group_index values or the complete fixed rollout layout"
    )


def reward_post_process(args: Any, samples: list[Any]) -> tuple[list[float], list[float]]:
    """Exclude verifier INVALID samples from GRPO mean, variance, and policy loss."""

    if not getattr(args, "group_rm", False):
        raise RuntimeError("Set 2 reward post-processing requires --group-rm")
    if not isinstance(samples, list) or any(isinstance(sample, list) for sample in samples):
        raise RuntimeError("Set 2 reward post-processing requires a flat Miles sample list")
    raw_rewards = [0.0] * len(samples)
    normalized_rewards = [0.0] * len(samples)
    normalize = bool(getattr(args, "rewards_normalization", False)) and getattr(
        args, "advantage_estimator", None
    ) in {"grpo", "gspo", "reinforce_plus_plus_baseline"}
    use_sample_std = (
        getattr(args, "advantage_estimator", None) in {"grpo", "gspo"}
        and bool(getattr(args, "grpo_std_normalization", False))
    )

    for indices in _reward_post_process_groups(args, samples):
        valid: list[tuple[int, float, dict[str, Any]]] = []
        invalid_indices: list[int] = []
        for index in indices:
            sample = samples[index]
            record = _sample_value(sample, "reward")
            is_valid = (
                isinstance(record, dict)
                and record.get("valid") is True
                and record.get("infrastructure_error") is False
                and record.get("include_in_normalization") is True
                and record.get("include_in_loss") is True
            )
            score = None
            if is_valid:
                try:
                    score = float(record["score"])
                except (KeyError, TypeError, ValueError):
                    is_valid = False
                if score is not None and not math.isfinite(score):
                    is_valid = False
            if is_valid and score is not None:
                valid.append((index, score, record))
                raw_rewards[index] = score
                setattr(sample, "remove_sample", False)
            else:
                invalid_indices.append(index)
                setattr(sample, "remove_sample", True)

        valid_scores = [score for _, score, _ in valid]
        mean = sum(valid_scores) / len(valid_scores) if valid_scores else 0.0
        std = 0.0
        if use_sample_std and len(valid_scores) > 1:
            std = math.sqrt(
                sum((score - mean) ** 2 for score in valid_scores)
                / (len(valid_scores) - 1)
            )
        for index, score, record in valid:
            normalized = score
            if normalize:
                normalized = score - mean
                if use_sample_std and std > 0.0:
                    normalized /= std + 1e-6
            normalized_rewards[index] = normalized
            record["post_process"] = {
                "included": True,
                "valid_group_size": len(valid_scores),
                "valid_group_mean": mean,
                "valid_group_sample_std": std,
                "normalized_score": normalized,
            }
        for index in invalid_indices:
            record = _sample_value(samples[index], "reward")
            if isinstance(record, dict):
                record["post_process"] = {
                    "included": False,
                    "valid_group_size": len(valid_scores),
                    "valid_group_mean": mean,
                    "valid_group_sample_std": std,
                    "normalized_score": 0.0,
                }
    return raw_rewards, normalized_rewards


def _reward_workers() -> int:
    try:
        return max(1, int(os.environ.get(WORKERS_ENV, str(DEFAULT_WORKERS))))
    except ValueError:
        return DEFAULT_WORKERS


def _score_sample_globally_limited(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Bound nested verifier executions across every concurrent Miles group."""

    global _GLOBAL_REWARD_ACTIVE
    limit = _reward_workers()
    with _GLOBAL_REWARD_LIMIT:
        while _GLOBAL_REWARD_ACTIVE >= limit:
            _GLOBAL_REWARD_LIMIT.wait()
        _GLOBAL_REWARD_ACTIVE += 1
    try:
        return score_sample(*args, **kwargs)
    finally:
        with _GLOBAL_REWARD_LIMIT:
            _GLOBAL_REWARD_ACTIVE -= 1
            _GLOBAL_REWARD_LIMIT.notify_all()


def _retry_audit_entry(record: Mapping[str, Any]) -> dict[str, Any]:
    receipt = record.get("verifier_receipt")
    return {
        "retry_attempt": record.get("retry_attempt"),
        "retry_token": record.get("retry_token"),
        "worker_identity": record.get("worker_identity"),
        "valid": record.get("valid"),
        "reason": record.get("reason"),
        "mediator_receipt_sha256": (
            receipt.get("mediator_receipt_sha256")
            if isinstance(receipt, Mapping)
            else None
        ),
        "verifier_receipt": receipt,
    }


async def _score_queued(
    samples: list[Any], registry: TaskBundleRegistry, *, executor: str, retries: int,
    runtime_args: Any = None,
) -> list[dict[str, Any]]:
    """Run INVALID retries in later bounded queue rounds, never in the first worker call."""

    semaphore = asyncio.Semaphore(min(len(samples), _reward_workers()) or 1)

    async def score(index: int, retry_attempt: int, retry_token: str | None) -> tuple[int, dict[str, Any]]:
        async with semaphore:
            record = await asyncio.to_thread(
                _score_sample_globally_limited,
                samples[index],
                registry,
                executor=executor,
                invalid_retries=0,
                retry_token=retry_token,
                retry_attempt=retry_attempt,
                retry_limit=retries,
                runtime_args=runtime_args,
            )
            return index, record

    records: list[dict[str, Any]] = [{} for _ in samples]
    histories: list[list[dict[str, Any]]] = [[] for _ in samples]
    first_round = await asyncio.gather(
        *(score(index, 0, None) for index in range(len(samples)))
    )
    for index, record in first_round:
        records[index] = record
        histories[index].append(_retry_audit_entry(record))

    for retry_attempt in range(1, retries + 1):
        pending = [
            index for index, record in enumerate(records)
            if record.get("retry_requested") is True
        ]
        if not pending:
            break
        round_results = await asyncio.gather(*(
            score(index, retry_attempt, records[index].get("retry_token"))
            for index in pending
        ))
        for index, record in round_results:
            records[index] = record
            histories[index].append(_retry_audit_entry(record))

    for index, record in enumerate(records):
        history = histories[index]
        record["retry_history"] = history
        record["retry_queue_rounds"] = len(history)
        record["retry_recovered"] = bool(
            len(history) > 1
            and any(entry.get("valid") is False for entry in history[:-1])
            and record.get("valid") is True
        )
    return neutralize_infrastructure_scores(records)


def _batch_required() -> bool:
    value = os.environ.get(REQUIRE_BATCH_ENV, "1").strip().lower()
    if value in {"1", "true", "yes"}:
        return True
    if value in {"0", "false", "no"}:
        return False
    raise MediatorError("INVALID_BATCH_REQUIREMENT", value)


async def reward_func(_args: Any, sample: Any, **_kwargs: Any) -> dict[str, Any] | list[dict[str, Any]]:
    """Miles custom-RM hook with bounded workers and trainer-safe queued INVALID retries."""

    is_batch = isinstance(sample, list)
    if not is_batch and _batch_required():
        raise MediatorError(
            "BATCH_SCORING_REQUIRED",
            "production scoring requires the complete normalization group",
        )
    registry, executor, retries = _settings()
    samples = sample if is_batch else [sample]
    records = await _score_queued(
        samples, registry, executor=executor, retries=retries, runtime_args=_args,
    )
    return records if is_batch else records[0]


def _control_gate(receipt: Mapping[str, Any]) -> str | None:
    policies = [
        item for item in receipt.get("policies", [])
        if isinstance(item, Mapping)
    ]
    for item in policies:
        if item.get("status") in {"FAIL", "INVALID"}:
            return str(item.get("policy"))
    if any(
        item.get("policy") == "G04" and item.get("status") == "PASS"
        for item in policies
    ):
        return "G04"
    passed = [str(item.get("policy")) for item in policies if item.get("status") == "PASS"]
    return passed[-1] if passed else None


def _run_bundle_controls(
    binding: BundleBinding, *, executor: str,
) -> list[dict[str, Any]]:
    controls = binding.manifest.get("controls")
    if not isinstance(controls, list) or not controls:
        raise MediatorError(
            "MISSING_PREFLIGHT_CONTROLS",
            f"{binding.task_bundle_id} has no authenticated controls",
        )
    results = []
    for index, control in enumerate(controls):
        if not isinstance(control, Mapping):
            raise MediatorError("INVALID_PREFLIGHT_CONTROL", f"control {index}")
        control_id = control.get("control_id")
        relative = _safe_relative(control.get("candidate"), f"controls[{index}].candidate")
        candidate = (binding.path / relative).resolve(strict=True)
        if not candidate.is_relative_to(binding.path) or not candidate.is_dir():
            raise MediatorError("INVALID_PREFLIGHT_CONTROL", str(control_id))
        expected_digest = control.get("candidate_sha256")
        if (
            not isinstance(expected_digest, str)
            or expected_digest != bundle_tree_sha256(candidate)
        ):
            raise MediatorError("CONTROL_HASH_MISMATCH", str(control_id))
        expected_status = control.get("expected_status")
        expected_gate = control.get("expected_gate")
        if expected_status not in {"PASS", "FAIL"} or not isinstance(expected_gate, str):
            raise MediatorError("INVALID_PREFLIGHT_CONTROL", str(control_id))
        receipt = evaluate_candidate(
            binding, candidate, executor=executor, invalid_retries=0,
            retry_token=_sha256_bytes(
                f"preflight:{binding.task_bundle_id}:{control_id}".encode("utf-8")
            ),
        )
        verify_mediator_receipt(receipt)
        actual_gate = _control_gate(receipt)
        if receipt.get("status") != expected_status or actual_gate != expected_gate:
            raise MediatorError(
                "PREFLIGHT_CONTROL_MISMATCH",
                (
                    f"{binding.task_bundle_id}/{control_id}: "
                    f"expected {expected_status}@{expected_gate}, "
                    f"got {receipt.get('status')}@{actual_gate}"
                ),
            )
        results.append({
            "control_id": control_id,
            "candidate_sha256": expected_digest,
            "expected_status": expected_status,
            "expected_gate": expected_gate,
            "actual_status": receipt["status"],
            "actual_gate": actual_gate,
            "mediator_receipt_sha256": receipt["mediator_receipt_sha256"],
        })
    return results


def _verify_configured_image(binding: BundleBinding, executor: str) -> str:
    image = binding.manifest.get("runtime", {}).get("image")
    if not isinstance(image, str):
        raise MediatorError("INVALID_TASK_BUNDLE", "runtime image is missing")
    configured_id = os.environ.get("GLOBAL_VERIFIER_SET2_IMAGE_ID")
    if executor == "docker" and configured_id is not None:
        digest = configured_id.removeprefix("sha256:")
        if (
            len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or image not in {configured_id, f"sha256:{digest}"}
        ):
            raise MediatorError(
                "VERIFIER_IMAGE_IDENTITY_MISMATCH",
                f"{binding.task_bundle_id} is not bound to {configured_id}",
            )
    return image


def _preflight_report(
    registry_path: Path, *, execute_controls: bool = False,
) -> dict[str, Any]:
    registry = TaskBundleRegistry(registry_path)
    executor = os.environ.get(EXECUTOR_ENV, "docker")
    if executor not in {"docker", "host"}:
        raise MediatorError("INVALID_EXECUTOR", executor)
    bundles = []
    for task_bundle_id in registry.bundle_ids:
        binding = registry.resolve(task_bundle_id)
        prompt = build_prompt(binding)
        bundle_report: dict[str, Any] = {
            "task_bundle_id": task_bundle_id,
            "bundle_sha256": binding.bundle_sha256,
            "manifest_sha256": binding.manifest_sha256,
            "prompt_sha256": prompt.metadata["prompt_sha256"],
            "verifier_image": _verify_configured_image(binding, executor),
        }
        if execute_controls:
            bundle_report["controls"] = _run_bundle_controls(
                binding, executor=executor,
            )
        bundles.append(bundle_report)
    if not bundles:
        raise MediatorError("INVALID_REGISTRY", "registry contains no bundles")
    return {
        "ready": True,
        "registry": str(registry.path),
        "registry_sha256": _sha256_file(registry.path),
        "executor": executor,
        "bundle_count": len(bundles),
        "control_count": sum(len(bundle.get("controls", [])) for bundle in bundles),
        "controls_executed": execute_controls,
        "bundles": bundles,
    }


def validate_dataset(path: Path, registry: TaskBundleRegistry) -> dict[str, Any]:
    """Authenticate every serialized prompt and bundle binding before rollout launch."""

    seen: set[str] = set()
    count = 0
    with path.resolve(strict=True).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise MediatorError(
                    "INVALID_DATASET_ROW", f"line {line_number}: {error}"
                ) from error
            if not isinstance(row, Mapping):
                raise MediatorError("INVALID_DATASET_ROW", f"line {line_number}")
            metadata = _sample_metadata(row)
            task_bundle_id = metadata.get("task_bundle_id")
            if not isinstance(task_bundle_id, str):
                raise MediatorError(
                    "MISSING_TASK_BUNDLE_ID", f"dataset line {line_number}"
                )
            binding = registry.resolve(task_bundle_id)
            envelope = build_prompt(binding)
            for key, expected in envelope.metadata.items():
                if metadata.get(key) != expected:
                    raise MediatorError(
                        "PROMPT_BINDING_MISMATCH", f"line {line_number}: {key}"
                    )
            if _sample_prompt_sha256(
                row, expected_messages=envelope.messages,
            ) != envelope.metadata["prompt_sha256"]:
                raise MediatorError(
                    "PROMPT_BINDING_MISMATCH",
                    f"line {line_number}: serialized prompt bytes",
                )
            seen.add(task_bundle_id)
            count += 1
    if count == 0:
        raise MediatorError("INVALID_DATASET", "prompt dataset is empty")
    return {
        "ready": True,
        "data": str(path.resolve()),
        "data_sha256": _sha256_file(path.resolve()),
        "row_count": count,
        "task_bundle_ids": sorted(seen),
        "registry": str(registry.path),
        "registry_sha256": _sha256_file(registry.path),
    }


def _hard_preflight_report(
    registry_path: Path, *, data_path: Path | None = None,
) -> dict[str, Any]:
    configured_data = data_path
    if configured_data is None:
        value = os.environ.get(TRAIN_DATA_ENV)
        if value:
            configured_data = Path(value)
    if configured_data is None:
        raise MediatorError(
            "MISSING_PREFLIGHT_DATASET",
            f"{TRAIN_DATA_ENV} must identify the generated train.jsonl",
        )
    registry = TaskBundleRegistry(registry_path)
    dataset = validate_dataset(configured_data, registry)
    if set(dataset["task_bundle_ids"]) != set(registry.bundle_ids):
        raise MediatorError(
            "PREFLIGHT_DATASET_COVERAGE_MISMATCH",
            "train.jsonl does not cover every configured bundle",
        )
    report = _preflight_report(registry_path, execute_controls=True)
    report["dataset"] = dataset
    return report


def preflight() -> None:
    """Launcher-compatible hard preflight for registry, controls, and train data."""
    report = _hard_preflight_report(
        Path(os.environ.get(REGISTRY_ENV, DEFAULT_REGISTRY))
    )
    print(json.dumps(report, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=("preflight", "validate-data"))
    parser.add_argument("--registry", type=Path, default=None)
    parser.add_argument("--data", type=Path)
    parser.add_argument("--task-bundle-id")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--print-prompt", action="store_true")
    args = parser.parse_args()
    registry_path = args.registry or Path(os.environ.get(REGISTRY_ENV, DEFAULT_REGISTRY))
    if args.command == "preflight" or args.preflight:
        print(json.dumps(
            _hard_preflight_report(registry_path, data_path=args.data),
            indent=2,
            sort_keys=True,
        ))
        return 0
    registry = TaskBundleRegistry(registry_path)
    if args.command == "validate-data":
        if args.data is None:
            parser.error("validate-data requires --data")
        print(json.dumps(validate_dataset(args.data, registry), indent=2, sort_keys=True))
        return 0
    if args.task_bundle_id is None:
        parser.error("provide preflight, validate-data, or --task-bundle-id")
    envelope = build_prompt(registry.resolve(args.task_bundle_id))
    if args.print_prompt:
        print(json.dumps(envelope.messages, indent=2, ensure_ascii=False))
    else:
        print(json.dumps({"metadata": envelope.metadata}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
