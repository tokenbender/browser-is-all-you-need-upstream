"""Fail-closed prompt rendering and token-count preflight for Aider GRPO."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Sequence


class PromptPreflightError(RuntimeError):
    """The exact scheduled prompt corpus cannot safely reach inference."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PromptPreflightError(f"expected JSON object: {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise PromptPreflightError(f"invalid JSONL: {path}:{line_number}") from exc
        if not isinstance(value, dict):
            raise PromptPreflightError(f"non-object JSONL row: {path}:{line_number}")
        rows.append(value)
    return rows


def _require_sha256(label: str, observed: str, expected: str) -> None:
    if observed != expected:
        raise PromptPreflightError(f"{label} SHA-256 mismatch: {observed} != {expected}")


def verify_tokenizer_assets(
    *,
    model_path: Path,
    tokenizer_manifest_path: Path,
    expected_manifest_sha256: str,
    chat_template_path: Path,
    expected_chat_template_sha256: str,
    expected_revision: str,
) -> dict[str, Any]:
    """Verify exact tokenizer files and template before loading Transformers."""

    if not model_path.is_dir():
        raise PromptPreflightError(f"model/tokenizer path is missing: {model_path}")
    for path in (tokenizer_manifest_path, chat_template_path):
        if path.is_symlink() or not path.is_file():
            raise PromptPreflightError(f"tokenizer preflight asset is missing/unsafe: {path}")
    _require_sha256(
        "tokenizer manifest", _sha256(tokenizer_manifest_path), expected_manifest_sha256
    )
    _require_sha256("chat template", _sha256(chat_template_path), expected_chat_template_sha256)
    manifest = _read_json(tokenizer_manifest_path)
    if manifest.get("model_revision") != expected_revision:
        raise PromptPreflightError("tokenizer revision drift")
    if manifest.get("chat_template", {}).get("sha256") != expected_chat_template_sha256:
        raise PromptPreflightError("tokenizer manifest binds a different chat template")
    verified: dict[str, Any] = {}
    for label, filename in (
        ("tokenizer", "tokenizer.json"),
        ("tokenizer_config", "tokenizer_config.json"),
    ):
        contract = manifest.get(label)
        path = model_path / filename
        if not isinstance(contract, dict) or not path.is_file() or path.is_symlink():
            raise PromptPreflightError(f"tokenizer asset is missing/unsafe: {path}")
        observed_sha256 = _sha256(path)
        _require_sha256(label, observed_sha256, str(contract.get("sha256", "")))
        if path.stat().st_size != int(contract.get("size_bytes", -1)):
            raise PromptPreflightError(f"tokenizer asset size drift: {path}")
        verified[label] = {
            "path": str(path),
            "sha256": observed_sha256,
            "size_bytes": path.stat().st_size,
        }
    return {
        "manifest_path": str(tokenizer_manifest_path),
        "manifest_sha256": expected_manifest_sha256,
        "revision": expected_revision,
        "chat_template_path": str(chat_template_path),
        "chat_template_sha256": expected_chat_template_sha256,
        "assets": verified,
    }


def render_and_measure_rows(
    rows: list[dict[str, Any]],
    *,
    tokenizer: Any,
    maximum_prompt_tokens: int,
    expected_rows: int,
    chat_template_kwargs: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Render every row exactly once and reject any missing/overlong prompt."""

    if maximum_prompt_tokens <= 0 or expected_rows <= 0:
        raise PromptPreflightError("prompt ceiling and expected row count must be positive")
    if len(rows) != expected_rows:
        raise PromptPreflightError(
            f"scheduled prompt row count mismatch: {len(rows)} != {expected_rows}"
        )
    kwargs = chat_template_kwargs or {}
    receipts: list[dict[str, Any]] = []
    failures: list[str] = []
    for index, row in enumerate(rows):
        prompt = row.get("prompt")
        metadata = row.get("metadata")
        if not isinstance(prompt, list) or not prompt or not isinstance(metadata, dict):
            raise PromptPreflightError(f"prompt row {index} lacks messages/metadata")
        token_ids = tokenizer.apply_chat_template(
            prompt,
            tokenize=True,
            add_generation_prompt=True,
            **kwargs,
        )
        if isinstance(token_ids, Mapping):
            input_ids = token_ids.get("input_ids")
            attention_mask = token_ids.get("attention_mask")
            if attention_mask is not None and (
                not isinstance(attention_mask, (list, tuple))
                or not isinstance(input_ids, (list, tuple))
                or len(attention_mask) != len(input_ids)
            ):
                raise PromptPreflightError(
                    f"tokenizer returned inconsistent attention mask for row {index}"
                )
            token_ids = input_ids
        if (
            not isinstance(token_ids, (list, tuple))
            or not token_ids
            or any(isinstance(token, bool) or not isinstance(token, int) for token in token_ids)
        ):
            raise PromptPreflightError(f"tokenizer returned non-token sequence for row {index}")
        token_count = len(token_ids)
        task_id = str(metadata.get("base_task_id") or row.get("task_id") or index)
        prompt_sha256 = hashlib.sha256(
            (
                json.dumps(prompt, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
            ).encode("utf-8")
        ).hexdigest()
        receipts.append(
            {
                "row_index": index,
                "task_id": task_id,
                "prompt_sha256": prompt_sha256,
                "prompt_token_count": token_count,
            }
        )
        if token_count > maximum_prompt_tokens:
            failures.append(f"{task_id}:{token_count}>{maximum_prompt_tokens}")
    if failures:
        raise PromptPreflightError("prompt overflow before inference: " + ", ".join(failures))
    return receipts


def run_prompt_preflight(
    *,
    prompt_data: Path,
    model_path: Path,
    tokenizer_manifest_path: Path,
    expected_tokenizer_manifest_sha256: str,
    tokenizer_revision: str,
    chat_template_path: Path,
    expected_chat_template_sha256: str,
    maximum_prompt_tokens: int,
    expected_rows: int,
    output: Path,
) -> dict[str, Any]:
    """Verify assets, render every row, and atomically write a PASS receipt."""

    if output.exists() or output.is_symlink():
        raise PromptPreflightError(f"refusing to overwrite prompt preflight receipt: {output}")
    assets = verify_tokenizer_assets(
        model_path=model_path,
        tokenizer_manifest_path=tokenizer_manifest_path,
        expected_manifest_sha256=expected_tokenizer_manifest_sha256,
        chat_template_path=chat_template_path,
        expected_chat_template_sha256=expected_chat_template_sha256,
        expected_revision=tokenizer_revision,
    )
    try:
        from transformers import AutoTokenizer
    except ImportError as exc:
        raise PromptPreflightError("Transformers is required for prompt preflight") from exc
    tokenizer = AutoTokenizer.from_pretrained(
        str(model_path),
        trust_remote_code=True,
        local_files_only=True,
    )
    tokenizer.chat_template = chat_template_path.read_text(encoding="utf-8")
    rows = _read_jsonl(prompt_data)
    row_receipts = render_and_measure_rows(
        rows,
        tokenizer=tokenizer,
        maximum_prompt_tokens=maximum_prompt_tokens,
        expected_rows=expected_rows,
        chat_template_kwargs={"enable_thinking": True},
    )
    counts = [receipt["prompt_token_count"] for receipt in row_receipts]
    payload = {
        "schema_version": "glm47-aider-prompt-preflight-v1",
        "decision": "PASS",
        "prompt_data_path": str(prompt_data),
        "prompt_data_sha256": _sha256(prompt_data),
        "expected_row_count": expected_rows,
        "observed_row_count": len(row_receipts),
        "maximum_prompt_tokens": maximum_prompt_tokens,
        "minimum_observed_prompt_tokens": min(counts),
        "maximum_observed_prompt_tokens": max(counts),
        "silent_filtering_allowed": False,
        "prompt_overflow_count": 0,
        "tokenizer": assets,
        "rows": row_receipts,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    payload["receipt_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, output)
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt-data", required=True, type=Path)
    parser.add_argument("--model-path", required=True, type=Path)
    parser.add_argument("--tokenizer-manifest", required=True, type=Path)
    parser.add_argument("--tokenizer-manifest-sha256", required=True)
    parser.add_argument("--tokenizer-revision", required=True)
    parser.add_argument("--chat-template", required=True, type=Path)
    parser.add_argument("--chat-template-sha256", required=True)
    parser.add_argument("--maximum-prompt-tokens", required=True, type=int)
    parser.add_argument("--expected-rows", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    payload = run_prompt_preflight(
        prompt_data=args.prompt_data,
        model_path=args.model_path,
        tokenizer_manifest_path=args.tokenizer_manifest,
        expected_tokenizer_manifest_sha256=args.tokenizer_manifest_sha256,
        tokenizer_revision=args.tokenizer_revision,
        chat_template_path=args.chat_template,
        expected_chat_template_sha256=args.chat_template_sha256,
        maximum_prompt_tokens=args.maximum_prompt_tokens,
        expected_rows=args.expected_rows,
        output=args.output,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
