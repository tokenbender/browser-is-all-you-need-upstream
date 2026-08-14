"""Generate the fail-closed SkyPilot profile for corrected Hybrid45 exact-40."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from glm47_posttraining.aider_polyglot.charm_grpo import (
    _canonical_bytes,
    sha256_file,
    tree_sha256,
)
from glm47_posttraining.aider_polyglot.effective_source import (
    write_effective_source_manifest,
)
from glm47_posttraining.aider_polyglot.charm_r8 import (
    CONTRACT,
    validate_corrected_exact40_dataset,
    validate_corrected_selection,
)
from glm47_posttraining.aider_polyglot.charm_r8_promotion import (
    validate_r8_promotion_split,
)

PROFILE_ID = "aider-charm-r8-candidate-hybrid45-exact40-r87-skypilot"
PROFILE_SCHEMA = "glm47-full-v5-charm-gcp-profile-v1"
EFFECTIVE_SOURCE_MANIFEST_REL = (
    "configs/full_v5_charm_grpo/r8-effective-source-manifest.json"
)
TOKENIZER_REVISION = "7dd20894a642a0aa287e9827cb1a1f7f91386b67"
TOKENIZER_MANIFEST_SHA256 = "53bcc04c0e0acedb8b57abbb03f28c29519b79a245c78784c341554ad33ce1a2"
CHAT_TEMPLATE_SHA256 = "d63ad536c3c81880043e22ec7fd08db42b4d8fb7c89c7138bc562bfa25281375"
MILES_BASE_IMAGE = (
    "radixark/miles:latest-cu12@"
    "sha256:6def6d45ffa6b34d668adcb7eeaaf8670bc38d29f5cb6e497e23a06c0ad1b900"
)
MILES_COMMIT = "8f0d065080076186ab152ee0129aceae34be756f"
VERIFIER_GCC13_BASE_IMAGE = (
    "gcc:13@sha256:4f86732b7340848efeb2b4ea4d907e2eb754eaeb6d4d26ab462b14c1e4a90c3a"
)
VERIFIER_CLANG18_BASE_IMAGE = (
    "silkeh/clang:18-bookworm@sha256:"
    "9388794775d1393c16b6897b4775b6d3e29459319de0bfafec59a20262e1fa68"
)
MILES_SOURCE_FILES = {
    "tools/convert_hf_to_torch_dist.py": (
        "0c2541d30073777a30344273a3773844a70ca1961287520c0496a1cec18d43f6"
    ),
    "miles/utils/external_utils/model_args_utils.py": (
        "9bc0bc742dac9c51300f2137bf35c6ceb224f85563735fb1b2ef3900831b9082"
    ),
    "scripts/models/glm4.7-flash.py": (
        "5533d9f88644f3b1d47c3dd869cf94b549872eaaf4879c66fab2731f1c5db571"
    ),
    "miles/backends/training_utils/loss.py": (
        "a30edc0a74356c4e470febac5d3551409dfbe8da220c7b60d60dc55293e6c602"
    ),
    "miles/backends/training_utils/loss_hub/advantages.py": (
        "3fc20719fba7448e78933c571e30aa8f54f96e7d425c4a1e6c1c0aadccacca3f"
    ),
    "miles/backends/training_utils/loss_hub/losses.py": (
        "4ddafab9cdae154f6122ef01aff86738d83713eaa49035c8e1a6df00e576e505"
    ),
    "miles/backends/training_utils/loss_hub/math_utils.py": (
        "0306b2cdadaa4effcf483b7d8e0d3a5da1a01cc83aca76ef99ae7a14c56e9cf9"
    ),
    "miles/ray/rollout/train_data_conversion.py": (
        "d4ea898d0242679146710d491e5b0bf362af8320810ff05bcafc6d4c096cab07"
    ),
    "miles/utils/arguments.py": (
        "c67e8340ff881a88844a82c9aa1e8e122e382b99c8a6167d465f3fb1ed2e73f0"
    ),
}


def _read_receipt(path: str | Path, label: str) -> tuple[Path, dict[str, Any]]:
    resolved = Path(path).resolve()
    if resolved.is_symlink() or not resolved.is_file():
        raise ValueError(f"{label} receipt is missing or unsafe: {resolved}")
    value = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} receipt must be a JSON object")
    return resolved, value


def _receipt_binding(
    repo_root: Path,
    path: Path,
    receipt: dict[str, Any],
) -> dict[str, Any]:
    try:
        relative = path.relative_to(repo_root).as_posix()
    except ValueError as exc:
        raise ValueError(f"preflight receipt is outside the repository: {path}") from exc
    return {
        "path": relative,
        "file_sha256": sha256_file(path),
        "receipt_sha256": receipt.get("receipt_sha256"),
        "schema_version": receipt.get("schema_version"),
        "decision": receipt.get("decision"),
    }


def _validate_internal_receipt(
    receipt: dict[str, Any],
    *,
    trailing_newline: bool,
) -> bool:
    expected = receipt.get("receipt_sha256")
    without_receipt = dict(receipt)
    without_receipt.pop("receipt_sha256", None)
    if trailing_newline:
        encoded = _canonical_bytes(without_receipt)
    else:
        encoded = json.dumps(
            without_receipt,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    return isinstance(expected, str) and hashlib.sha256(encoded).hexdigest() == expected


def _validate_local_preflight_receipts(
    *,
    repo_root: Path,
    runtime_root: Path,
    runtime: dict[str, Any],
    manifest: dict[str, Any],
    pretraining_revalidation: str | Path,
    reward_replay: str | Path,
    sanitizer_preflight: str | Path,
    train_prompt_preflight: str | Path,
    monitor_prompt_preflight: str | Path,
) -> dict[str, Any]:
    """Validate and bind local zero-update evidence without claiming admission."""

    runtime_tree = tree_sha256(runtime_root)
    pretraining_path, pretraining = _read_receipt(
        pretraining_revalidation, "V4.1 corpus pre-training revalidation"
    )
    if (
        pretraining.get("schema_version") != "charm-generator-admission-receipt-v4.1"
        or pretraining.get("decision") != "PASS"
        or pretraining.get("stage") != "pre-training"
        or pretraining.get("passed_rule_count") != 75
        or pretraining.get("failed_rule_count") != 0
        or pretraining.get("hard_failure_ids") != []
        or pretraining.get("subject_sha256")
        != "f3d7ec9b8eaf3a5e60752e6733efa1466fb813f0734f37f58cb3eebfa3ec29ba"
    ):
        raise ValueError("V4.1 corpus pre-training revalidation did not pass")

    oracle_path, oracle = _read_receipt(
        runtime_root / "oracle-verification-receipt.json", "executable oracle"
    )
    if (
        oracle.get("schema_version") != CONTRACT.oracle_receipt_schema
        or oracle.get("decision") != "PASS"
        or oracle.get("failure_count") != 0
        or oracle.get("task_count") != 51
        or oracle.get("dataset_manifest_sha256") != runtime["manifest_sha256"]
        or oracle.get("selection_sha256") != runtime["selection_sha256"]
        or not _validate_internal_receipt(oracle, trailing_newline=True)
    ):
        raise ValueError("executable-oracle receipt does not bind the corrected runtime")

    replay_path, replay = _read_receipt(reward_replay, "Hybrid45 no-update replay")
    if (
        replay.get("schema_version") != "charm-r8-hybrid45-corpus-no-update-replay-v1"
        or replay.get("decision") != "PASS"
        or replay.get("optimizer_updates") != 0
        or replay.get("policy_version") != CONTRACT.reward_policy
        or replay.get("task_count") != 51
        or replay.get("gradient_task_count") != 40
        or replay.get("functional_reference_pass_count") != 51
        or replay.get("gradient_full_positive_reward_count") != 40
        or replay.get("functional_failures") != []
        or replay.get("gradient_reward_failures") != []
        or replay.get("runtime_manifest_sha256") != runtime["manifest_sha256"]
        or replay.get("runtime_tree_sha256") != runtime_tree
        or replay.get("selection_sha256") != runtime["selection_sha256"]
        or replay.get("public_api_manifest_set_sha256")
        != runtime["public_api_manifest_set_sha256"]
        or not _validate_internal_receipt(replay, trailing_newline=True)
    ):
        raise ValueError("Hybrid45 no-update replay does not prove all 40 gradient tasks")

    sanitizer_path, sanitizer = _read_receipt(
        sanitizer_preflight, "sanitizer preflight"
    )
    verifier_dockerfile = repo_root / "docker/full-v5-charm-grpo-gcp/Verifier.Dockerfile"
    if (
        sanitizer.get("schema_version") != "charm-r8-sanitizer-preflight-v1"
        or sanitizer.get("decision") != "PASS"
        or sanitizer.get("normal") is not True
        or sanitizer.get("asan_ubsan_lsan") is not True
        or sanitizer.get("tsan") is not True
        or sanitizer.get("candidate_environment_inherited") is not False
        or sanitizer.get("verifier_dockerfile_sha256") != sha256_file(verifier_dockerfile)
        or sanitizer.get("verifier_image_id") != replay.get("verifier_image_id")
    ):
        raise ValueError("sanitizer preflight does not bind the replay verifier")

    def validate_prompt_receipt(
        path: str | Path,
        *,
        label: str,
        prompt_path: Path,
        expected_rows: int,
    ) -> dict[str, Any]:
        receipt_path, receipt = _read_receipt(path, label)
        tokenizer = receipt.get("tokenizer")
        maximum_observed = receipt.get("maximum_observed_prompt_tokens")
        if (
            receipt.get("schema_version") != "glm47-aider-prompt-preflight-v1"
            or receipt.get("decision") != "PASS"
            or receipt.get("expected_row_count") != expected_rows
            or receipt.get("observed_row_count") != expected_rows
            or receipt.get("maximum_prompt_tokens") != 2048
            or receipt.get("prompt_overflow_count") != 0
            or not isinstance(maximum_observed, int)
            or maximum_observed > 2048
            or receipt.get("silent_filtering_allowed") is not False
            or receipt.get("prompt_data_sha256") != sha256_file(prompt_path)
            or not isinstance(receipt.get("rows"), list)
            or len(receipt["rows"]) != expected_rows
            or not isinstance(tokenizer, dict)
            or tokenizer.get("revision") != TOKENIZER_REVISION
            or tokenizer.get("manifest_sha256") != TOKENIZER_MANIFEST_SHA256
            or tokenizer.get("chat_template_sha256") != CHAT_TEMPLATE_SHA256
            or not _validate_internal_receipt(receipt, trailing_newline=False)
        ):
            raise ValueError(f"{label} receipt does not prove the scheduled prompts")
        return {
            **_receipt_binding(repo_root, receipt_path, receipt),
            "row_count": expected_rows,
            "minimum_prompt_tokens": receipt["minimum_observed_prompt_tokens"],
            "maximum_prompt_tokens": maximum_observed,
            "prompt_data_sha256": receipt["prompt_data_sha256"],
        }

    train_path = runtime_root / str(manifest["files"]["grpo_train"])
    monitor_path = runtime_root / str(manifest["files"]["task_disjoint_monitor"])
    return {
        "scope": "local-zero-update-evidence-not-training-admission",
        "all_local_zero_update_gates_passed": True,
        "training_admission_status": "NOT_COMPLETED",
        "verifier_image_id": replay["verifier_image_id"],
        "corpus_v4_1_pretraining": _receipt_binding(
            repo_root, pretraining_path, pretraining
        ),
        "executable_oracle": _receipt_binding(repo_root, oracle_path, oracle),
        "hybrid45_corpus_replay": {
            **_receipt_binding(repo_root, replay_path, replay),
            "optimizer_updates": 0,
            "functional_reference_pass_count": 51,
            "gradient_full_positive_reward_count": 40,
        },
        "sanitizer_preflight": _receipt_binding(
            repo_root, sanitizer_path, sanitizer
        ),
        "train_prompt_preflight": validate_prompt_receipt(
            train_prompt_preflight,
            label="training prompt preflight",
            prompt_path=train_path,
            expected_rows=40,
        ),
        "monitor_prompt_preflight": validate_prompt_receipt(
            monitor_prompt_preflight,
            label="monitor prompt preflight",
            prompt_path=monitor_path,
            expected_rows=11,
        ),
    }


def _validate_canary_manifest(
    *,
    repo_root: Path,
    runtime_root: Path,
    runtime: dict[str, Any],
    manifest: dict[str, Any],
    selection: dict[str, Any],
    promotion: dict[str, Any],
    preflight_evidence: dict[str, Any],
    canary_manifest: str | Path,
) -> dict[str, Any]:
    path, payload = _read_receipt(canary_manifest, "R8 canary task manifest")
    schedule_path = runtime_root / str(manifest["files"]["canary_schedule"])
    if (
        payload.get("schema_version") != "charm-r8-canary-task-manifest-v1"
        or payload.get("decision") != "FROZEN"
        or payload.get("profile_id") != PROFILE_ID
        or payload.get("source_manifest_sha256") != runtime["manifest_sha256"]
        or payload.get("source_tree_sha256") != tree_sha256(runtime_root)
        or payload.get("selection_sha256") != runtime["selection_sha256"]
        or payload.get("reward_policy") != CONTRACT.reward_policy
        or payload.get("prompt_preflight_file_sha256")
        != preflight_evidence["train_prompt_preflight"]["file_sha256"]
        or payload.get("promotion_split_sha256") != promotion["split_sha256"]
        or payload.get("task_ids") != selection["canary_ids"]
        or not isinstance(payload.get("trial_ids"), list)
        or len(set(payload["trial_ids"])) < 4
        or payload.get("epochs") != 5
        or payload.get("optimizer_updates") != 5
        or payload.get("schedule_path") != manifest["files"]["canary_schedule"]
        or payload.get("schedule_sha256") != sha256_file(schedule_path)
        or payload.get("ordinary_task_count") != 15
        or payload.get("repair_task_count") != 5
    ):
        raise ValueError("R8 canary manifest does not bind the corrected schedule")
    return {
        "path": path.relative_to(repo_root).as_posix(),
        "sha256": sha256_file(path),
        "decision": "FROZEN",
        "task_count": 20,
        "epochs": 5,
        "optimizer_updates": 5,
        "matched_trial_count": len(set(payload["trial_ids"])),
    }


def write_candidate_skypilot_profile(
    *,
    historical_profile: str | Path,
    corrected_selection: str | Path,
    corrected_runtime: str | Path,
    promotion_split: str | Path,
    canary_manifest: str | Path,
    pretraining_revalidation: str | Path,
    reward_replay: str | Path,
    sanitizer_preflight: str | Path,
    train_prompt_preflight: str | Path,
    monitor_prompt_preflight: str | Path,
    output: str | Path,
    force: bool = False,
) -> dict[str, Any]:
    """Derive a non-runnable profile whose missing gates are explicit."""

    historical_path = Path(historical_profile).resolve()
    selection_path = Path(corrected_selection).resolve()
    runtime_root = Path(corrected_runtime).resolve()
    destination = Path(output).resolve()
    if destination.is_symlink() or (destination.exists() and not force):
        raise FileExistsError(f"refusing to overwrite corrected profile: {destination}")
    selection = validate_corrected_selection(selection_path)
    runtime = validate_corrected_exact40_dataset(runtime_root)
    manifest = json.loads((runtime_root / "manifest.json").read_text(encoding="utf-8"))
    profile = copy.deepcopy(json.loads(historical_path.read_text(encoding="utf-8")))
    repo_root = Path(__file__).resolve().parents[3]
    promotion = validate_r8_promotion_split(promotion_split)
    try:
        promotion_relative = promotion["split_path"].relative_to(repo_root).as_posix()
    except ValueError as exc:
        raise ValueError("R8 promotion split is outside the repository") from exc
    source_manifest_path = repo_root / EFFECTIVE_SOURCE_MANIFEST_REL
    source_manifest = write_effective_source_manifest(
        repo_root, source_manifest_path, force=True
    )
    profile["preflight_evidence"] = _validate_local_preflight_receipts(
        repo_root=repo_root,
        runtime_root=runtime_root,
        runtime=runtime,
        manifest=manifest,
        pretraining_revalidation=pretraining_revalidation,
        reward_replay=reward_replay,
        sanitizer_preflight=sanitizer_preflight,
        train_prompt_preflight=train_prompt_preflight,
        monitor_prompt_preflight=monitor_prompt_preflight,
    )
    canary_binding = _validate_canary_manifest(
        repo_root=repo_root,
        runtime_root=runtime_root,
        runtime=runtime,
        manifest=manifest,
        selection=selection,
        promotion=promotion,
        preflight_evidence=profile["preflight_evidence"],
        canary_manifest=canary_manifest,
    )
    profile["checkpoint_selection"] = {
        "algorithm": "weighted-development-metrics-v1",
        "implementation": (
            "glm47_posttraining.aider_polyglot.charm_r8_checkpoint_selection"
        ),
        "split_path": promotion_relative,
        "split_sha256": promotion["split_sha256"],
        "development_task_count": len(promotion["development_ids"]),
        "unseen_shadow_task_count": len(promotion["shadow_ids"]),
        **promotion["split"]["checkpoint_selection_contract"],
    }

    profile["profile_id"] = PROFILE_ID
    profile["decision"] = "NOT_COMPLETED"
    profile["source_lineage"]["rubric_update"] = {
        "historical_profile_path": str(historical_path),
        "historical_profile_sha256": sha256_file(historical_path),
        "historical_r6_checkpoint": "QUARANTINE_DIAGNOSTICS_ONLY",
        "starting_checkpoint_changed": False,
        "hybrid45_formula_changed": False,
        "curriculum_task_ids_changed": selection["selection"]["rubric_update"][
            "curriculum_task_ids_changed"
        ],
        "task_replacements": selection["selection"]["rubric_update"].get(
            "task_replacements", {}
        ),
        "downstream_admission_invalidated": True,
    }
    profile["effective_source"] = {
        "schema_version": source_manifest["schema_version"],
        "manifest_path": EFFECTIVE_SOURCE_MANIFEST_REL,
        "manifest_sha256": sha256_file(source_manifest_path),
        "source_set_sha256": source_manifest["source_set_sha256"],
        "file_count": source_manifest["file_count"],
        "git_commit_is_provenance_only": True,
    }
    profile["execution"] = {
        "profile": "gcp-skypilot-h100-tp4-ep8-dp8-candidate-r8-hybrid45-r87",
        "provisioner": "skypilot",
        "task_yaml": "grpo_h100_full_v5_charm_r8.yaml",
        "smoke_mode": "prepare-only",
        "smoke_optimizer_updates": 0,
        "canary_launcher": "managed-jobs",
        "admission_mode": "PRETRAINING_GATES_NOT_COMPLETED",
        "checkpoint_disposition": "GATED",
        "charm_eligible": True,
    }
    profile["gcp"]["instance_name"] = "skypilot-managed"
    profile["gcp"]["provisioned_status"] = "NOT_PROVISIONED"
    profile["gcp"]["provisioned_status_checked_at"] = None
    profile["gcp"]["runtime_source"] = (
        "gs://lifeandhalf-24122025-w8-biayn/glm47-full-v5/assets/runtime/"
        f"{runtime_root.name}"
    )
    profile["gcp"]["result_destination"] = (
        "gs://lifeandhalf-24122025-w8-biayn/runs/glm47/charm/r8-candidate-hybrid45-exact40-r87"
    )
    profile["full_v5_runtime"].update(
        {
            "kind": CONTRACT.dataset_kind,
            "manifest_sha256": runtime["manifest_sha256"],
            "tree_sha256": tree_sha256(runtime_root),
            "oracle_receipt_sha256": profile["preflight_evidence"]["executable_oracle"][
                "file_sha256"
            ],
            "selection_sha256": selection["selection_sha256"],
            "asset_subdir": f"runtime/{runtime_root.name}",
            "gcp_asset_status": "LOCAL_MATERIALIZED_ORACLE_PASS_UPLOAD_PENDING",
            "public_api_manifest_count": runtime["public_api_manifest_count"],
            "public_api_manifest_set_sha256": runtime["public_api_manifest_set_sha256"],
            "public_api_manifest_schema": "glm47-public-api-ast-manifest-v1",
        }
    )
    profile["training_image"].update(
        {
            "base": MILES_BASE_IMAGE,
            "local_name": "glm47-full-v5-charm-grpo:gcp-r8-corrected-hybrid45-r87",
            "registry": (
                "us-central1-docker.pkg.dev/lifeandhalf-24122025/w8-biayn/"
                "glm47-full-v5-charm-grpo:gcp-r8-corrected-hybrid45-r87"
            ),
            "miles_commit": MILES_COMMIT,
            "miles_source_files": MILES_SOURCE_FILES,
            "trainer_contract_preflight_required": True,
        }
    )
    profile["optimizer_policy"] = {
        "policy_version": "miles-standard-grpo-group-std-v1",
        "advantage_estimator": "grpo",
        "rewards_normalization": True,
        "group_std_normalization": True,
        "global_advantage_normalization": False,
        "epsilon": 1e-6,
        "dr_grpo_selected": False,
    }
    profile["verifier_image"].update(
        {
            "local_name": "glm47-full-v5-charm-verifier:gcp-r8-corrected-hybrid45-r87",
            "network": "none",
            "compile_compiler": "gcc-13.4.0",
            "public_api_compiler": "clang-18.1.8",
            "gcc13_base": VERIFIER_GCC13_BASE_IMAGE,
            "clang18_base": VERIFIER_CLANG18_BASE_IMAGE,
        }
    )
    profile["tokenizer"] = {
        "revision": TOKENIZER_REVISION,
        "manifest_path": "dataset/configs/glm47-flash-tokenizer-manifest.json",
        "manifest_sha256": TOKENIZER_MANIFEST_SHA256,
        "chat_template_path": "dataset/configs/glm47-flash-chat-template.jinja",
        "chat_template_sha256": CHAT_TEMPLATE_SHA256,
    }
    profile["full_training"]["maximum_prompt_length"] = 2048
    profile["reward"].update(
        {
            "profile": "hybrid45_v2_r8_corrected_exact40_r87",
            "implementation_mode": "hybrid_bipolar45",
            "policy_version": CONTRACT.reward_policy,
            "context_isolation_required": True,
            "chat_template_sha256": CHAT_TEMPLATE_SHA256,
            "tsan_execution_allowed": True,
            "tsan_preflight_required": True,
            "repair_bonus": False,
        }
    )
    profile["reward"]["signal_thresholds"] = {
        "minimum_positive_groups": 1,
        "minimum_semantic_variance_groups": 2,
        "minimum_reward_variance_groups": 2,
        "minimum_kernel_variance_groups": 2,
        "require_unique_task_groups": True,
        "minimum_exact_format_rate": 0.50,
        "minimum_compile_rate": 0.20,
    }
    profile["admission"].update(
        {
            "pretraining_receipt": "NOT_COMPLETED",
            "sft_ready_manifest_sha256": "INVALIDATED_BY_RUBRIC_UPDATE",
            "promotion_evaluation_split": {
                "path": promotion_relative,
                "sha256": promotion["split_sha256"],
                "decision": "FROZEN",
                "development_task_count": len(promotion["development_ids"]),
                "unseen_shadow_task_count": len(promotion["shadow_ids"]),
                "calibration_tasks_are_post_selection_only": True,
            },
            "canary_task_manifest": canary_binding,
            "canary_result": "NOT_COMPLETED",
            "promotion_receipt": "NOT_COMPLETED",
            "full_training_authorized": False,
            "charm_eligible": True,
            "checkpoint_disposition": "GATED",
            "retroactive_admission_allowed": False,
        }
    )
    profile["tracking"]["wandb_project"] = "glm47-aider-charm-r8-corrected-hybrid45-r87"
    profile["task_selection"].update(
        {
            "ranking": "frozen-r8-rewardable-selection-v2",
            "selection_sha256": selection["selection_sha256"],
        }
    )
    profile["full_v5_runtime"]["targets"] = int(manifest["counts"]["certified_source_tasks"])

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(profile, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, destination)
    return profile
