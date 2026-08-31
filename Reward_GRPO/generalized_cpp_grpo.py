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
import os
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
REGISTRY_ENV = "GENERALIZED_CPP_VERIFIER_REGISTRY"
PROFILE_ENV = "GENERALIZED_CPP_VERIFIER_PROFILE"
WORKERS_ENV = "GENERALIZED_CPP_REWARD_WORKERS"
DEFAULT_WORKERS = 4
CURRICULUM_NAME = "generalized-cpp-v1"
POLYGLOT_COMMIT = "7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f"
VERIFICATION_GATE = "generalized-cpp-global-verifier-gcc13-v1"
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
    parsed = parse_whole_file_response(response, editable)
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


def _numeric_kernels(receipt: Mapping[str, Any]) -> list[int]:
    values: list[int] = []
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
            value = kernel.get("kernel")
            if isinstance(value, int) and not isinstance(value, bool) and value in {-1, 1}:
                values.append(value)
    return values


def receipt_to_reward(receipt: Mapping[str, Any]) -> tuple[float, bool, str]:
    """Return (score, infrastructure_error, reason) from an aggregate receipt."""

    status = str(receipt.get("status") or "invalid").lower()
    if status == "invalid":
        return 0.0, True, "verifier_invalid"
    values = _numeric_kernels(receipt)
    if values:
        score = sum(values) / len(values)
    else:
        score = 1.0 if status == "pass" else -1.0
    return max(-1.0, min(1.0, float(score))), False, status


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
    if engine is None or not response:
        return None
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
        score, infrastructure_error, reason = receipt_to_reward(receipt)
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


def _fixture_test(fixture: Path, task_id: str) -> Path:
    tests = sorted(path for path in fixture.glob("*_test.cpp") if path.is_file())
    if len(tests) != 1:
        raise BindingError("invalid_fixture", f"{task_id} must have exactly one *_test.cpp")
    return tests[0]


def _write_task_source(registry: TaskRegistry, output: Path) -> Path:
    """Materialize an answer-free Aider shadow task tree from the registry."""

    practice = output / "cpp" / "exercises" / "practice"
    practice.mkdir(parents=True)
    task_ids = _curriculum_task_ids(registry)
    for task_id in task_ids:
        binding = registry.resolve(task_id)
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
        shutil.copy2(cmake_source, exercise / "CMakeLists.txt")
        shutil.copy2(test_source, exercise / test_source.name)
        for relative in binding.manifest["candidate_files"]:
            shutil.copy2(
                binding.starter_dir.joinpath(*PurePosixPath(relative).parts),
                exercise.joinpath(*PurePosixPath(relative).parts),
            )
        rubric = AiderShadowRubric(
            task_id=task_id,
            split="train",
            editable_files=list(binding.manifest["candidate_files"]),
            hidden_test_file=test_source.name,
            hidden_test_sha256=_sha256(test_source),
            source_prompt_sha256=_sha256(docs / "instructions.md"),
            reference_answer_packaged=False,
            verification_stage="passed",
            verification_gate=VERIFICATION_GATE,
            family=task_id,
            category="generalized-cpp-global",
            lineage_id=f"polyglot-cpp/{task_id}",
            episode_kind="full-solve",
            objective_group="generalized-cpp-global",
            failure_signature=None,
            tags=[
                CURRICULUM_NAME,
                "official-task-training-authorized",
                "whole-file-action",
                "global-cpp-verifier",
            ],
        )
        (exercise / ".rubric.json").write_text(
            rubric.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
    manifest = {
        "kind": SOURCE_MANIFEST_KIND,
        "schema_version": 1,
        "source_locator": (
            f"official:Aider-AI/polyglot-benchmark@{POLYGLOT_COMMIT}/cpp/exercises/practice"
        ),
        "counts": {"tasks": len(task_ids), "train": len(task_ids), "validation": 0},
        "task_ids": task_ids,
        "contract": {
            "official_task_id_overlap": task_ids,
            "official_training_authorized": True,
            "reference_answers_packaged": False,
            "shared_hidden_tests_within_lineage": False,
            "verifier_gate": VERIFICATION_GATE,
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
