from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from glm47_posttraining.aider_polyglot.prompt_preflight import (
    PromptPreflightError,
    render_and_measure_rows,
    verify_tokenizer_assets,
)


class FakeTokenizer:
    def apply_chat_template(
        self,
        prompt: list[dict[str, str]],
        *,
        tokenize: bool,
        add_generation_prompt: bool,
        **kwargs: object,
    ) -> list[int]:
        assert tokenize is True
        assert add_generation_prompt is True
        assert kwargs == {"enable_thinking": True}
        return list(range(sum(len(message["content"]) for message in prompt) + 1))


class BatchEncodingTokenizer(FakeTokenizer):
    def apply_chat_template(
        self,
        prompt: list[dict[str, str]],
        *,
        tokenize: bool,
        add_generation_prompt: bool,
        **kwargs: object,
    ) -> dict[str, list[int]]:
        input_ids = super().apply_chat_template(
            prompt,
            tokenize=tokenize,
            add_generation_prompt=add_generation_prompt,
            **kwargs,
        )
        return {"input_ids": input_ids, "attention_mask": [1] * len(input_ids)}


def _rows() -> list[dict[str, object]]:
    return [
        {
            "task_id": f"task-{index}",
            "prompt": [{"role": "user", "content": "x" * (index + 2)}],
            "metadata": {"base_task_id": f"logical-{index}"},
        }
        for index in range(2)
    ]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_render_preflight_requires_exact_rows_and_rejects_overflow() -> None:
    receipts = render_and_measure_rows(
        _rows(),
        tokenizer=FakeTokenizer(),
        maximum_prompt_tokens=4,
        expected_rows=2,
        chat_template_kwargs={"enable_thinking": True},
    )
    assert [receipt["prompt_token_count"] for receipt in receipts] == [3, 4]
    assert [receipt["task_id"] for receipt in receipts] == ["logical-0", "logical-1"]

    with pytest.raises(PromptPreflightError, match="row count mismatch"):
        render_and_measure_rows(
            _rows(),
            tokenizer=FakeTokenizer(),
            maximum_prompt_tokens=4,
            expected_rows=3,
            chat_template_kwargs={"enable_thinking": True},
        )
    with pytest.raises(PromptPreflightError, match="prompt overflow before inference"):
        render_and_measure_rows(
            _rows(),
            tokenizer=FakeTokenizer(),
            maximum_prompt_tokens=3,
            expected_rows=2,
            chat_template_kwargs={"enable_thinking": True},
        )


def test_render_preflight_accepts_batch_encoding_shape() -> None:
    receipts = render_and_measure_rows(
        _rows(),
        tokenizer=BatchEncodingTokenizer(),
        maximum_prompt_tokens=4,
        expected_rows=2,
        chat_template_kwargs={"enable_thinking": True},
    )
    assert [receipt["prompt_token_count"] for receipt in receipts] == [3, 4]


def test_tokenizer_assets_are_digest_revision_and_size_bound(tmp_path: Path) -> None:
    model = tmp_path / "model"
    model.mkdir()
    tokenizer = model / "tokenizer.json"
    tokenizer_config = model / "tokenizer_config.json"
    tokenizer.write_text('{"tokenizer":true}\n', encoding="utf-8")
    tokenizer_config.write_text('{"config":true}\n', encoding="utf-8")
    chat_template = tmp_path / "chat-template.jinja"
    chat_template.write_text("{{ messages }}\n", encoding="utf-8")
    manifest = tmp_path / "tokenizer-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "model_revision": "pinned-revision",
                "tokenizer": {
                    "sha256": _sha256(tokenizer),
                    "size_bytes": tokenizer.stat().st_size,
                },
                "tokenizer_config": {
                    "sha256": _sha256(tokenizer_config),
                    "size_bytes": tokenizer_config.stat().st_size,
                },
                "chat_template": {"sha256": _sha256(chat_template)},
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    result = verify_tokenizer_assets(
        model_path=model,
        tokenizer_manifest_path=manifest,
        expected_manifest_sha256=_sha256(manifest),
        chat_template_path=chat_template,
        expected_chat_template_sha256=_sha256(chat_template),
        expected_revision="pinned-revision",
    )
    assert result["assets"]["tokenizer"]["sha256"] == _sha256(tokenizer)

    with pytest.raises(PromptPreflightError, match="revision drift"):
        verify_tokenizer_assets(
            model_path=model,
            tokenizer_manifest_path=manifest,
            expected_manifest_sha256=_sha256(manifest),
            chat_template_path=chat_template,
            expected_chat_template_sha256=_sha256(chat_template),
            expected_revision="wrong-revision",
        )
