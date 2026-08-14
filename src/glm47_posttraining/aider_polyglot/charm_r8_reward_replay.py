"""Replay every R8 reference through the production Hybrid45 path with zero updates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Sequence

from glm47_posttraining.aider_polyglot.charm_grpo import (
    CharmGRPOProjectionError,
    _canonical_bytes,
    _validate_task,
    sha256_file,
    tree_sha256,
)
from glm47_posttraining.aider_polyglot.charm_r8 import (
    validate_corrected_exact40_dataset,
    validate_corrected_selection,
)
from glm47_posttraining.aider_polyglot.harness import (
    capture_stage_receipts,
    stage_receipt_bundle,
)
from glm47_posttraining.aider_polyglot.hybrid45 import validate_hybrid45_receipt
from glm47_posttraining.aider_polyglot.rollout_receipts import (
    validate_hidden_partition_accounting,
)
from glm47_posttraining.aider_polyglot.schema import (
    AiderPolyglotTask,
    HYBRID45_POLICY_VERSION,
    WEIGHTED45_CHECK_IDS,
)
from glm47_posttraining.integrations.miles_aider_polyglot import (
    REWARD_MODE_ENV,
    SANDBOX_IMAGE_ENV,
    _score_sample,
)


SCHEMA_VERSION = "charm-r8-hybrid45-corpus-no-update-replay-v1"


def _read_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise CharmGRPOProjectionError(f"non-object replay row: {path}:{line_number}")
        rows.append(value)
    return rows


def _whole_file_response(files: dict[str, str], editable_files: Sequence[str]) -> str:
    chunks: list[str] = []
    for name in editable_files:
        contents = files[name]
        if "```" in contents:
            raise CharmGRPOProjectionError(f"reference contains a code fence: {name}")
        chunks.append(f"{name}\n```cpp\n{contents}```\n")
    return "".join(chunks)


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def run_corpus_no_update_replay(
    *,
    runtime_root: str | Path,
    verifier_image: str,
    verifier_image_id: str,
    verifier_dockerfile: str | Path,
    output: str | Path,
    workers: int = 4,
) -> dict[str, Any]:
    """Exercise every reference, all 45 kernels, and all hidden partitions."""

    if workers < 1:
        raise ValueError("workers must be positive")
    root = Path(runtime_root).resolve()
    output_path = Path(output).resolve()
    if output_path.exists() or output_path.is_symlink():
        raise FileExistsError(f"refusing to overwrite corpus replay: {output_path}")
    validation = validate_corrected_exact40_dataset(root)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    frozen = validate_corrected_selection(manifest["source"]["selection_path"])
    selected_by_id = {str(item["task_id"]): item for item in frozen["all_tasks"]}
    files = manifest["files"]
    rows = [
        *_read_rows(root / files["grpo_train"]),
        *_read_rows(root / files["task_disjoint_monitor"]),
    ]
    rows.sort(key=lambda row: str(row["metadata"]["base_task_id"]))
    if len(rows) != 51:
        raise CharmGRPOProjectionError("R8 corpus replay requires exactly 51 task rows")

    environment = {
        REWARD_MODE_ENV: "hybrid_bipolar45",
        SANDBOX_IMAGE_ENV: verifier_image_id,
        "GLM47_TOKENIZER_REVISION": "7dd20894a642a0aa287e9827cb1a1f7f91386b67",
        "GLM47_TOKENIZER_MANIFEST_SHA256": (
            "53bcc04c0e0acedb8b57abbb03f28c29519b79a245c78784c341554ad33ce1a2"
        ),
        "GLM47_CHAT_TEMPLATE_SHA256": (
            "d63ad536c3c81880043e22ec7fd08db42b4d8fb7c89c7138bc562bfa25281375"
        ),
    }
    previous = {name: os.environ.get(name) for name in environment}
    os.environ.update(environment)

    def score(row: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(row["metadata"])
        base_task_id = str(metadata["base_task_id"])
        selected = selected_by_id[base_task_id]
        source_root, rubric = _validate_task(selected)
        task_path = root / str(metadata["task_path"])
        task = AiderPolyglotTask.read_json(task_path)
        reference_files = {
            name: (source_root / ".reference" / name).read_text(encoding="utf-8")
            for name in task.editable_files
        }
        response = _whole_file_response(reference_files, task.editable_files)
        sample = {
            "metadata": {**metadata, "task_root": str(root)},
            "prompt": row["prompt"],
            "response": response,
            "index": 0,
            "rollout_id": f"r8-no-update-reference-{base_task_id}",
            "finish_reason": "stop",
        }
        with capture_stage_receipts() as stage_receipts:
            record = _score_sample(sample)
        receipt = record.get("hybrid45")
        partition_accounting = record.get("hidden_partition_accounting")
        if not isinstance(receipt, dict) or not isinstance(partition_accounting, dict):
            raise CharmGRPOProjectionError(
                f"production reward omitted Hybrid45 evidence: {base_task_id}"
            )
        validate_hybrid45_receipt(receipt)
        validate_hidden_partition_accounting(partition_accounting)
        kernels = receipt["kernels"]
        evidence = receipt["evidence"]
        functional_pass = (
            record.get("all_tests_pass") is True
            and receipt.get("hidden_partitions_passed") == 5
            and receipt.get("hidden_partitions_total") == 5
            and evidence.get("K2", "").find("clang18_ast decision=PASS") >= 0
        )
        full_reward = (
            record.get("optimizer_score") == 1.0
            and receipt.get("reachability_stage") == 8
            and all(kernels.get(check_id) == 1 for check_id in WEIGHTED45_CHECK_IDS)
        )
        source_role = str(selected["role"])
        return {
            "task_id": base_task_id,
            "split": task.split,
            "gradient_bearing": metadata.get("gradient_bearing") is True,
            "source_role": source_role,
            "source_tree_sha256": selected["tree_sha256"],
            "task_descriptor_sha256": sha256_file(task_path),
            "reference_response_sha256": hashlib.sha256(response.encode()).hexdigest(),
            "functional_reference_pass": functional_pass,
            "full_positive_reward": full_reward,
            "optimizer_score": record.get("optimizer_score"),
            "optimizer_override": receipt.get("optimizer_override"),
            "reachability_stage": receipt.get("reachability_stage"),
            "primary_failure_kernel": receipt.get("primary_failure_kernel"),
            "kernel_count": len(kernels),
            "positive_kernel_count": sum(value == 1 for value in kernels.values()),
            "hidden_partitions_passed": receipt.get("hidden_partitions_passed"),
            "public_api_ast_pass": evidence.get("K2", "").find("clang18_ast decision=PASS") >= 0,
            "hybrid45_receipt_sha256": _canonical_sha256(receipt),
            "hidden_partition_accounting_sha256": _canonical_sha256(partition_accounting),
            "stage_receipts": stage_receipt_bundle(stage_receipts),
        }

    try:
        with ThreadPoolExecutor(max_workers=min(workers, len(rows))) as executor:
            task_receipts = list(executor.map(score, rows))
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    functional_failures = [
        item["task_id"] for item in task_receipts if item["functional_reference_pass"] is not True
    ]
    gradient_reward_failures = [
        item["task_id"]
        for item in task_receipts
        if item["gradient_bearing"] and item["full_positive_reward"] is not True
    ]
    calibration_gradient_failures = [
        item["task_id"]
        for item in task_receipts
        if item["gradient_bearing"]
        and item["source_role"] == "calibration"
        and item["full_positive_reward"] is not True
    ]
    decision = "PASS" if not functional_failures and not gradient_reward_failures else "FAIL"
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "decision": decision,
        "policy_version": HYBRID45_POLICY_VERSION,
        "optimizer_updates": 0,
        "runtime_manifest_sha256": validation["manifest_sha256"],
        "runtime_tree_sha256": tree_sha256(root),
        "selection_sha256": validation["selection_sha256"],
        "public_api_manifest_set_sha256": validation["public_api_manifest_set_sha256"],
        "verifier_image": verifier_image,
        "verifier_image_id": verifier_image_id,
        "verifier_dockerfile_sha256": sha256_file(Path(verifier_dockerfile)),
        "task_count": len(task_receipts),
        "gradient_task_count": sum(item["gradient_bearing"] for item in task_receipts),
        "functional_reference_pass_count": sum(
            item["functional_reference_pass"] for item in task_receipts
        ),
        "full_positive_reward_count": sum(item["full_positive_reward"] for item in task_receipts),
        "gradient_full_positive_reward_count": sum(
            item["gradient_bearing"] and item["full_positive_reward"] for item in task_receipts
        ),
        "functional_failures": functional_failures,
        "gradient_reward_failures": gradient_reward_failures,
        "calibration_gradient_failures": calibration_gradient_failures,
        "context_token_count_validation": "SEPARATE_PROMPT_PREFLIGHT_REQUIRED",
        "task_receipts": task_receipts,
    }
    payload["receipt_sha256"] = _canonical_sha256(payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, output_path)
    return payload


def _main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--verifier-image", required=True)
    parser.add_argument("--verifier-image-id", required=True)
    parser.add_argument("--verifier-dockerfile", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)
    payload = run_corpus_no_update_replay(
        runtime_root=args.runtime_root,
        verifier_image=args.verifier_image,
        verifier_image_id=args.verifier_image_id,
        verifier_dockerfile=args.verifier_dockerfile,
        output=args.output,
        workers=args.workers,
    )
    print(
        json.dumps(
            {
                key: payload[key]
                for key in (
                    "decision",
                    "task_count",
                    "functional_reference_pass_count",
                    "gradient_full_positive_reward_count",
                    "gradient_reward_failures",
                    "receipt_sha256",
                )
            },
            indent=2,
            sort_keys=True,
        )
    )
    if payload["decision"] != "PASS":
        raise SystemExit(3)


if __name__ == "__main__":
    _main()
