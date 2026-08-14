"""Deterministic GRPO advantage contract and telemetry for CHARM runs."""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


POLICY_VERSION = "miles-standard-grpo-group-std-v1"
EPSILON = 1e-6


class GRPOAdvantageContractError(ValueError):
    """Raised when a reward group cannot safely reach the optimizer."""


def standard_group_advantages(rewards: Sequence[float], *, epsilon: float = EPSILON) -> list[float]:
    """Match Miles' per-prompt sample-std GRPO normalization in pure Python."""

    if len(rewards) < 2:
        raise GRPOAdvantageContractError("GRPO requires at least two rewards per group")
    values: list[float] = []
    for reward in rewards:
        if isinstance(reward, bool) or not isinstance(reward, (int, float)):
            raise GRPOAdvantageContractError("GRPO reward must be numeric")
        value = float(reward)
        if not math.isfinite(value):
            raise GRPOAdvantageContractError("GRPO reward must be finite")
        values.append(value)
    if not math.isfinite(epsilon) or epsilon <= 0:
        raise GRPOAdvantageContractError("GRPO epsilon must be finite and positive")

    mean = math.fsum(values) / len(values)
    centered = [value - mean for value in values]
    variance = math.fsum(value * value for value in centered) / (len(values) - 1)
    standard_deviation = math.sqrt(max(0.0, variance))
    advantages = [value / (standard_deviation + epsilon) for value in centered]
    if not all(math.isfinite(value) for value in advantages):
        raise GRPOAdvantageContractError("GRPO produced a non-finite advantage")
    return advantages


def summarize_group_advantages(rewards: Sequence[float]) -> dict[str, Any]:
    """Return receipt-safe statistics for one prompt-local reward group."""

    values = [float(value) for value in rewards]
    advantages = standard_group_advantages(values)
    reward_mean = math.fsum(values) / len(values)
    centered_rewards = [value - reward_mean for value in values]
    reward_variance = math.fsum(value * value for value in centered_rewards) / (len(values) - 1)
    advantage_mean = math.fsum(advantages) / len(advantages)
    centered_advantages = [value - advantage_mean for value in advantages]
    advantage_variance = math.fsum(value * value for value in centered_advantages) / (
        len(advantages) - 1
    )
    homogeneous = all(value == values[0] for value in values[1:])
    return {
        "policy_version": POLICY_VERSION,
        "sample_count": len(values),
        "reward_mean": reward_mean,
        "reward_std": math.sqrt(max(0.0, reward_variance)),
        "advantage_mean": advantage_mean,
        "advantage_variance": advantage_variance,
        "maximum_absolute_advantage": max(abs(value) for value in advantages),
        "mean_centered_sum": math.fsum(advantages),
        "homogeneous": homogeneous,
        "reward_policy_gradient_zero": homogeneous and all(value == 0.0 for value in advantages),
    }


def summarize_advantage_batch(groups: Sequence[Sequence[float]]) -> dict[str, Any]:
    """Aggregate prompt-local advantage telemetry without mixing group baselines."""

    summaries = [summarize_group_advantages(group) for group in groups]
    if not summaries:
        raise GRPOAdvantageContractError("GRPO batch must contain at least one group")
    return {
        "policy_version": POLICY_VERSION,
        "group_count": len(summaries),
        "homogeneous_group_count": sum(item["homogeneous"] for item in summaries),
        "maximum_absolute_advantage": max(item["maximum_absolute_advantage"] for item in summaries),
        "maximum_group_advantage_variance": max(item["advantage_variance"] for item in summaries),
        "non_finite_advantage_count": 0,
        "groups": summaries,
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _actual_miles_checks() -> dict[str, Any]:
    """Execute the exact installed Miles normalization and policy-loss kernels."""

    import torch
    from miles.backends.training_utils.loss_hub.math_utils import compute_policy_loss
    from miles.ray.rollout.train_data_conversion import _post_process_rewards

    class Sample:
        def __init__(self, score: float) -> None:
            self.reward = {"score": score}

        def get_reward_value(self, args: Any) -> float:
            return float(self.reward[args.reward_key])

    class Args:
        advantage_estimator = "grpo"
        rewards_normalization = True
        grpo_std_normalization = True
        n_samples_per_prompt = 8
        rollout_batch_size = 2
        reward_key = "score"

    groups = [
        [-1.0, -0.5, 0.0, 0.5, 1.0, -0.25, 0.25, 0.75],
        [99.0, 99.5, 100.0, 100.5, 101.0, 99.75, 100.25, 100.75],
    ]
    flat = [Sample(value) for group in groups for value in group]
    raw, actual = _post_process_rewards(Args(), flat, None)
    expected = [value for group in groups for value in standard_group_advantages(group)]
    if raw != [value for group in groups for value in group]:
        raise RuntimeError("Miles changed raw Hybrid45 rewards during GRPO processing")
    if len(actual) != len(expected) or any(
        not math.isclose(left, right, rel_tol=2e-5, abs_tol=2e-6)
        for left, right in zip(actual, expected, strict=True)
    ):
        raise RuntimeError("Miles GRPO normalization is not prompt-group-local")

    homogeneous = [Sample(0.25) for _ in range(16)]
    _raw, zero_advantages = _post_process_rewards(Args(), homogeneous, None)
    if any(value != 0.0 for value in zero_advantages):
        raise RuntimeError("homogeneous Miles reward groups did not produce zero advantages")

    tiny_values = [1.0 + index * 1e-10 for index in range(8)]
    tiny = [Sample(value) for value in tiny_values + tiny_values]
    _raw, tiny_advantages = _post_process_rewards(Args(), tiny, None)
    if not all(math.isfinite(value) for value in tiny_advantages):
        raise RuntimeError("low-variance Miles rewards produced non-finite advantages")

    log_ratio = torch.tensor([0.4, -0.3], dtype=torch.float64, requires_grad=True)
    zero = torch.zeros_like(log_ratio)
    policy_loss, _clip_fraction = compute_policy_loss(log_ratio, zero, 0.2, 0.28)
    policy_loss.sum().backward()
    if policy_loss.detach().abs().max().item() != 0.0:
        raise RuntimeError("zero advantages produced nonzero Miles policy loss")
    if log_ratio.grad is None or log_ratio.grad.abs().max().item() != 0.0:
        raise RuntimeError("zero advantages produced nonzero Miles policy gradient")

    return {
        "actual_group_local_normalization": True,
        "actual_homogeneous_policy_gradient_zero": True,
        "actual_low_variance_finite": True,
        "selected_policy": POLICY_VERSION,
    }


def run_pinned_miles_preflight(
    *,
    miles_root: str | Path,
    expected_commit: str,
    expected_files: Mapping[str, str],
) -> dict[str, Any]:
    """Bind exact Miles source bytes and execute its CPU-only GRPO kernels."""

    root = Path(miles_root).resolve()
    observed_commit = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    if observed_commit != expected_commit:
        raise RuntimeError(
            f"Miles source revision mismatch: {observed_commit} != {expected_commit}"
        )
    observed_files: dict[str, str] = {}
    for relative, expected_sha256 in sorted(expected_files.items()):
        path = root / relative
        observed = _sha256(path)
        if observed != expected_sha256:
            raise RuntimeError(
                f"Miles source drift for {relative}: {observed} != {expected_sha256}"
            )
        observed_files[relative] = observed
    checks = _actual_miles_checks()
    return {
        "schema_version": "glm47-miles-grpo-advantage-preflight-v1",
        "status": "PASS",
        "optimizer_updates": 0,
        "miles_commit": observed_commit,
        "source_files": observed_files,
        "checks": checks,
    }


def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--miles-root", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-file", action="append", default=[], metavar="RELATIVE=SHA256")
    parser.add_argument("--output")
    args = parser.parse_args()
    expected_files: dict[str, str] = {}
    for value in args.expected_file:
        relative, separator, digest = value.partition("=")
        if not separator or not relative or len(digest) != 64:
            raise SystemExit(f"invalid --expected-file binding: {value!r}")
        expected_files[relative] = digest
    payload = run_pinned_miles_preflight(
        miles_root=args.miles_root,
        expected_commit=args.expected_commit,
        expected_files=expected_files,
    )
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = Path(args.output).resolve()
        if output.exists() or output.is_symlink():
            raise FileExistsError(f"refusing to overwrite trainer receipt: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(rendered, encoding="utf-8")
        os.replace(temporary, output)
    print(rendered, end="")


if __name__ == "__main__":
    _main()
