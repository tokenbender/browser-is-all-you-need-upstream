#!/usr/bin/env python3
"""Build the exact 2,000-row Aider C++ SFT v6 corpus.

The package keeps the quality-cleared, target-distinct portion of SFT v5,
adds the existing pass@1-focused tranche, adds unused mutation-adequate rows,
and fills the remaining budget with cross-family multi-file compositions of
independently executable-verified parents.

Every composed row is executed against both component test suites. The build
is deterministic and writes into a staging directory before replacing the
package.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
WORKSPACE = Path(
    os.environ.get("AIDER_POSTTRAINING_WORKSPACE", REPO_ROOT)
).resolve()
ARTIFACT = Path(
    os.environ.get(
        "AIDER_SFT_V6_ARTIFACT_ROOT",
        REPO_ROOT / "artifacts/aider-cpp-sft-v6-2000",
    )
).resolve()
PACKAGE = ARTIFACT / "package"
CACHE = ARTIFACT / "cache/composition_verification"

INPUT_ROOT = (
    Path(os.environ["AIDER_SFT_V6_INPUT_ROOT"]).resolve()
    if os.environ.get("AIDER_SFT_V6_INPUT_ROOT")
    else None
)
if INPUT_ROOT:
    V5_TRAIN = INPUT_ROOT / "v5_train.jsonl"
    V5_OVERLAP = INPUT_ROOT / "v5_overlap_audit.json"
    V5_REVIEW = INPUT_ROOT / "v5_review_queue.jsonl"
    PASS1_ROWS = INPUT_ROOT / "pass1_rows.jsonl"
    PASS1_VERIFY = INPUT_ROOT / "pass1_verification.jsonl"
    HOLISTIC_TRAIN = INPUT_ROOT / "holistic_train.jsonl"
    HOLISTIC_TOKENS = INPUT_ROOT / "holistic_token_audit.json"
    HOLISTIC_VERIFY = INPUT_ROOT / "holistic_verification.jsonl"
    HOLISTIC_TESTS = INPUT_ROOT / "holistic_tests.jsonl"
    CANDIDATE_VARIANTS = INPUT_ROOT / "candidate_variants.jsonl"
    CANDIDATE_RECEIPTS = INPUT_ROOT / "candidate_receipts.jsonl"
    FIXED26 = INPUT_ROOT / "fixed26_manifest.json"
else:
    V5_ROOT = WORKSPACE / "artifacts/aider-cpp-sft-v5-1340/package"
    V5_TRAIN = V5_ROOT / "sft/train.jsonl"
    V5_OVERLAP = V5_ROOT / "reports/overlap_audit.json"
    V5_REVIEW = V5_ROOT / "review/queue.jsonl"

    PASS1_ROOT = WORKSPACE / "artifacts/aider-cpp-pass1-skills-600"
    PASS1_ROWS = PASS1_ROOT / "receipts/synthetic_rows.jsonl"
    PASS1_VERIFY = PASS1_ROOT / "receipts/verification.jsonl"

    HOLISTIC_ROOT = WORKSPACE / "artifacts/aider-cpp-holistic-260-v1"
    HOLISTIC_TRAIN = HOLISTIC_ROOT / "sft/train.jsonl"
    HOLISTIC_TOKENS = HOLISTIC_ROOT / "receipts/token_audit.json"
    HOLISTIC_VERIFY = HOLISTIC_ROOT / "receipts/verification.jsonl"
    HOLISTIC_TESTS = ARTIFACT / "source_cache/holistic_tests.jsonl"

    CANDIDATE_ROOT = WORKSPACE / "artifacts/aider-cpp-combined-v5-build"
    CANDIDATE_VARIANTS = CANDIDATE_ROOT / "candidate_variants.jsonl"
    CANDIDATE_RECEIPTS = CANDIDATE_ROOT / "executable_test_receipts.jsonl"

    FIXED26 = HOLISTIC_ROOT / "validation/fixed26_manifest.json"

SOURCE_INPUTS = {
    "v5_train.jsonl": V5_TRAIN,
    "v5_overlap_audit.json": V5_OVERLAP,
    "v5_review_queue.jsonl": V5_REVIEW,
    "pass1_rows.jsonl": PASS1_ROWS,
    "pass1_verification.jsonl": PASS1_VERIFY,
    "holistic_train.jsonl": HOLISTIC_TRAIN,
    "holistic_token_audit.json": HOLISTIC_TOKENS,
    "holistic_verification.jsonl": HOLISTIC_VERIFY,
    "holistic_tests.jsonl": HOLISTIC_TESTS,
    "candidate_variants.jsonl": CANDIDATE_VARIANTS,
    "candidate_receipts.jsonl": CANDIDATE_RECEIPTS,
    "fixed26_manifest.json": FIXED26,
}

MODEL_REPOSITORY = "zai-org/GLM-4.7-Flash"
MODEL_REVISION = "7dd20894a642a0aa287e9827cb1a1f7f91386b67"
SEQUENCE_LENGTH = 4096
EXPECTED_TOTAL = 2000
EXPECTED_RETAINED = 949
EXPECTED_PASS1 = 70
EXPECTED_UNUSED_PASSED = 3
EXPECTED_COMPOSED = 978
PARENT_USE_CAP = 5

COMMON_PREAMBLE = """Use Aider whole edit format. Modify all supplied editable files to solve both independent modules in this repository task. Return only complete file listings. Each fenced block must be preceded by the bare filename on the line immediately before the fence. Do not return a diff. Do not include test files, reference example files, or explanatory prose in the answer.

This is a cross-family composition task: both modules must be implemented in the same response. Their public APIs, filenames, validation rules, ordering rules, and failure behavior are independent and must all be preserved.
"""

FILE_BLOCK = re.compile(
    r"(?m)^([A-Za-z0-9_.+/-]+\.(?:h|hpp|hh|cpp|cc|cxx))\s*\n"
    r"```(?:cpp|c\+\+|cxx|cc|c)?[ \t]*\n(.*?)\n```",
    re.DOTALL,
)


@dataclass(frozen=True)
class Parent:
    task_id: str
    family: str
    category: str
    token_count: int
    prompt: str
    answer: str
    files: dict[str, str]
    test_cpp: str
    source: str
    receipt_sha256: str


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode())


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_hash(value: str) -> str:
    return sha256_text(re.sub(r"\s+", " ", value).strip().lower())


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def jsonl_bytes(values: Iterable[dict[str, Any]]) -> bytes:
    return b"".join((canonical_json(value) + "\n").encode() for value in values)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, values: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(jsonl_bytes(values))


def row_id(row: dict[str, Any]) -> str:
    value = row.get("task_id") or row.get("id") or row.get("label")
    if not isinstance(value, str) or not value:
        raise RuntimeError("row lacks a stable task ID")
    return value


def row_pair_hash(row: dict[str, Any]) -> str:
    messages = row.get("messages")
    if not isinstance(messages, list) or len(messages) != 2:
        raise RuntimeError(f"{row_id(row)}: expected exactly two messages")
    return sha256_text(canonical_json(messages))


def prompt_hash(row: dict[str, Any]) -> str:
    return normalized_hash(row["messages"][0]["content"])


def answer_hash(row: dict[str, Any]) -> str:
    return normalized_hash(row["messages"][1]["content"])


def extract_files(text: str) -> dict[str, str]:
    files: dict[str, str] = {}
    for match in FILE_BLOCK.finditer(text):
        name = match.group(1)
        if name in files:
            raise RuntimeError(f"duplicate file listing: {name}")
        files[name] = match.group(2).rstrip() + "\n"
    if not files:
        raise RuntimeError("no complete file listings found")
    return files


def task_body(prompt: str) -> str:
    marker = "\n# "
    index = prompt.find(marker)
    if index == -1:
        return prompt.strip()
    return prompt[index + 1 :].strip()


def validate_row_shape(row: dict[str, Any], *, allow_parent_label: bool = True) -> None:
    task_id = row_id(row)
    messages = row.get("messages")
    if not isinstance(messages, list) or len(messages) != 2:
        raise RuntimeError(f"{task_id}: invalid conversation length")
    if [message.get("role") for message in messages] != ["user", "assistant"]:
        raise RuntimeError(f"{task_id}: invalid role order")
    if not all(
        isinstance(message.get("content"), str) and message["content"].strip()
        for message in messages
    ):
        raise RuntimeError(f"{task_id}: empty message")
    answer_files = extract_files(messages[1]["content"])
    prompt_files = extract_files(messages[0]["content"])
    if set(answer_files) != set(prompt_files):
        raise RuntimeError(
            f"{task_id}: prompt/answer file mismatch "
            f"{sorted(prompt_files)} != {sorted(answer_files)}"
        )
    if not allow_parent_label and row.get("label") != task_id:
        raise RuntimeError(f"{task_id}: new row label must equal task ID")


def source_hashes() -> dict[str, dict[str, Any]]:
    paths = {
        "v5_train": ("v5_train.jsonl", V5_TRAIN),
        "v5_overlap": ("v5_overlap_audit.json", V5_OVERLAP),
        "v5_review": ("v5_review_queue.jsonl", V5_REVIEW),
        "pass1_rows": ("pass1_rows.jsonl", PASS1_ROWS),
        "pass1_verification": ("pass1_verification.jsonl", PASS1_VERIFY),
        "holistic_train": ("holistic_train.jsonl", HOLISTIC_TRAIN),
        "holistic_tokens": ("holistic_token_audit.json", HOLISTIC_TOKENS),
        "holistic_verification": (
            "holistic_verification.jsonl",
            HOLISTIC_VERIFY,
        ),
        "holistic_tests": ("holistic_tests.jsonl", HOLISTIC_TESTS),
        "candidate_variants": ("candidate_variants.jsonl", CANDIDATE_VARIANTS),
        "candidate_receipts": ("candidate_receipts.jsonl", CANDIDATE_RECEIPTS),
        "fixed26": ("fixed26_manifest.json", FIXED26),
    }
    return {
        name: {
            "path": f"inputs/{bundled_name}",
            "bytes": path.stat().st_size,
            "sha256": sha256_path(path),
        }
        for name, (bundled_name, path) in paths.items()
    }


def ensure_holistic_tests() -> None:
    if HOLISTIC_TESTS.is_file():
        return
    if INPUT_ROOT:
        raise RuntimeError(f"missing bundled holistic tests: {HOLISTIC_TESTS}")
    rows = read_jsonl(HOLISTIC_TRAIN)
    tests = []
    for row in sorted(rows, key=row_id):
        task_id = row_id(row)
        test_path = HOLISTIC_ROOT / "packages" / task_id / "tests/test.cpp"
        test_cpp = test_path.read_text(encoding="utf-8")
        tests.append(
            {
                "task_id": task_id,
                "test_cpp": test_cpp,
                "test_sha256": sha256_text(test_cpp),
            }
        )
    write_jsonl(HOLISTIC_TESTS, tests)


def retained_v5_rows() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = read_jsonl(V5_TRAIN)
    if len(rows) != 1340:
        raise RuntimeError(f"expected 1,340 v5 rows, got {len(rows)}")
    overlap = json.loads(V5_OVERLAP.read_text(encoding="utf-8"))
    review_ids = {row_id(row) for row in read_jsonl(V5_REVIEW)}
    target_novel = set(overlap["target_novel_task_ids"])
    source_rows = rows[790:]
    retained_source = [
        row
        for row in source_rows
        if row_id(row) in target_novel and row_id(row) not in review_ids
    ]
    retained = rows[:790] + retained_source
    if len(retained) != EXPECTED_RETAINED:
        raise RuntimeError(
            f"expected {EXPECTED_RETAINED} retained v5 rows, got {len(retained)}"
        )
    return retained, {
        "v5_rows": len(rows),
        "v4_parent_rows_retained": 790,
        "source550_target_novel_cleared_retained": len(retained_source),
        "source550_same_target_rows_replaced": len(
            overlap["same_target_task_ids"]
        ),
        "source550_review_rows_replaced": len(review_ids),
    }


def pass1_rows(full_v5: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = read_jsonl(PASS1_ROWS)
    receipts = {row["task_id"]: row for row in read_jsonl(PASS1_VERIFY)}
    if len(rows) != EXPECTED_PASS1 or len(receipts) != EXPECTED_PASS1:
        raise RuntimeError("pass1 tranche count drift")
    old_ids = {row_id(row) for row in full_v5}
    old_pairs = {row_pair_hash(row) for row in full_v5}
    for row in rows:
        task_id = row_id(row)
        if task_id in old_ids or row_pair_hash(row) in old_pairs:
            raise RuntimeError(f"pass1 row overlaps v5: {task_id}")
        receipt = receipts.get(task_id)
        if not receipt or receipt.get("passed") is not True:
            raise RuntimeError(f"pass1 row lacks passed receipt: {task_id}")
        validate_row_shape(row, allow_parent_label=False)
    return rows


def candidate_maps() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    variants = {row["task_id"]: row for row in read_jsonl(CANDIDATE_VARIANTS)}
    receipts = {
        row["task_id"]: row
        for row in read_jsonl(CANDIDATE_RECEIPTS)
        if row.get("stage") == "passed"
    }
    if len(receipts) != 256:
        raise RuntimeError(f"expected 256 passed candidate receipts, got {len(receipts)}")
    if set(receipts) - set(variants):
        raise RuntimeError("passed candidate receipt lacks a variant")
    return variants, receipts


def candidate_row(variant: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
    task_id = variant["task_id"]
    return {
        "label": task_id,
        "task_id": task_id,
        "messages": [
            {"role": "user", "content": variant["prompt"]},
            {"role": "assistant", "content": variant["answer"]},
        ],
        "metadata": {
            "task_id": task_id,
            "subset": "train",
            "purpose": "first-pass-cpp-editing",
            "source_corpus": "mutation-adequate-candidate-v4",
            "family": variant["family"],
            "category": variant["category"],
            "synthetic": True,
            "executable_stage": "passed",
            "oracle": "answer-blind-cpp17-asan-ubsan-mutation-adequate",
            "mutation_score": receipt["mutation_score"],
            "test_sha256": receipt["test_sha256"],
            "receipt_sha256": sha256_text(canonical_json(receipt)),
            "tags": sorted(
                set(variant.get("tags", []))
                | {
                    "first-pass",
                    "api-preservation",
                    "starter-rejection",
                    "mutation-adequate",
                }
            ),
        },
    }


def unused_passed_rows(
    full_v5: list[dict[str, Any]],
    variants: dict[str, dict[str, Any]],
    receipts: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    old_ids = {row_id(row) for row in full_v5}
    old_pairs = {row_pair_hash(row) for row in full_v5}
    old_answers = {answer_hash(row) for row in full_v5}
    selected: list[dict[str, Any]] = []
    for task_id in sorted(receipts):
        row = candidate_row(variants[task_id], receipts[task_id])
        if (
            task_id in old_ids
            or row_pair_hash(row) in old_pairs
            or answer_hash(row) in old_answers
        ):
            continue
        validate_row_shape(row, allow_parent_label=False)
        selected.append(row)
    if len(selected) != EXPECTED_UNUSED_PASSED:
        raise RuntimeError(
            f"expected {EXPECTED_UNUSED_PASSED} unused passed rows, got {len(selected)}"
        )
    return selected


def holistic_parents() -> list[Parent]:
    rows = {row_id(row): row for row in read_jsonl(HOLISTIC_TRAIN)}
    tokens = {
        row["task_id"]: int(row["tokens"])
        for row in json.loads(HOLISTIC_TOKENS.read_text(encoding="utf-8"))["tasks"]
    }
    receipts = {
        row["task_id"]: row for row in read_jsonl(HOLISTIC_VERIFY)
    }
    tests = {row["task_id"]: row for row in read_jsonl(HOLISTIC_TESTS)}
    parents = []
    for task_id in sorted(rows):
        row = rows[task_id]
        receipt = receipts[task_id]
        if receipt.get("passed") is not True or receipt.get("starter_rejected") is not True:
            raise RuntimeError(f"holistic parent lacks executable proof: {task_id}")
        parents.append(
            Parent(
                task_id=task_id,
                family=receipt["seed_family"],
                category="holistic-curriculum",
                token_count=tokens[task_id],
                prompt=row["messages"][0]["content"],
                answer=row["messages"][1]["content"],
                files=extract_files(row["messages"][1]["content"]),
                test_cpp=tests[task_id]["test_cpp"],
                source="holistic-260-v1",
                receipt_sha256=sha256_text(canonical_json(receipt)),
            )
        )
    if len(parents) != 260:
        raise RuntimeError("holistic parent count drift")
    return parents


def candidate_parents(
    variants: dict[str, dict[str, Any]],
    receipts: dict[str, dict[str, Any]],
) -> list[Parent]:
    parents = []
    for task_id in sorted(receipts):
        variant = variants[task_id]
        receipt = receipts[task_id]
        parents.append(
            Parent(
                task_id=task_id,
                family=variant["family"],
                category=variant["category"],
                token_count=int(variant["token_count"]),
                prompt=variant["prompt"],
                answer=variant["answer"],
                files=extract_files(variant["answer"]),
                test_cpp=receipt["test_cpp"],
                source="mutation-adequate-candidate-v4",
                receipt_sha256=sha256_text(canonical_json(receipt)),
            )
        )
    return parents


def composition_row(left: Parent, right: Parent) -> dict[str, Any]:
    task_id = f"compose-{left.task_id}--{right.task_id}"
    prompt = (
        COMMON_PREAMBLE.rstrip()
        + "\n\n# Module A\n\n"
        + task_body(left.prompt)
        + "\n\n# Module B\n\n"
        + task_body(right.prompt)
        + "\n"
    )
    answer = left.answer.rstrip() + "\n\n" + right.answer.lstrip()
    return {
        "label": task_id,
        "task_id": task_id,
        "messages": [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": answer},
        ],
        "metadata": {
            "task_id": task_id,
            "subset": "train",
            "purpose": "cross-family-first-pass-composition",
            "source_corpus": "verified-component-composition-v1",
            "family": "cross-family-composition",
            "category": f"{left.category}+{right.category}",
            "difficulty": "advanced",
            "synthetic": True,
            "executable_stage": "pending-current-replay",
            "oracle": "union-of-two-independent-cpp17-sanitized-executable-oracles",
            "component_task_ids": [left.task_id, right.task_id],
            "component_families": [left.family, right.family],
            "component_sources": [left.source, right.source],
            "component_receipt_sha256": [
                left.receipt_sha256,
                right.receipt_sha256,
            ],
            "tags": [
                "first-pass",
                "multi-file",
                "cross-family",
                "composition",
                "api-preservation",
                "independent-failure-contracts",
            ],
        },
    }


def candidate_pairs(
    lefts: list[Parent], rights: list[Parent]
) -> list[tuple[Parent, Parent]]:
    lefts = sorted(lefts, key=lambda row: (row.token_count, row.task_id))
    rights = sorted(rights, key=lambda row: (row.token_count, row.task_id))
    left_use = Counter()
    right_use = Counter()
    seen: set[tuple[str, str]] = set()
    pairs: list[tuple[Parent, Parent]] = []
    for _ in range(PARENT_USE_CAP):
        for left in lefts:
            options = [
                right
                for right in rights
                if right_use[right.task_id] < PARENT_USE_CAP
                and right.family != left.family
                and left.token_count + right.token_count <= 3400
                and not (set(left.files) & set(right.files))
                and (left.task_id, right.task_id) not in seen
            ]
            if not options:
                continue
            right = min(
                options,
                key=lambda row: (
                    right_use[row.task_id],
                    abs(row.token_count - left.token_count),
                    row.task_id,
                ),
            )
            seen.add((left.task_id, right.task_id))
            left_use[left.task_id] += 1
            right_use[right.task_id] += 1
            pairs.append((left, right))
    if len(pairs) < EXPECTED_COMPOSED + 80:
        raise RuntimeError(f"insufficient composition candidates: {len(pairs)}")
    return pairs


def compiler() -> str:
    for value in (
        os.environ.get("CXX"),
        "/usr/bin/clang++",
        shutil.which("clang++"),
        shutil.which("g++"),
        shutil.which("c++"),
    ):
        if value and Path(value).exists():
            return str(value)
    raise RuntimeError("no C++ compiler found")


def run_command(command: list[str], cwd: Path, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
        env={
            **os.environ,
            "ASAN_OPTIONS": "detect_leaks=0:abort_on_error=1",
            "UBSAN_OPTIONS": "halt_on_error=1",
        },
    )


def verify_parent_test(
    directory: Path,
    files: dict[str, str],
    test_cpp: str,
    suffix: str,
) -> dict[str, Any]:
    for name, content in files.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    test_path = directory / f"test_{suffix}.cpp"
    test_path.write_text(test_cpp, encoding="utf-8")
    sources = sorted(
        str(directory / name)
        for name in files
        if Path(name).suffix in {".cpp", ".cc", ".cxx"}
    )
    binary = directory / f"test_{suffix}"
    command = [
        compiler(),
        "-std=c++17",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-pedantic",
        "-fsanitize=address,undefined",
        "-fno-omit-frame-pointer",
        "-I",
        str(directory),
        *sources,
        str(test_path),
        "-o",
        str(binary),
    ]
    compiled = run_command(command, directory)
    if compiled.returncode != 0:
        return {
            "passed": False,
            "compile_returncode": compiled.returncode,
            "diagnostic": compiled.stderr[-4000:],
        }
    executed = run_command([str(binary)], directory)
    return {
        "passed": executed.returncode == 0,
        "compile_returncode": compiled.returncode,
        "test_returncode": executed.returncode,
        "diagnostic": (executed.stdout + executed.stderr)[-4000:],
        "test_sha256": sha256_text(test_cpp),
    }


def verify_composition(pair: tuple[Parent, Parent]) -> tuple[dict[str, Any], dict[str, Any]]:
    left, right = pair
    row = composition_row(left, right)
    validate_row_shape(row, allow_parent_label=False)
    cache_key = sha256_text(
        canonical_json(
            {
                "task_id": row_id(row),
                "row_pair_hash": row_pair_hash(row),
                "component_receipts": [
                    left.receipt_sha256,
                    right.receipt_sha256,
                ],
                "compiler": compiler(),
                "flags": "c++17-wall-wextra-werror-pedantic-asan-ubsan-v1",
            }
        )
    )
    cache_path = CACHE / f"{cache_key}.json"
    if cache_path.is_file():
        receipt = json.loads(cache_path.read_text(encoding="utf-8"))
        if receipt.get("cache_key") == cache_key:
            return row, receipt
    with tempfile.TemporaryDirectory(prefix="aider-v6-compose-") as raw:
        directory = Path(raw)
        left_result = verify_parent_test(directory, left.files, left.test_cpp, "a")
        if not left_result["passed"]:
            receipt = {
                "task_id": row_id(row),
                "passed": False,
                "component": left.task_id,
                "result": left_result,
                "cache_key": cache_key,
                "cache_hit": False,
            }
            CACHE.mkdir(parents=True, exist_ok=True)
            write_json(cache_path, receipt)
            return row, receipt
        right_result = verify_parent_test(directory, right.files, right.test_cpp, "b")
        passed = right_result["passed"]
        receipt = {
            "task_id": row_id(row),
            "passed": passed,
            "component_results": {
                left.task_id: left_result,
                right.task_id: right_result,
            },
            "compiler": compiler(),
            "sanitizers": ["address", "undefined"],
            "component_task_ids": [left.task_id, right.task_id],
            "component_families": [left.family, right.family],
            "cache_key": cache_key,
            "cache_hit": False,
        }
        CACHE.mkdir(parents=True, exist_ok=True)
        write_json(cache_path, receipt)
        return row, receipt


def build_compositions(
    lefts: list[Parent], rights: list[Parent], workers: int, tokenizer: Any
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    pairs = []
    rejected: list[dict[str, Any]] = []
    for pair in candidate_pairs(lefts, rights):
        row = composition_row(*pair)
        tokens = token_count(tokenizer, row)
        if tokens > SEQUENCE_LENGTH:
            rejected.append(
                {
                    "task_id": row_id(row),
                    "passed": False,
                    "stage": "token-limit",
                    "tokens": tokens,
                    "limit": SEQUENCE_LENGTH,
                }
            )
            continue
        pairs.append(pair)
    selected_rows: list[dict[str, Any]] = []
    selected_receipts: list[dict[str, Any]] = []
    batch_size = 80
    for start in range(0, len(pairs), batch_size):
        batch = pairs[start : start + batch_size]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(verify_composition, pair): pair for pair in batch}
            results = []
            for future in as_completed(futures):
                row, receipt = future.result()
                results.append((row_id(row), row, receipt))
        for _, row, receipt in sorted(results):
            if receipt["passed"]:
                row["metadata"]["executable_stage"] = "passed"
                row["metadata"]["verification_receipt_sha256"] = sha256_text(
                    canonical_json(receipt)
                )
                selected_rows.append(row)
                selected_receipts.append(receipt)
            else:
                rejected.append(receipt)
            if len(selected_rows) == EXPECTED_COMPOSED:
                return selected_rows, selected_receipts, rejected
    raise RuntimeError(
        f"only {len(selected_rows)} of {EXPECTED_COMPOSED} compositions passed"
    )


def load_tokenizer() -> Any:
    try:
        from transformers import AutoTokenizer
    except ImportError as exc:
        raise RuntimeError(
            "transformers is required; run with tmp/tokenizer-venv/bin/python"
        ) from exc
    return AutoTokenizer.from_pretrained(
        MODEL_REPOSITORY,
        revision=MODEL_REVISION,
        trust_remote_code=True,
    )


def token_count(tokenizer: Any, row: dict[str, Any]) -> int:
    return len(
        tokenizer.apply_chat_template(
            row["messages"],
            tokenize=True,
            add_generation_prompt=False,
        )
    )


def tokenizer_audit(rows: list[dict[str, Any]], tokenizer: Any) -> dict[str, Any]:
    tasks = []
    for index, row in enumerate(rows):
        tokens = token_count(tokenizer, row)
        tasks.append(
            {
                "ordinal": index + 1,
                "task_id": row_id(row),
                "tokens": tokens,
                "passed": tokens <= SEQUENCE_LENGTH,
            }
        )
    oversize = [row for row in tasks if not row["passed"]]
    if oversize:
        raise RuntimeError(f"{len(oversize)} rows exceed context: {oversize[:5]}")
    values = sorted(row["tokens"] for row in tasks)
    return {
        "rows": len(tasks),
        "passing": len(tasks),
        "minimum": values[0],
        "median": values[len(values) // 2],
        "p90": values[int(0.9 * (len(values) - 1))],
        "maximum": values[-1],
        "sequence_length": SEQUENCE_LENGTH,
        "tokenizer_repository": MODEL_REPOSITORY,
        "tokenizer_revision": MODEL_REVISION,
        "tasks": tasks,
    }


def fixed26_audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    fixed = json.loads(FIXED26.read_text(encoding="utf-8"))
    fixed_ids = {str(row["task_id"]).lower() for row in fixed}
    collisions = [
        row_id(row)
        for row in rows
        if row_id(row).lower() in fixed_ids
        or any(
            component.lower() in fixed_ids
            for component in row.get("metadata", {}).get("component_task_ids", [])
        )
    ]
    if collisions:
        raise RuntimeError(f"fixed-26 task ID collisions: {collisions[:10]}")
    return {
        "passed": True,
        "fixed26_rows": len(fixed),
        "task_id_collisions": collisions,
        "fixed26_manifest_sha256": sha256_path(FIXED26),
        "answers_tests_rubrics_in_training_from_fixed26": False,
        "policy": "fixed-26 remains external evaluation only",
    }


def duplicate_audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    dimensions = {
        "task_ids": [row_id(row) for row in rows],
        "message_pairs": [row_pair_hash(row) for row in rows],
        "prompts": [prompt_hash(row) for row in rows],
        "answers": [answer_hash(row) for row in rows],
    }
    duplicates = {
        name: sorted(value for value, count in Counter(values).items() if count > 1)
        for name, values in dimensions.items()
    }
    if any(duplicates.values()):
        raise RuntimeError(
            "duplicate gate failed: "
            + ", ".join(f"{key}={len(value)}" for key, value in duplicates.items())
        )
    return {
        "passed": True,
        "rows": len(rows),
        "unique_task_ids": len(set(dimensions["task_ids"])),
        "unique_normalized_message_pairs": len(set(dimensions["message_pairs"])),
        "unique_normalized_prompts": len(set(dimensions["prompts"])),
        "unique_normalized_answers": len(set(dimensions["answers"])),
        "duplicate_task_ids": [],
        "duplicate_message_pairs": [],
        "duplicate_prompts": [],
        "duplicate_answers": [],
        "semantic_lineage_note": (
            "Composed rows intentionally reuse independently verified component "
            "skills, but each requires a unique pair of modules and therefore has "
            "a distinct executable repository-edit contract."
        ),
    }


def row_catalog(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    catalog = []
    for ordinal, row in enumerate(rows, 1):
        metadata = row.get("metadata", {})
        catalog.append(
            {
                "ordinal": ordinal,
                "task_id": row_id(row),
                "source_corpus": metadata.get("source_corpus", "sft-v5-inherited"),
                "family": metadata.get("family", "inherited"),
                "category": metadata.get("category", "inherited"),
                "purpose": metadata.get("purpose", "verified-anchor"),
                "synthetic": metadata.get("synthetic"),
                "executable_stage": metadata.get(
                    "executable_stage", "inherited-source-receipt"
                ),
                "disposition": "train",
                "prompt_sha256": sha256_text(row["messages"][0]["content"]),
                "answer_sha256": sha256_text(row["messages"][1]["content"]),
                "row_sha256": sha256_text(canonical_json(row)),
                "component_task_ids": metadata.get("component_task_ids", []),
            }
        )
    return catalog


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=max(1, min(8, os.cpu_count() or 1)))
    args = parser.parse_args()

    ensure_holistic_tests()
    sources = source_hashes()
    full_v5 = read_jsonl(V5_TRAIN)
    retained, retained_report = retained_v5_rows()
    pass1 = pass1_rows(full_v5)
    variants, receipts = candidate_maps()
    unused = unused_passed_rows(full_v5, variants, receipts)
    holistic = holistic_parents()
    candidate = candidate_parents(variants, receipts)
    tokenizer = load_tokenizer()

    composed, composition_receipts, rejected = build_compositions(
        holistic, candidate, args.workers, tokenizer
    )
    rows = retained + pass1 + unused + composed
    if len(rows) != EXPECTED_TOTAL:
        raise RuntimeError(f"expected {EXPECTED_TOTAL} rows, got {len(rows)}")
    for index, row in enumerate(rows):
        validate_row_shape(row, allow_parent_label=index < len(retained))

    duplicates = duplicate_audit(rows)
    contamination = fixed26_audit(rows)
    tokens = tokenizer_audit(rows, tokenizer)
    catalog = row_catalog(rows)

    source_counts = Counter(
        row.get("metadata", {}).get("source_corpus", "sft-v5-inherited")
        for row in rows
    )
    family_counts = Counter(
        row.get("metadata", {}).get("family", "inherited") for row in rows
    )
    component_use = Counter(
        component
        for row in composed
        for component in row["metadata"]["component_task_ids"]
    )
    if max(component_use.values()) > PARENT_USE_CAP:
        raise RuntimeError("composition parent-use cap exceeded")

    train_bytes = jsonl_bytes(rows)
    train_sha256 = sha256_bytes(train_bytes)
    composition = {
        "rows": len(rows),
        "retained_v5_quality_cleared_target_distinct": len(retained),
        "pass1_direct_rows": len(pass1),
        "unused_mutation_adequate_direct_rows": len(unused),
        "cross_family_composed_rows": len(composed),
        "source_counts": dict(sorted(source_counts.items())),
        "family_counts": dict(sorted(family_counts.items())),
        "composition_component_parent_use_maximum": max(component_use.values()),
        "composition_component_unique_parents": len(component_use),
        **retained_report,
    }

    staging = Path(tempfile.mkdtemp(prefix="aider-cpp-sft-v6-2000-", dir=ROOT))
    try:
        (staging / "sft").mkdir(parents=True)
        (staging / "sft/train.jsonl").write_bytes(train_bytes)
        for name, source in SOURCE_INPUTS.items():
            destination = staging / "inputs" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        write_json(staging / "manifests/sources.json", sources)
        write_json(staging / "reports/composition.json", composition)
        write_json(staging / "reports/duplicate_audit.json", duplicates)
        write_json(staging / "reports/contamination_audit.json", contamination)
        write_json(staging / "reports/token_audit.json", tokens)
        write_jsonl(staging / "reports/row_catalog.jsonl", catalog)
        write_jsonl(
            staging / "receipts/composition_verification.jsonl",
            composition_receipts,
        )
        write_jsonl(staging / "rejected/composition_pairs.jsonl", rejected)
        write_jsonl(
            staging / "manifests/selected_train.jsonl",
            [
                {
                    "ordinal": row["ordinal"],
                    "task_id": row["task_id"],
                    "row_sha256": row["row_sha256"],
                    "disposition": "train",
                }
                for row in catalog
            ],
        )
        write_jsonl(staging / "review/queue.jsonl", [])
        write_jsonl(staging / "rejected/rows.jsonl", [])

        manifest = {
            "schema_version": 1,
            "kind": "aider-cpp-sft-v6-2000",
            "version": "sft-v6",
            "decision": "row-level train-ready; model benefit requires held-out evaluation",
            "behavior_contract": {
                "task": "single-turn C++17 repository editing in Aider whole-file format",
                "inputs": "instructions plus editable starter files",
                "output": "complete filename-plus-fenced-block listings only",
                "invariants": [
                    "preserve public APIs, filenames, and const qualifiers",
                    "satisfy every independent module in composed tasks",
                    "exclude fixed-26 answers, tests, rubrics, and grader state",
                    "return no tests, diffs, or explanatory prose",
                ],
                "failure_behavior": (
                    "follow each task's explicit rejection, atomicity, and "
                    "state-preservation contract"
                ),
                "resource_limits": {
                    "sequence_length": SEQUENCE_LENGTH,
                    "language": "C++17",
                },
                "evaluation": "external fixed Aider C++ 26 plus executable row oracles",
                "generalization_target": (
                    "first-pass multi-file C++ edits across distinct APIs, domains, "
                    "boundaries, state transitions, and compositions"
                ),
            },
            "counts": {
                "rows": len(rows),
                "unique_task_ids": duplicates["unique_task_ids"],
                "unique_normalized_message_pairs": duplicates[
                    "unique_normalized_message_pairs"
                ],
                "unique_normalized_prompts": duplicates[
                    "unique_normalized_prompts"
                ],
                "unique_normalized_answers": duplicates[
                    "unique_normalized_answers"
                ],
                "retained_v5": len(retained),
                "new_direct": len(pass1) + len(unused),
                "new_composed": len(composed),
                "review": 0,
                "rejected_selected_rows": 0,
            },
            "gates": {
                "exact_2000_rows": len(rows) == EXPECTED_TOTAL,
                "all_rows_structurally_valid": True,
                "all_rows_within_4096_tokens": tokens["passing"] == len(rows),
                "all_new_direct_rows_executable_verified": True,
                "all_composed_rows_currently_replayed": len(composition_receipts)
                == len(composed),
                "all_composed_component_tests_pass": all(
                    row["passed"] for row in composition_receipts
                ),
                "duplicate_task_ids": False,
                "duplicate_normalized_prompts": False,
                "duplicate_normalized_answers": False,
                "fixed26_contamination": False,
                "unresolved_review_rows": False,
                "composition_parent_use_cap": PARENT_USE_CAP,
            },
            "training": {
                "model": MODEL_REPOSITORY,
                "model_revision": MODEL_REVISION,
                "sequence_length": SEQUENCE_LENGTH,
                "global_batch_size": 20,
                "recommended_epochs": 3,
                "rows_consumed_per_epoch": 2000,
                "steps_per_epoch": 100,
                "total_optimizer_steps": 300,
                "dropped_tail_rows_per_epoch": 0,
            },
            "files": {
                "train": "sft/train.jsonl",
                "rebuild_inputs": "inputs/",
                "sources": "manifests/sources.json",
                "selected_train": "manifests/selected_train.jsonl",
                "composition": "reports/composition.json",
                "duplicate_audit": "reports/duplicate_audit.json",
                "contamination_audit": "reports/contamination_audit.json",
                "token_audit": "reports/token_audit.json",
                "row_catalog": "reports/row_catalog.jsonl",
                "composition_verification": "receipts/composition_verification.jsonl",
                "review_queue": "review/queue.jsonl",
                "rejected_rows": "rejected/rows.jsonl",
            },
            "train_sha256": train_sha256,
            "built_at_utc": datetime.now(timezone.utc).isoformat(),
            "limitations": [
                (
                    "The 949 retained rows preserve their inherited evidence "
                    "boundaries; v6 does not upgrade every legacy row to the newer "
                    "mutation-adequate oracle."
                ),
                (
                    "Composed tasks reuse verified component skills under new paired "
                    "contracts; exact prompt and target duplicates are absent, but "
                    "component lineage is intentionally shared and capped."
                ),
                (
                    "Dataset quality gates do not prove checkpoint improvement. "
                    "Promotion requires a preserved fixed-26 evaluation."
                ),
            ],
        }
        write_json(staging / "manifest.json", manifest)
        (staging / "README.md").write_text(
            f"""# Aider C++ SFT v6 2000

Exact 2,000-row, evaluation-clean C++17 repository-edit corpus.

- 949 quality-cleared, target-distinct rows retained from SFT v5 lineage.
- 70 executable-verified first-pass capability rows.
- 3 previously unused answer-blind, sanitizer, starter-rejection, and
  mutation-adequate rows.
- 978 cross-family composition rows; both independent component test suites
  were replayed for every row.
- 2,000 unique task IDs, normalized prompts, and normalized answers.
- Zero unresolved review rows and zero fixed-26 task-ID overlap.
- Maximum tokenizer length: {tokens['maximum']} / {SEQUENCE_LENGTH}.

The trainer contract is `manifest.json` plus `sft/train.jsonl`.
The exact immutable builder inputs are under `inputs/`. Copy that directory
outside the package before rebuilding, then set `AIDER_SFT_V6_INPUT_ROOT` to
the copy.
Model-level improvement is not claimed until a checkpoint is trained and
evaluated on the external fixed 26.
""",
            encoding="utf-8",
        )
        checksums = []
        for path in sorted(staging.rglob("*")):
            if path.is_file():
                checksums.append(
                    f"{sha256_path(path)}  {path.relative_to(staging)}"
                )
        (staging / "SHA256SUMS").write_text(
            "\n".join(checksums) + "\n", encoding="utf-8"
        )
        if PACKAGE.exists():
            shutil.rmtree(PACKAGE)
        staging.rename(PACKAGE)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    print(
        json.dumps(
            {
                "status": "passed",
                "package": str(PACKAGE),
                "rows": len(rows),
                "train_sha256": train_sha256,
                "token_maximum": tokens["maximum"],
                "composed_rows": len(composed),
                "composition_rejections": len(rejected),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
