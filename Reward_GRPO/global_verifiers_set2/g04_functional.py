"""G04: compare candidate-probe observations against an isolated trusted oracle."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from receipt import PolicyReceipt, policy
from sandbox import CommandResult, Limits, result_facts

Execute = Callable[[list[str], Path, Limits, dict[str, str] | None], CommandResult]


def _strings(value: Any) -> list[str] | None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    return list(value)


def _materialize_probe_sources(
    workspace: Path, names: list[str], encoding: str,
) -> tuple[list[str], list[dict[str, str]], str | None]:
    if encoding not in {"plain", "gzip"}:
        return [], [], "PROBE_SOURCE_ENCODING_UNSUPPORTED"
    target = workspace / ".gv2" / "probe_sources"
    target.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    facts: list[dict[str, str]] = []
    for index, name in enumerate(names):
        source = workspace / name
        try:
            payload = source.read_bytes()
            decoded = gzip.decompress(payload) if encoding == "gzip" else payload
            decoded.decode("utf-8")
        except (OSError, EOFError, UnicodeDecodeError, gzip.BadGzipFile):
            return [], facts, "PROBE_SOURCE_DECODE_FAILED"
        if len(decoded) > 4_000_000:
            return [], facts, "PROBE_SOURCE_TOO_LARGE"
        destination = target / f"source_{index}.cpp"
        destination.write_bytes(decoded)
        paths.append(destination.relative_to(workspace).as_posix())
        facts.append({
            "asset": name,
            "asset_sha256": hashlib.sha256(payload).hexdigest(),
            "source_sha256": hashlib.sha256(decoded).hexdigest(),
        })
    return paths, facts, None


def _load_oracle_cases(
    trusted_assets: Path, manifest: dict[str, Any], asset: str,
    encoding: str, expected_total: int,
) -> tuple[list[dict[str, str]], dict[str, Any], str | None]:
    if encoding != "gzip":
        return [], {}, "EXTERNAL_ORACLE_ENCODING_UNSUPPORTED"
    source = trusted_assets / asset
    try:
        payload = source.read_bytes()
        decoded = gzip.decompress(payload)
        document = json.loads(decoded)
    except (OSError, EOFError, UnicodeDecodeError, gzip.BadGzipFile, json.JSONDecodeError):
        return [], {}, "EXTERNAL_ORACLE_DECODE_FAILED"
    facts: dict[str, Any] = {
        "asset": asset,
        "asset_sha256": hashlib.sha256(payload).hexdigest(),
        "oracle_sha256": hashlib.sha256(decoded).hexdigest(),
    }
    protected_digest = manifest.get("protected_files", {}).get(asset)
    if protected_digest != facts["asset_sha256"]:
        return [], facts, "EXTERNAL_ORACLE_DIGEST_MISMATCH"
    values = document.get("cases") if isinstance(document, dict) else None
    if (
        not isinstance(document, dict) or document.get("schema_version") != 1
        or not isinstance(values, list) or len(values) != expected_total
    ):
        return [], facts, "EXTERNAL_ORACLE_SCHEMA_INVALID"
    cases: list[dict[str, str]] = []
    identifiers: set[str] = set()
    aggregate_request_bytes = 0
    for value in values:
        if not isinstance(value, dict):
            return [], facts, "EXTERNAL_ORACLE_SCHEMA_INVALID"
        identifier = value.get("id")
        request = value.get("request")
        expected = value.get("expected")
        if (
            not isinstance(identifier, str) or not identifier or identifier in identifiers
            or not isinstance(request, str) or not request or "\0" in request
            or not isinstance(expected, str) or "\0" in expected
            or "\n" in expected or "\r" in expected
            or len(request.encode()) > 16_384 or len(expected.encode()) > 16_384
        ):
            return [], facts, "EXTERNAL_ORACLE_SCHEMA_INVALID"
        aggregate_request_bytes += len(request.encode()) + 1
        if aggregate_request_bytes > 128 * 1024:
            return [], facts, "EXTERNAL_ORACLE_REQUEST_BUDGET_EXCEEDED"
        identifiers.add(identifier)
        cases.append({"id": identifier, "request": request, "expected": expected})
    facts["case_count"] = len(cases)
    facts["request_count"] = len(cases)
    facts["aggregate_request_bytes"] = aggregate_request_bytes
    facts["case_ids"] = [case["id"] for case in cases]
    return cases, facts, None


def verify(
    workspace: Path, manifest: dict[str, Any], objects: list[str], execute: Execute,
    limits: Limits, *, trusted_assets: Path | None = None,
) -> PolicyReceipt:
    functional = manifest.get("functional", {})
    build = manifest.get("build", {})
    if functional.get("mode") != "external_oracle_v1":
        return policy("G04", "INVALID", "FUNCTIONAL_MODE_MISSING_OR_UNSUPPORTED")
    if trusted_assets is None:
        return policy("G04", "INVALID", "TRUSTED_ASSET_ROOT_REQUIRED")
    try:
        candidate_root = workspace.resolve(strict=True)
        trusted_root = trusted_assets.resolve(strict=True)
    except OSError:
        return policy("G04", "INVALID", "TRUSTED_ASSET_ROOT_REQUIRED")
    if (
        candidate_root == trusted_root
        or trusted_root.is_relative_to(candidate_root)
        or candidate_root.is_relative_to(trusted_root)
    ):
        return policy("G04", "INVALID", "TRUSTED_ASSET_ISOLATION_REQUIRED")

    bridge_sources = _strings(functional.get("bridge_sources"))
    bridge_encoding = functional.get("bridge_source_encoding", "plain")
    includes = _strings(functional.get("include_dirs", build.get("include_dirs", ["."])))
    defines = _strings(functional.get("defines", []))
    build_flags = _strings(build.get("flags", []))
    bridge_flags = _strings(functional.get("bridge_compile_flags", []))
    libraries = _strings(functional.get("libraries", build.get("libraries", [])))
    link_args = _strings(functional.get("link_args", build.get("link_args", [])))
    runtime_assets = _strings(functional.get("runtime_assets", []))
    env_value = functional.get("env", {})
    oracle_asset = functional.get("oracle_cases")
    oracle_encoding = functional.get("oracle_cases_encoding")
    expected_total = functional.get("expected_total")
    if (
        not bridge_sources or any(value is None for value in (
            includes, defines, build_flags, bridge_flags, libraries, link_args, runtime_assets,
        ))
        or bridge_encoding not in {"plain", "gzip"}
        or not isinstance(oracle_asset, str) or not oracle_asset
        or not isinstance(oracle_encoding, str)
        or not isinstance(expected_total, int) or not (1 <= expected_total <= 4096)
        or runtime_assets
        or not isinstance(env_value, dict)
        or not all(isinstance(key, str) and isinstance(value, str) for key, value in env_value.items())
        or oracle_asset not in manifest.get("protected_files", {})
    ):
        return policy("G04", "INVALID", "EXTERNAL_ORACLE_CONTRACT_INCOMPLETE")
    oracle_path = trusted_root / oracle_asset
    if not oracle_path.is_file() or oracle_path.is_symlink():
        return policy("G04", "INVALID", "EXTERNAL_ORACLE_CONTRACT_INCOMPLETE")

    probe_sources, source_facts, source_error = _materialize_probe_sources(
        workspace, bridge_sources, str(bridge_encoding),
    )
    if source_error:
        return policy("G04", "INVALID", source_error, bridge_sources=source_facts)
    compiler = str(build.get("compiler", "g++"))
    standard = str(build.get("standard", "c++17"))
    probe_binary = ".gv2/candidate_probe"
    compile_command = [
        compiler, f"-std={standard}", *build_flags, *bridge_flags,
        *(f"-I{value}" for value in includes), *(f"-D{value}" for value in defines),
        *probe_sources, *objects, *(f"-l{value}" for value in libraries),
        *link_args, "-o", probe_binary,
    ]
    compiled = execute(compile_command, workspace, limits, None)
    if compiled.launch_error or compiled.timed_out:
        return policy(
            "G04", "INVALID", "PROBE_BUILD_INFRASTRUCTURE_FAILURE",
            probe_compile=result_facts(compiled), bridge_sources=source_facts,
        )
    if compiled.returncode != 0:
        return policy(
            "G04", "FAIL", "PROBE_LINK_FAIL", probe_compile=result_facts(compiled),
            bridge_sources=source_facts,
        )

    # Expected values enter memory only after the candidate-linked probe is frozen.
    # They are never copied into candidate workspace/runtime or passed through argv/env.
    cases, oracle_facts, oracle_error = _load_oracle_cases(
        trusted_root, manifest, oracle_asset, oracle_encoding, expected_total,
    )
    if oracle_error:
        return policy("G04", "INVALID", oracle_error, oracle=oracle_facts)

    runtime = workspace / ".gv2" / "external_runtime"
    runtime.mkdir(exist_ok=False)
    probe_runtime = runtime / "candidate_probe"
    probe_runtime.write_bytes((workspace / probe_binary).read_bytes())
    probe_runtime.chmod(0o500)
    command = ["./candidate_probe", *(case["request"] for case in cases)]
    executed = execute(command, runtime, limits, dict(env_value))
    run_facts = result_facts(executed)
    if executed.launch_error:
        return policy("G04", "INVALID", "PROBE_RUNTIME_UNAVAILABLE", run=run_facts)
    if executed.timed_out:
        return policy("G04", "FAIL", "CANDIDATE_RUNTIME_TIMEOUT", run=run_facts)
    if executed.stdout_truncated or executed.stderr_truncated:
        return policy("G04", "FAIL", "TEST_OUTPUT_LIMIT_EXCEEDED", run=run_facts)

    observed = executed.stdout.splitlines()
    expected = [f"{index}\t{case['expected']}" for index, case in enumerate(cases)]
    per_case = [
        {
            "id": case["id"],
            "passed": index < len(observed) and observed[index] == expected[index],
            "observed_sha256": hashlib.sha256(
                (observed[index] if index < len(observed) else "").encode()
            ).hexdigest(),
            "expected_sha256": hashlib.sha256(expected[index].encode()).hexdigest(),
        }
        for index, case in enumerate(cases)
    ]
    passed = sum(bool(item["passed"]) for item in per_case)
    cardinality_ok = len(observed) == expected_total
    status = "PASS" if (
        executed.returncode == 0 and cardinality_ok and passed == expected_total
    ) else "FAIL"
    scored_passes = passed
    if status == "FAIL" and scored_passes == expected_total:
        # A protocol/cardinality/process failure must never project the same reward
        # as a terminal PASS, even when every indexed observation before it matched.
        scored_passes = expected_total - 1
    semantic_score = scored_passes / expected_total
    return policy(
        "G04", status, "FUNCTIONAL_PASS" if status == "PASS" else "SEMANTIC_FAIL",
        tests_passed=passed, tests_total=expected_total, score=semantic_score,
        output_cardinality_ok=cardinality_ok, observed_line_count=len(observed),
        per_case=per_case, authoritative=True,
        trust_boundary="python-compares-raw-observations-v1",
        trusted_assets_isolated=True, oracle=oracle_facts,
        bridge_sources=source_facts, probe_compile=result_facts(compiled), run=run_facts,
    )
