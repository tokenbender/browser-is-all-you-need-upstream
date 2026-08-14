#!/usr/bin/env python3
"""Prepare and run admission-gated full-v5 plus CHARM GRPO on GCP."""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from glm47_posttraining.aider_polyglot.full_v5_charm import (
    SCHEDULE_KIND,
    build_charm_schedule,
    read_jsonl,
    sha256_path,
    validate_full_v5_package,
)
from glm47_posttraining.aider_polyglot.charm_grpo import tree_sha256
from glm47_posttraining.aider_polyglot.charm_r7 import (
    DATASET_KIND as R7_DATASET_KIND,
    validate_charm_r7_exact40_dataset,
)
from glm47_posttraining.aider_polyglot.charm_r8 import (
    validate_corrected_exact40_dataset,
)
from glm47_posttraining.aider_polyglot.charm_r8_profile import (
    MILES_BASE_IMAGE as R8_MILES_BASE_IMAGE,
    MILES_COMMIT as R8_MILES_COMMIT,
    MILES_SOURCE_FILES as R8_MILES_SOURCE_FILES,
    VERIFIER_CLANG18_BASE_IMAGE as R8_VERIFIER_CLANG18_BASE_IMAGE,
    VERIFIER_GCC13_BASE_IMAGE as R8_VERIFIER_GCC13_BASE_IMAGE,
)
from glm47_posttraining.aider_polyglot.grpo_advantage_contract import (
    POLICY_VERSION as GRPO_ADVANTAGE_POLICY_VERSION,
)
from glm47_posttraining.aider_polyglot.effective_source import (
    validate_effective_source_manifest,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = REPO_ROOT / "configs/full_v5_charm_grpo/gcp-r1.json"
CONFIG_PATH = Path(
    os.environ.get("GLM47_FULL_V5_CONFIG_PATH", str(DEFAULT_CONFIG_PATH))
).expanduser()
if not CONFIG_PATH.is_absolute():
    CONFIG_PATH = REPO_ROOT / CONFIG_PATH
ASSET_ROOT = Path(
    os.environ.get("GLM47_FULL_V5_ASSET_ROOT", "/opt/glm47-full-v5/assets")
).expanduser()
MODEL_DIR = ASSET_ROOT / "model/GLM-4.7-Flash"
ADAPTER_DIR = ASSET_ROOT / "synthmem-v1-ep50/adapter"
REF_LOAD_DIR = MODEL_DIR.parent / "GLM-4.7-Flash_torch_dist_tp4_pp1_ep8"
REF_LOAD_MARKER = REF_LOAD_DIR / "latest_checkpointed_iteration.txt"
MILES_MODEL_ARGS_COMPAT_PATH = REPO_ROOT / "configs/miles/glm4.7-flash.sh"
MILES_MODEL_ARGS_COMPAT_CONTAINER_PATH = "/root/miles/scripts/models/glm4.7-flash.sh"
RESULT_ROOT = Path(
    os.environ.get("GLM47_FULL_V5_RESULT_ROOT", "/opt/glm47-full-v5/results")
).expanduser()
LOCK_PATH = Path("/tmp/glm47-gpu-heavy.lock")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FULL_AUTHORIZATION_ENV = "GLM47_FULL_V5_CHARM_FULL_TRAINING_AUTHORIZATION"
FULL_AUTHORIZATION_PHRASE = "I_AUTHORIZE_FULL_V5_CHARM_57_UPDATE_TRAINING"
EXPERIMENT_AUTHORIZATION_ENV = "GLM47_FULL_V5_UNADMITTED_EXPERIMENT_AUTHORIZATION"
EXPERIMENT_AUTHORIZATION_PHRASE = "I_AUTHORIZE_UNADMITTED_R2_57_UPDATE_EXPERIMENT_AND_GCP_COSTS"
EXPERIMENT_PROFILE_ID = "aider-full-v5-experimental-unadmitted-r2-api-contracts"
EXPERIMENT_SKYPILOT_PROFILE_ID = "aider-full-v5-experimental-unadmitted-r2-api-contracts-skypilot"
EXPERIMENT_R3_PROFILE_ID = "aider-full-v5-experimental-unadmitted-r3-thinking-final-v1"
EXPERIMENT_R3_SMOKE_PROFILE_ID = "aider-full-v5-experimental-unadmitted-r3-thinking-final-v1-smoke"
EXPERIMENT_R4_PROFILE_ID = "aider-full-v5-experimental-unadmitted-r4-thinking-final-pack34816-v1"
EXPERIMENT_R4_SMOKE_PROFILE_ID = (
    "aider-full-v5-experimental-unadmitted-r4-thinking-final-pack34816-v1-smoke"
)
EXPERIMENT_R5_PROFILE_ID = (
    "aider-full-v5-experimental-unadmitted-r5-thinking-final-resp16384-pack18432-v1"
)
EXPERIMENT_R5_SMOKE_PROFILE_ID = (
    "aider-full-v5-experimental-unadmitted-r5-thinking-final-resp16384-pack18432-v1-smoke"
)
EXPERIMENT_R6_V2_PROFILE_ID = "aider-full-v5-experimental-unadmitted-r6-hybrid45-v2-full"
EXPERIMENT_R6_V2_SMOKE_PROFILE_ID = "aider-full-v5-experimental-unadmitted-r6-hybrid45-v2-smoke"
EXPERIMENT_R6_V2_FOUR_TOPIC40_PROFILE_ID = (
    "aider-full-v5-experimental-unadmitted-r6-hybrid45-v2-four-topic40"
)
ADMITTED_R7_MEF_R87_PROFILE_ID = "aider-charm-r7-admitted-mef-exact40-r87"
ADMITTED_R7_MEF_R87_SKYPILOT_PROFILE_ID = "aider-charm-r7-admitted-mef-exact40-r87-skypilot"
PROFILE_OVERLAY_SCHEMA = "glm47-full-v5-charm-gcp-profile-overlay-v1"
ADMITTED_R7_MEF_R87_BASE_CONFIG_REL = (
    "configs/full_v5_charm_grpo/gcp-r7-admitted-mef-exact40-r87.json"
)
CORRECTED_R8_HYBRID45_R87_SKYPILOT_PROFILE_ID = (
    "aider-charm-r8-candidate-hybrid45-exact40-r87-skypilot"
)
UNADMITTED_R8_HYBRID45_R87_SKYPILOT_PROFILE_ID = (
    "aider-charm-r8-experimental-unadmitted-hybrid45-exact40-r87-skypilot"
)
ADMITTED_R7_MEF_R87_BASE_CONFIG_SHA256 = (
    "f4fcd3d54c88b36e7d92c302c49caefc4dfdf5062c1ce1800e4eaa6250eb549e"
)
FOUR_TOPIC40_TASK_IDS = (
    "aider-cpp-rl/all-different-validator",
    "aider-cpp-rl/allowed-assignment-solver",
    "aider-cpp-rl/arithmetic-coil",
    "aider-cpp-rl/axis-mirror-metrics",
    "aider-cpp-rl/burn-perimeter-wave",
    "aider-cpp-rl/coil-cursor",
    "aider-cpp-rl/coil-position-index",
    "aider-cpp-rl/coiled-rectangle-fill",
    "aider-cpp-rl/daily-instant-formatter",
    "aider-cpp-rl/daily-minute-normalizer",
    "aider-cpp-rl/daily-window-overlap",
    "aider-cpp-rl/directed-neighbor-clues",
    "aider-cpp-rl/dock-logistics-riddle",
    "aider-cpp-rl/finite-countdown-state",
    "aider-cpp-rl/forward-daily-gap",
    "aider-cpp-rl/laboratory-color-assignment",
    "aider-cpp-rl/left-turn-corner-fill",
    "aider-cpp-rl/migration-dag-validator-v2",
    "aider-cpp-rl/next-weekly-events",
    "aider-cpp-rl/offset-localizer",
    "aider-cpp-rl/oriented-coil-path",
    "aider-cpp-rl/paired-polynomial-evaluator",
    "aider-cpp-rl/paired-product-rule",
    "aider-cpp-rl/planar-affine-step",
    "aider-cpp-rl/planar-pair-sum",
    "aider-cpp-rl/polar-pair-builder",
    "aider-cpp-rl/precise-period-ratio",
    "aider-cpp-rl/pruned-schedule-count",
    "aider-cpp-rl/quadratic-orbit-counter",
    "aider-cpp-rl/right-turn-boundary-walk",
    "aider-cpp-rl/safe-paired-quotient",
    "aider-cpp-rl/safe-square-coil",
    "aider-cpp-rl/single-frequency-projection",
    "aider-cpp-rl/small-permutation-catalog",
    "aider-cpp-rl/time-school-bell-repair",
    "aider-cpp-rl/typed-position-clues",
    "aider-cpp-rl/unique-assignment-audit",
    "aider-cpp-rl/warehouse-coil-route",
    "aider-cpp-rl/weekly-minute-index",
    "aider-cpp-rl/wrapped-window-membership",
)
EXPERIMENT_PROFILE_IDS = {
    EXPERIMENT_PROFILE_ID,
    EXPERIMENT_SKYPILOT_PROFILE_ID,
    EXPERIMENT_R3_PROFILE_ID,
    EXPERIMENT_R3_SMOKE_PROFILE_ID,
    EXPERIMENT_R4_PROFILE_ID,
    EXPERIMENT_R4_SMOKE_PROFILE_ID,
    EXPERIMENT_R5_PROFILE_ID,
    EXPERIMENT_R5_SMOKE_PROFILE_ID,
    EXPERIMENT_R6_V2_PROFILE_ID,
    EXPERIMENT_R6_V2_SMOKE_PROFILE_ID,
    EXPERIMENT_R6_V2_FOUR_TOPIC40_PROFILE_ID,
    UNADMITTED_R8_HYBRID45_R87_SKYPILOT_PROFILE_ID,
}
EXPERIMENT_RUN_ID_PREFIX = "unadmitted-r2-"
EXPERIMENT_RESULT_DESTINATION = (
    "gs://lifeandhalf-24122025-w8-biayn/runs/glm47/experiments/unadmitted-full-v5-r2"
)
DURABLE_SYNC_EXCLUDE_RE = (
    r"(^|/)(runtime_state|wandb|checkpoints)(/|$)"
    r"|(^|/)([^/]*\.tmp([.-][^/]*)?|torchinductor_root)(/|$)"
)
LIVE_SYNC_EXCLUDE_RE = (
    r"(^|/)(runtime_state|wandb|checkpoints|rollout_dumps)(/|$)"
    r"|(^|/)([^/]*\.tmp([.-][^/]*)?|torchinductor_root)(/|$)"
)
CHECKPOINT_ITERATION_RE = re.compile(r"^iter_(\d+)$")
EXPECTED_CHECKPOINT_NATIVE_SHARDS = {
    f"adapter_megatron_tp{rank % 4}_pp0_ep{rank}.pt" for rank in range(8)
}
EXPECTED_CHECKPOINT_TRAINING_STATES = {f"training_state_rank{rank}.pt" for rank in range(8)}
PROFILE_CONTRACTS = {
    "aider-full-v5-production-ast17-gcp-r1": {
        "provisioner": "skypilot",
        "runtime_manifest_sha256": (
            "93d671faa44abcc6deca21c6a49e247d76436835bfa2905ee33968a478fb532a"
        ),
        "runtime_tree_sha256": ("0a3df3ce40eed45814651c933277bfc5ca17359a2b3e6f0a7027b184e3569c7e"),
        "runtime_asset_subdir": "runtime/aider_cpp_rl_full_v5",
    },
    "aider-full-v5-production-ast17-gcp-r2-api-contracts": {
        "profile_class": "production",
        "provisioner": "gce-existing-vm",
        "runtime_manifest_sha256": (
            "7e23cf99c0bfcd5bec56aa53cb3c1960282fab742c4edd835efd47fa5092d605"
        ),
        "runtime_tree_sha256": ("06a644c59f94837d587b6eb0242e7242ad8c81efa8161e53ca0cac59de668bad"),
        "runtime_asset_subdir": ("runtime/aider_cpp_rl_full_v5_api_contracts_r2"),
    },
    EXPERIMENT_PROFILE_ID: {
        "profile_class": "unadmitted_experiment",
        "provisioner": "gce-existing-vm",
        "authorization_env": EXPERIMENT_AUTHORIZATION_ENV,
        "authorization_phrase": EXPERIMENT_AUTHORIZATION_PHRASE,
        "run_id_prefix": EXPERIMENT_RUN_ID_PREFIX,
        "result_destination": EXPERIMENT_RESULT_DESTINATION,
        "rollout_updates": 57,
        "runtime_manifest_sha256": (
            "7e23cf99c0bfcd5bec56aa53cb3c1960282fab742c4edd835efd47fa5092d605"
        ),
        "runtime_tree_sha256": ("06a644c59f94837d587b6eb0242e7242ad8c81efa8161e53ca0cac59de668bad"),
        "runtime_asset_subdir": ("runtime/aider_cpp_rl_full_v5_api_contracts_r2"),
    },
    EXPERIMENT_SKYPILOT_PROFILE_ID: {
        "profile_class": "unadmitted_experiment",
        "provisioner": "skypilot",
        "authorization_env": EXPERIMENT_AUTHORIZATION_ENV,
        "authorization_phrase": EXPERIMENT_AUTHORIZATION_PHRASE,
        "run_id_prefix": EXPERIMENT_RUN_ID_PREFIX,
        "result_destination": EXPERIMENT_RESULT_DESTINATION,
        "rollout_updates": 57,
        "runtime_manifest_sha256": (
            "7e23cf99c0bfcd5bec56aa53cb3c1960282fab742c4edd835efd47fa5092d605"
        ),
        "runtime_tree_sha256": ("06a644c59f94837d587b6eb0242e7242ad8c81efa8161e53ca0cac59de668bad"),
        "runtime_asset_subdir": ("runtime/aider_cpp_rl_full_v5_api_contracts_r2"),
    },
    EXPERIMENT_R3_PROFILE_ID: {
        "profile_class": "unadmitted_experiment",
        "provisioner": "gce-existing-vm",
        "authorization_env": "GLM47_FULL_V5_UNADMITTED_EXPERIMENT_AUTHORIZATION",
        "authorization_phrase": ("I_AUTHORIZE_UNADMITTED_R3_57_UPDATE_EXPERIMENT_AND_GCP_COSTS"),
        "run_id_prefix": "unadmitted-r3-full-",
        "result_destination": (
            "gs://lifeandhalf-24122025-w8-biayn/runs/glm47/experiments/"
            "unadmitted-full-v5-r3-thinking-final-v1"
        ),
        "rollout_updates": 57,
        "training_image": "glm47-full-v5-unadmitted-grpo:gcp-r3-thinking-final-v1",
        "response_contract": "glm47-thinking-final-answer-v1",
        "sync_contract": "durable-marker-last-v1",
        "requires_smoke_receipt": True,
        "smoke_profile_id": EXPERIMENT_R3_SMOKE_PROFILE_ID,
        "smoke_permit_field": "permits_r3_57_update_launch",
        "maximum_tokens_per_gpu": 49152,
        "minimum_free_storage_gib": 220,
        "runtime_manifest_sha256": (
            "7e23cf99c0bfcd5bec56aa53cb3c1960282fab742c4edd835efd47fa5092d605"
        ),
        "runtime_tree_sha256": ("06a644c59f94837d587b6eb0242e7242ad8c81efa8161e53ca0cac59de668bad"),
        "runtime_asset_subdir": "runtime/aider_cpp_rl_full_v5_api_contracts_r2",
    },
    EXPERIMENT_R3_SMOKE_PROFILE_ID: {
        "profile_class": "unadmitted_experiment",
        "provisioner": "gce-existing-vm",
        "smoke_mode": "one-update",
        "authorization_env": "GLM47_FULL_V5_UNADMITTED_SMOKE_AUTHORIZATION",
        "authorization_phrase": ("I_AUTHORIZE_UNADMITTED_R3_ONE_UPDATE_SMOKE_AND_GCP_COSTS"),
        "run_id_prefix": "unadmitted-r3-smoke-",
        "result_destination": (
            "gs://lifeandhalf-24122025-w8-biayn/runs/glm47/experiments/"
            "unadmitted-smoke-r3-thinking-final-v1"
        ),
        "rollout_updates": 1,
        "training_image": "glm47-full-v5-unadmitted-grpo:gcp-r3-thinking-final-v1",
        "response_contract": "glm47-thinking-final-answer-v1",
        "sync_contract": "durable-marker-last-v1",
        "minimum_free_storage_gib": 220,
        "maximum_tokens_per_gpu": 49152,
        "runtime_manifest_sha256": (
            "7e23cf99c0bfcd5bec56aa53cb3c1960282fab742c4edd835efd47fa5092d605"
        ),
        "runtime_tree_sha256": ("06a644c59f94837d587b6eb0242e7242ad8c81efa8161e53ca0cac59de668bad"),
        "runtime_asset_subdir": "runtime/aider_cpp_rl_full_v5_api_contracts_r2",
    },
    EXPERIMENT_R4_PROFILE_ID: {
        "profile_class": "unadmitted_experiment",
        "provisioner": "gce-existing-vm",
        "authorization_env": "GLM47_FULL_V5_UNADMITTED_EXPERIMENT_AUTHORIZATION",
        "authorization_phrase": ("I_AUTHORIZE_UNADMITTED_R4_57_UPDATE_EXPERIMENT_AND_GCP_COSTS"),
        "run_id_prefix": "unadmitted-r4-full-",
        "result_destination": (
            "gs://lifeandhalf-24122025-w8-biayn/runs/glm47/experiments/"
            "unadmitted-full-v5-r4-thinking-final-pack34816-v1"
        ),
        "rollout_updates": 57,
        "training_image": ("glm47-full-v5-unadmitted-grpo:gcp-r4-thinking-final-pack34816-v1"),
        "response_contract": "glm47-thinking-final-answer-v1",
        "sync_contract": "durable-marker-last-v1",
        "requires_smoke_receipt": True,
        "smoke_profile_id": EXPERIMENT_R4_SMOKE_PROFILE_ID,
        "smoke_permit_field": "permits_r4_57_update_launch",
        "minimum_free_storage_gib": 220,
        "maximum_tokens_per_gpu": 34816,
        "required_provisioning_policy": "SPOT",
        "runtime_manifest_sha256": (
            "7e23cf99c0bfcd5bec56aa53cb3c1960282fab742c4edd835efd47fa5092d605"
        ),
        "runtime_tree_sha256": ("06a644c59f94837d587b6eb0242e7242ad8c81efa8161e53ca0cac59de668bad"),
        "runtime_asset_subdir": "runtime/aider_cpp_rl_full_v5_api_contracts_r2",
    },
    EXPERIMENT_R4_SMOKE_PROFILE_ID: {
        "profile_class": "unadmitted_experiment",
        "provisioner": "gce-existing-vm",
        "smoke_mode": "one-update",
        "authorization_env": "GLM47_FULL_V5_UNADMITTED_SMOKE_AUTHORIZATION",
        "authorization_phrase": ("I_AUTHORIZE_UNADMITTED_R4_ONE_UPDATE_SMOKE_AND_GCP_COSTS"),
        "run_id_prefix": "unadmitted-r4-smoke-",
        "result_destination": (
            "gs://lifeandhalf-24122025-w8-biayn/runs/glm47/experiments/"
            "unadmitted-smoke-r4-thinking-final-pack34816-v1"
        ),
        "rollout_updates": 1,
        "training_image": ("glm47-full-v5-unadmitted-grpo:gcp-r4-thinking-final-pack34816-v1"),
        "response_contract": "glm47-thinking-final-answer-v1",
        "sync_contract": "durable-marker-last-v1",
        "minimum_free_storage_gib": 220,
        "maximum_tokens_per_gpu": 34816,
        "required_provisioning_policy": "SPOT",
        "runtime_manifest_sha256": (
            "7e23cf99c0bfcd5bec56aa53cb3c1960282fab742c4edd835efd47fa5092d605"
        ),
        "runtime_tree_sha256": ("06a644c59f94837d587b6eb0242e7242ad8c81efa8161e53ca0cac59de668bad"),
        "runtime_asset_subdir": "runtime/aider_cpp_rl_full_v5_api_contracts_r2",
    },
    EXPERIMENT_R5_PROFILE_ID: {
        "profile_class": "unadmitted_experiment",
        "provisioner": "gce-existing-vm",
        "authorization_env": "GLM47_FULL_V5_UNADMITTED_EXPERIMENT_AUTHORIZATION",
        "authorization_phrase": ("I_AUTHORIZE_UNADMITTED_R5_57_UPDATE_EXPERIMENT_AND_GCP_COSTS"),
        "run_id_prefix": "unadmitted-r5-full-",
        "result_destination": (
            "gs://lifeandhalf-24122025-w8-biayn/runs/glm47/experiments/"
            "unadmitted-full-v5-r5-thinking-final-resp16384-pack18432-v1"
        ),
        "rollout_updates": 57,
        "training_image": (
            "glm47-full-v5-unadmitted-grpo:gcp-r5-thinking-final-resp16384-pack18432-v1"
        ),
        "response_contract": "glm47-thinking-final-answer-v1",
        "sync_contract": "durable-marker-last-v1",
        "requires_smoke_receipt": True,
        "smoke_profile_id": EXPERIMENT_R5_SMOKE_PROFILE_ID,
        "smoke_permit_field": "permits_r5_57_update_launch",
        "minimum_free_storage_gib": 220,
        "maximum_response_length": 16384,
        "maximum_tokens_per_gpu": 18432,
        "required_provisioning_policy": "SPOT",
        "runtime_manifest_sha256": (
            "7e23cf99c0bfcd5bec56aa53cb3c1960282fab742c4edd835efd47fa5092d605"
        ),
        "runtime_tree_sha256": ("06a644c59f94837d587b6eb0242e7242ad8c81efa8161e53ca0cac59de668bad"),
        "runtime_asset_subdir": "runtime/aider_cpp_rl_full_v5_api_contracts_r2",
    },
    EXPERIMENT_R5_SMOKE_PROFILE_ID: {
        "profile_class": "unadmitted_experiment",
        "provisioner": "gce-existing-vm",
        "smoke_mode": "one-update",
        "authorization_env": "GLM47_FULL_V5_UNADMITTED_SMOKE_AUTHORIZATION",
        "authorization_phrase": ("I_AUTHORIZE_UNADMITTED_R5_ONE_UPDATE_SMOKE_AND_GCP_COSTS"),
        "run_id_prefix": "unadmitted-r5-smoke-",
        "result_destination": (
            "gs://lifeandhalf-24122025-w8-biayn/runs/glm47/experiments/"
            "unadmitted-smoke-r5-thinking-final-resp16384-pack18432-v1"
        ),
        "rollout_updates": 1,
        "training_image": (
            "glm47-full-v5-unadmitted-grpo:gcp-r5-thinking-final-resp16384-pack18432-v1"
        ),
        "response_contract": "glm47-thinking-final-answer-v1",
        "sync_contract": "durable-marker-last-v1",
        "minimum_free_storage_gib": 220,
        "maximum_response_length": 16384,
        "maximum_tokens_per_gpu": 18432,
        "required_provisioning_policy": "SPOT",
        "runtime_manifest_sha256": (
            "7e23cf99c0bfcd5bec56aa53cb3c1960282fab742c4edd835efd47fa5092d605"
        ),
        "runtime_tree_sha256": ("06a644c59f94837d587b6eb0242e7242ad8c81efa8161e53ca0cac59de668bad"),
        "runtime_asset_subdir": "runtime/aider_cpp_rl_full_v5_api_contracts_r2",
    },
    EXPERIMENT_R6_V2_PROFILE_ID: {
        "profile_class": "unadmitted_experiment",
        "provisioner": "gce-existing-vm",
        "authorization_env": "GLM47_FULL_V5_HYBRID45_V2_EXPERIMENT_AUTHORIZATION",
        "authorization_phrase": (
            "I_AUTHORIZE_UNADMITTED_R6_HYBRID45_V2_57_UPDATE_EXPERIMENT_AND_GCP_COSTS"
        ),
        "run_id_prefix": "unadmitted-r6-v2-full-",
        "result_destination": (
            "gs://lifeandhalf-24122025-w8-biayn/runs/glm47/experiments/"
            "unadmitted-r6-hybrid45-v2-full"
        ),
        "rollout_updates": 57,
        "training_image": "glm47-full-v5-unadmitted-grpo:gcp-r6-hybrid45-v2",
        "response_contract": "glm47-thinking-final-answer-v1",
        "reward_mode": "hybrid_bipolar45",
        "reward_policy": "hybrid-bipolar45-v2",
        "sync_contract": "durable-marker-last-v1",
        "requires_smoke_receipt": True,
        "smoke_profile_id": EXPERIMENT_R6_V2_SMOKE_PROFILE_ID,
        "smoke_permit_field": "permits_r6_v2_57_update_launch",
        "minimum_free_storage_gib": 220,
        "maximum_response_length": 16384,
        "maximum_tokens_per_gpu": 18432,
        "required_provisioning_policy": "SPOT",
        "task_selection": {
            "harness_kind": "aider_cpp17",
            "ranking": "sha256-task-id-ascending-v1",
            "count": 475,
            "selected_task_ids_sha256": (
                "074b37fe2668f64bf5ceac2e70a5860716c2954fe8f5cad101471c6f3393615a"
            ),
        },
        "runtime_manifest_sha256": (
            "7e23cf99c0bfcd5bec56aa53cb3c1960282fab742c4edd835efd47fa5092d605"
        ),
        "runtime_tree_sha256": ("06a644c59f94837d587b6eb0242e7242ad8c81efa8161e53ca0cac59de668bad"),
        "runtime_asset_subdir": "runtime/aider_cpp_rl_full_v5_api_contracts_r2",
    },
    EXPERIMENT_R6_V2_FOUR_TOPIC40_PROFILE_ID: {
        "profile_class": "unadmitted_experiment",
        "provisioner": "gce-existing-vm",
        "authorization_env": ("GLM47_FULL_V5_HYBRID45_V2_FOUR_TOPIC40_EXPERIMENT_AUTHORIZATION"),
        "authorization_phrase": (
            "I_AUTHORIZE_UNADMITTED_R6_HYBRID45_V2_FOUR_TOPIC40_6_UPDATE_EXPERIMENT_AND_GCP_COSTS"
        ),
        "run_id_prefix": "unadmitted-r6-v2-four-topic40-",
        "result_destination": (
            "gs://lifeandhalf-24122025-w8-biayn/runs/glm47/experiments/"
            "unadmitted-r6-hybrid45-v2-four-topic40"
        ),
        "rollout_updates": 6,
        "training_image": "glm47-full-v5-unadmitted-grpo:gcp-r6-hybrid45-v2",
        "response_contract": "glm47-thinking-final-answer-v1",
        "reward_mode": "hybrid_bipolar45",
        "reward_policy": "hybrid-bipolar45-v2",
        "sync_contract": "durable-marker-last-v1",
        "requires_smoke_receipt": True,
        "smoke_profile_id": EXPERIMENT_R6_V2_SMOKE_PROFILE_ID,
        "smoke_permit_field": "permits_r6_v2_57_update_launch",
        "minimum_free_storage_gib": 220,
        "maximum_response_length": 16384,
        "maximum_tokens_per_gpu": 18432,
        "required_provisioning_policy": "SPOT",
        "tsan_preflight_required": False,
        "tsan_execution_allowed": False,
        "task_selection": {
            "harness_kind": "aider_cpp17",
            "ranking": "explicit-task-id-list-v1",
            "count": 40,
            "topic_counts": {
                "clock": 10,
                "complex-numbers": 10,
                "spiral-matrix": 10,
                "zebra-puzzle": 10,
            },
            "task_ids": list(FOUR_TOPIC40_TASK_IDS),
            "selected_task_ids_sha256": (
                "d7dae7ca5cde5aab9025d95d55eb88877854d5b19aac181f05924e809d7b6c65"
            ),
        },
        "runtime_manifest_sha256": (
            "7e23cf99c0bfcd5bec56aa53cb3c1960282fab742c4edd835efd47fa5092d605"
        ),
        "runtime_tree_sha256": ("06a644c59f94837d587b6eb0242e7242ad8c81efa8161e53ca0cac59de668bad"),
        "runtime_asset_subdir": "runtime/aider_cpp_rl_full_v5_api_contracts_r2",
    },
    ADMITTED_R7_MEF_R87_PROFILE_ID: {
        "profile_class": "admitted_charm",
        "provisioner": "gce-existing-vm",
        "authorization_env": "GLM47_CHARM_R7_FULL_TRAINING_AUTHORIZATION",
        "authorization_phrase": (
            "I_AUTHORIZE_CHARM_R7_ADMITTED_MEF_EXACT40_FULL_TRAINING_AND_GCP_COSTS"
        ),
        "run_id_prefix": "charm-r7-r87-",
        "result_destination": (
            "gs://lifeandhalf-24122025-w8-biayn/runs/glm47/charm/r7-admitted-mef-exact40-r87"
        ),
        "rollout_updates": 6,
        "training_image": "glm47-full-v5-charm-grpo:gcp-r7-admitted-mef-r87",
        "response_contract": "glm47-thinking-final-answer-v1",
        "reward_mode": "hybrid_bipolar45_mef",
        "reward_policy": "hybrid-bipolar45-mef-v1",
        "sync_contract": "durable-marker-last-v1",
        "minimum_free_storage_gib": 220,
        "maximum_response_length": 16384,
        "maximum_tokens_per_gpu": 18432,
        "required_provisioning_policy": "SPOT",
        "tsan_preflight_required": False,
        "tsan_execution_allowed": False,
        "runtime_manifest_sha256": (
            "3229c159e298f24cb96f4d777cffdbedcb523e0561caeba62755ddb7e0ff637b"
        ),
        "runtime_tree_sha256": ("88a65fc1dae1909d33e1053fd4fe8f8493a45a3c3968ec7b68fea1afc0826dca"),
        "runtime_asset_subdir": ("runtime/charm-r7-admitted-mef-exact40-r87-20260812T190000Z"),
        "oracle_receipt_sha256": (
            "6374d83da31bf027cc4ad21bae8f42d7924a8f172d70a840f101bb6134bd8404"
        ),
        "selection_sha256": ("435a672df93755ab1baeaad355c9f52294de931838d0d58ec3570475328acdf6"),
        "canary_manifest_sha256": (
            "5308b5a260d8a4dd467cfe833298f47b6c05ecb04047f0d114e052a36410cf67"
        ),
        "rollout_shuffle": False,
    },
    EXPERIMENT_R6_V2_SMOKE_PROFILE_ID: {
        "profile_class": "unadmitted_experiment",
        "provisioner": "gce-existing-vm",
        "smoke_mode": "one-update",
        "authorization_env": "GLM47_FULL_V5_HYBRID45_V2_SMOKE_AUTHORIZATION",
        "authorization_phrase": (
            "I_AUTHORIZE_UNADMITTED_R6_HYBRID45_V2_ONE_UPDATE_SMOKE_AND_GCP_COSTS"
        ),
        "run_id_prefix": "unadmitted-r6-v2-smoke-",
        "result_destination": (
            "gs://lifeandhalf-24122025-w8-biayn/runs/glm47/experiments/"
            "unadmitted-r6-hybrid45-v2-smoke"
        ),
        "rollout_updates": 1,
        "training_image": "glm47-full-v5-unadmitted-grpo:gcp-r6-hybrid45-v2",
        "response_contract": "glm47-thinking-final-answer-v1",
        "reward_mode": "hybrid_bipolar45",
        "reward_policy": "hybrid-bipolar45-v2",
        "sync_contract": "durable-marker-last-v1",
        "minimum_free_storage_gib": 220,
        "maximum_response_length": 16384,
        "maximum_tokens_per_gpu": 18432,
        "required_provisioning_policy": "SPOT",
        "task_selection": {
            "harness_kind": "aider_cpp17",
            "ranking": "sha256-task-id-ascending-v1",
            "count": 475,
            "selected_task_ids_sha256": (
                "074b37fe2668f64bf5ceac2e70a5860716c2954fe8f5cad101471c6f3393615a"
            ),
        },
        "runtime_manifest_sha256": (
            "7e23cf99c0bfcd5bec56aa53cb3c1960282fab742c4edd835efd47fa5092d605"
        ),
        "runtime_tree_sha256": ("06a644c59f94837d587b6eb0242e7242ad8c81efa8161e53ca0cac59de668bad"),
        "runtime_asset_subdir": "runtime/aider_cpp_rl_full_v5_api_contracts_r2",
    },
}

# Keep the admitted R7 data, model, reward, and optimization contract byte-for-byte
# identical.  The separate profile changes only the infrastructure provisioner.
PROFILE_CONTRACTS[ADMITTED_R7_MEF_R87_SKYPILOT_PROFILE_ID] = {
    **PROFILE_CONTRACTS[ADMITTED_R7_MEF_R87_PROFILE_ID],
    "provisioner": "skypilot",
}
PROFILE_CONTRACTS[CORRECTED_R8_HYBRID45_R87_SKYPILOT_PROFILE_ID] = {
    "profile_class": "candidate_charm",
    "provisioner": "skypilot",
    "run_id_prefix": "charm-r8-r87-",
    "result_destination": (
        "gs://lifeandhalf-24122025-w8-biayn/runs/glm47/charm/r8-candidate-hybrid45-exact40-r87"
    ),
    "rollout_updates": 6,
    "training_image": "glm47-full-v5-charm-grpo:gcp-r8-corrected-hybrid45-r87",
    "response_contract": "glm47-thinking-final-answer-v1",
    "reward_mode": "hybrid_bipolar45",
    "reward_policy": "hybrid-bipolar45-v2",
    "sync_contract": "durable-marker-last-v1",
    "minimum_free_storage_gib": 220,
    "maximum_response_length": 16384,
    "maximum_tokens_per_gpu": 18432,
    "required_provisioning_policy": "SPOT",
    "tsan_preflight_required": True,
    "tsan_execution_allowed": True,
    "runtime_kind": "charm-r8-candidate-hybrid45-exact40",
    "runtime_schema": "charm-grpo-exact40-runtime-v2",
    "runtime_tree_sha256": ("b1fff05e66a4198dca8d74ae41e2837e0926b24b8acfb281822bd08583554075"),
    "runtime_manifest_sha256": ("72296f7bae1b4690a613922f3f29b2011e4a8646d356a4e7663cfc5822e7bfd2"),
    "runtime_public_api_manifest_set_sha256": (
        "691eaa29592877385ff10b265a592c7e9884214f279eae0a8c31fe879535be64"
    ),
    "runtime_asset_subdir": (
        "runtime/charm-r8-candidate-hybrid45-exact40-r87-rewardable-20260813T044420Z"
    ),
    "selection_sha256": ("b340fbd212f7ba8472161448ac8a579abc91178d3d0731e3e546470594ae1788"),
    "oracle_receipt_sha256": ("f3878a58fe6fb7b4412d00a90eab732230c823ff0c73d0409669ebf18b878ce6"),
    "promotion_split_sha256": (
        "817aa22252acf9c6687313396be7d59b79052585ead9fbb6a2cdae797275e858"
    ),
    "canary_manifest_sha256": (
        "83624d84f04dd479f415329f65ab6602d6a5d1be8f98dde64a82fe199bbe1b63"
    ),
    "local_preflight_receipts": {
        "corpus_v4_1_pretraining": {
            "file_sha256": "f129fb2c953e7c87fae3f796c9c04c546943f0ad8518c0cfc795a85c1c4218e0",
            "receipt_sha256": None,
        },
        "executable_oracle": {
            "file_sha256": "f3878a58fe6fb7b4412d00a90eab732230c823ff0c73d0409669ebf18b878ce6",
            "receipt_sha256": "0b033bc84873ca4bbf0264053cfa08e0cf6d125597e11bdad41818bf4c721e66",
        },
        "hybrid45_corpus_replay": {
            "file_sha256": "fd0e5560a864ae3bb29f48b9b0dc522013bad278f60e20cc6bb48bfb3b491593",
            "receipt_sha256": "3bf7cf32b8140de292ebb9193808373a506ed8b163fe57ab7e51219e8ff022bf",
        },
        "sanitizer_preflight": {
            "file_sha256": "363042ba6b406e69a483f3c38aa5d608b9ab0e2399a3b258d4f898455ea13ac0",
            "receipt_sha256": None,
        },
        "train_prompt_preflight": {
            "file_sha256": "94a19103e324ef2d8ba16fdcebe59aacc6114bfce939bfbd54b62d07df433f19",
            "receipt_sha256": "63dc4b647e281ca141834bdc72c17bdce15f360724d9cde13a7a9ec695b8c4f6",
        },
        "monitor_prompt_preflight": {
            "file_sha256": "eb946a4cabe749de19a703423937306f9102db57fdd9d1621f078b78f3427530",
            "receipt_sha256": "8b1c8b8dc31c30d688c14d0ca1f85c941b8b1d24077534f6398208daf32627eb",
        },
    },
    "rollout_shuffle": False,
    "miles_base_image": R8_MILES_BASE_IMAGE,
    "miles_commit": R8_MILES_COMMIT,
    "miles_source_files": R8_MILES_SOURCE_FILES,
    "verifier_toolchain": {
        "compile_compiler": "gcc-13.4.0",
        "public_api_compiler": "clang-18.1.8",
        "gcc13_base": R8_VERIFIER_GCC13_BASE_IMAGE,
        "clang18_base": R8_VERIFIER_CLANG18_BASE_IMAGE,
    },
    "optimizer_policy": {
        "policy_version": GRPO_ADVANTAGE_POLICY_VERSION,
        "advantage_estimator": "grpo",
        "rewards_normalization": True,
        "group_std_normalization": True,
        "global_advantage_normalization": False,
        "epsilon": 1e-6,
        "dr_grpo_selected": False,
    },
    "exact40_runtime": True,
}
PROFILE_CONTRACTS[UNADMITTED_R8_HYBRID45_R87_SKYPILOT_PROFILE_ID] = {
    **PROFILE_CONTRACTS[CORRECTED_R8_HYBRID45_R87_SKYPILOT_PROFILE_ID],
    "profile_class": "unadmitted_experiment",
    "authorization_env": "GLM47_CHARM_R8_UNADMITTED_FULL_AUTHORIZATION",
    "authorization_phrase": (
        "I_AUTHORIZE_UNADMITTED_R8_HYBRID45_EXACT40_6_UPDATE_EXPERIMENT_AND_GCP_COSTS"
    ),
    "run_id_prefix": "unadmitted-r8-r87-",
    "result_destination": (
        "gs://lifeandhalf-24122025-w8-biayn/runs/glm47/experiments/"
        "unadmitted-r8-hybrid45-exact40-r87"
    ),
    "training_image": (
        "glm47-full-v5-unadmitted-grpo:"
        "gcp-r8-hybrid45-exact40-r87-asleepfix-20260814"
    ),
    "training_registry_digest": "sha256:5df1c41efb6062a292ac68a49d68ad955d9f8209c182d3fc2f7e8c634ca076a2",
    "training_immutable_ref": "us-central1-docker.pkg.dev/lifeandhalf-24122025/w8-biayn/glm47-full-v5-unadmitted-grpo@sha256:5df1c41efb6062a292ac68a49d68ad955d9f8209c182d3fc2f7e8c634ca076a2",
    "verifier_registry_digest": "sha256:14c9e6e468ff65b3f205eeaf95dbcc6bd509e6515dbd601089a1cdca8fa66464",
    "verifier_immutable_ref": "us-central1-docker.pkg.dev/lifeandhalf-24122025/w8-biayn/glm47-full-v5-charm-verifier@sha256:14c9e6e468ff65b3f205eeaf95dbcc6bd509e6515dbd601089a1cdca8fa66464",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_config_document() -> dict[str, Any]:
    document = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if document.get("schema_version") != PROFILE_OVERLAY_SCHEMA:
        return document

    required_keys = {
        "schema_version",
        "profile_id",
        "base_config_path",
        "base_config_sha256",
        "execution",
    }
    if set(document) != required_keys:
        raise RuntimeError("GCP profile overlay has unexpected or missing fields")
    if (
        document.get("profile_id") != ADMITTED_R7_MEF_R87_SKYPILOT_PROFILE_ID
        or document.get("base_config_path") != ADMITTED_R7_MEF_R87_BASE_CONFIG_REL
        or document.get("base_config_sha256") != ADMITTED_R7_MEF_R87_BASE_CONFIG_SHA256
    ):
        raise RuntimeError("GCP profile overlay does not bind the frozen R7 base")

    base_path = (REPO_ROOT / ADMITTED_R7_MEF_R87_BASE_CONFIG_REL).resolve()
    try:
        base_path.relative_to(REPO_ROOT.resolve())
    except ValueError as exc:
        raise RuntimeError("GCP profile overlay base escapes the repository") from exc
    if sha256_path(base_path) != ADMITTED_R7_MEF_R87_BASE_CONFIG_SHA256:
        raise RuntimeError("GCP profile overlay base-config digest mismatch")
    config = json.loads(base_path.read_text(encoding="utf-8"))
    if (
        config.get("schema_version") != "glm47-full-v5-charm-gcp-profile-v1"
        or config.get("profile_id") != ADMITTED_R7_MEF_R87_PROFILE_ID
    ):
        raise RuntimeError("GCP profile overlay base is not the frozen admitted R7 profile")
    config["profile_id"] = document["profile_id"]
    config["execution"] = document["execution"]
    return config


def load_config() -> dict[str, Any]:
    config = _resolve_config_document()
    profile_id = str(config.get("profile_id", ""))
    profile_contract = PROFILE_CONTRACTS.get(profile_id)
    if (
        config.get("schema_version") != "glm47-full-v5-charm-gcp-profile-v1"
        or profile_contract is None
        or config.get("modal_policy", {}).get("default") != "DENY"
        or config.get("execution", {}).get("provisioner") != profile_contract["provisioner"]
        or config.get("execution", {}).get("smoke_mode")
        != profile_contract.get("smoke_mode", "prepare-only")
        or config.get("gcp", {}).get("gpu_count") != 8
        or config.get("gcp", {}).get("machine_type") != "a3-highgpu-8g"
        or config.get("starting_adapter", {}).get("profile") != "synthmem-v1-ep50"
        or config.get("starting_adapter", {}).get("checkpoint_path")
        != "checkpoints/sft_lora_r16/iter_0000649"
        or config.get("starting_adapter", {}).get("epoch") != 50
        or config.get("starting_adapter", {}).get("optimizer_iteration") != 649
        or config.get("starting_adapter", {}).get("adapter_model_sha256")
        != "4acb7f23c295f45380155c5d9ee6bc59422262f0cb51f0c02f7e550d405b575a"
        or config.get("starting_adapter", {}).get("gcp_asset_status") != "AVAILABLE"
        or config.get("canary", {}).get("task_count") != 20
        or config.get("canary", {}).get("epochs") != 5
        or config.get("canary", {}).get("matched_trials") < 4
        or config.get("full_training", {}).get("rollout_updates")
        != profile_contract.get("rollout_updates", 57)
        or config.get("full_training", {}).get("thinking_enabled") is not True
        or config.get("reward", {}).get("signal_gate_required") is not True
        or config.get("admission", {}).get("fixed26_role") != "FROZEN_POST_TRAINING_EVALUATION_ONLY"
        or config.get("full_v5_runtime", {}).get("manifest_sha256")
        != profile_contract["runtime_manifest_sha256"]
        or config.get("full_v5_runtime", {}).get("tree_sha256")
        != profile_contract["runtime_tree_sha256"]
        or config.get("full_v5_runtime", {}).get("asset_subdir")
        != profile_contract["runtime_asset_subdir"]
    ):
        raise RuntimeError("GCP full-v5 CHARM profile is not the frozen production contract")
    if profile_contract.get("profile_class") == "unadmitted_experiment":
        admission = config.get("admission", {})
        execution = config.get("execution", {})
        if (
            config.get("decision") != "EXPERIMENTAL_UNADMITTED"
            or execution.get("admission_mode") != "UNADMITTED_EXPERIMENT_ONLY"
            or execution.get("checkpoint_disposition") != "QUARANTINE_ONLY"
            or execution.get("charm_eligible") is not False
            or config.get("gcp", {}).get("result_destination")
            != profile_contract.get("result_destination")
            or admission.get("pretraining_receipt") != "NOT_COMPLETED"
            or admission.get("canary_result") != "NOT_COMPLETED"
            or admission.get("promotion_receipt") != "NOT_COMPLETED"
            or admission.get("full_training_authorized") is not False
            or admission.get("charm_eligible") is not False
            or admission.get("checkpoint_disposition") != "QUARANTINE_ONLY"
            or admission.get("retroactive_admission_allowed") is not False
            or (
                profile_contract.get("training_image") is not None
                and config.get("training_image", {}).get("local_name")
                != profile_contract["training_image"]
            )
            or (
                profile_contract.get("response_contract") is not None
                and config.get("reward", {}).get("response_contract")
                != profile_contract["response_contract"]
            )
            or (
                profile_contract.get("sync_contract") is not None
                and config.get("tracking", {}).get("sync_contract")
                != profile_contract["sync_contract"]
            )
            or int(config.get("tracking", {}).get("minimum_free_storage_gib", 250))
            != int(profile_contract.get("minimum_free_storage_gib", 250))
            or (
                profile_contract.get("maximum_tokens_per_gpu") is not None
                and int(config.get("full_training", {}).get("maximum_tokens_per_gpu", 0))
                != int(profile_contract["maximum_tokens_per_gpu"])
            )
            or (
                profile_contract.get("maximum_response_length") is not None
                and int(config.get("full_training", {}).get("maximum_response_length", 0))
                != int(profile_contract["maximum_response_length"])
            )
            or (
                profile_contract.get("required_provisioning_policy") is not None
                and str(config.get("gcp", {}).get("provisioning_policy", "")).upper()
                != str(profile_contract["required_provisioning_policy"]).upper()
            )
            or (
                profile_contract.get("reward_mode") is not None
                and config.get("reward", {}).get("implementation_mode")
                != profile_contract["reward_mode"]
            )
            or (
                profile_contract.get("reward_policy") is not None
                and config.get("reward", {}).get("policy_version")
                != profile_contract["reward_policy"]
            )
            or (
                profile_contract.get("tsan_preflight_required") is not None
                and config.get("reward", {}).get("tsan_preflight_required")
                is not profile_contract["tsan_preflight_required"]
            )
            or (
                profile_contract.get("tsan_execution_allowed") is not None
                and config.get("reward", {}).get("tsan_execution_allowed")
                is not profile_contract["tsan_execution_allowed"]
            )
            or (
                profile_contract.get("task_selection") is not None
                and config.get("task_selection") != profile_contract["task_selection"]
            )
            or (
                profile_contract.get("training_registry_digest") is not None
                and config.get("training_image", {}).get("registry_digest")
                != profile_contract["training_registry_digest"]
            )
            or (
                profile_contract.get("training_immutable_ref") is not None
                and config.get("training_image", {}).get("immutable_ref")
                != profile_contract["training_immutable_ref"]
            )
            or (
                profile_contract.get("verifier_registry_digest") is not None
                and config.get("verifier_image", {}).get("registry_digest")
                != profile_contract["verifier_registry_digest"]
            )
            or (
                profile_contract.get("verifier_immutable_ref") is not None
                and config.get("verifier_image", {}).get("immutable_ref")
                != profile_contract["verifier_immutable_ref"]
            )
        ):
            raise RuntimeError(
                "unadmitted experiment profile does not preserve quarantine boundaries"
            )
    if profile_contract.get("profile_class") == "admitted_charm":
        _validate_admitted_r7_config(config, profile_contract)
    if profile_contract.get("profile_class") == "candidate_charm":
        _validate_candidate_r8_config(config, profile_contract)
    if profile_id == UNADMITTED_R8_HYBRID45_R87_SKYPILOT_PROFILE_ID:
        _validate_unadmitted_r8_config(config, profile_contract)
    return config


def is_experimental_profile(config: Mapping[str, Any]) -> bool:
    profile = PROFILE_CONTRACTS.get(str(config.get("profile_id")), {})
    return profile.get("profile_class") == "unadmitted_experiment"


def is_candidate_charm_profile(config: Mapping[str, Any]) -> bool:
    profile = PROFILE_CONTRACTS.get(str(config.get("profile_id")), {})
    return profile.get("profile_class") == "candidate_charm"


def is_r7_profile(config: Mapping[str, Any]) -> bool:
    """Return whether a profile uses the receipt-bound exact-40 runtime layout."""

    profile = PROFILE_CONTRACTS.get(str(config.get("profile_id")), {})
    return profile.get("profile_class") in {"admitted_charm", "candidate_charm"} or bool(
        profile.get("exact40_runtime")
    )


def _validate_admitted_r7_config(
    config: Mapping[str, Any], profile_contract: Mapping[str, Any]
) -> None:
    admission = config.get("admission", {})
    execution = config.get("execution", {})
    pretraining = admission.get("pretraining_receipt", {})
    canary_manifest = admission.get("canary_task_manifest", {})
    checks = {
        "decision": config.get("decision") == "ADMITTED_CANARY",
        "admission_mode": execution.get("admission_mode") == "PRETRAINING_PASS_CANARY_REQUIRED",
        "execution_disposition": execution.get("checkpoint_disposition") == "GATED",
        "execution_charm": execution.get("charm_eligible") is True,
        "result_destination": config.get("gcp", {}).get("result_destination")
        == profile_contract["result_destination"],
        "training_image": config.get("training_image", {}).get("local_name")
        == profile_contract["training_image"],
        "response_contract": config.get("reward", {}).get("response_contract")
        == profile_contract["response_contract"],
        "reward_mode": config.get("reward", {}).get("implementation_mode")
        == profile_contract["reward_mode"],
        "reward_policy": config.get("reward", {}).get("policy_version")
        == profile_contract["reward_policy"],
        "tsan_preflight": config.get("reward", {}).get("tsan_preflight_required")
        is profile_contract["tsan_preflight_required"],
        "tsan_execution": config.get("reward", {}).get("tsan_execution_allowed")
        is profile_contract["tsan_execution_allowed"],
        "sync_contract": config.get("tracking", {}).get("sync_contract")
        == profile_contract["sync_contract"],
        "storage": int(config.get("tracking", {}).get("minimum_free_storage_gib", 0))
        == int(profile_contract["minimum_free_storage_gib"]),
        "response_length": int(config.get("full_training", {}).get("maximum_response_length", 0))
        == int(profile_contract["maximum_response_length"]),
        "token_pack": int(config.get("full_training", {}).get("maximum_tokens_per_gpu", 0))
        == int(profile_contract["maximum_tokens_per_gpu"]),
        "provisioning": str(config.get("gcp", {}).get("provisioning_policy", "")).upper()
        == profile_contract["required_provisioning_policy"],
        "runtime_kind": config.get("full_v5_runtime", {}).get("kind") == R7_DATASET_KIND,
        "oracle": config.get("full_v5_runtime", {}).get("oracle_receipt_sha256")
        == profile_contract["oracle_receipt_sha256"],
        "selection": config.get("full_v5_runtime", {}).get("selection_sha256")
        == profile_contract["selection_sha256"],
        "pretraining": isinstance(pretraining, Mapping)
        and pretraining.get("sha256")
        == "f129fb2c953e7c87fae3f796c9c04c546943f0ad8518c0cfc795a85c1c4218e0",
        "canary_manifest": isinstance(canary_manifest, Mapping)
        and canary_manifest.get("sha256") == profile_contract["canary_manifest_sha256"],
        "canary_pending": admission.get("canary_result") == "NOT_COMPLETED",
        "promotion_pending": admission.get("promotion_receipt") == "NOT_COMPLETED",
        "full_pending": admission.get("full_training_authorized") is False,
        "canary_epoch_batches": config.get("canary", {}).get("rollout_shuffle")
        is profile_contract["rollout_shuffle"],
        "full_epoch_batches": config.get("full_training", {}).get("rollout_shuffle")
        is profile_contract["rollout_shuffle"],
        "admission_charm": admission.get("charm_eligible") is True,
        "admission_disposition": admission.get("checkpoint_disposition") == "GATED",
        "no_retroactive": admission.get("retroactive_admission_allowed") is False,
    }
    failed = sorted(name for name, passed in checks.items() if not passed)
    if failed:
        raise RuntimeError(
            "admitted R7 profile does not preserve its pre-training and canary gates: "
            + ", ".join(failed)
        )


def _validate_candidate_r8_config(
    config: Mapping[str, Any], profile_contract: Mapping[str, Any]
) -> None:
    admission = config.get("admission", {})
    execution = config.get("execution", {})
    runtime = config.get("full_v5_runtime", {})
    reward = config.get("reward", {})
    tokenizer = config.get("tokenizer", {})
    canary_manifest = admission.get("canary_task_manifest", {})
    preflight = config.get("preflight_evidence", {})
    checkpoint_selection = config.get("checkpoint_selection", {})
    promotion_split = admission.get("promotion_evaluation_split", {})
    expected_preflight_receipts = profile_contract["local_preflight_receipts"]
    preflight_receipts_match = isinstance(preflight, Mapping) and all(
        isinstance(preflight.get(name), Mapping)
        and "file_sha256" in preflight[name]
        and "receipt_sha256" in preflight[name]
        and {
            "file_sha256": preflight[name].get("file_sha256"),
            "receipt_sha256": preflight[name].get("receipt_sha256"),
        }
        == expected
        for name, expected in expected_preflight_receipts.items()
    )
    frozen_thresholds = {
        "minimum_positive_groups": 1,
        "minimum_semantic_variance_groups": 2,
        "minimum_reward_variance_groups": 2,
        "minimum_kernel_variance_groups": 2,
        "require_unique_task_groups": True,
        "minimum_exact_format_rate": 0.50,
        "minimum_compile_rate": 0.20,
    }
    effective_source = config.get("effective_source", {})
    effective_source_path = REPO_ROOT / str(effective_source.get("manifest_path", ""))
    try:
        effective_source_validation = validate_effective_source_manifest(
            REPO_ROOT,
            effective_source_path,
            expected_file_sha256=str(effective_source.get("manifest_sha256", "")),
        )
    except (OSError, ValueError, json.JSONDecodeError):
        effective_source_validation = None
    checks = {
        "decision": config.get("decision") == "NOT_COMPLETED",
        "admission_mode": execution.get("admission_mode") == "PRETRAINING_GATES_NOT_COMPLETED",
        "skypilot": execution.get("provisioner") == "skypilot",
        "checkpoint_gated": execution.get("checkpoint_disposition") == "GATED",
        "effective_source": effective_source_validation is not None
        and effective_source_validation.get("source_set_sha256")
        == effective_source.get("source_set_sha256")
        and effective_source_validation.get("file_count") == effective_source.get("file_count")
        and effective_source.get("git_commit_is_provenance_only") is True,
        "execution_charm": execution.get("charm_eligible") is True,
        "result_destination": config.get("gcp", {}).get("result_destination")
        == profile_contract["result_destination"],
        "runtime_kind": runtime.get("kind") == profile_contract["runtime_kind"],
        "runtime_selection": runtime.get("selection_sha256")
        == profile_contract["selection_sha256"],
        "runtime_public_api_count": runtime.get("public_api_manifest_count") == 51,
        "runtime_public_api_schema": runtime.get("public_api_manifest_schema")
        == "glm47-public-api-ast-manifest-v1",
        "runtime_public_api_set": runtime.get("public_api_manifest_set_sha256")
        == profile_contract["runtime_public_api_manifest_set_sha256"],
        "verifier_toolchain": config.get("verifier_image", {})
        == {
            "dockerfile": "docker/full-v5-charm-grpo-gcp/Verifier.Dockerfile",
            "local_name": "glm47-full-v5-charm-verifier:gcp-r8-corrected-hybrid45-r87",
            "network": "none",
            **profile_contract["verifier_toolchain"],
        },
        "oracle_bound": runtime.get("oracle_receipt_sha256")
        == profile_contract["oracle_receipt_sha256"],
        "asset_pending": runtime.get("gcp_asset_status")
        == "LOCAL_MATERIALIZED_ORACLE_PASS_UPLOAD_PENDING",
        "local_preflight_scope": isinstance(preflight, Mapping)
        and preflight.get("scope") == "local-zero-update-evidence-not-training-admission"
        and preflight.get("all_local_zero_update_gates_passed") is True
        and preflight.get("training_admission_status") == "NOT_COMPLETED",
        "local_preflight_receipts": preflight_receipts_match,
        "local_replay_counts": isinstance(
            preflight.get("hybrid45_corpus_replay"), Mapping
        )
        and preflight["hybrid45_corpus_replay"].get("optimizer_updates") == 0
        and preflight["hybrid45_corpus_replay"].get(
            "functional_reference_pass_count"
        )
        == 51
        and preflight["hybrid45_corpus_replay"].get(
            "gradient_full_positive_reward_count"
        )
        == 40,
        "local_prompt_counts": isinstance(
            preflight.get("train_prompt_preflight"), Mapping
        )
        and preflight["train_prompt_preflight"].get("row_count") == 40
        and int(preflight["train_prompt_preflight"].get("maximum_prompt_tokens", 2049))
        <= 2048
        and isinstance(preflight.get("monitor_prompt_preflight"), Mapping)
        and preflight["monitor_prompt_preflight"].get("row_count") == 11
        and int(preflight["monitor_prompt_preflight"].get("maximum_prompt_tokens", 2049))
        <= 2048,
        "training_image": config.get("training_image", {}).get("local_name")
        == profile_contract["training_image"],
        "miles_base_image": config.get("training_image", {}).get("base")
        == profile_contract["miles_base_image"],
        "miles_commit": config.get("training_image", {}).get("miles_commit")
        == profile_contract["miles_commit"],
        "miles_source_files": config.get("training_image", {}).get("miles_source_files")
        == profile_contract["miles_source_files"],
        "trainer_preflight": config.get("training_image", {}).get(
            "trainer_contract_preflight_required"
        )
        is True,
        "optimizer_policy": config.get("optimizer_policy") == profile_contract["optimizer_policy"],
        "reward_mode": reward.get("implementation_mode") == profile_contract["reward_mode"],
        "reward_policy": reward.get("policy_version") == profile_contract["reward_policy"],
        "reward_formula_unchanged": reward.get("repair_bonus") is False,
        "context_isolation": reward.get("context_isolation_required") is True,
        "signal_thresholds": reward.get("signal_thresholds") == frozen_thresholds,
        "tsan_preflight": reward.get("tsan_preflight_required") is True,
        "tsan_execution": reward.get("tsan_execution_allowed") is True,
        "tokenizer_revision": isinstance(tokenizer, Mapping)
        and tokenizer.get("revision") == "7dd20894a642a0aa287e9827cb1a1f7f91386b67",
        "tokenizer_manifest": isinstance(tokenizer, Mapping)
        and tokenizer.get("manifest_sha256")
        == "53bcc04c0e0acedb8b57abbb03f28c29519b79a245c78784c341554ad33ce1a2",
        "chat_template": isinstance(tokenizer, Mapping)
        and tokenizer.get("chat_template_sha256")
        == "d63ad536c3c81880043e22ec7fd08db42b4d8fb7c89c7138bc562bfa25281375",
        "prompt_limit": config.get("full_training", {}).get("maximum_prompt_length") == 2048,
        "promotion_split": isinstance(promotion_split, Mapping)
        and promotion_split.get("sha256") == profile_contract["promotion_split_sha256"]
        and promotion_split.get("decision") == "FROZEN"
        and promotion_split.get("development_task_count") == 6
        and promotion_split.get("unseen_shadow_task_count") == 5
        and promotion_split.get("calibration_tasks_are_post_selection_only") is True,
        "checkpoint_selection": isinstance(checkpoint_selection, Mapping)
        and checkpoint_selection.get("algorithm") == "weighted-development-metrics-v1"
        and checkpoint_selection.get("split_sha256")
        == profile_contract["promotion_split_sha256"]
        and checkpoint_selection.get("expected_canary_checkpoint_count") == 5
        and checkpoint_selection.get("weights")
        == {
            "compile_rate": 0.4,
            "hidden_test_pass_rate": 0.4,
            "validation_loss": 0.2,
        }
        and checkpoint_selection.get("validation_loss_utility")
        == "one_over_one_plus_loss"
        and checkpoint_selection.get("always_final") is False
        and checkpoint_selection.get("final_checkpoint_competes_on_metrics") is True
        and checkpoint_selection.get("shadow_metrics_excluded") is True,
        "canary_selection_policy": config.get("canary", {}).get("selection_policy")
        == {
            "compile_rate_weight": 0.4,
            "hidden_test_rate_weight": 0.4,
            "validation_loss_weight": 0.2,
            "always_final": False,
        },
        "pretraining_pending": admission.get("pretraining_receipt") == "NOT_COMPLETED",
        "canary_manifest": isinstance(canary_manifest, Mapping)
        and canary_manifest.get("sha256")
        == profile_contract["canary_manifest_sha256"]
        and canary_manifest.get("decision") == "FROZEN"
        and canary_manifest.get("task_count") == 20
        and canary_manifest.get("epochs") == 5
        and canary_manifest.get("optimizer_updates") == 5
        and int(canary_manifest.get("matched_trial_count", 0)) >= 4,
        "canary_pending": admission.get("canary_result") == "NOT_COMPLETED",
        "promotion_pending": admission.get("promotion_receipt") == "NOT_COMPLETED",
        "full_blocked": admission.get("full_training_authorized") is False,
        "admission_charm": admission.get("charm_eligible") is True,
        "admission_disposition": admission.get("checkpoint_disposition") == "GATED",
        "no_retroactive": admission.get("retroactive_admission_allowed") is False,
    }
    failed = sorted(name for name, passed in checks.items() if not passed)
    if failed:
        raise RuntimeError(
            "corrected R8 candidate does not preserve fail-closed gates: " + ", ".join(failed)
        )


def _validate_unadmitted_r8_config(
    config: Mapping[str, Any], profile_contract: Mapping[str, Any]
) -> None:
    """Bind direct-full R8 to corrected bytes while preserving quarantine."""

    execution = config.get("execution", {})
    admission = config.get("admission", {})
    runtime = config.get("full_v5_runtime", {})
    training = config.get("full_training", {})
    reward = config.get("reward", {})
    preflight = config.get("preflight_evidence", {})
    effective_source = config.get("effective_source", {})
    try:
        source_validation = validate_effective_source_manifest(
            REPO_ROOT,
            REPO_ROOT / str(effective_source.get("manifest_path", "")),
            expected_file_sha256=str(effective_source.get("manifest_sha256", "")),
        )
    except (OSError, ValueError, json.JSONDecodeError):
        source_validation = None
    expected_receipts = profile_contract["local_preflight_receipts"]
    receipts_match = isinstance(preflight, Mapping) and all(
        isinstance(preflight.get(name), Mapping)
        and {
            "file_sha256": preflight[name].get("file_sha256"),
            "receipt_sha256": preflight[name].get("receipt_sha256"),
        }
        == expected
        for name, expected in expected_receipts.items()
    )
    frozen_thresholds = {
        "minimum_positive_groups": 1,
        "minimum_semantic_variance_groups": 2,
        "minimum_reward_variance_groups": 2,
        "minimum_kernel_variance_groups": 2,
        "require_unique_task_groups": True,
        "minimum_exact_format_rate": 0.50,
        "minimum_compile_rate": 0.20,
    }
    experimental = config.get("experimental_contract", {})
    checks = {
        "source": source_validation is not None
        and source_validation.get("source_set_sha256")
        == effective_source.get("source_set_sha256")
        and source_validation.get("file_count") == effective_source.get("file_count"),
        "execution": execution.get("provisioner") == "skypilot"
        and execution.get("admission_mode") == "UNADMITTED_EXPERIMENT_ONLY"
        and execution.get("checkpoint_disposition") == "QUARANTINE_ONLY"
        and execution.get("charm_eligible") is False,
        "runtime": runtime.get("kind") == profile_contract["runtime_kind"]
        and runtime.get("manifest_sha256") == profile_contract["runtime_manifest_sha256"]
        and runtime.get("tree_sha256") == profile_contract["runtime_tree_sha256"]
        and runtime.get("selection_sha256") == profile_contract["selection_sha256"]
        and runtime.get("oracle_receipt_sha256")
        == profile_contract["oracle_receipt_sha256"]
        and runtime.get("public_api_manifest_set_sha256")
        == profile_contract["runtime_public_api_manifest_set_sha256"]
        and runtime.get("train_targets") == 40,
        "training": training.get("train_targets") == 40
        and training.get("development_targets") == 11
        and training.get("epochs") == 3
        and training.get("rollout_batch_size") == 20
        and training.get("global_batch_size") == 160
        and training.get("rollout_updates") == 6
        and training.get("rollout_shuffle") is False
        and training.get("requires_canary_promotion_pass") is False,
        "reward": reward.get("implementation_mode") == profile_contract["reward_mode"]
        and reward.get("policy_version") == profile_contract["reward_policy"]
        and reward.get("repair_bonus") is False
        and reward.get("context_isolation_required") is True
        and reward.get("signal_thresholds") == frozen_thresholds
        and reward.get("tsan_preflight_required") is True
        and reward.get("tsan_execution_allowed") is True,
        "optimizer": config.get("optimizer_policy") == profile_contract["optimizer_policy"],
        "preflight": receipts_match
        and preflight.get("all_local_zero_update_gates_passed") is True
        and preflight.get("training_admission_status") == "NOT_COMPLETED",
        "admission": admission.get("pretraining_receipt") == "NOT_COMPLETED"
        and admission.get("canary_result") == "NOT_COMPLETED"
        and admission.get("promotion_receipt") == "NOT_COMPLETED"
        and admission.get("full_training_authorized") is False
        and admission.get("charm_eligible") is False
        and admission.get("checkpoint_disposition") == "QUARANTINE_ONLY"
        and admission.get("retroactive_admission_allowed") is False,
        "quarantine": experimental.get("eligible_for_charm_promotion") is False
        and experimental.get("retroactive_admission_allowed") is False
        and experimental.get("canary_skipped_by_operator") is True
        and experimental.get("direct_full_is_not_evidence_of_charm_admission") is True,
    }
    failed = sorted(name for name, passed in checks.items() if not passed)
    if failed:
        raise RuntimeError(
            "unadmitted R8 direct-full profile changed corrected quarantine bindings: "
            + ", ".join(failed)
        )


def runtime_dir(config: Mapping[str, Any] | None = None) -> Path:
    override = os.environ.get("GLM47_FULL_V5_RUNTIME_DIR")
    if override:
        return Path(override).expanduser()
    selected = config or load_config()
    return ASSET_ROOT / str(selected["full_v5_runtime"]["asset_subdir"])


def selected_experimental_task_ids(config: Mapping[str, Any]) -> list[str] | None:
    """Resolve and bind a deterministic reward-compatible experiment subset."""

    profile_contract = PROFILE_CONTRACTS[str(config["profile_id"])]
    selection = profile_contract.get("task_selection")
    if not isinstance(selection, Mapping):
        return None
    ranking = selection.get("ranking")
    if ranking not in {"sha256-task-id-ascending-v1", "explicit-task-id-list-v1"}:
        raise RuntimeError("unsupported experimental task-selection algorithm")
    source_manifest = json.loads(
        (runtime_dir(config) / "manifest.json").read_text(encoding="utf-8")
    )
    train_path = runtime_dir(config) / str(source_manifest["files"]["grpo_train"])
    harness_kind = str(selection["harness_kind"])
    candidates = {
        str(row.get("task_id", ""))
        for row in read_jsonl(train_path)
        if isinstance(row.get("metadata"), Mapping)
        and row["metadata"].get("harness_kind") == harness_kind
    }
    if "" in candidates:
        raise RuntimeError("task selection encountered an empty task ID")
    count = int(selection["count"])
    if ranking == "explicit-task-id-list-v1":
        declared = selection.get("task_ids")
        if (
            not isinstance(declared, list)
            or len(declared) != count
            or len(set(declared)) != count
            or not all(isinstance(task_id, str) and task_id for task_id in declared)
        ):
            raise RuntimeError("explicit experimental task selection is malformed")
        selected = sorted(declared)
        missing = sorted(set(selected) - candidates)
        if missing:
            raise RuntimeError(
                f"explicit task selection contains incompatible tasks: {missing[:5]}"
            )
    else:
        ranked = sorted(
            candidates,
            key=lambda task_id: (hashlib.sha256(task_id.encode()).hexdigest(), task_id),
        )
        if len(ranked) < count:
            raise RuntimeError(
                f"task selection requires {count} {harness_kind} tasks; found {len(ranked)}"
            )
        selected = sorted(ranked[:count])
    observed_sha256 = hashlib.sha256(("\n".join(selected) + "\n").encode()).hexdigest()
    if observed_sha256 != selection.get("selected_task_ids_sha256"):
        raise RuntimeError(
            "experimental task-selection digest mismatch: "
            f"{observed_sha256} != {selection.get('selected_task_ids_sha256')}"
        )
    return selected


def source_commit() -> str:
    override = os.environ.get("GLM47_SOURCE_COMMIT", "").strip()
    if override:
        if re.fullmatch(r"[0-9a-f]{40}", override):
            return override
        raise RuntimeError("GLM47_SOURCE_COMMIT must be a lowercase 40-character Git SHA")
    try:
        return output(["git", "rev-parse", "HEAD"])
    except (OSError, subprocess.CalledProcessError):
        marker = REPO_ROOT / "SOURCE_COMMIT"
        value = marker.read_text(encoding="utf-8").strip() if marker.is_file() else ""
        if re.fullmatch(r"[0-9a-f]{40}", value):
            return value
        raise RuntimeError("source commit is unavailable")


def docker_prefix() -> list[str]:
    if os.geteuid() == 0:
        return ["docker"]
    if shutil.which("sudo"):
        return ["sudo", "docker"]
    return ["docker"]


def docker_image_id(image: str) -> str:
    value = output(docker_prefix() + ["image", "inspect", "--format={{.Id}}", image])
    if re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise RuntimeError(f"Docker image has no immutable content ID: {image} -> {value!r}")
    return value


def docker_repo_digests(image: str) -> set[str]:
    """Return registry identities without conflating them with Docker image IDs."""

    value = output(
        docker_prefix()
        + ["image", "inspect", "--format={{json .RepoDigests}}", image]
    )
    try:
        records = json.loads(value)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Docker image has invalid repository digests: {image} -> {value!r}"
        ) from exc
    if not isinstance(records, list) or any(not isinstance(item, str) for item in records):
        raise RuntimeError(
            f"Docker image has invalid repository digests: {image} -> {value!r}"
        )
    digests = set(records)
    if not digests:
        raise RuntimeError(f"Docker image has no immutable registry identity: {image}")
    return digests


def run(command: Sequence[str], *, env: Mapping[str, str] | None = None) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(list(command), cwd=REPO_ROOT, env=env, check=True)


def output(command: Sequence[str]) -> str:
    return subprocess.check_output(list(command), cwd=REPO_ROOT, text=True).strip()


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite receipt: {path}")
    temporary = path.with_suffix(path.suffix + f".tmp-{os.getpid()}")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def gpu_inventory() -> list[dict[str, Any]]:
    if shutil.which("nvidia-smi") is None:
        return []
    raw = output(
        [
            "nvidia-smi",
            "--query-gpu=index,name,memory.total,uuid",
            "--format=csv,noheader,nounits",
        ]
    )
    inventory = []
    for line in raw.splitlines():
        index, name, memory, uuid = [part.strip() for part in line.split(",", 3)]
        inventory.append(
            {"index": int(index), "name": name, "memory_mib": int(memory), "uuid": uuid}
        )
    return inventory


def require_h100() -> list[dict[str, Any]]:
    config = load_config()["gcp"]
    inventory = gpu_inventory()
    valid = len(inventory) == int(config["gpu_count"]) and all(
        str(config["gpu_model_contains"]) in str(item["name"])
        and int(item["memory_mib"]) >= int(config["minimum_gpu_memory_mib"])
        for item in inventory
    )
    if not valid:
        found = [(item["name"], item["memory_mib"]) for item in inventory]
        raise RuntimeError(f"training requires exactly eight H100 80GB GPUs; found {found}")
    return inventory


def require_provisioning_policy(config: Mapping[str, Any]) -> dict[str, str]:
    expected = str(config.get("gcp", {}).get("provisioning_policy", "")).upper()
    observed_preemptible = metadata_value("instance/scheduling/preemptible").upper()
    expected_preemptible = {"SPOT": "TRUE", "STANDARD": "FALSE"}.get(expected)
    if expected_preemptible is None or observed_preemptible != expected_preemptible:
        raise RuntimeError(
            "GCE provisioning policy mismatch: "
            f"expected={expected or 'missing'} "
            f"metadata_preemptible={observed_preemptible}"
        )
    return {
        "provisioning_policy": expected,
        "metadata_preemptible": observed_preemptible,
    }


def metadata_value(name: str, default: str = "unknown") -> str:
    request = urllib.request.Request(
        f"http://metadata.google.internal/computeMetadata/v1/{name}",
        headers={"Metadata-Flavor": "Google"},
    )
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            return response.read().decode("utf-8").strip().split("/")[-1]
    except Exception:
        return default


@contextmanager
def exclusive_gpu_job(label: str) -> Iterator[None]:
    with LOCK_PATH.open("w", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"another GPU-heavy job owns {LOCK_PATH}") from exc
        handle.write(f"pid={os.getpid()} label={label} started={utc_now()}\n")
        handle.flush()
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _sync_result_tree(
    local_root: Path,
    destination: str,
    *,
    include_completed_rollouts: bool = False,
) -> None:
    """Synchronize durable non-checkpoint artifacts only."""

    exclude = DURABLE_SYNC_EXCLUDE_RE if include_completed_rollouts else LIVE_SYNC_EXCLUDE_RE
    if shutil.which("gcloud") is not None:
        run(
            [
                "gcloud",
                "storage",
                "rsync",
                "--recursive",
                "--checksums-only",
                f"--exclude={exclude}",
                str(local_root),
                destination,
            ]
        )
        return
    if shutil.which("gsutil") is not None:
        run(
            [
                "gsutil",
                "-m",
                "rsync",
                "-r",
                "-x",
                exclude,
                str(local_root),
                destination,
            ]
        )
        return
    raise RuntimeError("gcloud or gsutil is required for durable GCS result synchronization")


def _copy_gcs_file(source: Path, destination: str) -> None:
    if shutil.which("gcloud") is not None:
        run(["gcloud", "storage", "cp", str(source), destination])
        return
    if shutil.which("gsutil") is not None:
        run(["gsutil", "cp", str(source), destination])
        return
    raise RuntimeError("gcloud or gsutil is required for durable GCS publication")


def _sync_checkpoint_tree(source: Path, destination: str) -> None:
    if shutil.which("gcloud") is not None:
        run(
            [
                "gcloud",
                "storage",
                "rsync",
                "--recursive",
                "--checksums-only",
                str(source),
                destination,
            ]
        )
        return
    if shutil.which("gsutil") is not None:
        run(["gsutil", "-m", "rsync", "-r", str(source), destination])
        return
    raise RuntimeError("gcloud or gsutil is required for checkpoint publication")


def _checkpoint_file_stats(checkpoint: Path) -> list[dict[str, Any]]:
    match = CHECKPOINT_ITERATION_RE.fullmatch(checkpoint.name)
    if match is None or checkpoint.is_symlink() or not checkpoint.is_dir():
        raise RuntimeError(f"invalid checkpoint directory: {checkpoint}")
    adapter = checkpoint / "adapter"
    required = (adapter / "adapter_model.bin", adapter / "adapter_config.json")
    for path in required:
        if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"checkpoint required file is incomplete: {path}")
    native = {path.name for path in adapter.glob("adapter_megatron_tp*_pp*.pt")}
    if native != EXPECTED_CHECKPOINT_NATIVE_SHARDS:
        raise RuntimeError(f"checkpoint native shard topology is incomplete: {adapter}")
    training = {path.name for path in adapter.glob("training_state_rank*.pt")}
    if training != EXPECTED_CHECKPOINT_TRAINING_STATES:
        raise RuntimeError(f"checkpoint training-state topology is incomplete: {adapter}")

    files: list[dict[str, Any]] = []
    for path in sorted(checkpoint.rglob("*")):
        if path.is_symlink():
            raise RuntimeError(f"checkpoint contains a symlink: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(checkpoint).as_posix()
        if ".tmp" in path.name or path.name == "COMPLETE.json":
            raise RuntimeError(f"checkpoint contains a volatile file: {relative}")
        stat = path.stat()
        if stat.st_size == 0:
            raise RuntimeError(f"checkpoint contains an empty file: {relative}")
        files.append(
            {
                "path": relative,
                "size_bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
    if not files:
        raise RuntimeError(f"checkpoint has no files: {checkpoint}")
    return files


def _canonical_sha256(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _checkpoint_stat_sha256(checkpoint: Path) -> str:
    return _canonical_sha256(_checkpoint_file_stats(checkpoint))


def _checkpoint_content_manifest(checkpoint: Path) -> dict[str, Any]:
    files = _checkpoint_file_stats(checkpoint)
    for item in files:
        item["sha256"] = sha256_path(checkpoint / str(item["path"]))
        item.pop("mtime_ns", None)
    payload = {
        "schema_version": "glm47-gcs-checkpoint-complete-v1",
        "status": "COMPLETE",
        "iteration": int(CHECKPOINT_ITERATION_RE.fullmatch(checkpoint.name).group(1)),
        "checkpoint": checkpoint.name,
        "file_count": len(files),
        "total_bytes": sum(int(item["size_bytes"]) for item in files),
        "files": files,
    }
    payload["manifest_sha256"] = _canonical_sha256(payload)
    return payload


def _publish_complete_checkpoints(
    local_root: Path,
    destination: str,
    state: dict[str, Any],
    *,
    final: bool,
) -> None:
    checkpoint_root = local_root / "checkpoints/grpo_lora_r16"
    if not checkpoint_root.is_dir():
        return
    for checkpoint in sorted(checkpoint_root.glob("iter_*")):
        if CHECKPOINT_ITERATION_RE.fullmatch(checkpoint.name) is None:
            continue
        try:
            stat_sha256 = _checkpoint_stat_sha256(checkpoint)
        except RuntimeError as exc:
            state["checkpoint_rejections"][checkpoint.name] = str(exc)
            continue
        published = state["published_checkpoints"].get(checkpoint.name)
        if published is not None:
            if published["source_stat_sha256"] != stat_sha256:
                raise RuntimeError(
                    f"published checkpoint changed after completion: {checkpoint.name}"
                )
            continue
        previous = state["checkpoint_candidates"].get(checkpoint.name)
        state["checkpoint_candidates"][checkpoint.name] = stat_sha256
        if not final and previous != stat_sha256:
            continue

        before = _checkpoint_content_manifest(checkpoint)
        checkpoint_destination = (
            f"{destination.rstrip('/')}/checkpoints/grpo_lora_r16/{checkpoint.name}"
        )
        _sync_checkpoint_tree(checkpoint, checkpoint_destination)
        after = _checkpoint_content_manifest(checkpoint)
        if before != after:
            raise RuntimeError(f"checkpoint changed during GCS publication: {checkpoint.name}")
        complete_receipt = local_root / (
            f"sync_receipts/checkpoints/{checkpoint.name}.COMPLETE.json"
        )
        if complete_receipt.is_file():
            marker = json.loads(complete_receipt.read_text(encoding="utf-8"))
            if marker.get("manifest_sha256") != after["manifest_sha256"]:
                raise RuntimeError(f"checkpoint completion receipt changed: {checkpoint.name}")
        else:
            marker = {
                **after,
                "published_at_utc": utc_now(),
                "gcs_destination": checkpoint_destination,
            }
            atomic_json(complete_receipt, marker)
        _copy_gcs_file(complete_receipt, f"{checkpoint_destination}/COMPLETE.json")
        state["published_checkpoints"][checkpoint.name] = {
            "source_stat_sha256": stat_sha256,
            "manifest_sha256": after["manifest_sha256"],
            "total_bytes": after["total_bytes"],
            "complete_marker": f"{checkpoint_destination}/COMPLETE.json",
        }
        state["checkpoint_rejections"].pop(checkpoint.name, None)


def _sync_cycle(
    local_root: Path,
    destination: str,
    state: dict[str, Any],
    *,
    kind: str,
    final: bool = False,
) -> None:
    sequence = int(state["sync_attempts"]) + 1
    state["sync_attempts"] = sequence
    _sync_result_tree(
        local_root,
        destination,
        include_completed_rollouts=final,
    )
    _publish_complete_checkpoints(local_root, destination, state, final=final)
    receipt = {
        "schema_version": "glm47-durable-result-sync-v1",
        "status": "passed",
        "completed_at_utc": utc_now(),
        "sequence": sequence,
        "kind": kind,
        "destination": destination,
        "published_checkpoints": state["published_checkpoints"],
        "volatile_paths_excluded": ["runtime_state", "wandb", "checkpoints until complete"],
    }
    receipt_path = local_root / f"sync_receipts/cycles/{sequence:04d}-{kind}.json"
    atomic_json(receipt_path, receipt)
    _copy_gcs_file(
        receipt_path,
        f"{destination.rstrip('/')}/sync_receipts/cycles/{receipt_path.name}",
    )
    state["successful_sync_receipts"].append(receipt_path.name)
    state["consecutive_successes"] += 1


@contextmanager
def periodic_result_sync(
    local_root: Path,
    destination: str,
    *,
    interval_seconds: int,
) -> Iterator[dict[str, Any]]:
    """Publish durable artifacts and complete checkpoints throughout a Spot run."""

    if interval_seconds < 30:
        raise ValueError("result sync interval must be at least 30 seconds")
    state: dict[str, Any] = {
        "destination": destination,
        "interval_seconds": interval_seconds,
        "periodic_failures": [],
        "successful_sync_receipts": [],
        "sync_attempts": 0,
        "consecutive_successes": 0,
        "checkpoint_candidates": {},
        "checkpoint_rejections": {},
        "published_checkpoints": {},
        "final_status": "not_completed",
    }
    _sync_cycle(local_root, destination, state, kind="initial")
    stop = threading.Event()

    def worker() -> None:
        while not stop.wait(interval_seconds):
            try:
                _sync_cycle(local_root, destination, state, kind="periodic")
            except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
                state["consecutive_successes"] = 0
                state["periodic_failures"].append(
                    {
                        "failed_at_utc": utc_now(),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

    thread = threading.Thread(
        target=worker,
        name="full-v5-charm-gcs-sync",
        daemon=True,
    )
    thread.start()
    try:
        yield state
    finally:
        stop.set()
        thread.join()
        try:
            _sync_cycle(local_root, destination, state, kind="final", final=True)
            state["final_status"] = "passed"
        except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
            state["final_status"] = "failed"
            state["final_error"] = f"{type(exc).__name__}: {exc}"


def _require_hash(path: Path, expected: str, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"missing regular {label}: {path}")
    observed = sha256_path(path)
    if observed != expected:
        raise RuntimeError(f"{label} SHA-256 mismatch: {observed} != {expected}")


def _require_marker(path: Path, expected: str, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"missing regular {label}: {path}")
    if path.read_text(encoding="utf-8").strip() != expected:
        raise RuntimeError(f"{label} mismatch: {path}")


def _verify_sha256_manifest(path: Path) -> None:
    """Verify every file in a caller-bound GNU sha256sum manifest."""

    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"missing regular SHA-256 manifest: {path}")
    subprocess.run(
        ["sha256sum", "--check", "--quiet", "--strict", path.name],
        cwd=path.parent,
        check=True,
    )


def verify_converted_checkpoint() -> dict[str, str]:
    if REF_LOAD_MARKER.is_symlink() or not REF_LOAD_MARKER.is_file():
        raise FileNotFoundError(
            f"missing converted TP4/PP1/EP8 checkpoint marker: {REF_LOAD_MARKER}"
        )
    iteration = REF_LOAD_MARKER.read_text(encoding="utf-8").strip()
    if not iteration:
        raise RuntimeError("converted checkpoint marker is empty")
    return {"path": str(REF_LOAD_DIR), "iteration": iteration}


def _verify_r7_runtime(config: Mapping[str, Any]) -> dict[str, Any]:
    runtime = config["full_v5_runtime"]
    profile_contract = PROFILE_CONTRACTS[str(config["profile_id"])]
    candidate = profile_contract.get("runtime_schema") == "charm-grpo-exact40-runtime-v2"
    root = runtime_dir(config).resolve()
    manifest_path = root / "manifest.json"
    oracle_path = root / "oracle-verification-receipt.json"
    _require_hash(manifest_path, runtime["manifest_sha256"], "CHARM runtime manifest")
    if tree_sha256(root) != runtime["tree_sha256"]:
        raise RuntimeError("CHARM runtime tree SHA-256 mismatch")
    _require_hash(
        oracle_path, runtime["oracle_receipt_sha256"], "CHARM executable-oracle receipt"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    oracle = json.loads(oracle_path.read_text(encoding="utf-8"))
    expected_kind = profile_contract.get("runtime_kind", R7_DATASET_KIND)
    expected_schema = profile_contract.get(
        "runtime_schema", "charm-grpo-exact40-runtime-v1"
    )
    expected_oracle_schema = (
        "charm-r8-executable-oracle-receipt-v1"
        if candidate
        else "charm-r7-executable-oracle-receipt-v1"
    )
    if (
        manifest.get("kind") != expected_kind
        or manifest.get("schema_version") != expected_schema
        or manifest.get("decision") != "PASS"
        or manifest.get("counts", {}).get("gradient_tasks") != 40
        or manifest.get("counts", {}).get("canary_tasks") != 20
        or manifest.get("counts", {}).get("repair_gradient_tasks") != 10
        or manifest.get("reward_contract", {}).get("policy")
        != profile_contract["reward_policy"]
        or oracle.get("schema_version") != expected_oracle_schema
        or oracle.get("decision") != "PASS"
        or oracle.get("failure_count") != 0
        or oracle.get("task_count") != 51
        or oracle.get("dataset_manifest_sha256") != runtime["manifest_sha256"]
        or oracle.get("selection_sha256") != runtime["selection_sha256"]
        or (
            candidate
            and manifest.get("public_api_contract", {}).get("manifest_set_sha256")
            != profile_contract["runtime_public_api_manifest_set_sha256"]
        )
    ):
        raise RuntimeError("CHARM runtime or executable-oracle contract mismatch")
    selection_path = Path(str(manifest.get("source", {}).get("selection_path", "")))
    if selection_path.is_file():
        validation = (
            validate_corrected_exact40_dataset(root)
            if candidate
            else validate_charm_r7_exact40_dataset(root)
        )
        validation_mode = "source-bound"
    else:
        validation = {
            "decision": "PASS",
            "manifest_sha256": runtime["manifest_sha256"],
            "selection_sha256": runtime["selection_sha256"],
        }
        validation_mode = "portable-exact-tree"
    return {
        **validation,
        "validation_mode": validation_mode,
        "tree_sha256": runtime["tree_sha256"],
        "oracle_receipt_sha256": runtime["oracle_receipt_sha256"],
    }

def verify_assets(*, require_converted_checkpoint: bool = True) -> dict[str, Any]:
    config = load_config()
    model = config["model"]
    adapter = config["starting_adapter"]
    runtime = config["full_v5_runtime"]
    _require_marker(MODEL_DIR / ".source-revision", model["revision"], "model revision")
    _require_hash(
        MODEL_DIR / ".source-manifest.sha256",
        model["manifest_sha256"],
        "model source manifest",
    )
    _verify_sha256_manifest(MODEL_DIR / ".source-manifest.sha256")
    _require_marker(
        ADAPTER_DIR / ".training-run-id",
        adapter["training_run_id"],
        "SynthMem-v1 training run ID",
    )
    _require_hash(
        ADAPTER_DIR / "adapter_model.bin",
        adapter["adapter_model_sha256"],
        "SynthMem-v1 ep50 adapter",
    )
    _require_hash(
        ADAPTER_DIR / "adapter_config.json",
        adapter["adapter_config_sha256"],
        "SynthMem-v1 ep50 adapter config",
    )
    reconstruction_path = ADAPTER_DIR / "native_reconstruction_manifest.json"
    _require_hash(
        reconstruction_path,
        adapter["native_reconstruction_manifest_sha256"],
        "SynthMem-v1 ep50 native reconstruction manifest",
    )
    adapter_config = json.loads((ADAPTER_DIR / "adapter_config.json").read_text(encoding="utf-8"))
    if int(adapter_config.get("r", -1)) != int(adapter["lora_rank"]) or int(
        adapter_config.get("lora_alpha", -1)
    ) != int(adapter["lora_alpha"]):
        raise RuntimeError("SynthMem-v1 ep50 adapter LoRA configuration mismatch")

    reconstruction = json.loads(reconstruction_path.read_text(encoding="utf-8"))
    source = reconstruction.get("source", {})
    mapping = reconstruction.get("mapping", {})
    roundtrip = mapping.get("source_hf_roundtrip", {})
    native_outputs = reconstruction.get("outputs", {}).get("native_shards", {})
    if (
        reconstruction.get("status") != "passed"
        or reconstruction.get("kind") != "glm47-hf-to-megatron-tp-native-reconstruction"
        or source.get("adapter_model_sha256") != adapter["adapter_model_sha256"]
        or source.get("adapter_config_sha256") != adapter["adapter_config_sha256"]
        or source.get("tensor_content_sha256") != adapter["source_tensor_content_sha256"]
        or source.get("tensor_count") != int(adapter["source_tensor_count"])
        or roundtrip.get("status") != "passed"
        or roundtrip.get("coverage_fraction") != 1.0
        or roundtrip.get("all_source_hf_tensors_value_exact") is not True
        or roundtrip.get("all_source_hf_tensor_bytes_exact") is not True
        or roundtrip.get("source_hf_tensor_bytes") != int(adapter["source_tensor_bytes"])
        or roundtrip.get("native_shard_count") != int(adapter["expected_native_shards"])
        or not isinstance(native_outputs, dict)
        or len(native_outputs) != int(adapter["expected_native_shards"])
    ):
        raise RuntimeError("SynthMem-v1 ep50 native reconstruction proof mismatch")

    native_names = set(native_outputs)
    observed_native = {path.name for path in ADAPTER_DIR.glob("adapter_megatron_tp*_pp*.pt")}
    if observed_native != native_names:
        raise RuntimeError("SynthMem-v1 ep50 adapter lacks its exact TP4/EP8 shard set")
    for name, metadata in native_outputs.items():
        if (
            not isinstance(metadata, dict)
            or SHA256_RE.fullmatch(str(metadata.get("sha256", ""))) is None
        ):
            raise RuntimeError(f"invalid native-shard receipt for {name}")
        _require_hash(ADAPTER_DIR / name, metadata["sha256"], f"native shard {name}")

    if is_r7_profile(config):
        runtime_receipt = _verify_r7_runtime(config)
    else:
        runtime_receipt = validate_full_v5_package(
            runtime_dir(config),
            expected_manifest_sha256=runtime["manifest_sha256"],
            expected_tree_sha256=runtime["tree_sha256"],
        )
    return {
        "status": "passed",
        "model_revision": model["revision"],
        "model_manifest_sha256": model["manifest_sha256"],
        "checkpoint_profile": adapter["profile"],
        "checkpoint_path": adapter["checkpoint_path"],
        "epoch": adapter["epoch"],
        "optimizer_iteration": adapter["optimizer_iteration"],
        "adapter_model_sha256": adapter["adapter_model_sha256"],
        "native_reconstruction_manifest_sha256": adapter["native_reconstruction_manifest_sha256"],
        "native_shards": sorted(native_names),
        "runtime": runtime_receipt,
        "converted_checkpoint": (
            verify_converted_checkpoint() if require_converted_checkpoint else None
        ),
    }


def _pass_receipt(
    path: Path,
    *,
    expected_sha256: str,
    expected_stage: str,
) -> dict[str, Any]:
    if SHA256_RE.fullmatch(expected_sha256) is None:
        raise ValueError(f"invalid expected {expected_stage} receipt SHA-256")
    _require_hash(path, expected_sha256, f"{expected_stage} receipt")
    payload = json.loads(path.read_text(encoding="utf-8"))
    status = str(payload.get("decision", payload.get("status", ""))).upper()
    stage = str(
        payload.get("stage", payload.get("requested_stage", payload.get("validation_stage", "")))
    ).lower()
    if status not in {"PASS", "PASSED"} or stage != expected_stage:
        raise RuntimeError(f"{expected_stage} receipt is not a matching PASS")
    return payload


def _experimental_smoke_receipt(
    path_value: str | None,
    expected_sha256: str,
    *,
    profile_contract: Mapping[str, Any],
) -> dict[str, Any]:
    if not path_value:
        raise RuntimeError("full experiment requires the one-update smoke PASS receipt")
    path = Path(path_value)
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"missing regular smoke PASS receipt: {path}")
    if SHA256_RE.fullmatch(expected_sha256) is None:
        raise ValueError("full experiment requires the exact smoke receipt SHA-256")
    _require_hash(path, expected_sha256, "one-update smoke receipt")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    smoke_profile_id = str(profile_contract.get("smoke_profile_id", ""))
    permit_field = str(profile_contract.get("smoke_permit_field", ""))
    if (
        receipt.get("schema_version") != "glm47-unadmitted-grpo-smoke-v1"
        or receipt.get("decision") != "PASS"
        or receipt.get("profile_id") != smoke_profile_id
        or not permit_field
        or receipt.get(permit_field) is not True
        or receipt.get("charm_eligible") is not False
        or receipt.get("checkpoint_disposition") != "QUARANTINE_ONLY"
        or receipt.get("retroactive_admission_allowed") is not False
        or receipt.get("checkpoint", {}).get("roundtrip_verified") is not True
        or receipt.get("training", {}).get("optimizer_updates_proven") != 1
        or (
            profile_contract.get("reward_mode") is not None
            and receipt.get("reward_mode") != profile_contract["reward_mode"]
        )
    ):
        raise RuntimeError("one-update smoke receipt is not a complete matching PASS")
    return receipt


def _operator_smoke_bypass(profile_id: str) -> dict[str, Any] | None:
    authorization_env = "GLM47_R6_V2_SMOKE_BYPASS_AUTHORIZATION"
    authorization_phrase = "I_AUTHORIZE_R6_V2_SMOKE_GATE_BYPASS_AFTER_FAILED_EXACT_FORMAT_SMOKE"
    if os.environ.get(authorization_env) != authorization_phrase:
        return None
    failed_run_id = os.environ.get("GLM47_R6_V2_FAILED_SMOKE_RUN_ID", "")
    failed_signal_sha256 = os.environ.get("GLM47_R6_V2_FAILED_SIGNAL_RECEIPT_SHA256", "")
    if not failed_run_id.startswith("unadmitted-r6-v2-smoke-"):
        raise ValueError("smoke bypass requires the exact failed R6 smoke run ID")
    if SHA256_RE.fullmatch(failed_signal_sha256) is None:
        raise ValueError("smoke bypass requires the failed signal receipt SHA-256")
    return {
        "status": "BYPASSED_BY_OPERATOR",
        "authorization_env": authorization_env,
        "failed_smoke_run_id": failed_run_id,
        "failed_signal_receipt_sha256": failed_signal_sha256,
        "failed_gate": "exact_format_rate=0.390000<0.5",
        "profile_id": profile_id,
        "optimizer_checkpoint_proof": "BYPASSED_BY_OPERATOR",
        "checkpoint_storage_projection": "BYPASSED_BY_OPERATOR",
        "charm_eligible": False,
        "checkpoint_disposition": "QUARANTINE_ONLY",
        "retroactive_admission_allowed": False,
    }


def _canary_tasks(path: Path, expected_sha256: str, config: Mapping[str, Any]) -> list[str]:
    _require_hash(path, expected_sha256, "canary task manifest")
    payload = json.loads(path.read_text(encoding="utf-8"))
    task_ids = payload.get("task_ids")
    trial_ids = payload.get("trial_ids")
    if (
        payload.get("profile_id") != config["profile_id"]
        or payload.get("source_manifest_sha256") != config["full_v5_runtime"]["manifest_sha256"]
        or not isinstance(task_ids, list)
        or len(task_ids) != 20
        or len(set(task_ids)) != 20
        or not all(isinstance(value, str) and value for value in task_ids)
        or not isinstance(trial_ids, list)
        or len(set(str(value) for value in trial_ids)) < 4
    ):
        raise RuntimeError("canary manifest is not the frozen 20-task/four-trial contract")
    return task_ids


def stage_r7_training_data(
    source_root: Path,
    destination: Path,
    *,
    phase: str,
    canary_task_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Expand the frozen compact R7 schedule into Miles prompt rows."""

    if phase not in {"canary", "full", "experimental"}:
        raise ValueError(f"unsupported R7 phase: {phase}")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"refusing to reuse R7 staged data: {destination}")
    shutil.copytree(source_root, destination)
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    files = manifest.get("files", {})
    if phase == "canary":
        base_key, schedule_key = "grpo_canary", "canary_schedule"
        output_relative, epochs = "grpo/canary-5ep-train.jsonl", 5
    else:
        # The quarantined R8 experiment intentionally reuses the frozen exact-40
        # full schedule.  Keep its outward phase as ``experimental`` so receipts
        # cannot be mistaken for an admitted production-full run.
        base_key, schedule_key = "grpo_train", "full_schedule"
        output_relative, epochs = "grpo/full-3ep-train.jsonl", 3
    base_rows = read_jsonl(destination / str(files[base_key]))
    compact_schedule = read_jsonl(destination / str(files[schedule_key]))
    by_base_id = {str(row.get("metadata", {}).get("base_task_id")): row for row in base_rows}
    if len(by_base_id) != len(base_rows):
        raise RuntimeError("R7 base prompt rows do not bind unique task IDs")
    if phase == "canary" and list(by_base_id) != list(canary_task_ids or []):
        raise RuntimeError("R7 canary admission manifest/task order mismatch")
    expanded: list[dict[str, Any]] = []
    for item in compact_schedule:
        base_id = str(item.get("base_task_id", ""))
        source = by_base_id.get(base_id)
        if source is None:
            raise RuntimeError(f"R7 schedule references an unknown task: {base_id}")
        row = json.loads(json.dumps(source))
        metadata = row["metadata"]
        if metadata.get("curriculum_role") != item.get("curriculum_role"):
            raise RuntimeError(f"R7 schedule role drift: {base_id}")
        metadata["schedule_phase"] = phase
        metadata["schedule_epoch"] = int(item["epoch"])
        metadata["schedule_position"] = int(item["position"])
        expanded.append(row)
    expected_rows = len(base_rows) * epochs
    if len(expanded) != expected_rows:
        raise RuntimeError(f"R7 expanded schedule size mismatch: {len(expanded)}")
    output_path = destination / output_relative
    output_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in expanded),
        encoding="utf-8",
    )
    return {
        "status": "passed",
        "phase": phase,
        "epochs": epochs,
        "unique_tasks": len(base_rows),
        "rows": len(expanded),
        "prompt_data": output_relative,
        "prompt_data_sha256": sha256_path(output_path),
        "source_manifest_sha256": sha256_path(destination / "manifest.json"),
        "source_tree_sha256": tree_sha256(source_root),
        "reward_policy": str(manifest.get("reward_contract", {}).get("policy", "")),
    }


def build_training_env(
    *,
    phase: str,
    run_id: str,
    container_run_root: str,
    host_run_root: Path | None = None,
    verifier_image: str,
    config: Mapping[str, Any],
) -> dict[str, str]:
    if phase not in {"canary", "full", "experimental"}:
        raise ValueError(f"unsupported phase: {phase}")
    phase_config = config["canary"] if phase == "canary" else config["full_training"]
    experimental = phase == "experimental"
    candidate = is_candidate_charm_profile(config)
    profile_contract = PROFILE_CONTRACTS[str(config["profile_id"])]
    signal = config["reward"]["signal_thresholds"]
    num_rollout = int(phase_config["rollout_updates"])
    rollout_batch = int(phase_config["rollout_batch_size"])
    global_batch = int(phase_config["global_batch_size"])
    reward_mode = str(config["reward"]["implementation_mode"])
    if reward_mode not in {
        "production_ast17",
        "hybrid_bipolar45",
        "hybrid_bipolar45_mef",
    }:
        raise RuntimeError(f"unsupported GCP reward mode: {reward_mode}")
    r7_profile = is_r7_profile(config)
    dataset_kind = str(config["full_v5_runtime"]["kind"]) if r7_profile else SCHEDULE_KIND
    schedule_name = "canary-5ep-train.jsonl" if phase == "canary" else "full-3ep-train.jsonl"
    prompt_data = f"{container_run_root}/data/grpo/{schedule_name}"
    save_interval = 1 if phase == "canary" else int(phase_config["save_interval"])
    eval_interval = 1 if phase == "canary" else int(phase_config["full_development_interval"])
    maximum_prompt_length = int(config["full_training"].get("maximum_prompt_length", 2048))
    context_isolation_required = bool(config["reward"].get("context_isolation_required", False))
    tokenizer = config.get("tokenizer", {})
    tokenizer = tokenizer if isinstance(tokenizer, Mapping) else {}
    tokenizer_revision = str(tokenizer.get("revision", config["model"]["revision"]))
    tokenizer_manifest_sha256 = str(
        tokenizer.get("manifest_sha256", config["model"]["manifest_sha256"])
    )
    chat_template_sha256 = str(config["reward"].get("chat_template_sha256", ""))
    optimizer_policy = config.get("optimizer_policy", {})
    optimizer_policy = optimizer_policy if isinstance(optimizer_policy, Mapping) else {}
    corrected_r8_offload = (
        experimental
        and str(config["profile_id"])
        == UNADMITTED_R8_HYBRID45_R87_SKYPILOT_PROFILE_ID
    )
    if context_isolation_required:
        frozen_thresholds = {
            "minimum_positive_groups": 1,
            "minimum_semantic_variance_groups": 2,
            "minimum_reward_variance_groups": 2,
            "minimum_kernel_variance_groups": 2,
            "require_unique_task_groups": True,
            "minimum_exact_format_rate": 0.50,
            "minimum_compile_rate": 0.20,
        }
        if dict(signal) != frozen_thresholds:
            raise RuntimeError("corrected Hybrid45 profile changed the frozen signal thresholds")
        if reward_mode != "hybrid_bipolar45":
            raise RuntimeError("corrected profile must use Hybrid45 V2 optimizer scores directly")
        if len(tokenizer_manifest_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in tokenizer_manifest_sha256
        ):
            raise RuntimeError("corrected profile lacks a pinned tokenizer manifest SHA-256")
        if not tokenizer_revision:
            raise RuntimeError("corrected profile lacks a pinned tokenizer revision")
        if len(chat_template_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in chat_template_sha256
        ):
            raise RuntimeError("corrected profile lacks a pinned chat-template SHA-256")
        if maximum_prompt_length <= 0:
            raise RuntimeError("corrected profile maximum prompt length must be positive")
    if profile_contract.get("optimizer_policy") is not None:
        expected_optimizer_policy = {
            "policy_version": GRPO_ADVANTAGE_POLICY_VERSION,
            "advantage_estimator": "grpo",
            "rewards_normalization": True,
            "group_std_normalization": True,
            "global_advantage_normalization": False,
            "epsilon": 1e-6,
            "dr_grpo_selected": False,
        }
        if dict(optimizer_policy) != expected_optimizer_policy:
            raise RuntimeError("corrected profile changed the pinned GRPO optimizer policy")
    return {
        # Docker-in-Docker bind sources are resolved by the host daemon. Give
        # verifier scratch files a path that is identical in the training
        # container and on the host so the nested sandbox sees their bytes.
        "TMPDIR": str(
            (host_run_root / "runtime_state/tmp").resolve()
            if host_run_root is not None
            else Path(container_run_root) / "runtime_state/tmp"
        ),
        "MILES_RUN_ID": run_id,
        "MILES_RUN_ROOT": container_run_root,
        "MILES_CPP_DATA_DIR": f"{container_run_root}/data",
        "MILES_CPP_TASKS_DIR": f"{container_run_root}/data/tasks",
        "MILES_DATA_BUILD_MODULE": "glm47_posttraining.integrations.miles_aider_polyglot",
        "MILES_CUSTOM_RM_PATH": "glm47_posttraining.integrations.miles_aider_polyglot.reward_func",
        "MILES_REWARD_PREFLIGHT_MODULE": "glm47_posttraining.integrations.miles_aider_polyglot",
        "MILES_SKIP_RUNTIME_PREFLIGHT": "0",
        "MILES_EXPECTED_DATASET_KIND": dataset_kind,
        "MILES_GRPO_PROMPT_DATA": prompt_data
        if r7_profile
        else f"{container_run_root}/data/grpo/train.jsonl",
        "MILES_EXPECTED_PROMPT_ROWS": str(num_rollout * rollout_batch),
        "MILES_CPP_SORT_BY_SIZE": "0",
        "MILES_EVAL_NAME": "full-v5-development",
        "MILES_EVAL_PROMPT_DATA": f"{container_run_root}/data/eval/task_disjoint_monitor.jsonl"
        if r7_profile
        else f"{container_run_root}/data/eval/development.jsonl",
        "MILES_EVAL_INTERVAL": str(eval_interval),
        "MILES_EVAL_N_SAMPLES_PER_PROMPT": "1",
        "MILES_EVAL_MAX_RESPONSE_LEN": str(config["full_training"]["maximum_response_length"]),
        "MILES_NUM_ROLLOUT": str(num_rollout),
        "MILES_ROLLOUT_BATCH_SIZE": str(rollout_batch),
        "MILES_N_SAMPLES_PER_PROMPT": str(phase_config["samples_per_prompt"]),
        "MILES_GLOBAL_BATCH_SIZE": str(global_batch),
        "MILES_ROLLOUT_TEMPERATURE": "0.7",
        # R7 materializes one complete, unique-task batch per epoch. Global
        # shuffling mixes repeated task IDs from different epochs into the
        # same optimizer batch and violates the unique-group signal gate.
        "MILES_GRPO_ROLLOUT_SHUFFLE": (
            "1" if bool(phase_config.get("rollout_shuffle", True)) else "0"
        ),
        "MILES_ROLLOUT_MAX_PROMPT_LEN": str(maximum_prompt_length),
        "MILES_ROLLOUT_MAX_RESPONSE_LEN": str(config["full_training"]["maximum_response_length"]),
        "MILES_ROLLOUT_SKIP_SPECIAL_TOKENS": "1",
        "MILES_ROLLOUT_STOP_TOKEN_IDS": "154820 154827 154829",
        "MILES_SAVE_INTERVAL": str(save_interval),
        "MILES_LR": "5e-7",
        "MILES_NO_REF": "0",
        "MILES_USE_KL_LOSS": "1",
        "MILES_KL_LOSS_COEF": "0.02",
        "MILES_GRPO_ADVANTAGE_POLICY": str(
            optimizer_policy.get("policy_version", "legacy-unbound")
        ),
        "MILES_REWARDS_NORMALIZATION": (
            "1" if optimizer_policy.get("rewards_normalization", True) else "0"
        ),
        "MILES_GRPO_STD_NORMALIZATION": (
            "1" if optimizer_policy.get("group_std_normalization", True) else "0"
        ),
        "MILES_NORMALIZE_ADVANTAGES": (
            "1" if optimizer_policy.get("global_advantage_normalization", False) else "0"
        ),
        "MILES_APPLY_CHAT_TEMPLATE_KWARGS": '{"enable_thinking": true}',
        "MILES_SEQ_LENGTH": "34816",
        "MILES_MAX_TOKENS_PER_GPU": str(config["full_training"]["maximum_tokens_per_gpu"]),
        "MILES_RECOMPUTE_GRANULARITY": "full",
        # Job 19 proved the resident-trainer workaround can complete update 1,
        # but leaves too little headroom for SGLang to restore its KV cache for
        # rollout 2. The image now carries the corrected ``_asleep`` lifecycle,
        # so use Miles' default trainer offload again while retaining the
        # conservative SGLang reservation. Reward and optimizer gates remain
        # unchanged.
        **(
            {
                "MILES_SGLANG_MEM_FRACTION_STATIC": "0.60",
            }
            if corrected_r8_offload
            else {}
        ),
        "MILES_GPUS_PER_NODE": "8",
        "MILES_TENSOR_MODEL_PARALLEL_SIZE": "4",
        "MILES_PIPELINE_MODEL_PARALLEL_SIZE": "1",
        "MILES_CONTEXT_PARALLEL_SIZE": "1",
        "MILES_EXPERT_MODEL_PARALLEL_SIZE": "8",
        "MILES_EXPERT_TENSOR_PARALLEL_SIZE": "1",
        "MILES_EXPECTED_NATIVE_SHARDS": "8",
        "MILES_HF_CHECKPOINT": "/root/models/GLM-4.7-Flash",
        "MILES_REF_LOAD_DIR": "/root/models/GLM-4.7-Flash_torch_dist_tp4_pp1_ep8",
        "MILES_LORA_ADAPTER_PATH": "/starting-adapter",
        "MILES_GRPO_ADAPTER_DIR": f"{container_run_root}/adapter_hybrid",
        "MILES_EXPECTED_SOURCE_ADAPTER_SHA256": config["starting_adapter"]["adapter_model_sha256"],
        "MILES_EXPECTED_SOURCE_TENSORS": str(config["starting_adapter"]["source_tensor_count"]),
        "MILES_EXPECTED_STRIPPED_TENSORS": str(
            config["starting_adapter"]["stripped_mtp_tensor_count"]
        ),
        "MILES_NATIVE_RECONSTRUCTION_MANIFEST_PATH": (
            "/starting-adapter/native_reconstruction_manifest.json"
        ),
        "MILES_EXPECTED_NATIVE_RECONSTRUCTION_MANIFEST_SHA256": config["starting_adapter"][
            "native_reconstruction_manifest_sha256"
        ],
        "MILES_LORA_RANK": str(config["starting_adapter"]["lora_rank"]),
        "MILES_LORA_ALPHA": str(config["starting_adapter"]["lora_alpha"]),
        "MILES_ROLLOUT_SAMPLE_FILTER_PATH": (
            "glm47_posttraining.integrations.miles_aider_polyglot.validate_aider_rollout_batch"
        ),
        "MILES_AIDER_REWARD_MODE": reward_mode,
        "MILES_CPP_INCLUDE_LOGS": "0",
        "GLM47_CPP_SANDBOX_BACKEND": "docker",
        "GLM47_CPP_SANDBOX_IMAGE": verifier_image,
        "GLM47_CPP_SANDBOX_UNSHARE_NET": "1",
        "GLM47_CPP_REWARD_WORKERS": str(config["reward"]["workers"]),
        "GLM47_CPP_TSAN_PREFLIGHT_REQUIRED": (
            "1" if config["reward"].get("tsan_preflight_required", True) else "0"
        ),
        "GLM47_CPP_TSAN_EXECUTION_ALLOWED": (
            "1" if config["reward"].get("tsan_execution_allowed", True) else "0"
        ),
        "GLM47_AIDER_EXPECTED_TRAIN_GROUPS": str(rollout_batch),
        "GLM47_AIDER_EXPECTED_SAMPLES_PER_GROUP": str(phase_config["samples_per_prompt"]),
        "GLM47_AIDER_REQUIRE_UNIQUE_TASK_GROUPS": (
            "1" if signal.get("require_unique_task_groups", True) else "0"
        ),
        "GLM47_AIDER_REQUIRE_SIGNAL": "1",
        "GLM47_AIDER_MIN_POSITIVE_GROUPS": str(signal["minimum_positive_groups"]),
        "GLM47_AIDER_MIN_SEMANTIC_VARIANCE_GROUPS": str(signal["minimum_semantic_variance_groups"]),
        "GLM47_AIDER_MIN_REWARD_VARIANCE_GROUPS": str(signal["minimum_reward_variance_groups"]),
        "GLM47_AIDER_MIN_KERNEL_VARIANCE_GROUPS": str(
            signal.get("minimum_kernel_variance_groups", 2)
        ),
        "GLM47_AIDER_MIN_EXACT_FORMAT_RATE": str(signal["minimum_exact_format_rate"]),
        "GLM47_AIDER_MIN_COMPILE_RATE": str(signal["minimum_compile_rate"]),
        "GLM47_AIDER_SIGNAL_GATE_DIR": f"{container_run_root}/signal-gates",
        "GLM47_AIDER_REQUIRE_CONTEXT_ISOLATION": ("1" if context_isolation_required else "0"),
        "GLM47_AIDER_MAX_PROMPT_TOKENS": str(maximum_prompt_length),
        "GLM47_TOKENIZER_REVISION": tokenizer_revision,
        "GLM47_TOKENIZER_MANIFEST_SHA256": tokenizer_manifest_sha256,
        "GLM47_TOKENIZER_MANIFEST_PATH": "/opt/full-v5-charm/dataset/configs/glm47-flash-tokenizer-manifest.json",
        "GLM47_CHAT_TEMPLATE_SHA256": chat_template_sha256,
        "GLM47_CHAT_TEMPLATE_PATH": "/opt/full-v5-charm/dataset/configs/glm47-flash-chat-template.jinja",
        "WANDB_MODE": config["tracking"]["wandb_mode"],
        "WANDB_DIR": f"{container_run_root}/wandb",
        "MILES_WANDB_PROJECT": config["tracking"]["wandb_project"],
        "MILES_WANDB_GROUP": run_id,
        "MILES_WANDB_RUN_ID": run_id,
        "MILES_WANDB_JOB_TYPE": f"grpo-{phase}",
        "WANDB_TAGS": (
            f"gcp,full-v5,unadmitted,quarantine,{reward_mode.replace('_', '-')},thinking"
            if experimental
            else f"gcp,full-v5,charm,{reward_mode.replace('_', '-')},thinking,{phase}"
        ),
        "GLM47_EXPERIMENT_ID": run_id,
        "GLM47_PROFILE_ID": config["profile_id"],
        "GLM47_SOURCE_COMMIT": source_commit(),
        "GLM47_EFFECTIVE_SOURCE_MANIFEST_SHA256": str(
            config.get("effective_source", {}).get("manifest_sha256", "")
        ),
        "GLM47_EFFECTIVE_SOURCE_SET_SHA256": str(
            config.get("effective_source", {}).get("source_set_sha256", "")
        ),
        "GLM47_FULL_V5_CHARM_PROFILE": config["profile_id"],
        "GLM47_EXECUTION_PROFILE": config["execution"]["profile"],
        "GLM47_PROVISIONER": config["execution"]["provisioner"],
        "GLM47_SKYPILOT_TASK_ID": os.environ.get("SKYPILOT_TASK_ID", "unknown"),
        "GLM47_ADMISSION_STATUS": "NOT_COMPLETED" if experimental or candidate else "GATED",
        "GLM47_CHARM_ELIGIBLE": "0" if experimental else "1",
        "GLM47_CHECKPOINT_DISPOSITION": ("QUARANTINE_ONLY" if experimental else "GATED"),
        "GLM47_RETROACTIVE_ADMISSION_ALLOWED": "0",
    }


def _docker_training_command(
    *,
    run_id: str,
    result_root: Path,
    train_image: str,
    env_values: Mapping[str, str],
) -> list[str]:
    if (
        MILES_MODEL_ARGS_COMPAT_PATH.is_symlink()
        or not MILES_MODEL_ARGS_COMPAT_PATH.is_file()
    ):
        raise RuntimeError("pinned Miles model-args compatibility loader is missing or unsafe")
    host_run_root = (result_root / "runs" / run_id).resolve()
    command = docker_prefix() + [
        "run",
        "--rm",
        "--name",
        run_id,
        "--gpus",
        "all",
        "--network",
        "none",
        "--ipc",
        "host",
        "--shm-size",
        "256g",
        "--volume",
        "/var/run/docker.sock:/var/run/docker.sock",
        "--volume",
        f"{MODEL_DIR.parent}:/root/models:ro",
        "--volume",
        f"{ADAPTER_DIR}:/starting-adapter:ro",
        "--volume",
        f"{result_root}:/results",
        "--volume",
        f"{host_run_root}:{host_run_root}",
        "--volume",
        (
            f"{MILES_MODEL_ARGS_COMPAT_PATH}:"
            f"{MILES_MODEL_ARGS_COMPAT_CONTAINER_PATH}:ro"
        ),
    ]
    for key, value in sorted(env_values.items()):
        command += ["--env", f"{key}={value}"]
    command += [train_image, "/opt/full-v5-charm/examples/grpo.sh"]
    return command


def inspect(_args: argparse.Namespace) -> None:
    config = load_config()
    inventory = gpu_inventory()
    payload = {
        "profile_id": config["profile_id"],
        "execution": config["execution"],
        "decision": config["decision"],
        "source_commit": source_commit(),
        "effective_source": config.get("effective_source"),
        "config_sha256": sha256_path(CONFIG_PATH),
        "modal_default": config["modal_policy"]["default"],
        "gpu_inventory": inventory,
        "h100_ready": len(inventory) == 8
        and all("H100" in str(item["name"]) for item in inventory),
        "gcp_metadata": {
            "instance": metadata_value("instance/name"),
            "zone": metadata_value("instance/zone"),
            "machine_type": metadata_value("instance/machine-type"),
        },
        "paths": {
            "model": str(MODEL_DIR),
            "adapter": str(ADAPTER_DIR),
            "runtime": str(runtime_dir(config)),
            "results": str(RESULT_ROOT),
        },
        "gates": config["admission"],
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


def _one_update_smoke_config(
    config: Mapping[str, Any],
    *,
    enabled: bool,
    phase: str,
) -> Mapping[str, Any]:
    if not enabled:
        return config
    if (
        phase != "experimental"
        or config.get("profile_id")
        != UNADMITTED_R8_HYBRID45_R87_SKYPILOT_PROFILE_ID
    ):
        raise ValueError(
            "one-update smoke is restricted to the quarantined unadmitted R8 experiment"
        )
    selected = copy.deepcopy(config)
    selected["full_training"]["rollout_updates"] = 1
    selected["execution"]["smoke_mode"] = "one-update"
    selected["execution"]["smoke_optimizer_updates"] = 1
    return selected


def render(args: argparse.Namespace) -> None:
    config = _one_update_smoke_config(
        load_config(), enabled=getattr(args, "one_update_smoke", False), phase=args.phase
    )
    run_id = args.run_id or f"render-{args.phase}"
    env = build_training_env(
        phase=args.phase,
        run_id=run_id,
        container_run_root=f"/results/runs/{run_id}",
        host_run_root=RESULT_ROOT.resolve() / "runs" / run_id,
        verifier_image=config["verifier_image"]["local_name"],
        config=config,
    )
    print(
        json.dumps(
            {
                "phase": args.phase,
                "run_id": run_id,
                "environment": env,
                "command": _docker_training_command(
                    run_id=run_id,
                    result_root=RESULT_ROOT,
                    train_image=config["training_image"]["local_name"],
                    env_values=env,
                ),
            },
            indent=2,
            sort_keys=True,
        )
    )


def host_check(_args: argparse.Namespace) -> None:
    config = load_config()
    inventory = require_h100()
    if shutil.which("docker") is None:
        raise RuntimeError("Docker is not installed")
    run(docker_prefix() + ["info"])
    free_gib = shutil.disk_usage("/opt" if Path("/opt").exists() else "/").free // (1024**3)
    minimum_free_gib = int(config.get("tracking", {}).get("minimum_free_storage_gib", 250))
    if free_gib < minimum_free_gib:
        raise RuntimeError(
            f"at least {minimum_free_gib} GiB free storage is required; found {free_gib}"
        )
    print(
        json.dumps(
            {
                "status": "passed",
                "profile_id": config["profile_id"],
                "execution": config["execution"],
                "gpu_inventory": inventory,
                "free_storage_gib": free_gib,
                "minimum_free_storage_gib": minimum_free_gib,
                "instance": metadata_value("instance/name"),
                "zone": metadata_value("instance/zone"),
                "machine_type": metadata_value("instance/machine-type"),
            },
            indent=2,
            sort_keys=True,
        )
    )


def _training_build_args(config: Mapping[str, Any]) -> list[str]:
    image = config.get("training_image", {})
    build_args = [
        "--build-arg",
        f"MILES_BASE_IMAGE={image['base']}",
    ]
    if image.get("trainer_contract_preflight_required") is not True:
        return build_args
    source_files = image["miles_source_files"]
    bindings = {
        "GLM47_ENFORCE_R8_TRAINER_CONTRACT": "1",
        "GLM47_MILES_COMMIT": image["miles_commit"],
        "GLM47_MILES_ADVANTAGES_SHA256": source_files[
            "miles/backends/training_utils/loss_hub/advantages.py"
        ],
        "GLM47_MILES_LOSS_SHA256": source_files["miles/backends/training_utils/loss.py"],
        "GLM47_MILES_LOSSES_SHA256": source_files[
            "miles/backends/training_utils/loss_hub/losses.py"
        ],
        "GLM47_MILES_MATH_UTILS_SHA256": source_files[
            "miles/backends/training_utils/loss_hub/math_utils.py"
        ],
        "GLM47_MILES_TRAIN_DATA_CONVERSION_SHA256": source_files[
            "miles/ray/rollout/train_data_conversion.py"
        ],
        "GLM47_MILES_ARGUMENTS_SHA256": source_files["miles/utils/arguments.py"],
        "GLM47_MILES_MODEL_ARGS_UTILS_SHA256": source_files[
            "miles/utils/external_utils/model_args_utils.py"
        ],
        "GLM47_MILES_GLM47_FLASH_MODEL_ARGS_SHA256": source_files[
            "scripts/models/glm4.7-flash.py"
        ],
        "GLM47_MILES_CONVERTER_SHA256": source_files[
            "tools/convert_hf_to_torch_dist.py"
        ],
    }
    for name, value in bindings.items():
        build_args.extend(["--build-arg", f"{name}={value}"])
    return build_args


def _trainer_contract_command(
    config: Mapping[str, Any], train_image: str, receipt_path: Path
) -> list[str]:
    image = config["training_image"]
    if image.get("trainer_contract_preflight_required") is not True:
        raise RuntimeError("trainer contract receipt requested for an unbound training image")
    command = docker_prefix() + [
        "run",
        "--rm",
        "--network",
        "none",
        "--volume",
        f"{receipt_path.parent}:{receipt_path.parent}",
        train_image,
        "env",
        "-u",
        "CPLUS_INCLUDE_PATH",
        "python3",
        "-m",
        "glm47_posttraining.aider_polyglot.grpo_advantage_contract",
        "--miles-root",
        "/root/miles",
        "--expected-commit",
        str(image["miles_commit"]),
    ]
    for relative, digest in sorted(image["miles_source_files"].items()):
        command.extend(["--expected-file", f"{relative}={digest}"])
    command.extend(["--output", str(receipt_path)])
    return command


def _pull_prebuilt_images(
    config: Mapping[str, Any],
    *,
    train_image: str,
    verifier_image: str,
) -> dict[str, str]:
    """Pull and verify immutable registry refs, then record local runtime IDs."""

    requested = {
        "training": (config.get("training_image", {}), train_image),
        "verifier": (config.get("verifier_image", {}), verifier_image),
    }
    image_ids: dict[str, str] = {}
    for label, (image, supplied_ref) in requested.items():
        immutable_ref = str(image.get("immutable_ref", ""))
        expected_digest = str(image.get("registry_digest", ""))
        if (
            supplied_ref != immutable_ref
            or not immutable_ref.endswith(f"@{expected_digest}")
            or re.fullmatch(r"sha256:[0-9a-f]{64}", expected_digest) is None
        ):
            raise RuntimeError(
                f"prebuilt {label} image is not the admitted immutable registry reference"
            )
        run(docker_prefix() + ["pull", immutable_ref])
        observed_repo_digests = docker_repo_digests(immutable_ref)
        if immutable_ref not in observed_repo_digests:
            raise RuntimeError(
                f"prebuilt {label} registry digest mismatch: {immutable_ref} not in "
                f"{sorted(observed_repo_digests)}"
            )
        observed_id = docker_image_id(immutable_ref)
        image_ids[label] = observed_id
    return image_ids


def prepare(args: argparse.Namespace) -> None:
    config = load_config()
    inventory = require_h100()
    assets = verify_assets(require_converted_checkpoint=False)
    env = dict(os.environ)
    env["DOCKER_BUILDKIT"] = "1"
    prebuilt_image_ids = None
    if args.prebuilt_images:
        prebuilt_image_ids = _pull_prebuilt_images(
            config,
            train_image=args.train_image,
            verifier_image=args.verifier_image,
        )
    else:
        for dockerfile, image in (
            (config["verifier_image"]["dockerfile"], args.verifier_image),
            (config["training_image"]["dockerfile"], args.train_image),
        ):
            build_args = (
                _training_build_args(config)
                if dockerfile == config["training_image"]["dockerfile"]
                else []
            )
            run(
                docker_prefix()
                + [
                    "build",
                    *build_args,
                    "--progress=plain",
                    "--file",
                    dockerfile,
                    "--tag",
                    image,
                    ".",
                ],
                env=env,
            )
    scratch = Path(args.result_root).resolve() / "preflight-scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    receipt_path = Path(args.receipt).resolve()
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    no_update_path = receipt_path.parent / "hybrid45-no-update-canary.json"
    trainer_contract_path = receipt_path.parent / "miles-grpo-advantage-contract.json"
    trainer_contract_receipt = None
    training_image = config["training_image"]
    if training_image.get("trainer_contract_preflight_required") is True:
        if trainer_contract_path.exists() or trainer_contract_path.is_symlink():
            raise FileExistsError(
                f"refusing to reuse trainer contract receipt: {trainer_contract_path}"
            )
        run(_trainer_contract_command(config, args.train_image, trainer_contract_path))
        trainer_contract_receipt = json.loads(trainer_contract_path.read_text(encoding="utf-8"))
        checks = trainer_contract_receipt.get("checks", {})
        if (
            trainer_contract_receipt.get("status") != "PASS"
            or trainer_contract_receipt.get("optimizer_updates") != 0
            or trainer_contract_receipt.get("miles_commit") != training_image["miles_commit"]
            or trainer_contract_receipt.get("source_files") != training_image["miles_source_files"]
            or checks.get("selected_policy") != GRPO_ADVANTAGE_POLICY_VERSION
            or checks.get("actual_group_local_normalization") is not True
            or checks.get("actual_homogeneous_policy_gradient_zero") is not True
            or checks.get("actual_low_variance_finite") is not True
        ):
            raise RuntimeError("pinned Miles GRPO trainer contract receipt is not a PASS")
    reward_mode = str(config["reward"]["implementation_mode"])
    preflight_command = docker_prefix() + [
        "run",
        "--rm",
        "--gpus",
        "all",
        "--network",
        "none",
        "--volume",
        "/var/run/docker.sock:/var/run/docker.sock",
        "--volume",
        f"{scratch}:{scratch}",
        "--volume",
        f"{receipt_path.parent}:{receipt_path.parent}",
        "--env",
        f"TMPDIR={scratch}",
        "--env",
        "GLM47_CPP_SANDBOX_BACKEND=docker",
        "--env",
        f"GLM47_CPP_SANDBOX_IMAGE={args.verifier_image}",
        "--env",
        f"MILES_AIDER_REWARD_MODE={reward_mode}",
    ]
    if reward_mode in {"hybrid_bipolar45", "hybrid_bipolar45_mef"}:
        preflight_command.extend(
            [
                "--env",
                f"GLM47_HYBRID45_NO_UPDATE_RECEIPT_PATH={no_update_path}",
            ]
        )
    preflight_command.extend(
        [
            args.train_image,
            "python3",
            "-m",
            "glm47_posttraining.integrations.miles_aider_polyglot",
            "preflight",
        ]
    )
    run(preflight_command)
    no_update_receipt = None
    if reward_mode in {"hybrid_bipolar45", "hybrid_bipolar45_mef"}:
        expected_policy = (
            "hybrid-bipolar45-mef-v1" if reward_mode.endswith("_mef") else "hybrid-bipolar45-v2"
        )
        if no_update_path.is_symlink() or not no_update_path.is_file():
            raise RuntimeError("Hybrid45 V2 no-update canary receipt is missing")
        no_update_receipt = json.loads(no_update_path.read_text(encoding="utf-8"))
        if (
            no_update_receipt.get("decision") != "PASS"
            or no_update_receipt.get("policy_version") != expected_policy
            or no_update_receipt.get("optimizer_updates") != 0
        ):
            raise RuntimeError("Hybrid45 V2 no-update canary receipt is not a PASS")
    if not REF_LOAD_MARKER.is_file():
        if (
            MILES_MODEL_ARGS_COMPAT_PATH.is_symlink()
            or not MILES_MODEL_ARGS_COMPAT_PATH.is_file()
        ):
            raise RuntimeError(
                "pinned Miles model-args compatibility loader is missing or unsafe"
            )
        with exclusive_gpu_job("full-v5-checkpoint-conversion"):
            run(
                docker_prefix()
                + [
                    "run",
                    "--rm",
                    "--gpus",
                    "all",
                    "--network",
                    "none",
                    "--ipc",
                    "host",
                    "--shm-size",
                    "256g",
                    "--volume",
                    f"{MODEL_DIR.parent}:/root/models",
                    "--volume",
                    (
                        f"{MILES_MODEL_ARGS_COMPAT_PATH}:"
                        f"{MILES_MODEL_ARGS_COMPAT_CONTAINER_PATH}:ro"
                    ),
                    "--env",
                    "MILES_HF_CHECKPOINT=/root/models/GLM-4.7-Flash",
                    "--env",
                    ("MILES_REF_LOAD_DIR=/root/models/GLM-4.7-Flash_torch_dist_tp4_pp1_ep8"),
                    "--env",
                    "MILES_CONVERT_NPROC=8",
                    args.train_image,
                    "/opt/full-v5-charm/scripts/convert_checkpoint.sh",
                ]
            )
    assets["converted_checkpoint"] = verify_converted_checkpoint()
    image_ids = prebuilt_image_ids or {
        "training": docker_image_id(args.train_image),
        "verifier": docker_image_id(args.verifier_image),
    }
    receipt = {
        "schema_version": "glm47-full-v5-charm-gcp-preparation-v1",
        "status": "passed",
        "created_at_utc": utc_now(),
        "profile_id": config["profile_id"],
        "execution": config["execution"],
        "source_commit": source_commit(),
        "driver_sha256": sha256_path(Path(__file__).resolve()),
        "config_sha256": sha256_path(CONFIG_PATH),
        "assets": assets,
        "gpu_inventory": inventory,
        "images": {
            "training": {"tag": args.train_image, "image_id": image_ids["training"]},
            "verifier": {"tag": args.verifier_image, "image_id": image_ids["verifier"]},
        },
        "no_update_canary": (
            {
                "decision": no_update_receipt["decision"],
                "policy_version": no_update_receipt["policy_version"],
                "optimizer_updates": no_update_receipt["optimizer_updates"],
                "receipt_path": str(no_update_path),
                "receipt_sha256": sha256_path(no_update_path),
            }
            if no_update_receipt is not None
            else None
        ),
        "trainer_contract": (
            {
                "status": trainer_contract_receipt["status"],
                "optimizer_updates": trainer_contract_receipt["optimizer_updates"],
                "miles_commit": trainer_contract_receipt["miles_commit"],
                "selected_policy": trainer_contract_receipt["checks"]["selected_policy"],
                "receipt_path": str(trainer_contract_path),
                "receipt_sha256": sha256_path(trainer_contract_path),
            }
            if trainer_contract_receipt is not None
            else None
        ),
    }
    atomic_json(receipt_path, receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))


def train(args: argparse.Namespace) -> None:
    config = _one_update_smoke_config(
        load_config(), enabled=getattr(args, "one_update_smoke", False), phase=args.phase
    )
    run_id = args.run_id
    if RUN_ID_RE.fullmatch(run_id) is None:
        raise ValueError(f"invalid run ID: {run_id!r}")
    experimental_profile = is_experimental_profile(config)
    profile_contract = PROFILE_CONTRACTS[str(config["profile_id"])]
    if is_candidate_charm_profile(config):
        raise RuntimeError(
            "corrected R8 profile is NOT_COMPLETED; optimizer launch is blocked until "
            "oracle replay, trainer proofs, fresh pre-training PASS, and admitted-profile regeneration"
        )
    smoke_receipt = None
    smoke_bypass = None
    if args.phase == "experimental":
        if not experimental_profile:
            raise RuntimeError("experimental phase requires the quarantined unadmitted profile")
        run_id_prefix = str(profile_contract["run_id_prefix"])
        if not run_id.startswith(run_id_prefix):
            raise ValueError(f"experimental run IDs must start with {run_id_prefix!r}")
        authorization_env = str(profile_contract["authorization_env"])
        authorization_phrase = str(profile_contract["authorization_phrase"])
        if os.environ.get(authorization_env) != authorization_phrase:
            raise RuntimeError(
                "unadmitted experiment is not authorized; set "
                f"{authorization_env}={authorization_phrase} "
                "only after accepting the 8xH100 cost and quarantine-only disposition"
            )
        if profile_contract.get("requires_smoke_receipt") is True:
            smoke_bypass = _operator_smoke_bypass(str(config["profile_id"]))
            if smoke_bypass is None:
                smoke_receipt = _experimental_smoke_receipt(
                    args.smoke_receipt,
                    args.expected_smoke_receipt_sha256,
                    profile_contract=profile_contract,
                )
                checkpoint_bytes = int(smoke_receipt["checkpoint"]["total_bytes"])
                projected_checkpoint_bytes = int(
                    checkpoint_bytes * int(config["full_training"]["rollout_updates"]) * 1.10
                )
                required_free_bytes = projected_checkpoint_bytes + 20 * 1024**3
                free_bytes = shutil.disk_usage("/opt" if Path("/opt").exists() else "/").free
                if free_bytes < required_free_bytes:
                    raise RuntimeError(
                        "R3 full checkpoint storage projection exceeds free disk: "
                        f"required={required_free_bytes} free={free_bytes} "
                        f"checkpoint={checkpoint_bytes}"
                    )
        admission = None
        task_ids = selected_experimental_task_ids(config)
        promotion = None
    elif args.phase == "canary":
        if experimental_profile:
            raise RuntimeError("the unadmitted experiment profile cannot run a CHARM canary")
        admission = _pass_receipt(
            Path(args.pretraining_receipt),
            expected_sha256=args.expected_pretraining_sha256,
            expected_stage="pre-training",
        )
        task_ids = _canary_tasks(
            Path(args.canary_task_manifest),
            args.expected_canary_task_manifest_sha256,
            config,
        )
        promotion = None
    else:
        if experimental_profile:
            raise RuntimeError("the unadmitted experiment profile cannot run production full")
        authorization_env = str(profile_contract.get("authorization_env", FULL_AUTHORIZATION_ENV))
        authorization_phrase = str(
            profile_contract.get("authorization_phrase", FULL_AUTHORIZATION_PHRASE)
        )
        if os.environ.get(authorization_env) != authorization_phrase:
            raise RuntimeError(
                "full training is not authorized; set "
                f"{authorization_env}={authorization_phrase} only after "
                "the exact CHARM canary promotion PASS"
            )
        admission = None
        task_ids = None
        promotion = _pass_receipt(
            Path(args.promotion_receipt),
            expected_sha256=args.expected_promotion_sha256,
            expected_stage="promotion",
        )
    with exclusive_gpu_job(f"full-v5-charm-{args.phase}"):
        inventory = require_h100()
        if profile_contract.get("required_provisioning_policy") is not None:
            scheduling = require_provisioning_policy(config)
        else:
            scheduling = {
                "provisioning_policy": str(
                    config.get("gcp", {}).get("provisioning_policy", "unknown")
                ).upper(),
                "metadata_preemptible": metadata_value("instance/scheduling/preemptible").upper(),
            }
        assets = verify_assets()
        result_root = Path(args.result_root).resolve()
        host_run_root = result_root / "runs" / run_id
        if host_run_root.exists() or host_run_root.is_symlink():
            raise FileExistsError(f"refusing to reuse run root: {host_run_root}")
        host_run_root.mkdir(parents=True)
        host_tmpdir = host_run_root / "runtime_state/tmp"
        host_tmpdir.mkdir(parents=True)
        phase_config = config["canary"] if args.phase == "canary" else config["full_training"]
        if is_r7_profile(config):
            schedule = stage_r7_training_data(
                runtime_dir(config),
                host_run_root / "data",
                phase=args.phase,
                canary_task_ids=task_ids,
            )
        else:
            schedule = build_charm_schedule(
                runtime_dir(config),
                host_run_root / "data",
                epochs=int(phase_config["epochs"]),
                rollout_batch_size=int(phase_config["rollout_batch_size"]),
                expected_manifest_sha256=config["full_v5_runtime"]["manifest_sha256"],
                expected_tree_sha256=config["full_v5_runtime"]["tree_sha256"],
                selected_task_ids=task_ids,
                reward_policy=profile_contract.get("reward_policy"),
            )
        container_run_root = f"/results/runs/{run_id}"
        training_image_id = docker_image_id(args.train_image)
        verifier_image_id = docker_image_id(args.verifier_image)
        if smoke_receipt is not None:
            smoke_images = smoke_receipt.get("images", {})
            if training_image_id != smoke_images.get("training", {}).get(
                "image_id"
            ) or verifier_image_id != smoke_images.get("verifier", {}).get("image_id"):
                raise RuntimeError(
                    "full experiment images differ from the smoke-certified image IDs"
                )
        env_values = build_training_env(
            phase=args.phase,
            run_id=run_id,
            container_run_root=container_run_root,
            host_run_root=host_run_root,
            verifier_image=verifier_image_id,
            config=config,
        )
        launch = {
            "schema_version": "glm47-full-v5-charm-launch-v1",
            "status": "authorized",
            "created_at_utc": utc_now(),
            "profile_id": config["profile_id"],
            "execution": config["execution"],
            "phase": args.phase,
            "run_id": run_id,
            "source_commit": source_commit(),
            "driver_sha256": sha256_path(Path(__file__).resolve()),
            "config_sha256": sha256_path(CONFIG_PATH),
            "admission_status": ("NOT_COMPLETED" if args.phase == "experimental" else "GATED"),
            "charm_eligible": args.phase != "experimental",
            "checkpoint_disposition": (
                "QUARANTINE_ONLY" if args.phase == "experimental" else "GATED"
            ),
            "retroactive_admission_allowed": False,
            "gpu_inventory": inventory,
            "gce_scheduling": scheduling,
            "assets": assets,
            "images": {
                "training": {"tag": args.train_image, "image_id": training_image_id},
                "verifier": {"tag": args.verifier_image, "image_id": verifier_image_id},
            },
            "schedule": schedule,
            "result_sync": {
                "destination": f"{config['gcp']['result_destination'].rstrip('/')}/{run_id}",
                "interval_seconds": int(config["tracking"]["result_sync_interval_seconds"]),
            },
            "pretraining_receipt_sha256": args.expected_pretraining_sha256 if admission else None,
            "promotion_receipt_sha256": args.expected_promotion_sha256 if promotion else None,
            "smoke_receipt_sha256": (args.expected_smoke_receipt_sha256 if smoke_receipt else None),
            "smoke_gate": (
                smoke_bypass
                if smoke_bypass is not None
                else {"status": "PASSED", "receipt_bound": True}
                if smoke_receipt is not None
                else None
            ),
            "storage_projection": (
                {
                    "checkpoint_bytes": int(smoke_receipt["checkpoint"]["total_bytes"]),
                    "rollout_updates": int(phase_config["rollout_updates"]),
                    "checkpoint_growth_margin": 1.10,
                    "fixed_headroom_bytes": 20 * 1024**3,
                    "required_free_bytes": int(
                        int(smoke_receipt["checkpoint"]["total_bytes"])
                        * int(phase_config["rollout_updates"])
                        * 1.10
                    )
                    + 20 * 1024**3,
                }
                if smoke_receipt
                else None
            ),
            "environment": env_values,
        }
        atomic_json(host_run_root / "launch-contract.json", launch)
        result_destination = launch["result_sync"]["destination"]
        sync_state: dict[str, Any] = {"final_status": "not_started"}
        try:
            with periodic_result_sync(
                host_run_root,
                result_destination,
                interval_seconds=launch["result_sync"]["interval_seconds"],
            ) as sync_state:
                run(
                    _docker_training_command(
                        run_id=run_id,
                        result_root=result_root,
                        train_image=training_image_id,
                        env_values=env_values,
                    )
                )
            receipt = host_run_root / "grpo_lora_r16/run_receipt.txt"
            if not receipt.is_file() or "status=success" not in receipt.read_text(encoding="utf-8"):
                raise RuntimeError("Miles training did not produce a successful run receipt")
            if sync_state["final_status"] != "passed":
                raise RuntimeError(
                    f"final GCS result sync failed: {sync_state.get('final_error', 'unknown')}"
                )
            if int(sync_state.get("consecutive_successes", 0)) < 2:
                raise RuntimeError(
                    "durable GCS synchronization did not produce two consecutive "
                    "successful receipts"
                )
            expected_checkpoints = int(phase_config["rollout_updates"])
            published_checkpoints = sync_state.get("published_checkpoints", {})
            if len(published_checkpoints) != expected_checkpoints:
                raise RuntimeError(
                    "complete GCS checkpoint count mismatch: "
                    f"{len(published_checkpoints)} != {expected_checkpoints}"
                )
        except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
            pre_receipt_sync_error = None
            try:
                _sync_result_tree(
                    host_run_root,
                    result_destination,
                    include_completed_rollouts=True,
                )
            except (OSError, RuntimeError, subprocess.CalledProcessError) as sync_exc:
                pre_receipt_sync_error = f"{type(sync_exc).__name__}: {sync_exc}"
            failure = {
                "schema_version": "glm47-full-v5-charm-execution-v1",
                "status": "failed",
                "completed_at_utc": utc_now(),
                "profile_id": config["profile_id"],
                "execution": config["execution"],
                "phase": args.phase,
                "run_id": run_id,
                "source_commit": source_commit(),
                "admission_status": ("NOT_COMPLETED" if args.phase == "experimental" else "GATED"),
                "charm_eligible": args.phase != "experimental",
                "checkpoint_disposition": (
                    "QUARANTINE_ONLY" if args.phase == "experimental" else "GATED"
                ),
                "retroactive_admission_allowed": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "result_sync": sync_state,
                "pre_receipt_sync_error": pre_receipt_sync_error,
            }
            atomic_json(host_run_root / "execution-receipt.json", failure)
            try:
                _sync_result_tree(
                    host_run_root,
                    result_destination,
                    include_completed_rollouts=True,
                )
            except (OSError, RuntimeError, subprocess.CalledProcessError):
                pass
            raise
        completion = {
            "schema_version": "glm47-full-v5-charm-execution-v1",
            "status": "passed",
            "completed_at_utc": utc_now(),
            "profile_id": config["profile_id"],
            "execution": config["execution"],
            "phase": args.phase,
            "run_id": run_id,
            "source_commit": source_commit(),
            "admission_status": ("NOT_COMPLETED" if args.phase == "experimental" else "GATED"),
            "charm_eligible": args.phase != "experimental",
            "checkpoint_disposition": (
                "QUARANTINE_ONLY" if args.phase == "experimental" else "GATED"
            ),
            "retroactive_admission_allowed": False,
            "result_sync": sync_state,
        }
        atomic_json(host_run_root / "execution-receipt.json", completion)
        _sync_result_tree(
            host_run_root,
            result_destination,
            include_completed_rollouts=True,
        )
        print(f"FULL_V5_CHARM_RUN_ROOT={host_run_root}")


def parser() -> argparse.ArgumentParser:
    config = load_config()
    result = argparse.ArgumentParser(description=__doc__)
    result.set_defaults(
        train_image=config["training_image"]["local_name"],
        verifier_image=config["verifier_image"]["local_name"],
    )
    sub = result.add_subparsers(dest="command", required=True)
    sub.add_parser("inspect").set_defaults(func=inspect)
    sub.add_parser("host-check").set_defaults(func=host_check)
    render_parser = sub.add_parser("render")
    render_parser.add_argument("--phase", choices=("canary", "full", "experimental"), required=True)
    render_parser.add_argument("--run-id")
    render_parser.add_argument("--one-update-smoke", action="store_true")
    render_parser.set_defaults(func=render)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--result-root", default=str(RESULT_ROOT))
    prepare_parser.add_argument("--receipt", default=str(RESULT_ROOT / "preparation-receipt.json"))
    prepare_parser.add_argument("--train-image", default=config["training_image"]["local_name"])
    prepare_parser.add_argument("--verifier-image", default=config["verifier_image"]["local_name"])
    prepare_parser.add_argument("--prebuilt-images", action="store_true")
    prepare_parser.set_defaults(func=prepare)
    train_parser = sub.add_parser("train")
    train_parser.add_argument("--phase", choices=("canary", "full", "experimental"), required=True)
    train_parser.add_argument("--run-id", required=True)
    train_parser.add_argument("--one-update-smoke", action="store_true")
    train_parser.add_argument("--result-root", default=str(RESULT_ROOT))
    train_parser.add_argument("--train-image", default=config["training_image"]["local_name"])
    train_parser.add_argument("--verifier-image", default=config["verifier_image"]["local_name"])
    train_parser.add_argument("--pretraining-receipt")
    train_parser.add_argument("--expected-pretraining-sha256", default="")
    train_parser.add_argument("--canary-task-manifest")
    train_parser.add_argument("--expected-canary-task-manifest-sha256", default="")
    train_parser.add_argument("--promotion-receipt")
    train_parser.add_argument("--expected-promotion-sha256", default="")
    train_parser.add_argument("--smoke-receipt")
    train_parser.add_argument("--expected-smoke-receipt-sha256", default="")
    train_parser.set_defaults(func=train)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "train" and args.phase == "canary":
            if not args.pretraining_receipt or not args.canary_task_manifest:
                raise ValueError("canary requires --pretraining-receipt and --canary-task-manifest")
        if args.command == "train" and args.phase == "full" and not args.promotion_receipt:
            raise ValueError("full training requires --promotion-receipt")
        args.func(args)
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"FULL_V5_CHARM_GCP_FAILED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
