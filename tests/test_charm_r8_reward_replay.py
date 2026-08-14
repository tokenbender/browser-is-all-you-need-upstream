from __future__ import annotations

import pytest

from glm47_posttraining.aider_polyglot.charm_grpo import CharmGRPOProjectionError
from glm47_posttraining.aider_polyglot.charm_r8_reward_replay import (
    _canonical_sha256,
    _whole_file_response,
)


def test_replay_whole_file_response_preserves_exact_editable_order() -> None:
    response = _whole_file_response(
        {"api.cpp": "int answer() { return 42; }\n", "api.h": "#pragma once\n"},
        ["api.h", "api.cpp"],
    )

    assert response == (
        "api.h\n```cpp\n#pragma once\n```\napi.cpp\n```cpp\nint answer() { return 42; }\n```\n"
    )
    assert _canonical_sha256({"a": 1}) == _canonical_sha256({"a": 1})


def test_replay_refuses_reference_content_with_a_code_fence() -> None:
    with pytest.raises(CharmGRPOProjectionError, match="reference contains a code fence"):
        _whole_file_response({"api.cpp": "```\n"}, ["api.cpp"])
