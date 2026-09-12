"""Old-task GRPO: generalized live policies plus targeted topic correctness gates.

Each reward runs in an offline, read-only Docker worker. The original verifier
and topic audit remain reusable and unchanged; this module owns their composition.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid

from Reward_GRPO import generalized_cpp_grpo as base
from Reward_GRPO.topic_coverage.runner import AuditSession, reference_sources, control_sources, response_from_sources
from Reward_GRPO.topic_coverage.specs import TOPICS
from Reward_GRPO.topic_coverage.scoring import SCORING_VERSION, summarize_requirements
from glm47_posttraining.aider_polyglot.harness import CandidatePolicyError, _validate_candidate_source
from glm47_posttraining.aider_polyglot.parser import AiderResponseError, parse_whole_file_response

ROOT = Path(__file__).resolve().parent.parent
CURRICULUM = "generalized-cpp-topics-v1"
MODULE = "Reward_GRPO.generalized_cpp_topic_grpo"
IMAGE = "glm47-generalized-cpp-topics:v4"
REWARD_FILES = (
    "Reward_GRPO/generalized_cpp_topic_grpo.py", "Reward_GRPO/generalized_cpp_grpo.py",
    "Reward_GRPO/global_cpp_verifier_runner.py", "Reward_GRPO/generalized_cpp_grpo_registry.json",
    "Reward_GRPO/generalized_cpp_grpo_mutations.json", "Reward_GRPO/generalized_cpp_midband_admission.json",
    "Reward_GRPO/generalized_cpp_topic_sandbox.Dockerfile",
)
REWARD_DIRS = (
    "src/glm47_posttraining", "generalized_verifier_docs", "Reward_GRPO/Generalized Cpp Verifiers",
    "Reward_GRPO/generalized_cpp_grpo_tasks", "Reward_GRPO/generalized_cpp_grpo_evidence",
    "Reward_GRPO/multi_env_fixtures", "Reward_GRPO/topic_coverage",
    "Reward_GRPO/generalized_cpp_grpo_canary",
)
# These tasks operate on values in memory. Filesystem/process primitives and
# verifier helper symbols are outside their editable API contract.
RESERVED = re.compile(
    r"\b(?:coverage|run_topic|TOPIC_COVERAGE_RECEIPT|Catch|CATCH_\w*|"
    r"fopen|freopen|openat|fwrite|unlink|chmod|ptrace|syscall|"
    r"getenv|setenv|putenv|dlopen|dlsym)\s*(?:\b|\()"
    r"|\b(?:i?fstream|ofstream|filebuf|filesystem)\b"
    r"|#\s*(?:define|undef)\s+(?:CHECK\w*|REQUIRE\w*|main)\b"
    r"|#\s*include\s*[<\"][^>\"]*(?:\.\./|/opt/|/tmp/|\.meta|coverage|catch|_test)"
    r"|__attribute__\s*\(\(\s*(?:constructor|destructor)"
)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def file_hashes():
    paths = {ROOT / name for name in REWARD_FILES}
    for name in REWARD_DIRS:
        paths.update(p for p in (ROOT / name).rglob("*")
                     if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
    return {p.relative_to(ROOT).as_posix(): base._sha256(p) for p in sorted(paths)}


@lru_cache(maxsize=1)
def contract_digest():
    return hashlib.sha256(json.dumps(file_hashes(), sort_keys=True).encode()).hexdigest()


def sample_dict(sample):
    return {key: base._sample_value(sample, key) for key in
            ("metadata", "response", "response_length", "rollout_id", "index")}


def compose(record, topic=None):
    if topic is not None:
        topic = {**topic, "audit_only": False, "changes_grpo_reward": True}
    result = {**record, "generalized_score": record["score"],
              "reward_contract": CURRICULUM, "reward_scoring_version": SCORING_VERSION,
              "topic_coverage": topic, "topic_required": record.get("problem_id") in TOPICS}
    if record.get("infrastructure_error") or topic is None:
        return result
    if topic.get("status") == "invalid":
        result.update(score=0.0, reward=0.0, infrastructure_error=True,
                      reason="topic_verifier_invalid")
        return result
    try:
        requirements = summarize_requirements(record["problem_id"], topic)
    except (ValueError, TypeError, KeyError) as error:
        result.update(score=0.0, reward=0.0, infrastructure_error=True,
                      reason="topic_scoring_invalid", error=str(error))
        return result
    result["topic_requirement_score"] = requirements
    base_score = float(record["score"])
    if topic["status"] == "pass" and base_score > 0:
        return result  # Both layers pass; preserve any recoverable format penalty.
    # A failed program stays nonpositive, but improvements in either independent
    # layer increase reward. No minimum/cap can flatten those improvements.
    topic_component = requirements["fraction"] - 1.0
    score = 0.5 * min(base_score, 0.0) + 0.5 * topic_component
    result.update(score=score, reward=score,
                  reason="topic_correctness_failed" if topic["status"] == "fail" else record.get("reason"),
                  partial_reward_components={"generalized": min(base_score, 0.0),
                                             "topic": topic_component, "weight_each": 0.5})
    return result


def worker_score(sample):
    """Only the Docker entrypoint calls this direct-execution implementation."""
    registry = base._registry()
    metadata = base._sample_metadata(sample)
    task_id = base._task_id(metadata)
    binding = registry.resolve(task_id)
    response = base._sample_response(sample)
    try:
        # Strict boundaries before either compiler. Recoverable filename markdown
        # is allowed, but duplicate and forbidden file listings are never executed.
        parsed = parse_whole_file_response(response, binding.manifest["candidate_files"])
        for name, text in parsed.files.items():
            _validate_candidate_source(name, text)
            if RESERVED.search(text):
                raise CandidatePolicyError("candidate refers to verifier or filesystem internals")
    except AiderResponseError as error:
        result = base._model_failure(sample, task_id, error.reason, str(error))
        # A partial/unclosed answer must not outrank a valid failed program.
        if result.get("integrity_verdict") == "TRUNCATED":
            result.update(score=-1.0, reward=-1.0)
        return compose(result)
    except CandidatePolicyError as error:
        return compose({**base._base_record(sample, task_id), "score": -1.0, "reward": -1.0,
                        "infrastructure_error": False, "reason": "candidate_boundary",
                        "error": str(error), "format_valid": parsed.format_valid})
    record = base.score_sample(sample, registry)
    kernels = {k["kernel_id"]: k.get("kernel") for k in record.get("kernel_results", [])}
    if (task_id not in TOPICS or record.get("infrastructure_error")
            or kernels.get("G02-1") != 1 or kernels.get("G02-2") != 1):
        return compose(record)
    with tempfile.TemporaryDirectory(prefix="combined-topic-") as temp:
        candidate = Path(temp) / "candidate"
        base._reconstruct(binding, response, candidate)
        sources = {name: (candidate / name).read_text() for name in binding.manifest["candidate_files"]}
        with AuditSession(task_id, Path(temp) / "audit", compiler="/usr/local/bin/g++",
                          allow_local_execution=True, include_diagnostics=False) as session:
            topic = session.audit(sources)
    return compose(record, topic)


@lru_cache(maxsize=1)
def image_identity():
    image = os.environ.get("GENERALIZED_TOPIC_SANDBOX_IMAGE", IMAGE)
    completed = subprocess.run(["docker", "image", "inspect", image], check=True,
                               capture_output=True, text=True, timeout=30)
    info = json.loads(completed.stdout)[0]
    if info["Config"]["Labels"].get("glm47.reward-contract") != contract_digest():
        raise ValueError("verifier image does not match current reward code and task assets")
    return info["Id"]


def docker_command(name):
    return ["docker", "run", "--rm", "-i", "--name", name,
            "--network", "none", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--user", "65534:65534",
            "--cpus", "2", "--memory", "4g", "--pids-limit", "2048",
            "--ulimit", "fsize=134217728:134217728", "--ulimit", "core=0:0",
            "--tmpfs", "/tmp:rw,exec,nosuid,size=1536m,mode=1777",
            "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "GENERALIZED_CPP_VERIFIER_PROFILE=live",
            image_identity(), "python3", "-m", MODULE, "worker"]


def score_sample(sample, registry=None):
    task_id = base._sample_metadata(sample).get("problem_id")
    metadata = base._sample_metadata(sample)
    if metadata.get("combined_reward_sha256") != contract_digest():
        return base._infrastructure_failure(sample, task_id, "combined_reward_binding_mismatch", "")
    name = "glm47-topic-reward-" + uuid.uuid4().hex
    worker = {"container_name": name, "timeout_seconds": 900}
    started = time.monotonic()
    try:
        proc = subprocess.run(docker_command(name), input=json.dumps(sample_dict(sample)),
                              capture_output=True, text=True, timeout=900)
        worker.update(returncode=proc.returncode, stderr_tail=proc.stderr[-4000:])
        if proc.returncode:
            worker["stdout_tail"] = proc.stdout[-4000:]
            raise RuntimeError(f"reward container exit {proc.returncode}: {proc.stderr[-1500:]}")
        result = json.loads(proc.stdout)
        if result.get("problem_id") != task_id or result.get("reward_contract") != CURRICULUM:
            raise ValueError("worker response identity mismatch")
        result["combined_reward_sha256"] = contract_digest()
        result["sandbox_image_id"] = image_identity()
    except Exception as error:
        if isinstance(error, subprocess.TimeoutExpired):
            worker["timed_out"] = True
            for stream in ("stdout", "stderr"):
                value = getattr(error, stream, None) or ""
                if isinstance(value, bytes):
                    value = value.decode("utf-8", errors="replace")
                worker[stream + "_tail"] = value[-4000:]
        result = base._infrastructure_failure(sample, task_id, "combined_reward_worker_error",
                                              f"{type(error).__name__}: {error}")
    finally:
        try:
            cleanup = subprocess.run(["docker", "rm", "-f", name], capture_output=True,
                                     text=True, timeout=30)
            if cleanup.returncode and "No such container" not in cleanup.stderr:
                worker["cleanup_error"] = cleanup.stderr[-1500:]
        except Exception as error:
            worker["cleanup_error"] = f"{type(error).__name__}: {error}"
    worker["elapsed_seconds"] = round(time.monotonic() - started, 6)
    if worker.get("cleanup_error"):
        result.update(score=0.0, reward=0.0, infrastructure_error=True,
                      reason="combined_reward_cleanup_error")
    result["worker"] = worker
    return result


class RewardInfrastructureError(RuntimeError):
    """No scalar reward is valid for a sample whose verifier did not run reliably."""


_SCORING_POOL = None
_SCORING_POOL_LOCK = threading.Lock()


def _scoring_executor():
    """One physical worker cap per process, across calls and event loops.

    Cancellation of an asyncio waiter cannot release a physical worker slot;
    the executor retains it until scoring, evidence capture and cleanup finish.
    """
    global _SCORING_POOL
    workers = max(1, min(int(os.environ.get("GENERALIZED_CPP_REWARD_WORKERS", "8")), 24))
    with _SCORING_POOL_LOCK:
        if _SCORING_POOL is None or _SCORING_POOL[0] != os.getpid():
            _SCORING_POOL = (os.getpid(), workers, ThreadPoolExecutor(
                max_workers=workers, thread_name_prefix="cpp-reward"))
        if _SCORING_POOL[1] != workers:
            raise RewardInfrastructureError("reward worker limit changed inside a running process")
        return _SCORING_POOL[2]


def _invalid_policies(record):
    return [{key: policy.get(key) for key in ("policy_id", "status", "reason", "receipt_errors")}
            for policy in record.get("policy_results", []) if policy.get("status") == "invalid"]


def _save_failed_attempt(sample, record, call_id, attempt):
    run_root = Path(os.environ.get("MILES_RUN_ROOT") or ROOT / ".glm47-posttraining/generalized-cpp-topics")
    directory = Path(os.environ.get("GENERALIZED_CPP_FAILURE_DIR") or run_root / "reward_failures")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{call_id}-attempt-{attempt}.json"
    temporary = path.with_suffix(".json.tmp")
    response = base._sample_response(sample)
    payload = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
               "run_id": os.environ.get("MILES_RUN_ID"), "call_id": call_id, "attempt": attempt,
               "response_sha256": hashlib.sha256(response.encode("utf-8")).hexdigest(),
               "sample": sample_dict(sample), "invalid_policies": _invalid_policies(record),
               "record": record}
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    print("REWARD_INFRASTRUCTURE_FAILURE " + json.dumps({
        "path": str(path), "task": record.get("problem_id"), "sample_index": record.get("sample_index"),
        "attempt": attempt, "reason": record.get("reason"),
        "invalid_policies": _invalid_policies(record)}, sort_keys=True), flush=True)
    return str(path)


def _score_attempt(sample, call_id, attempt):
    # This runs inside the bounded worker so evidence survives waiter cancellation.
    try:
        record = score_sample(sample)
    except Exception as error:
        record = base._infrastructure_failure(
            sample, base._sample_metadata(sample).get("problem_id"),
            "unexpected_reward_exception", f"{type(error).__name__}: {error}")
    path = None
    if record.get("infrastructure_error"):
        try:
            path = _save_failed_attempt(sample, record, call_id, attempt)
        except Exception as error:
            raise RewardInfrastructureError(
                f"Cannot preserve failed verifier evidence: task={record.get('problem_id')} "
                f"reason={record.get('reason')} policies={_invalid_policies(record)}; "
                "no reward returned to training") from error
    return record, path


async def reward_func(_args, sample, **_kwargs):
    executor = _scoring_executor()
    loop = asyncio.get_running_loop()

    async def score(item):
        call_id, receipts = uuid.uuid4().hex, []
        for attempt in range(1, 4):
            record, path = await loop.run_in_executor(executor, _score_attempt, item, call_id, attempt)
            if path:
                receipts.append(path)
            if not record.get("infrastructure_error"):
                record["reward"] = record["score"]
                record["infrastructure_attempts"] = attempt
                if receipts:
                    record["infrastructure_failure_receipts"] = receipts
                return record
        raise RewardInfrastructureError(
            f"Verifier infrastructure failed after 3 attempts: "
            f"task={record.get('problem_id')} reason={record.get('reason')} "
            f"policies={_invalid_policies(record)} receipts={receipts}; "
            "no reward returned to training")

    if not isinstance(sample, list):
        return await score(sample)
    records = await asyncio.gather(*(score(item) for item in sample), return_exceptions=True)
    for record in records:
        if isinstance(record, BaseException):
            raise record
    return records


def build_data(args):
    if args.curriculum != CURRICULUM or args.train_limit is not None or args.eval_limit is not None:
        raise ValueError("combined run requires the full 15 train / 4 validation curriculum")
    original = argparse.Namespace(**vars(args))
    original.curriculum = base.CURRICULUM_NAME
    paths = base.build_data(original)
    for path in args.out.rglob("*.jsonl"):
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        for row in rows:
            row["metadata"]["combined_reward_sha256"] = contract_digest()
            row["metadata"]["topic_coverage_required"] = row["metadata"]["problem_id"] in TOPICS
        path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
    manifest_path = Path(paths["manifest"])
    manifest = json.loads(manifest_path.read_text())
    manifest.update(reward_function=MODULE + ".reward_func", combined_reward_sha256=contract_digest(),
                    topic_tasks=sorted(TOPICS), topic_groups=sum(len(t.groups) for t in TOPICS.values()),
                    reward_scoring_version=SCORING_VERSION,
                    partial_reward_formula="0.5*min(generalized_score,0)+0.5*(topic_fraction-1)",
                    topic_reward_families={task: dict(topic.families) for task, topic in TOPICS.items()},
                    sandbox_required=True, diagnostic_topics_affect_reward=False)
    manifest["file_sha256s"] = {p.relative_to(args.out).as_posix(): base._sha256(p)
                               for p in args.out.rglob("*") if p.is_file() and p != manifest_path}
    write_json(manifest_path, manifest)
    return {k: str(v) for k, v in paths.items()}


def copy_reward_code(destination):
    for name in REWARD_FILES:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    for name in REWARD_DIRS:
        shutil.copytree(ROOT / name, destination / name,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def build_image():
    with tempfile.TemporaryDirectory(prefix="combined-verifier-image-") as temp:
        context = Path(temp)
        copy_reward_code(context)
        subprocess.run(["docker", "build", "--label", "glm47.reward-contract=" + contract_digest(),
                        "-t", IMAGE, "-f", str(context / "Reward_GRPO/generalized_cpp_topic_sandbox.Dockerfile"),
                        str(context)], check=True)
    image_identity.cache_clear()
    return {"image_id": image_identity(), "combined_reward_sha256": contract_digest()}


def stage_launch(args):
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=False)
    copy_reward_code(output)
    shutil.copytree(ROOT / "scripts", output / "scripts", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in ("src/sitecustomize.py", "pyproject.toml", "examples/grpo.sh",
                 "Reward_GRPO/generalized_cpp_topic_grpo_skypilot.yaml"):
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    write_json(output / "launch-manifest.json", {
        "schema_version": 1, "kind": CURRICULUM, "run_id": args.run_id,
        "combined_reward_sha256": contract_digest(),
        "files": {p.relative_to(output).as_posix(): base._sha256(p) for p in output.rglob("*") if p.is_file()},
    })
    from glm47_posttraining.integrations.charm_bridge_preflight import verify_package
    return {"workdir": str(output), **verify_package(output)}


def preflight(output=None, quick=False):
    from Reward_GRPO.topic_coverage.controls import controls
    registry = base._registry()
    base.validate_midband_admission(registry)
    samples = []
    def add(task, response, kind, expected, control):
        samples.append({"metadata": {"problem_id": task, "combined_reward_sha256": contract_digest()},
                        "response": response, "rollout_id": "preflight", "control": control,
                        "expected": expected, "kind": kind})
    for task in registry.task_ids():
        binding = registry.resolve(task)
        if task in TOPICS and TOPICS[task].reference_control:
            add(task, response_from_sources(control_sources(binding, task)), "reference", "pass", "reference")
        elif binding.preflight_response:
            add(task, binding.preflight_response, "reference", "pass", "reference")
        elif task in base._curriculum_task_ids(registry) + base._validation_task_ids(registry):
            add(task, response_from_sources(reference_sources(binding)), "reference", "pass", "reference")
    if not quick:
        for sample in base._mutation_control_samples(registry):
            if (sample["metadata"]["problem_id"] == "perfect-numbers"
                    and sample["metadata"]["mutation_case"] in {"alternate_correct", "recoverable_format"}):
                sources = control_sources(registry.resolve("perfect-numbers"), "perfect-numbers")
                sample["response"] = base._render_whole_file_response(
                    sources, decorate_labels=sample["metadata"]["mutation_case"] == "recoverable_format")
                sample["metadata"]["control_revision"] = "overflow-safe-positive-v3"
            if (sample["metadata"]["problem_id"] == "spiral-matrix"
                    and sample["metadata"]["mutation_case"] == "semantic_failure"):
                # The old direction mutation can index outside the matrix.
                # Offset non-first values instead: sizes 0/1 still pass, larger
                # matrices are wrong without changing any bounds or traversal.
                original = registry.resolve("spiral-matrix").preflight_response
                anchor = "matrix_elem(coords) = i;"
                if original.count(anchor) != 1:
                    raise ValueError("spiral control anchor drift")
                sample["response"] = original.replace(anchor, "matrix_elem(coords) = i + (i > 1 ? 1u : 0u);")
                sample["metadata"]["control_revision"] = "defined-value-offset-v1"
            sample["metadata"]["combined_reward_sha256"] = contract_digest()
            sample["kind"] = "generalized_control"
            samples.append(sample)
        for task in TOPICS:
            binding = registry.resolve(task)
            for control in controls(task, control_sources(binding, task)):
                if control.kind == "diagnostic":
                    continue
                add(task, response_from_sources(control.sources), "topic_" + control.kind,
                    control.expected, control.name)
                samples[-1]["required_failed_group"] = control.required_failed_group
        for sample in base._heldout_negative_samples(registry):
            sample["metadata"]["combined_reward_sha256"] = contract_digest()
            sample["kind"] = "heldout_negative"
            samples.append(sample)
    records = []
    with ThreadPoolExecutor(max_workers=max(1, min(int(os.environ.get("GENERALIZED_CPP_REWARD_WORKERS", "8")), 24))) as pool:
        futures = {pool.submit(score_sample, sample): sample for sample in samples}
        for future in as_completed(futures):
            sample, result = futures[future], future.result()
            matched = not result.get("infrastructure_error")
            if sample["kind"] == "generalized_control":
                if sample["metadata"]["mutation_case"] == "boundary_failure":
                    matched = matched and result["score"] == -1.0 and result["reason"] == "forbidden_file"
                else:
                    try:
                        baseline_result = result
                        if sample["metadata"]["mutation_case"] == "semantic_failure":
                            baseline_result = {**result, "score": result["generalized_score"]}
                            matched = matched and -1.0 <= result["score"] < 0.0
                        base._validate_mutation_record(sample, baseline_result)
                    except RuntimeError:
                        matched = False
            elif sample["kind"] == "heldout_negative":
                try:
                    base._validate_heldout_negative_record(sample, result)
                except RuntimeError:
                    matched = False
            else:
                matched = matched and ((result["score"] > 0) == (sample["expected"] == "pass"))
                if sample["kind"] == "topic_semantic":
                    topic_result = result.get("topic_coverage") or {}
                    candidate = topic_result.get("candidate", {})
                    groups = {row["group"]: row["status"] for row in candidate.get("groups", [])}
                    matched = matched and topic_result.get("status") == "fail"
                    matched = matched and candidate.get("build", {}).get("returncode") == 0
                    matched = matched and groups.get(sample["required_failed_group"]) == "fail"
            entry = {"task": sample["metadata"]["problem_id"], "kind": sample["kind"],
                     "control": sample.get("control", sample["metadata"].get("mutation_case", "starter")),
                     "matched": matched, "result": result}
            records.append(entry)
            if output:
                write_json(Path(output) / "progress.json", {"completed": len(records), "total": len(samples),
                                                            "failed": sum(not r["matched"] for r in records)})
                write_json(Path(output) / f"case-{len(records):03d}.json", entry)
            print(f"PREFLIGHT {len(records)}/{len(samples)} {entry['task']} {entry['control']} "
                  f"score={result['score']} matched={matched}", flush=True)
    result = {"status": "passed" if all(r["matched"] for r in records) else "failed",
              "cases": len(records), "matched": sum(r["matched"] for r in records),
              "combined_reward_sha256": contract_digest(), "sandbox_image_id": image_identity(),
              "train": base._curriculum_task_ids(registry), "validation": base._validation_task_ids(registry),
              "topic_tasks": sorted(TOPICS)}
    if output:
        write_json(Path(output) / "preflight.json", result)
    if result["status"] != "passed":
        raise RuntimeError(f"combined reward preflight failed: {result['matched']}/{result['cases']}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("worker")
    sub.add_parser("build-image")
    check = sub.add_parser("preflight")
    check.add_argument("--output", type=Path)
    check.add_argument("--quick", action="store_true")
    stage = sub.add_parser("stage-launch")
    stage.add_argument("--out", type=Path, required=True)
    stage.add_argument("--run-id", required=True)
    build = sub.add_parser("build-data")
    build.add_argument("--tasks-dir", required=True)
    build.add_argument("--out", type=Path, required=True)
    build.add_argument("--curriculum", default=CURRICULUM)
    build.add_argument("--profile", default=CURRICULUM)
    build.add_argument("--run-id")
    build.add_argument("--train-limit", type=int)
    build.add_argument("--eval-limit", type=int)
    build.add_argument("--eval-splits", default="validation")
    build.add_argument("--sort-by-size", action="store_true")
    build.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.command == "worker":
        if os.getuid() != 65534 or Path("/opt/reward") != ROOT:
            raise RuntimeError("direct reward execution is restricted to the verifier image")
        with redirect_stdout(sys.stderr):
            result = worker_score(json.load(sys.stdin))
        print(json.dumps(result, allow_nan=False))
        return
    result = (build_image() if args.command == "build-image" else
              stage_launch(args) if args.command == "stage-launch" else
              build_data(args) if args.command == "build-data" else preflight(args.output, args.quick or os.environ.get("GENERALIZED_TOPIC_PREFLIGHT_QUICK") == "1"))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
