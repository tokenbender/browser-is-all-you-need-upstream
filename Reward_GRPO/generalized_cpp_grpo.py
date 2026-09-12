"""Miles/GRPO adapter for the generalized C++ verifier pack.

This is the deliberately small vertical integration layer: it binds a rollout
to an authenticated task registry entry, reconstructs the candidate from an
Aider whole-file response, invokes the direct aggregate verifier, and projects
the bound receipt into a Miles reward record.  Production container execution
is a separate hardening step; this adapter currently runs the direct verifier
inside the already-isolated reward worker used by tests and preflight.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Any, Mapping, Sequence

from glm47_posttraining.aider_polyglot.dataset import (
    DATASET_KIND,
    SOURCE_MANIFEST_KIND,
    build_aider_polyglot_datasets,
)
from glm47_posttraining.aider_polyglot.parser import (
    AiderResponseError,
    parse_whole_file_response,
)
from glm47_posttraining.aider_polyglot.schema import AiderShadowRubric
from glm47_posttraining.integrations.miles_aider_polyglot import (
    neutralize_infrastructure_scores,
    run_response_contract_preflight,
)

from Reward_GRPO import global_cpp_verifier_runner


REWARD_ROOT = Path(__file__).resolve().parent
DEFAULT_REGISTRY = REWARD_ROOT / "generalized_cpp_grpo_registry.json"
DEFAULT_MUTATION_CONTROLS = REWARD_ROOT / "generalized_cpp_grpo_mutations.json"
DEFAULT_MIDBAND_ADMISSION = REWARD_ROOT / "generalized_cpp_midband_admission.json"
REGISTRY_ENV = "GENERALIZED_CPP_VERIFIER_REGISTRY"
PROFILE_ENV = "GENERALIZED_CPP_VERIFIER_PROFILE"
WORKERS_ENV = "GENERALIZED_CPP_REWARD_WORKERS"
DEFAULT_WORKERS = 4
CURRICULUM_NAME = "generalized-cpp-v2"
POLYGLOT_COMMIT = "7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f"
VERIFICATION_GATE = "generalized-cpp-global-verifier-gcc13-v2"
GENERATION_TOKEN_CAP = 8192
INTEGRITY_ENGINE = "05_response_integrity_verifier.py"
ENGINE_DIR_ENV = "GENERALIZED_VERIFIER_ENGINE_DIR"


class BindingError(ValueError):
    """The rollout cannot be bound to trustworthy verifier inputs."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_relative(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise BindingError("invalid_registry", f"{label} must be a relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise BindingError("invalid_registry", f"{label} is unsafe")
    return value


def _regular_file(root: Path, relative: str, label: str) -> Path:
    path = root.joinpath(*PurePosixPath(relative).parts)
    if path.is_symlink() or not path.is_file():
        raise BindingError("invalid_registry", f"{label} is missing or unsafe")
    resolved = path.resolve()
    if resolved == root or root not in resolved.parents:
        raise BindingError("invalid_registry", f"{label} escapes the registry root")
    return resolved


def _regular_directory(root: Path, relative: str, label: str) -> Path:
    path = root.joinpath(*PurePosixPath(relative).parts)
    if path.is_symlink() or not path.is_dir():
        raise BindingError("invalid_registry", f"{label} is missing or unsafe")
    resolved = path.resolve()
    if resolved == root or root not in resolved.parents:
        raise BindingError("invalid_registry", f"{label} escapes the registry root")
    return resolved


@dataclass(frozen=True)
class TaskBinding:
    task_id: str
    manifest_path: Path
    manifest_sha256: str
    fixture_dir: Path
    starter_dir: Path
    manifest: dict[str, Any]
    preflight_response: str | None = None


class TaskRegistry:
    """Resolve task IDs to immutable manifests, fixtures, and starter files."""

    def __init__(self, path: Path) -> None:
        if path.is_symlink() or not path.is_file():
            raise BindingError("invalid_registry", f"registry is unavailable: {path}")
        self.path = path.resolve()
        self.root = self.path.parent
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise BindingError("invalid_registry", str(error)) from error
        if payload.get("schema_version") != 1 or not isinstance(payload.get("tasks"), dict):
            raise BindingError("invalid_registry", "unsupported registry schema")
        self.payload = payload
        self.dataset = payload.get("dataset", {})
        if not isinstance(self.dataset, dict):
            raise BindingError("invalid_registry", "dataset metadata must be an object")
        self.entries: dict[str, Any] = payload["tasks"]

    def task_ids(self) -> list[str]:
        return sorted(self.entries)

    def resolve(self, task_id: str) -> TaskBinding:
        entry = self.entries.get(task_id)
        if not isinstance(entry, dict):
            raise BindingError("unknown_task", task_id)
        manifest_name = _safe_relative(entry.get("manifest"), f"{task_id}.manifest")
        fixture_name = _safe_relative(entry.get("fixture_dir"), f"{task_id}.fixture_dir")
        starter_name = _safe_relative(
            entry.get("starter_dir", fixture_name), f"{task_id}.starter_dir"
        )
        manifest_path = _regular_file(self.root, manifest_name, "manifest")
        fixture_dir = _regular_directory(self.root, fixture_name, "fixture directory")
        starter_dir = _regular_directory(self.root, starter_name, "starter directory")
        expected = entry.get("manifest_sha256")
        if not isinstance(expected, str) or len(expected) != 64:
            raise BindingError("invalid_registry", "manifest_sha256 is malformed")
        observed = _sha256(manifest_path)
        if observed != expected:
            raise BindingError("manifest_hash_mismatch", task_id)
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise BindingError("invalid_manifest", str(error)) from error
        if manifest.get("task_id") != task_id:
            raise BindingError("task_identity_mismatch", task_id)
        candidate_files = manifest.get("candidate_files")
        if not isinstance(candidate_files, list) or not candidate_files:
            raise BindingError("invalid_manifest", "candidate_files is empty")
        for index, name in enumerate(candidate_files):
            relative = _safe_relative(name, f"candidate_files[{index}]")
            _regular_file(starter_dir, relative, f"starter file {relative}")
        protected = manifest.get("protected_files", {})
        if not isinstance(protected, dict):
            raise BindingError("invalid_manifest", "protected_files is not an object")
        for name, digest in protected.items():
            relative = _safe_relative(name, "protected file")
            path = _regular_file(fixture_dir, relative, f"protected file {relative}")
            if not isinstance(digest, str) or _sha256(path) != digest:
                raise BindingError("protected_file_mismatch", relative)
        preflight_response = entry.get("preflight_response")
        if preflight_response is not None and not isinstance(preflight_response, str):
            raise BindingError("invalid_registry", "preflight_response must be text")
        return TaskBinding(
            task_id,
            manifest_path,
            observed,
            fixture_dir,
            starter_dir,
            manifest,
            preflight_response,
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


def _task_id(metadata: Mapping[str, Any]) -> str:
    value = metadata.get("problem_id") or metadata.get("generalized_verifier_task_id")
    if not isinstance(value, str) or not value:
        raise BindingError("missing_task_id", "metadata.problem_id is required")
    return value


def _registry() -> TaskRegistry:
    return TaskRegistry(Path(os.environ.get(REGISTRY_ENV, DEFAULT_REGISTRY)))


def _profile() -> str:
    value = os.environ.get(PROFILE_ENV, "live").strip().lower()
    if value not in {"live", "full"}:
        raise BindingError("invalid_profile", value)
    return value


def _workers() -> int:
    try:
        return max(1, int(os.environ.get(WORKERS_ENV, DEFAULT_WORKERS)))
    except ValueError:
        return DEFAULT_WORKERS


def _reconstruct(binding: TaskBinding, response: str, destination: Path) -> bool:
    editable = list(binding.manifest["candidate_files"])
    parsed = parse_whole_file_response(
        response, editable, recover_boundary_errors=True
    )
    destination.mkdir(parents=True)
    for relative in editable:
        source = binding.starter_dir.joinpath(*PurePosixPath(relative).parts)
        target = destination.joinpath(*PurePosixPath(relative).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for relative, contents in parsed.files.items():
        target = destination.joinpath(*PurePosixPath(relative).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf-8")
    return parsed.format_valid


def _evaluation_manifest(binding: TaskBinding, response: str, output: Path) -> tuple[Path, str]:
    payload = dict(binding.manifest)
    payload["fixture_dir"] = str(binding.fixture_dir)
    payload["response_text"] = response
    payload.pop("response_file", None)
    payload.pop("trajectory", None)
    data = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    output.write_bytes(data)
    return output, hashlib.sha256(data).hexdigest()


MODEL_REWARD_KERNEL_WEIGHTS = {
    "G01-1": 0.10,   # candidate API shape
    "G02-1": 0.20,   # candidate translation unit compiles
    "G02-2": 0.20,   # candidate links against the official test
    "G03-2": 0.45,   # candidate passes the differential semantic test
    "G04-1": 0.025,  # response integrity (shaping only)
    "G05-1": 0.025,  # editable-file boundary (shaping only)
}


def _model_kernel_values(receipt: Mapping[str, Any]) -> dict[str, int]:
    """Return only candidate-owned kernels that are eligible for model reward.

    In particular, G03-1 is the trusted reference-control run. Its result
    authenticates the fixture but says nothing about the candidate and must
    never contribute reward.
    """

    values: dict[str, int] = {}
    results = receipt.get("policy_results", [])
    if not isinstance(results, list):
        return values
    for policy in results:
        if not isinstance(policy, Mapping):
            continue
        kernels = policy.get("kernels", [])
        if not isinstance(kernels, list):
            continue
        for kernel in kernels:
            if not isinstance(kernel, Mapping):
                continue
            kernel_id = kernel.get("kernel_id")
            value = kernel.get("kernel")
            if (
                isinstance(kernel_id, str)
                and kernel_id in MODEL_REWARD_KERNEL_WEIGHTS
                and isinstance(value, int)
                and not isinstance(value, bool)
                and value in {-1, 1}
            ):
                values[str(kernel_id)] = value
    return values


def _candidate_semantic_fraction(receipt: Mapping[str, Any]) -> float | None:
    """Return a validated G03 candidate assertion fraction, when available.

    The binary verifier-kernel contract remains unchanged. Fractional shaping
    is projected only here, from the authenticated G03-2 facts, and only for a
    candidate that actually ran against a healthy reference control. Counts
    are treated as the source of truth; the engine's rounded score must agree
    with them so malformed receipt facts cannot create reward.
    """

    results = receipt.get("policy_results", [])
    if not isinstance(results, list):
        return None
    for policy in results:
        if not isinstance(policy, Mapping) or policy.get("policy_id") != "G03":
            continue
        kernels = policy.get("kernels", [])
        if not isinstance(kernels, list):
            return None
        for kernel in kernels:
            if not isinstance(kernel, Mapping) or kernel.get("kernel_id") != "G03-2":
                continue
            # Full passes are handled by the receipt-level +1 branch. This
            # helper supplies shaping only for a genuine semantic failure.
            if kernel.get("status") != "fail" or kernel.get("kernel") != -1:
                return None
            facts = kernel.get("facts")
            if not isinstance(facts, Mapping):
                return None
            reference = facts.get("reference")
            candidate = facts.get("candidate")
            if (
                not isinstance(reference, Mapping)
                or reference.get("status") != "OK"
                or not isinstance(candidate, Mapping)
                or candidate.get("status") != "RAN"
            ):
                return None
            run = candidate.get("run")
            if not isinstance(run, Mapping) or run.get("crashed") is True:
                return None
            passed = run.get("passed_assertions")
            total = run.get("total_assertions")
            reported = run.get("score")
            if (
                not isinstance(passed, int)
                or isinstance(passed, bool)
                or not isinstance(total, int)
                or isinstance(total, bool)
                or total <= 0
                or passed < 0
                or passed >= total
                or not isinstance(reported, (int, float))
                or isinstance(reported, bool)
                or not math.isfinite(float(reported))
            ):
                return None
            fraction = passed / total
            # The engine serializes its score rounded to four decimals.
            if not math.isclose(float(reported), fraction, abs_tol=5e-5):
                return None
            return fraction
        return None
    return None


def receipt_to_reward(
    receipt: Mapping[str, Any], *, format_valid: bool = True
) -> tuple[float, bool, str]:
    """Return (score, infrastructure_error, reason) from an aggregate receipt."""

    status = str(receipt.get("status") or "invalid").lower()
    if status == "invalid":
        return 0.0, True, "verifier_invalid"
    if status == "pass":
        score = 1.0 if format_valid else 1.0 - MODEL_REWARD_KERNEL_WEIGHTS["G04-1"]
        return score, False, status

    # Failed and not-run candidate gates receive no credit. This keeps every
    # model-caused overall failure non-positive while retaining ordered shaping
    # between API, build/link, and semantic progress. Correctness owns 85% of
    # the available failure credit; format and boundary checks own only 5%.
    values = _model_kernel_values(receipt)
    earned_credit = sum(
        weight
        for kernel_id, weight in MODEL_REWARD_KERNEL_WEIGHTS.items()
        if values.get(kernel_id) == 1
    )
    semantic_fraction = _candidate_semantic_fraction(receipt)
    if semantic_fraction is not None and values.get("G03-2") == -1:
        earned_credit += MODEL_REWARD_KERNEL_WEIGHTS["G03-2"] * semantic_fraction
    if not format_valid:
        earned_credit -= MODEL_REWARD_KERNEL_WEIGHTS["G04-1"]
    score = -1.0 + earned_credit
    return max(-1.0, min(0.0, score)), False, status


def _base_record(sample: Any, task_id: str | None) -> dict[str, Any]:
    metadata = _sample_metadata(sample)
    return {
        "task_id": metadata.get("task_id") or task_id,
        "problem_id": task_id,
        "split": metadata.get("split"),
        "sample_index": _sample_value(sample, "index"),
        "rollout_id": _sample_value(sample, "rollout_id"),
        "response": _sample_response(sample),
    }


def _integrity_engine_path() -> Path | None:
    candidates = []
    override = os.environ.get(ENGINE_DIR_ENV)
    if override:
        candidates.append(Path(override))
    candidates.append(REWARD_ROOT.parent / "generalized_verifier_docs")
    for directory in candidates:
        path = directory / INTEGRITY_ENGINE
        if path.is_file():
            return path
    return None


def _response_integrity(response: str, gen_tokens: Any) -> dict[str, Any] | None:
    """Run the G04 engine on a parser-rejected response; None on any failure.

    The parser pre-absorbs truncated/format-bad rows before the verifier runs,
    so G04's TRUNCATED/EMPTY/LOOP classes would otherwise never fire in
    training.  Any engine/IO problem falls back to the flat penalty silently.
    """
    engine = _integrity_engine_path()
    if engine is None:
        return None
    if not response.strip():
        # A missing or empty generation is EMPTY by definition; only an
        # absent engine still falls back to the flat penalty silently.
        return {"verdict": "EMPTY", "details": {"reason": "empty_response"}}
    gen = gen_tokens if isinstance(gen_tokens, int) and not isinstance(gen_tokens, bool) else None
    temporary_path: Path | None = None
    try:
        with TemporaryDirectory(prefix="generalized-cpp-g04-") as temporary:
            temporary_path = Path(temporary) / "response.txt"
            temporary_path.write_text(response, encoding="utf-8")
            command = [sys.executable, str(engine), "--response", str(temporary_path), "--json"]
            if gen is not None:
                command += ["--gen-tokens", str(gen), "--max-tokens", str(GENERATION_TOKEN_CAP)]
            completed = subprocess.run(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, timeout=60,
            )
            report = json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None
    return report if isinstance(report, dict) and "verdict" in report else None


def _model_failure(sample: Any, task_id: str | None, reason: str, error: str) -> dict[str, Any]:
    score = -1.0 if reason in {"forbidden_file", "duplicate_file"} else -0.8
    record = {
        **_base_record(sample, task_id),
        "score": score,
        "reward": score,
        "reason": reason,
        "format_valid": False,
        "infrastructure_error": False,
        "exception": error,
        "policy_results": [],
        "kernel_results": [],
    }
    if reason not in {"forbidden_file", "duplicate_file"}:
        report = _response_integrity(
            _sample_response(sample), _sample_value(sample, "response_length")
        )
        if report is not None:
            verdict = report.get("verdict")
            record["integrity_verdict"] = verdict
            record["integrity_facts"] = report.get("details", {})
            if verdict in {"LOOP", "EMPTY"}:
                record["score"] = record["reward"] = -1.0
    return record


def _infrastructure_failure(
    sample: Any, task_id: str | None, reason: str, error: str
) -> dict[str, Any]:
    return {
        **_base_record(sample, task_id),
        "score": 0.0,
        "reward": 0.0,
        "reason": reason,
        "format_valid": False,
        "infrastructure_error": True,
        "exception": error,
        "policy_results": [],
        "kernel_results": [],
    }


def score_sample(sample: Any, registry: TaskRegistry | None = None) -> dict[str, Any]:
    metadata = _sample_metadata(sample)
    task_id: str | None = None
    try:
        task_id = _task_id(metadata)
        binding = (registry or _registry()).resolve(task_id)
        declared_digest = metadata.get("generalized_verifier_manifest_sha256")
        if declared_digest is not None and declared_digest != binding.manifest_sha256:
            raise BindingError("metadata_binding_mismatch", "manifest digest disagrees")
        response = _sample_response(sample)
        with TemporaryDirectory(prefix="generalized-cpp-grpo-") as temporary:
            root = Path(temporary)
            candidate = root / "candidate"
            format_valid = _reconstruct(binding, response, candidate)
            manifest_path, manifest_digest = _evaluation_manifest(
                binding, response, root / "evaluation-manifest.json"
            )
            output = root / "receipt"
            arguments = argparse.Namespace(
                candidate_dir=candidate,
                manifest=manifest_path,
                expected_manifest_sha256=manifest_digest,
                output_dir=output,
                reward_root=REWARD_ROOT,
                profile=_profile(),
            )
            return_code = global_cpp_verifier_runner.run(arguments)
            receipt_path = output / global_cpp_verifier_runner.AGGREGATE_RECEIPT
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        score, infrastructure_error, reason = receipt_to_reward(
            receipt, format_valid=format_valid
        )
        if return_code not in {0, 1, 2}:
            raise BindingError("runner_protocol_error", f"unexpected return code {return_code}")
        if (return_code == 2) != infrastructure_error:
            raise BindingError("runner_protocol_error", "receipt and return code disagree")
        policy_results = receipt.get("policy_results", [])
        kernel_results = [
            kernel
            for policy in policy_results
            if isinstance(policy, Mapping)
            for kernel in policy.get("kernels", [])
            if isinstance(kernel, Mapping)
        ]
        return {
            **_base_record(sample, task_id),
            "score": score,
            "reward": score,
            "reason": reason,
            "format_valid": format_valid,
            "infrastructure_error": infrastructure_error,
            "manifest_sha256": binding.manifest_sha256,
            "evaluation_manifest_sha256": receipt.get("manifest_sha256"),
            "candidate_source_sha256": receipt.get("candidate_source_sha256_before"),
            "candidate_source_unchanged": receipt.get("candidate_source_unchanged"),
            "profile": receipt.get("profile"),
            "policy_results": policy_results,
            "kernel_results": kernel_results,
            "candidate_semantic_fraction": _candidate_semantic_fraction(receipt),
            "verifier_receipt": receipt,
        }
    except AiderResponseError as error:
        return _model_failure(sample, task_id, error.reason, str(error))
    except BindingError as error:
        return _infrastructure_failure(sample, task_id, error.reason, str(error))
    except Exception as error:  # reward workers must return records, not crash the batch
        return _infrastructure_failure(
            sample, task_id, "generalized_verifier_exception", f"{type(error).__name__}: {error}"
        )


async def reward_func(
    _args: Any, sample: Any, **_kwargs: Any
) -> dict[str, Any] | list[dict[str, Any]]:
    """Miles custom-RM entry point with bounded batch concurrency."""

    registry = _registry()
    if isinstance(sample, list):
        semaphore = asyncio.Semaphore(max(1, min(len(sample), _workers())))

        async def score(item: Any) -> dict[str, Any]:
            async with semaphore:
                return await asyncio.to_thread(score_sample, item, registry)

        records = list(await asyncio.gather(*(score(item) for item in sample)))
        return neutralize_infrastructure_scores(records)
    return await asyncio.to_thread(score_sample, sample, registry)


def _curriculum_task_ids(registry: TaskRegistry) -> list[str]:
    """Registry tasks selected for training; canaries opt out with train=false."""

    return [
        task_id
        for task_id in registry.task_ids()
        if registry.entries[task_id].get("train", True)
    ]


def _validation_task_ids(registry: TaskRegistry) -> list[str]:
    """Registry tasks reserved for checkpoint selection, never training."""

    return [
        task_id
        for task_id in registry.task_ids()
        if registry.entries[task_id].get("validation") is True
        and registry.entries[task_id].get("train", True) is False
    ]


def _admitted_midband_task_ids(registry: TaskRegistry) -> list[str]:
    admission_id = registry.dataset.get("midband_admission")
    return [
        task_id
        for task_id in registry.task_ids()
        if registry.entries[task_id].get("admission_evidence") == admission_id
    ]


def validate_midband_admission(registry: TaskRegistry) -> None:
    """Recompute admitted task difficulty from hash-bound warm-start receipts."""

    try:
        admission = json.loads(
            DEFAULT_MIDBAND_ADMISSION.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise BindingError("invalid_midband_admission", str(error)) from error
    admission_id = registry.dataset.get("midband_admission")
    source = admission.get("source_checkpoint")
    criterion = admission.get("criterion")
    receipt_files = admission.get("receipt_files")
    advertised = admission.get("admitted_tasks")
    if (
        admission.get("schema_version") != 1
        or admission.get("admission_id") != admission_id
        or not isinstance(source, Mapping)
        or not isinstance(criterion, Mapping)
        or not isinstance(receipt_files, Mapping)
        or not receipt_files
        or not isinstance(advertised, Mapping)
    ):
        raise BindingError(
            "invalid_midband_admission", "admission document is malformed"
        )
    admitted = set(_admitted_midband_task_ids(registry))
    if admitted != set(advertised):
        raise BindingError(
            "invalid_midband_admission",
            "registry and admission document select different tasks",
        )
    if admitted & set(_validation_task_ids(registry)):
        raise BindingError(
            "invalid_midband_admission", "admitted task leaks into validation"
        )
    if not admitted <= set(_curriculum_task_ids(registry)):
        raise BindingError(
            "invalid_midband_admission", "admitted task is not enabled for training"
        )

    required_trials = criterion.get("required_trials")
    minimum = criterion.get("minimum_passes")
    maximum = criterion.get("maximum_passes")
    if (required_trials, minimum, maximum) != (4, 1, 3):
        raise BindingError(
            "invalid_midband_admission", "unsupported midband criterion"
        )
    observed = {
        task_id: {"pass_at_1": 0, "pass_with_mef": 0, "trials": 0}
        for task_id in admitted
    }
    repo_root = REWARD_ROOT.parent
    for relative, expected_sha256 in receipt_files.items():
        safe_relative = _safe_relative(relative, "midband receipt")
        path = _regular_file(repo_root, safe_relative, "midband receipt")
        if not isinstance(expected_sha256, str) or _sha256(path) != expected_sha256:
            raise BindingError(
                "invalid_midband_admission", f"receipt hash mismatch: {relative}"
            )
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise BindingError("invalid_midband_admission", str(error)) from error
        if (
            receipt.get("source_checkpoint") != "iter_0000014"
            or receipt.get("source_run_id") != source.get("run_id")
            or receipt.get("polyglot_commit") != source.get("polyglot_commit")
        ):
            raise BindingError(
                "invalid_midband_admission", f"receipt binding mismatch: {relative}"
            )
        validation = receipt.get("validation")
        outcomes = validation.get("outcomes") if isinstance(validation, Mapping) else None
        if not isinstance(outcomes, Mapping):
            raise BindingError(
                "invalid_midband_admission", f"receipt has no outcomes: {relative}"
            )
        for task_id in admitted & set(outcomes):
            attempts = outcomes[task_id]
            if (
                not isinstance(attempts, list)
                or not attempts
                or any(type(value) is not bool for value in attempts)
            ):
                raise BindingError(
                    "invalid_midband_admission",
                    f"malformed outcomes for {task_id}: {relative}",
                )
            observed[task_id]["trials"] += 1
            observed[task_id]["pass_at_1"] += int(attempts[0])
            observed[task_id]["pass_with_mef"] += int(any(attempts))

    for task_id, counts in observed.items():
        if counts != advertised.get(task_id):
            raise BindingError(
                "invalid_midband_admission",
                f"advertised and observed outcomes differ for {task_id}",
            )
        if (
            counts["trials"] != required_trials
            or not minimum <= counts["pass_at_1"] <= maximum
        ):
            raise BindingError(
                "invalid_midband_admission", f"{task_id} is outside the midband"
            )


def _fixture_test(fixture: Path, task_id: str) -> Path:
    tests = sorted(path for path in fixture.glob("*_test.cpp") if path.is_file())
    if len(tests) != 1:
        raise BindingError("invalid_fixture", f"{task_id} must have exactly one *_test.cpp")
    return tests[0]


def _render_whole_file_response(
    files: Mapping[str, str], *, decorate_labels: bool = False
) -> str:
    listings = []
    for name, contents in files.items():
        label = f"**{name}**" if decorate_labels else name
        listings.append(f"{label}\n```cpp\n{contents.rstrip()}\n```")
    return "\n\n".join(listings) + "\n"


def _mutation_control_samples(registry: TaskRegistry) -> list[dict[str, Any]]:
    """Build deterministic positive and negative controls for every train task."""

    if (
        DEFAULT_MUTATION_CONTROLS.is_symlink()
        or not DEFAULT_MUTATION_CONTROLS.is_file()
    ):
        raise BindingError("invalid_mutation_controls", "mutation control file is missing")
    try:
        controls = json.loads(DEFAULT_MUTATION_CONTROLS.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise BindingError("invalid_mutation_controls", str(error)) from error
    entries = controls.get("tasks") if controls.get("schema_version") == 1 else None
    task_ids = _curriculum_task_ids(registry)
    if not isinstance(entries, dict) or set(entries) != set(task_ids):
        raise BindingError(
            "invalid_mutation_controls",
            "mutation controls must cover every training task exactly once",
        )

    samples: list[dict[str, Any]] = []
    for task_id in task_ids:
        binding = registry.resolve(task_id)
        if binding.preflight_response is None:
            raise BindingError(
                "invalid_mutation_controls", f"{task_id} has no positive control"
            )
        parsed = parse_whole_file_response(
            binding.preflight_response, binding.manifest["candidate_files"]
        )
        if not parsed.format_valid or set(parsed.files) != set(
            binding.manifest["candidate_files"]
        ):
            raise BindingError(
                "invalid_mutation_controls",
                f"{task_id} positive control is not an exact whole-file response",
            )
        oracle_files = dict(parsed.files)
        headers = [name for name in oracle_files if name.endswith((".h", ".hpp"))]
        sources = [name for name in oracle_files if name.endswith((".cpp", ".cc"))]
        if len(headers) != 1 or len(sources) != 1:
            raise BindingError(
                "invalid_mutation_controls",
                f"{task_id} controls require exactly one header and one source",
            )
        header, source = headers[0], sources[0]

        case_responses: dict[str, str] = {}
        alternate = dict(oracle_files)
        alternate[source] = (
            "// non-reference positive mutation control\n" + alternate[source]
        )
        case_responses["alternate_correct"] = _render_whole_file_response(alternate)

        api_failure = dict(oracle_files)
        namespace_match = re.search(
            r"\bnamespace\s+([A-Za-z_]\w*)", api_failure[header]
        )
        if namespace_match is None:
            raise BindingError(
                "invalid_mutation_controls",
                f"{task_id} API control could not find the header namespace",
            )
        namespace = namespace_match.group(1)
        namespace_pattern = rf"\bnamespace\s+{re.escape(namespace)}\b"
        substitutions = 0
        for name, contents in api_failure.items():
            api_failure[name], count = re.subn(
                namespace_pattern,
                "namespace generalized_mutation_control",
                contents,
            )
            substitutions += count
        if substitutions < 2:
            raise BindingError(
                "invalid_mutation_controls",
                f"{task_id} API control did not remove the task namespace",
            )
        case_responses["api_failure"] = _render_whole_file_response(api_failure)

        compile_failure = dict(oracle_files)
        compile_failure[source] = (
            "#error generalized verifier compile mutation control\n"
            + compile_failure[source]
        )
        case_responses["compile_failure"] = _render_whole_file_response(
            compile_failure
        )

        task_control = entries[task_id]
        semantic = task_control.get("semantic") if isinstance(task_control, dict) else None
        if not isinstance(semantic, dict):
            raise BindingError(
                "invalid_mutation_controls", f"{task_id} semantic control is missing"
            )
        semantic_file = semantic.get("file")
        find = semantic.get("find")
        replace = semantic.get("replace")
        if (
            semantic_file not in oracle_files
            or not isinstance(find, str)
            or not find
            or not isinstance(replace, str)
            or oracle_files[semantic_file].count(find) != 1
        ):
            raise BindingError(
                "invalid_mutation_controls",
                f"{task_id} semantic control must make one pinned replacement",
            )
        semantic_failure = dict(oracle_files)
        semantic_failure[semantic_file] = semantic_failure[semantic_file].replace(
            find, replace, 1
        )
        case_responses["semantic_failure"] = _render_whole_file_response(
            semantic_failure
        )

        case_responses["recoverable_format"] = _render_whole_file_response(
            oracle_files, decorate_labels=True
        )
        case_responses["boundary_failure"] = (
            "CMakeLists.txt\n```cmake\nproject(do_not_apply)\n```\n\n"
            + _render_whole_file_response(oracle_files)
        )

        for case, response in case_responses.items():
            samples.append(
                {
                    "metadata": {
                        "task_id": f"mutation-control/{task_id}/{case}",
                        "problem_id": task_id,
                        "split": "mutation-control",
                        "mutation_case": case,
                        "generalized_verifier_manifest_sha256": binding.manifest_sha256,
                    },
                    "response": response,
                    "rollout_id": f"mutation-control-{task_id}-{case}",
                }
            )
    return samples


def _policy_statuses(record: Mapping[str, Any]) -> dict[str, str]:
    return {
        str(policy.get("policy_id")): str(policy.get("status"))
        for policy in record.get("policy_results", [])
        if isinstance(policy, Mapping)
    }


def _validate_mutation_record(sample: Mapping[str, Any], record: Mapping[str, Any]) -> None:
    task_id = str(sample["metadata"]["problem_id"])
    case = str(sample["metadata"]["mutation_case"])
    if record.get("infrastructure_error"):
        raise RuntimeError(f"{task_id}/{case} produced an infrastructure error")
    score = record.get("score")
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        raise RuntimeError(f"{task_id}/{case} produced no numeric score")
    statuses = _policy_statuses(record)

    valid = False
    if case == "alternate_correct":
        valid = (
            score == 1.0
            and record.get("reason") == "pass"
            and record.get("format_valid") is True
            and all(statuses.get(policy) == "pass" for policy in ("G01", "G02", "G03", "G04", "G05"))
        )
    elif case == "api_failure":
        valid = score == -1.0 and statuses.get("G01") == "fail"
    elif case == "compile_failure":
        candidate_kernel = next(
            (
                kernel
                for kernel in record.get("kernel_results", [])
                if kernel.get("kernel_id") == "G03-2"
            ),
            {},
        )
        valid = (
            score == -0.85
            and statuses.get("G01") == "pass"
            and statuses.get("G02") == "fail"
            and candidate_kernel.get("status") == "not_run"
        )
    elif case == "semantic_failure":
        fraction = record.get("candidate_semantic_fraction")
        valid = (
            -0.45 <= score < 0.0
            and isinstance(fraction, float)
            and 0.0 < fraction < 1.0
            and statuses.get("G01") == "pass"
            and statuses.get("G02") == "pass"
            and statuses.get("G03") == "fail"
        )
    elif case == "recoverable_format":
        valid = (
            score == 0.975
            and record.get("reason") == "pass"
            and record.get("format_valid") is False
            and statuses.get("G03") == "pass"
            and statuses.get("G05") == "pass"
        )
    elif case == "boundary_failure":
        valid = (
            -0.1 < score <= 0.0
            and record.get("format_valid") is False
            and statuses.get("G03") == "pass"
            and statuses.get("G05") == "fail"
        )
    if not valid:
        raise RuntimeError(
            f"mutation control failed: {task_id}/{case}: "
            f"score={score}, statuses={statuses}, "
            f"fraction={record.get('candidate_semantic_fraction')}"
        )


def run_mutation_preflight(registry: TaskRegistry) -> None:
    samples = _mutation_control_samples(registry)
    records = asyncio.run(reward_func(None, samples))
    if not isinstance(records, list) or len(records) != len(samples):
        raise RuntimeError("mutation preflight returned an incomplete result set")
    for sample, record in zip(samples, records):
        _validate_mutation_record(sample, record)
    print(f"GENERALIZED_CPP_MUTATION_CONTROLS_READY tasks={len(_curriculum_task_ids(registry))} cases={len(samples)}")


def _heldout_negative_samples(registry: TaskRegistry) -> list[dict[str, Any]]:
    """Render each validation starter as a deterministic negative control."""

    samples: list[dict[str, Any]] = []
    for task_id in _validation_task_ids(registry):
        binding = registry.resolve(task_id)
        files = {
            relative: binding.starter_dir.joinpath(
                *PurePosixPath(relative).parts
            ).read_text(encoding="utf-8")
            for relative in binding.manifest["candidate_files"]
        }
        samples.append(
            {
                "metadata": {
                    "task_id": f"heldout-control/{task_id}/starter",
                    "problem_id": task_id,
                    "split": "heldout-control",
                    "generalized_verifier_manifest_sha256": (
                        binding.manifest_sha256
                    ),
                },
                "response": _render_whole_file_response(files),
                "rollout_id": f"heldout-control-{task_id}-starter",
            }
        )
    return samples


def _validate_heldout_negative_record(
    sample: Mapping[str, Any], record: Mapping[str, Any]
) -> None:
    task_id = str(sample["metadata"]["problem_id"])
    statuses = _policy_statuses(record)
    fraction = record.get("candidate_semantic_fraction")
    score = record.get("score")
    valid = (
        record.get("infrastructure_error") is False
        and record.get("format_valid") is True
        and isinstance(score, (int, float))
        and not isinstance(score, bool)
        and -0.45 < float(score) < 0.0
        and isinstance(fraction, float)
        and 0.0 < fraction < 1.0
        and statuses.get("G01") == "pass"
        and statuses.get("G02") == "pass"
        and statuses.get("G03") == "fail"
    )
    if not valid:
        raise RuntimeError(
            f"held-out starter control failed: {task_id}: score={score}, "
            f"statuses={statuses}, fraction={fraction}, "
            f"infrastructure_error={record.get('infrastructure_error')}"
        )


def run_heldout_monitor_preflight(registry: TaskRegistry) -> None:
    """Prove held-out tasks are buildable, nontrivial, and never train rows."""

    task_ids = _validation_task_ids(registry)
    if not task_ids:
        raise RuntimeError("held-out monitor contains no validation tasks")
    if set(task_ids) & set(_curriculum_task_ids(registry)):
        raise RuntimeError("held-out monitor overlaps the training curriculum")
    samples = _heldout_negative_samples(registry)
    records = asyncio.run(reward_func(None, samples))
    if not isinstance(records, list) or len(records) != len(samples):
        raise RuntimeError("held-out monitor preflight returned incomplete results")
    for sample, record in zip(samples, records):
        _validate_heldout_negative_record(sample, record)
    print(
        "GENERALIZED_CPP_HELDOUT_MONITOR_READY "
        f"tasks={len(task_ids)} starter_controls={len(samples)}"
    )


def _write_task_source(registry: TaskRegistry, output: Path) -> Path:
    """Materialize an answer-free Aider shadow task tree from the registry."""

    practice = output / "cpp" / "exercises" / "practice"
    practice.mkdir(parents=True)
    train_task_ids = _curriculum_task_ids(registry)
    validation_task_ids = _validation_task_ids(registry)
    task_ids = [*train_task_ids, *validation_task_ids]
    for task_id in task_ids:
        binding = registry.resolve(task_id)
        entry = registry.entries[task_id]
        split = "train" if task_id in train_task_ids else "validation"
        family = entry.get("family", task_id)
        if not isinstance(family, str) or not family:
            raise BindingError("invalid_registry", f"{task_id}.family is invalid")
        fixture = binding.fixture_dir
        docs_source = fixture / ".docs" / "instructions.md"
        cmake_source = fixture / "CMakeLists.txt"
        for path in (docs_source, cmake_source):
            if path.is_symlink() or not path.is_file():
                raise BindingError("invalid_fixture", f"{task_id} is missing {path.name}")
        test_source = _fixture_test(fixture, task_id)
        exercise = practice / task_id
        docs = exercise / ".docs"
        docs.mkdir(parents=True)
        shutil.copy2(docs_source, docs / "instructions.md")
        if task_id == "perfect-numbers":
            # Answer-free interface information missing from the empty starter;
            # pinned benchmark fixtures and tests remain unchanged.
            with (docs / "instructions.md").open("a") as instructions:
                instructions.write("\n\n## C++ interface contract\n\n"
                    "Implement `perfect_numbers::classification classify(int n)` with "
                    "`enum class classification { deficient, perfect, abundant };` "
                    "in namespace `perfect_numbers`. Nonpositive inputs must throw "
                    "`std::domain_error` from `<stdexcept>`. Classify positive signed-int "
                    "inputs by the sum of their positive proper divisors (excluding "
                    "the number itself), without arithmetic overflow.\n")
        shutil.copy2(cmake_source, exercise / "CMakeLists.txt")
        shutil.copy2(test_source, exercise / test_source.name)
        for relative in binding.manifest["candidate_files"]:
            shutil.copy2(
                binding.starter_dir.joinpath(*PurePosixPath(relative).parts),
                exercise.joinpath(*PurePosixPath(relative).parts),
            )
        rubric = AiderShadowRubric(
            task_id=task_id,
            split=split,
            editable_files=list(binding.manifest["candidate_files"]),
            hidden_test_file=test_source.name,
            hidden_test_sha256=_sha256(test_source),
            source_prompt_sha256=_sha256(docs / "instructions.md"),
            reference_answer_packaged=False,
            verification_stage="passed",
            verification_gate=VERIFICATION_GATE,
            family=family,
            category=str(registry.dataset.get("category", "generalized-cpp-global")),
            lineage_id=str(entry.get("lineage_id", f"polyglot-cpp/{task_id}")),
            episode_kind="full-solve",
            objective_group=str(
                registry.dataset.get("objective_group", "generalized-cpp-global")
            ),
            failure_signature=None,
            tags=list(
                dict.fromkeys(
                    [
                        CURRICULUM_NAME,
                        str(registry.dataset.get("dataset_tag", CURRICULUM_NAME)),
                        family,
                        str(entry.get("admission_evidence", "unrecorded-admission")),
                        "heldout-monitor" if split == "validation" else "training",
                        "whole-file-action",
                        "global-cpp-verifier",
                    ]
                )
            ),
        )
        (exercise / ".rubric.json").write_text(
            rubric.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
    manifest = {
        "kind": SOURCE_MANIFEST_KIND,
        "schema_version": 1,
        "source_locator": str(
            registry.dataset.get(
                "source_locator",
                f"official:Aider-AI/polyglot-benchmark@{POLYGLOT_COMMIT}/cpp/exercises/practice",
            )
        ),
        "counts": {
            "tasks": len(task_ids),
            "train": len(train_task_ids),
            "validation": len(validation_task_ids),
        },
        "task_ids": task_ids,
        "contract": {
            "official_task_id_overlap": registry.dataset.get(
                "official_task_id_overlap", train_task_ids
            ),
            "official_training_authorized": bool(
                registry.dataset.get("official_training_authorized", True)
            ),
            "reference_answers_packaged": False,
            "shared_hidden_tests_within_lineage": False,
            "verifier_gate": VERIFICATION_GATE,
            "midband_admission": registry.dataset.get("midband_admission"),
        },
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return output


def build_data(args: argparse.Namespace) -> dict[str, Path]:
    if args.curriculum not in (None, CURRICULUM_NAME):
        raise ValueError(f"unsupported curriculum: {args.curriculum}")
    tasks_dir = Path(args.tasks_dir)
    if not tasks_dir.is_dir() or tasks_dir.is_symlink():
        raise ValueError("--tasks-dir must be a regular directory")
    registry = _registry()
    with TemporaryDirectory(prefix="generalized-cpp-grpo-tasks-") as temporary:
        source = _write_task_source(registry, Path(temporary))
        return build_aider_polyglot_datasets(
            source,
            args.out,
            train_limit=args.train_limit,
            monitor_limit=args.eval_limit or len(_curriculum_task_ids(registry)),
            profile=args.profile,
            run_id=args.run_id,
            sort_by_size=args.sort_by_size,
            force=args.force,
        )


def preflight() -> None:
    """Validate parser, registry bindings, dataset build, and registry canaries."""

    run_response_contract_preflight()
    registry = _registry()
    validate_midband_admission(registry)
    for task_id in registry.task_ids():
        binding = registry.resolve(task_id)
        if binding.preflight_response is None:
            continue
        record = score_sample(
            {
                "metadata": {
                    "task_id": f"generalized-cpp/{task_id}",
                    "problem_id": task_id,
                    "generalized_verifier_manifest_sha256": binding.manifest_sha256,
                },
                "response": binding.preflight_response,
                "rollout_id": "preflight",
            },
            registry,
        )
        if record.get("infrastructure_error") or record.get("score") != 1.0:
            raise RuntimeError(f"generalized verifier canary failed: {task_id}: {record}")
    run_mutation_preflight(registry)
    run_heldout_monitor_preflight(registry)
    with TemporaryDirectory(prefix="generalized-cpp-grpo-preflight-") as temporary:
        args = argparse.Namespace(
            curriculum=CURRICULUM_NAME,
            tasks_dir=str(REWARD_ROOT),
            out=Path(temporary) / "data",
            train_limit=None,
            eval_limit=None,
            profile="generalized-cpp-preflight",
            run_id="generalized-cpp-preflight",
            sort_by_size=False,
            force=True,
        )
        paths = build_data(args)
        manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
        if (
            manifest.get("kind") != DATASET_KIND
            or manifest["counts"]["train"] != len(_curriculum_task_ids(registry))
            or manifest["counts"]["validation"] != len(_validation_task_ids(registry))
        ):
            raise RuntimeError("generalized C++ dataset preflight produced an invalid manifest")
    print("GENERALIZED_CPP_GRPO_READY")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build-data")
    build.add_argument("--tasks-dir", required=True)
    build.add_argument("--out", required=True, type=Path)
    build.add_argument("--curriculum", choices=[CURRICULUM_NAME])
    build.add_argument("--train-limit", type=int)
    build.add_argument("--eval-limit", type=int)
    build.add_argument("--eval-splits", default="validation,test")
    build.add_argument("--profile", default="generalized-cpp-grpo")
    build.add_argument("--run-id")
    build.add_argument("--sort-by-size", action="store_true")
    build.add_argument("--force", action="store_true")
    subparsers.add_parser("preflight")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    if args.command == "preflight":
        preflight()
        return
    paths = build_data(args)
    print(
        json.dumps(
            {key: str(value) for key, value in paths.items()},
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
