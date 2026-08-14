"""Digest-bound, non-scoring receipts for isolated Aider GRPO rollouts."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from glm47_posttraining.aider_polyglot.charm_grpo import PRIVATE_PROMPT_MARKERS
from glm47_posttraining.aider_polyglot.schema import AiderPolyglotTask, AiderTestResult


CONTEXT_ISOLATION_ENV = "GLM47_AIDER_REQUIRE_CONTEXT_ISOLATION"
MAX_PROMPT_TOKENS_ENV = "GLM47_AIDER_MAX_PROMPT_TOKENS"
TOKENIZER_REVISION_ENV = "GLM47_TOKENIZER_REVISION"
TOKENIZER_MANIFEST_SHA256_ENV = "GLM47_TOKENIZER_MANIFEST_SHA256"
CHAT_TEMPLATE_SHA256_ENV = "GLM47_CHAT_TEMPLATE_SHA256"
SANDBOX_IMAGE_ENV = "GLM47_CPP_SANDBOX_IMAGE"
HIDDEN_PARTITION_IDS = tuple(f"H{index}" for index in range(1, 6))


class RolloutReceiptError(ValueError):
    """A context or hidden-partition receipt is incomplete or inconsistent."""


def canonical_bytes(value: Any) -> bytes:
    """Return the repository canonical JSON representation, including newline."""

    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sample_value(sample: Any, name: str, default: Any = None) -> Any:
    if isinstance(sample, Mapping):
        return sample.get(name, default)
    return getattr(sample, name, default)


def _manifest(root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise RolloutReceiptError(f"starter workspace contains symlink: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        payload = path.read_bytes()
        entries.append(
            {
                "path": relative,
                "sha256": sha256_bytes(payload),
                "size": len(payload),
            }
        )
    return entries


def _rendered_prompt(sample: Any, task_prompt: list[dict[str, Any]]) -> tuple[Any, bool]:
    value = _sample_value(sample, "prompt")
    if isinstance(value, (str, list, dict)) and value:
        return value, True
    return task_prompt, False


def _token_counts(sample: Any) -> tuple[int | None, int | None]:
    response_length = _sample_value(sample, "response_length")
    tokens = _sample_value(sample, "tokens")
    if isinstance(response_length, bool) or not isinstance(response_length, int):
        return None, None
    if not isinstance(tokens, (list, tuple)) or response_length < 0:
        return None, response_length
    prompt_length = len(tokens) - response_length
    if prompt_length < 0:
        return None, response_length
    return prompt_length, response_length


def _termination_reason(sample: Any) -> str | None:
    for name in ("finish_reason", "termination_reason", "status"):
        value = _sample_value(sample, name)
        if value is not None:
            return str(getattr(value, "value", value))
    return None


def build_context_identity(
    *,
    sample: Any,
    task: AiderPolyglotTask,
    task_path: Path,
    exercise_dir: Path,
    raw_response: str,
    scored_response: str,
    harness: AiderTestResult | None,
    receipt_workspace_id: str | None = None,
) -> dict[str, Any]:
    """Bind task, prompt, tokenizer, workspace, response, and split identity."""

    metadata = _sample_value(sample, "metadata", {})
    metadata = metadata if isinstance(metadata, Mapping) else {}
    task_prompt = [message.model_dump(mode="json") for message in task.prompt]
    rendered_prompt, rendered_available = _rendered_prompt(sample, task_prompt)
    prompt_tokens, response_tokens = _token_counts(sample)
    full_manifest = _manifest(exercise_dir)
    editable_names = set(task.editable_files)
    editable_manifest = [entry for entry in full_manifest if entry["path"] in editable_names]
    protected_manifest = [entry for entry in full_manifest if entry["path"] not in editable_names]
    prompt_text = "\n".join(str(message["content"]) for message in task_prompt).lower()
    private_markers = sorted(
        marker for marker in PRIVATE_PROMPT_MARKERS if marker.lower() in prompt_text
    )
    clean_room_tags = [tag for tag in task.tags if tag.startswith("clean-room-charm-")]
    logical_task_id = str(
        metadata.get("base_task_id") or metadata.get("logical_task_id") or task.exercise
    )
    prompt_variant = str(
        metadata.get("prompt_variant")
        or metadata.get("prompt_variant_id")
        or task.task_id.rsplit("/", 1)[-1]
    )
    task_descriptor_sha256 = sha256_bytes(task_path.read_bytes())
    complete_prompt_sha256 = sha256_bytes(canonical_bytes(task_prompt))
    starter_workspace_sha256 = sha256_bytes(canonical_bytes(full_manifest))
    raw_response_sha256 = sha256_bytes(raw_response.encode("utf-8"))
    harness_workspace_id = (
        harness.verification_workspace_id if harness is not None else None
    )
    verification_workspace_id = harness_workspace_id or receipt_workspace_id
    return {
        "schema_version": "glm47-aider-context-identity-v2",
        "logical_task_id": logical_task_id,
        "task_version": task.source_revision,
        "task_descriptor_sha256": task_descriptor_sha256,
        "task_lineage_digest": task.source_revision,
        "prompt_variant_id": prompt_variant,
        "source_prompt_sha256": task.source_prompt_sha256,
        "complete_prompt_sha256": complete_prompt_sha256,
        "rendered_prompt_sha256": sha256_bytes(
            rendered_prompt.encode("utf-8")
            if isinstance(rendered_prompt, str)
            else canonical_bytes(rendered_prompt)
        ),
        "rendered_prompt_available": rendered_available,
        "rendered_system_message_sha256": [
            sha256_bytes(str(message["content"]).encode("utf-8"))
            for message in task_prompt
            if message["role"] == "system"
        ],
        "rendered_user_message_sha256": [
            sha256_bytes(str(message["content"]).encode("utf-8"))
            for message in task_prompt
            if message["role"] == "user"
        ],
        "starter_workspace_sha256": starter_workspace_sha256,
        "editable_file_manifest": editable_manifest,
        "editable_file_manifest_sha256": sha256_bytes(canonical_bytes(editable_manifest)),
        "protected_file_manifest": protected_manifest,
        "protected_file_manifest_sha256": sha256_bytes(canonical_bytes(protected_manifest)),
        "tokenizer_revision": os.environ.get(TOKENIZER_REVISION_ENV),
        "tokenizer_manifest_sha256": os.environ.get(TOKENIZER_MANIFEST_SHA256_ENV),
        "chat_template_sha256": os.environ.get(CHAT_TEMPLATE_SHA256_ENV),
        "prompt_token_count": prompt_tokens,
        "response_token_count": response_tokens,
        "termination_reason": _termination_reason(sample),
        "verification_executed": harness is not None,
        "verification_workspace_binding": (
            "harness" if harness_workspace_id else "isolated_receipt"
        ),
        "verification_workspace_id": verification_workspace_id,
        "sample_index": _sample_value(sample, "index"),
        "rollout_id": _sample_value(sample, "rollout_id"),
        "raw_response_sha256": raw_response_sha256,
        "scored_response_sha256": sha256_bytes(scored_response.encode("utf-8")),
        "split": task.split,
        "training_split_membership": task.split == "train",
        "fixed26_exclusion_passed": (
            task.harness_kind != "official_cmake" and bool(clean_room_tags)
        ),
        "private_marker_scan_passed": not private_markers,
        "private_markers_found": private_markers,
        "hidden_test_sha256": task.hidden_test_sha256,
        "verifier_image_digest": os.environ.get(SANDBOX_IMAGE_ENV),
    }


def context_group_key(context: Mapping[str, Any]) -> tuple[Any, ...]:
    """Return the immutable group identity shared by eight candidate samples."""

    return tuple(
        context.get(name)
        for name in (
            "logical_task_id",
            "task_version",
            "task_descriptor_sha256",
            "prompt_variant_id",
            "source_prompt_sha256",
            "complete_prompt_sha256",
            "rendered_prompt_sha256",
            "starter_workspace_sha256",
        )
    )


def validate_context_identity(context: Mapping[str, Any], *, maximum_prompt_tokens: int) -> None:
    """Reject incomplete, contaminated, truncated, or mis-bound context receipts."""

    required_strings = (
        "logical_task_id",
        "task_version",
        "task_descriptor_sha256",
        "prompt_variant_id",
        "source_prompt_sha256",
        "complete_prompt_sha256",
        "rendered_prompt_sha256",
        "starter_workspace_sha256",
        "editable_file_manifest_sha256",
        "protected_file_manifest_sha256",
        "tokenizer_revision",
        "tokenizer_manifest_sha256",
        "chat_template_sha256",
        "verification_workspace_id",
        "raw_response_sha256",
        "scored_response_sha256",
        "hidden_test_sha256",
        "verifier_image_digest",
    )
    missing = [
        name
        for name in required_strings
        if not isinstance(context.get(name), str) or not context.get(name)
    ]
    if missing:
        raise RolloutReceiptError(f"context identity lacks required bindings: {missing}")
    if context.get("schema_version") != "glm47-aider-context-identity-v2":
        raise RolloutReceiptError("context identity schema is not v2")
    verification_executed = context.get("verification_executed")
    verification_binding = context.get("verification_workspace_binding")
    if not isinstance(verification_executed, bool):
        raise RolloutReceiptError("verification execution status is missing")
    if verification_binding not in {"harness", "isolated_receipt"}:
        raise RolloutReceiptError("verification workspace binding is invalid")
    if verification_binding == "harness" and verification_executed is not True:
        raise RolloutReceiptError("non-executed verification cannot claim a harness workspace")
    if context.get("rendered_prompt_available") is not True:
        raise RolloutReceiptError("rendered prompt is unavailable")
    for name in (
        "training_split_membership",
        "fixed26_exclusion_passed",
        "private_marker_scan_passed",
    ):
        if context.get(name) is not True:
            raise RolloutReceiptError(f"context isolation failed: {name}")
    prompt_tokens = context.get("prompt_token_count")
    response_tokens = context.get("response_token_count")
    if (
        isinstance(prompt_tokens, bool)
        or not isinstance(prompt_tokens, int)
        or prompt_tokens < 0
        or prompt_tokens > maximum_prompt_tokens
        or isinstance(response_tokens, bool)
        or not isinstance(response_tokens, int)
        or response_tokens < 0
    ):
        raise RolloutReceiptError(
            f"invalid token counts: prompt={prompt_tokens} response={response_tokens}"
        )
    if not isinstance(context.get("termination_reason"), str):
        raise RolloutReceiptError("response termination reason is missing")
    editable = context.get("editable_file_manifest")
    if not isinstance(editable, list) or not editable:
        raise RolloutReceiptError("editable starter manifest is empty")


def build_hidden_partition_accounting(
    context: Mapping[str, Any], hybrid45: Mapping[str, Any]
) -> dict[str, Any]:
    """Bind the five independent hidden partitions without changing reward math."""

    checks = hybrid45.get("checks")
    observed = hybrid45.get("observed")
    applicable = hybrid45.get("applicable")
    if not all(isinstance(value, Mapping) for value in (checks, observed, applicable)):
        raise RolloutReceiptError("Hybrid45 partition maps are missing")
    partitions: list[dict[str, Any]] = []
    for partition_id in HIDDEN_PARTITION_IDS:
        binding = {
            "task_digest": context.get("task_descriptor_sha256"),
            "hidden_test_sha256": context.get("hidden_test_sha256"),
            "partition_id": partition_id,
        }
        partitions.append(
            {
                "partition_id": partition_id,
                "partition_sha256": sha256_bytes(canonical_bytes(binding)),
                "applicable": applicable.get(partition_id),
                "executed": observed.get(partition_id),
                "passed": checks.get(partition_id),
            }
        )
    return {
        "schema_version": "glm47-hybrid45-hidden-partitions-v1",
        "task_digest": context.get("task_descriptor_sha256"),
        "verifier_image_digest": context.get("verifier_image_digest"),
        "hidden_test_sha256": context.get("hidden_test_sha256"),
        "hidden_manifest_digest": sha256_bytes(canonical_bytes(partitions)),
        "partition_count": len(partitions),
        "partitions": partitions,
        "aggregate_semantic_score": hybrid45.get("continuous_semantic_score"),
    }


def validate_hidden_partition_accounting(record: Mapping[str, Any]) -> None:
    """Prove exact, distinct, deterministic five-partition accounting."""

    partitions = record.get("partitions")
    if record.get("partition_count") != 5 or not isinstance(partitions, list):
        raise RolloutReceiptError("hidden partition count is not five")
    if [partition.get("partition_id") for partition in partitions] != list(HIDDEN_PARTITION_IDS):
        raise RolloutReceiptError("hidden partition order/identity drift")
    digests = [partition.get("partition_sha256") for partition in partitions]
    if len(set(digests)) != 5 or any(not isinstance(value, str) for value in digests):
        raise RolloutReceiptError("hidden partitions are not distinctly digest-bound")
    if record.get("hidden_manifest_digest") != sha256_bytes(canonical_bytes(partitions)):
        raise RolloutReceiptError("hidden partition manifest digest drift")
    for partition in partitions:
        if any(
            not isinstance(partition.get(name), bool)
            for name in ("applicable", "executed", "passed")
        ):
            raise RolloutReceiptError("hidden partition status is incomplete")
