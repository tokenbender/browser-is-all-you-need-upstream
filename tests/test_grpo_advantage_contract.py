from __future__ import annotations

import math

import pytest

from glm47_posttraining.aider_polyglot.grpo_advantage_contract import (
    GRPOAdvantageContractError,
    POLICY_VERSION,
    standard_group_advantages,
    summarize_advantage_batch,
    summarize_group_advantages,
)


def test_homogeneous_group_has_exactly_zero_reward_policy_gradient() -> None:
    advantages = standard_group_advantages([0.25] * 8)
    summary = summarize_group_advantages([0.25] * 8)

    assert advantages == [0.0] * 8
    assert summary["reward_policy_gradient_zero"] is True
    assert summary["maximum_absolute_advantage"] == 0.0


def test_low_variance_group_is_finite_and_mean_centered() -> None:
    rewards = [1.0 + index * 1e-10 for index in range(8)]
    advantages = standard_group_advantages(rewards)
    summary = summarize_group_advantages(rewards)

    assert all(math.isfinite(value) for value in advantages)
    assert math.isclose(math.fsum(advantages), 0.0, abs_tol=1e-9)
    assert summary["advantage_variance"] >= 0.0


def test_normalization_is_group_local_and_never_uses_cross_task_baseline() -> None:
    first = [-1.0, -0.5, 0.0, 0.5, 1.0, -0.25, 0.25, 0.75]
    shifted = [value + 100.0 for value in first]

    assert standard_group_advantages(first) == pytest.approx(
        standard_group_advantages(shifted), abs=1e-12
    )


def test_batch_receipt_exposes_required_advantage_telemetry() -> None:
    receipt = summarize_advantage_batch([[0.0] * 8, [0.0, 1.0] * 4])

    assert receipt["policy_version"] == POLICY_VERSION
    assert receipt["group_count"] == 2
    assert receipt["homogeneous_group_count"] == 1
    assert receipt["non_finite_advantage_count"] == 0
    assert receipt["maximum_absolute_advantage"] > 0.0
    assert receipt["maximum_group_advantage_variance"] > 0.0


@pytest.mark.parametrize("rewards", [[0.0], [0.0, math.nan], [0.0, math.inf]])
def test_invalid_group_is_rejected_before_optimizer(rewards: list[float]) -> None:
    with pytest.raises(GRPOAdvantageContractError):
        standard_group_advantages(rewards)
