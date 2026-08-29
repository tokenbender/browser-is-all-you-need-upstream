"""Shared helpers for the generalized C++ verifier pack wrappers.

Each wrapper in this directory is a thin adapter between the direct runner's
four-argument contract (``--candidate-dir``, ``--manifest``,
``--expected-manifest-sha256``, ``--output-dir``) and one verifier engine in
the sibling ``generalized_verifier_docs`` directory.  This module centralizes
the parts every wrapper needs:

  * manifest authentication (sha256 re-check against the out-of-band digest),
  * the candidate-source digest (same name/content framing the runner uses,
    so the before/after hashes in the receipt authenticate against it),
  * engine location and subprocess invocation,
  * emission of the schema-version-2 ``verification_receipt.json`` with all
    binding fields the runner validates.

stdlib only.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

SCHEMA_VERSION = 2
EXIT_CODE = {"pass": 0, "fail": 1, "invalid": 2}
KERNEL_VALUE = {"pass": 1, "fail": -1, "invalid": None}
ENGINES_DIR_NAME = "generalized_verifier_docs"
ENGINE_DIR_ENV = "GENERALIZED_VERIFIER_ENGINE_DIR"
ENGINE_TIMEOUT_SECONDS = 600
FACT_TEXT_LIMIT = 4096

# Compiler invocation used for the standalone stage-1 translation-unit
# compile (wrapper 06).  Kept identical to the build engine's stage 1.
STAGE1_CXX = os.environ.get("CXX", "g++")
STAGE1_CXXFLAGS = [
    "-std=c++17", "-Wall", "-Wextra", "-Wpedantic", "-Werror",
    "-DEXERCISM_RUN_ALL_TESTS",
]

HEADER_SUFFIXES = (".h", ".hpp", ".hh", ".hxx")
SOURCE_SUFFIXES = (".cpp", ".cc", ".cxx")


class ManifestError(ValueError):
    """The manifest could not be authenticated or parsed."""


class InvalidInput(ValueError):
    """A required verifier input is absent or unusable; verdict is invalid."""


def sha256_path(path):
    value = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def candidate_source_sha256(candidate_dir, candidate_files):
    """Digest the manifest-declared candidate files.

    The framing (sorted relative path, NUL, content, NUL) matches the
    runner's own candidate digest so receipts authenticate byte-for-byte
    against the value the runner computes.
    """
    value = hashlib.sha256()
    for relative in sorted(candidate_files):
        path = os.path.join(candidate_dir, *relative.split("/"))
        if not os.path.isfile(path):
            raise InvalidInput(f"candidate file is unavailable: {relative}")
        value.update(relative.encode("utf-8"))
        value.update(b"\0")
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                value.update(chunk)
        value.update(b"\0")
    return value.hexdigest()


def parse_runner_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Verifier wrapper for the direct runner contract.")
    parser.add_argument("--candidate-dir", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args(argv)


def load_manifest(args):
    """Authenticate and parse the manifest.  Raises ManifestError."""
    try:
        observed = sha256_path(args.manifest)
    except OSError as exc:
        raise ManifestError(f"manifest is unreadable: {exc}") from exc
    if observed != args.expected_manifest_sha256:
        raise ManifestError(
            "manifest digest mismatch: "
            f"expected {args.expected_manifest_sha256}, observed {observed}")
    try:
        with open(args.manifest, encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestError(f"manifest is not valid JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ManifestError("manifest root must be an object")
    if not isinstance(manifest.get("task_id"), str):
        raise ManifestError("manifest task_id is missing or not a string")
    files = manifest.get("candidate_files")
    if not isinstance(files, list) or not files or not all(
            isinstance(item, str) for item in files):
        raise ManifestError("manifest candidate_files must be a "
                            "non-empty list of relative paths")
    return manifest, observed


def find_engine(engine_filename):
    """Locate an engine script in the sibling engines directory.

    The engines directory is found by walking upward from this file, so the
    pack works both in the repository layout and inside an assembled reward
    root.  ``GENERALIZED_VERIFIER_ENGINE_DIR`` overrides the search.
    """
    override = os.environ.get(ENGINE_DIR_ENV)
    candidates = [override] if override else []
    cursor = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        candidates.append(os.path.join(cursor, ENGINES_DIR_NAME))
        parent = os.path.dirname(cursor)
        if parent == cursor:
            break
        cursor = parent
    for directory in candidates:
        if not directory:
            continue
        path = os.path.join(directory, engine_filename)
        if os.path.isfile(path):
            return path
    raise InvalidInput(
        f"verifier engine {engine_filename} not found; set {ENGINE_DIR_ENV}")


def run_engine(engine_path, extra_args, timeout=ENGINE_TIMEOUT_SECONDS):
    """Run one engine via ``[sys.executable, engine, *extra_args]``."""
    command = [sys.executable, engine_path, *extra_args]
    started = time.monotonic()
    try:
        proc = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InvalidInput(f"engine could not be executed: {exc}") from exc
    return {
        "command": [os.path.basename(command[1]), *extra_args],
        "return_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "duration_seconds": round(time.monotonic() - started, 6),
    }


def parse_engine_json(engine_result, label):
    """Parse an engine's ``--json`` stdout; exit code 2 means invalid."""
    if engine_result["return_code"] == 2:
        raise InvalidInput(
            f"{label} reported a usage/IO error: "
            f"{tail(engine_result['stderr'], 400)}")
    try:
        return json.loads(engine_result["stdout"])
    except json.JSONDecodeError as exc:
        raise InvalidInput(
            f"{label} did not emit a JSON report: {exc}") from exc


def tail(text, limit=FACT_TEXT_LIMIT):
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated, {len(text)} chars total]"


def kernel(kernel_id, status, summary, facts=None, command=None,
           duration_seconds=None):
    return {
        "kernel_id": kernel_id,
        "kernel": KERNEL_VALUE[status],
        "status": status,
        "summary": summary,
        "facts": facts or {},
        "command": command,
        "duration_seconds": duration_seconds,
        "stdout_log": None,
        "stderr_log": None,
    }


def fixture_dir(manifest):
    value = manifest.get("fixture_dir")
    if not isinstance(value, str) or not value:
        raise InvalidInput(
            "manifest fixture_dir is required for this verifier (a task "
            "fixture directory with <stem>_test.cpp, test/ harness and "
            ".meta/example.* reference files)")
    if not os.path.isdir(value):
        raise InvalidInput(f"fixture_dir is not a directory: {value}")
    return value


def fixture_test_file(fixture):
    tests = sorted(glob.glob(os.path.join(fixture, "*_test.cpp")))
    if len(tests) != 1:
        raise InvalidInput(
            f"expected exactly one *_test.cpp in fixture_dir, "
            f"found {len(tests)}")
    stem = os.path.basename(tests[0])[:-len("_test.cpp")]
    return tests[0], stem


def split_candidate_files(manifest):
    """Split manifest candidate_files into (header, sources) by suffix."""
    headers, sources, other = [], [], []
    for relative in manifest["candidate_files"]:
        base = os.path.basename(relative)
        if base.endswith(HEADER_SUFFIXES):
            headers.append(relative)
        elif base.endswith(SOURCE_SUFFIXES):
            sources.append(relative)
        else:
            other.append(relative)
    if other:
        raise InvalidInput(
            "candidate_files contains entries that are neither headers nor "
            f"C++ sources: {', '.join(other)}")
    if len(headers) != 1:
        raise InvalidInput(
            f"expected exactly one candidate header, found {len(headers)}")
    return headers[0], sources


def candidate_path(candidate_dir, relative):
    path = os.path.join(candidate_dir, *relative.split("/"))
    if not os.path.isfile(path):
        raise InvalidInput(f"candidate file is unavailable: {relative}")
    return path


def find_response(manifest):
    """Return (path, cleanup) for the raw model response, or raise.

    Resolution order: the last trajectory turn carrying ``response_file`` or
    ``response_text``, then the same fields at manifest top level.
    ``response_text`` is materialized to a temp file for the engines.
    """
    turns = []
    trajectory = manifest.get("trajectory")
    if isinstance(trajectory, dict) and isinstance(
            trajectory.get("turns"), list):
        turns = list(trajectory["turns"])
    sources = [t for t in reversed(turns) if isinstance(t, dict)]
    sources.append(manifest)
    for source in sources:
        path = source.get("response_file")
        if isinstance(path, str) and path:
            if not os.path.isfile(path):
                raise InvalidInput(
                    f"response_file is not a readable file: {path}")
            return path, None
        text = source.get("response_text")
        if isinstance(text, str) and text:
            handle = tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", suffix=".response.txt", delete=False)
            with handle:
                handle.write(text)
            return handle.name, handle.name
    raise InvalidInput(
        "manifest carries no model response: no trajectory turn and no "
        "top-level field provides response_file or response_text")


def _binding_fields(wrapper_path, manifest_sha256):
    pack_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    common_path = os.path.abspath(__file__)
    schema_path = os.path.join(
        pack_dir, "global_verifier_manifest.schema.json")
    wrapper_sha256 = sha256_path(wrapper_path)
    return {
        "verifier_source_sha256": wrapper_sha256,
        "verifier_wrapper_sha256": wrapper_sha256,
        "verifier_common_sha256": sha256_path(common_path),
        "manifest_schema_sha256": sha256_path(schema_path),
        "manifest_sha256": manifest_sha256,
    }


def _assemble(wrapper_path, policy_id, manifest, manifest_sha256,
              candidate_before, candidate_after, kernels, status, reason,
              extra_fields=None):
    numeric = [item for item in kernels if item["kernel"] in (-1, 1)]
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "task_id": manifest.get("task_id") if isinstance(manifest, dict)
        else None,
        "policy_id": policy_id,
        "status": status,
        "kernel_results": kernels,
        "kernel_sum": (
            None if status == "invalid"
            else sum(int(item["kernel"]) for item in numeric)),
        "maximum_kernel_sum": len(numeric),
        **_binding_fields(wrapper_path, manifest_sha256),
        "candidate_source_sha256": candidate_before,
        "candidate_source_sha256_before": candidate_before,
        "candidate_source_sha256_after": candidate_after,
        "candidate_source_unchanged": (
            candidate_before is not None
            and candidate_before == candidate_after),
        "excluded_conditions": [],
        "reason": reason,
    }
    if extra_fields:
        receipt.update(extra_fields)
    return receipt


def write_receipt(output_dir, receipt):
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "verification_receipt.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(receipt, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return path


def finish_invalid(wrapper_path, args, policy_id, manifest, manifest_sha256,
                   candidate_before, reason, facts=None):
    """Write an invalid receipt (no numeric kernel sum) and return 2."""
    kernels = [kernel(f"{policy_id}-1", "invalid", reason, facts=facts)]
    receipt = _assemble(
        wrapper_path, policy_id, manifest or {}, manifest_sha256 or "",
        candidate_before, candidate_before, kernels, "invalid", reason)
    write_receipt(args.output_dir, receipt)
    print(f"INVALID: {reason}", file=sys.stderr)
    return EXIT_CODE["invalid"]


def finish(wrapper_path, args, policy_id, manifest, manifest_sha256,
           candidate_before, kernels, status, reason, extra_fields=None):
    """Re-hash the candidate, write the receipt, return the exit code."""
    try:
        candidate_after = candidate_source_sha256(
            args.candidate_dir, manifest["candidate_files"])
    except InvalidInput as exc:
        return finish_invalid(
            wrapper_path, args, policy_id, manifest, manifest_sha256,
            candidate_before,
            f"candidate source cannot be authenticated after verification: "
            f"{exc}")
    if candidate_after != candidate_before:
        return finish_invalid(
            wrapper_path, args, policy_id, manifest, manifest_sha256,
            candidate_before,
            "candidate source changed during verification")
    receipt = _assemble(
        wrapper_path, policy_id, manifest, manifest_sha256,
        candidate_before, candidate_after, kernels, status, reason,
        extra_fields)
    write_receipt(args.output_dir, receipt)
    print(f"{status.upper()}: {reason}", file=sys.stderr)
    return EXIT_CODE[status]
