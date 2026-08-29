"""Portable orchestrator for the manifest-driven Global Verifiers Set 2."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path, PurePath
from tempfile import TemporaryDirectory
from typing import Any

import candidate_reconstruction
import g01_integrity
import g02_build
import g03_api_link
import g04_functional
import g05_safety
import g07_portability
import g09_invalid_attribution
from receipt import PolicyReceipt, VerificationReceipt, policy
from sandbox import Limits, result_facts, run_docker, run_host

MANDATORY = ("G01", "G02", "G03", "G04")
OPTIONAL = ("G05", "G07")
REPORTING = ("G09",)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty relative path")
    path = PurePath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{field} is unsafe")
    return value


def load_bundle(bundle: Path) -> tuple[dict[str, Any], str]:
    manifest_path = bundle / "manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ValueError("task bundle lacks a regular manifest.json")
    manifest = json.loads(manifest_path.read_text())
    if (
        manifest.get("schema_version") != 2
        or not isinstance(manifest.get("task_id"), str)
        or not manifest["task_id"]
        or not isinstance(manifest.get("contract_version"), str)
        or not manifest["contract_version"]
    ):
        raise ValueError("unsupported task-bundle manifest")
    editable = manifest.get("editable_files")
    protected = manifest.get("protected_files")
    if not isinstance(editable, list) or not editable or not isinstance(protected, dict):
        raise ValueError("manifest lacks editable/protected file contracts")
    for index, name in enumerate(editable):
        _relative(name, f"editable_files[{index}]")
    if len(set(editable)) != len(editable):
        raise ValueError("editable-file contract contains duplicates")
    for name, digest in protected.items():
        _relative(name, "protected_files")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError("protected digest is malformed")
    if set(editable) & set(protected):
        raise ValueError("editable and protected paths overlap")
    contract = manifest.get("api", {}).get("contract")
    for required in ("instructions.md", contract):
        if not isinstance(required, str):
            raise ValueError("task bundle lacks an API contract")
        _relative(required, "required asset")
        path = bundle / required
        if not path.is_file() or path.is_symlink() or required not in protected:
            raise ValueError(f"task bundle lacks protected {required}")
    starter = bundle / "starter"
    if not starter.is_dir() or starter.is_symlink():
        raise ValueError("task bundle lacks a regular starter tree")
    for name in editable:
        path = starter / name
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"starter lacks editable file {name}")
    preflight = manifest.get("preflight_commands", [])
    if not isinstance(preflight, list) or any(
        not isinstance(command, list)
        or not command
        or not all(isinstance(argument, str) and argument for argument in command)
        for command in preflight
    ):
        raise ValueError("preflight commands must be non-empty argument arrays")

    build = manifest.get("build", {})
    sources = build.get("sources", [])
    if not isinstance(sources, list) or not sources:
        raise ValueError("build.sources must be a non-empty list")
    for source in sources:
        _relative(source, "build.sources")
        if source not in editable and source not in protected:
            raise ValueError(f"build source is neither editable nor protected: {source}")
    public_assets = build.get("public_assets", [])
    if not isinstance(public_assets, list):
        raise ValueError("build.public_assets must be a list")
    for asset in public_assets:
        _relative(asset, "build.public_assets")
        if asset not in protected:
            raise ValueError(f"public build asset must be protected: {asset}")

    caller = manifest.get("api", {}).get("caller")
    if not isinstance(caller, str) or caller not in protected:
        raise ValueError("API caller must be a protected asset")
    functional = manifest.get("functional", {})
    if functional.get("mode") != "external_oracle_v1":
        raise ValueError("functional.mode must be authoritative external_oracle_v1")
    bridge_sources = functional.get("bridge_sources")
    if not isinstance(bridge_sources, list) or not bridge_sources:
        raise ValueError("functional.bridge_sources must be a non-empty list")
    for source in bridge_sources:
        _relative(source, "functional.bridge_sources")
        if source not in protected:
            raise ValueError(f"functional bridge source must be protected: {source}")
    if functional.get("bridge_source_encoding", "plain") not in {"plain", "gzip"}:
        raise ValueError("functional.bridge_source_encoding is unsupported")
    oracle_cases = functional.get("oracle_cases")
    _relative(oracle_cases, "functional.oracle_cases")
    if oracle_cases not in protected:
        raise ValueError("functional oracle cases must be protected")
    if functional.get("oracle_cases_encoding") != "gzip":
        raise ValueError("functional oracle cases must use gzip encoding")
    test_sources = functional.get("test_sources")
    if test_sources is None and isinstance(functional.get("test_source"), str):
        test_sources = [functional["test_source"]]
    if not isinstance(test_sources, list) or not test_sources:
        raise ValueError("functional tests must be a non-empty source list")
    for source in test_sources:
        _relative(source, "functional.test_sources")
        if source not in protected:
            raise ValueError(f"functional test source must be protected: {source}")
    if test_sources != [oracle_cases]:
        raise ValueError("functional.test_sources must contain only oracle_cases")
    runtime_assets = functional.get("runtime_assets", [])
    if not isinstance(runtime_assets, list):
        raise ValueError("functional.runtime_assets must be a list")
    for asset in runtime_assets:
        _relative(asset, "functional.runtime_assets")
        if asset not in protected:
            raise ValueError(f"functional runtime asset must be protected: {asset}")
    early_protected = (set(sources) | set(public_assets)) & set(protected)
    hidden_functional = set(test_sources) | set(runtime_assets) | {oracle_cases}
    overlap = sorted(early_protected & hidden_functional)
    if overlap:
        raise ValueError(f"hidden functional assets exposed during candidate build: {overlap}")
    expected_total = functional.get("expected_total")
    if not isinstance(expected_total, int) or not (1 <= expected_total <= 4096):
        raise ValueError("functional expected_total must be a positive integer")
    return manifest, sha256(manifest_path)


def _not_run(identifier: str, prerequisite: str) -> PolicyReceipt:
    return policy(identifier, "NOT_RUN", "PREREQUISITE_FAILED", prerequisite=prerequisite)


def run(args: argparse.Namespace) -> VerificationReceipt:
    bundle = args.bundle.resolve(strict=True)
    manifest, manifest_sha = load_bundle(bundle)
    limits_data = manifest.get("limits", {})
    limits = Limits(timeout_s=int(limits_data.get("timeout_s", 120)),
                    memory_mb=int(limits_data.get("memory_mb", 2048)),
                    pids=int(limits_data.get("pids", 128)),
                    cpus=float(limits_data.get("cpus", 2.0)),
                    output_bytes=int(limits_data.get("output_bytes", 1_000_000)))
    if args.executor == "docker":
        image = str(manifest.get("runtime", {}).get("image", ""))
        if not re.fullmatch(
            r"(?:[^\s@]+@)?sha256:[0-9a-f]{64}", image
        ):
            raise ValueError("Docker execution requires a digest-pinned image")
    with TemporaryDirectory(prefix="global-verifiers-set2-") as temporary:
        workspace = Path(temporary) / "bundle"
        shutil.copytree(bundle, workspace)
        candidate_input = args.candidate.resolve(strict=True) if args.candidate else None
        reconstruction = candidate_reconstruction.reconstruct(
            workspace / "starter", Path(temporary) / "candidate", manifest["editable_files"],
            response=args.response, supplied_dir=candidate_input, finish_reason=args.finish_reason)
        (reconstruction.root / ".gv2").mkdir()
        original_candidate_sha = reconstruction.candidate_sha256

        staged_assets: set[str] = set()

        def stage_assets(names: set[str]) -> None:
            """Expose only authenticated assets needed by the next trusted phase."""

            for name in sorted(names):
                source = workspace / name
                target_path = reconstruction.root / name
                if target_path.exists():
                    continue
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target_path)
                staged_assets.add(name)

        protected_names = set(manifest["protected_files"])
        build_names = set(manifest.get("build", {}).get("sources", []))
        public_build_names = set(manifest.get("build", {}).get("public_assets", []))
        api_names = {
            str(manifest.get("api", {}).get("contract", "")),
            str(manifest.get("api", {}).get("caller", "")),
        } - {""}
        functional_bridge_names = set(
            manifest.get("functional", {}).get("bridge_sources", [])
        )
        # G02 receives authenticated build sources plus explicitly declared public assets.
        # API contract/caller assets not declared public are delayed until G03;
        # functional tests and runtime assets remain hidden until preprocessing freezes.
        stage_assets((build_names | public_build_names) & protected_names)

        def post_execution_integrity(stage: str) -> PolicyReceipt | None:
            fixed = g01_integrity.verify(workspace, manifest)
            if fixed.status != "PASS":
                return policy("INTEGRITY", "FAIL", "PROTECTED_ASSET_MUTATED_DURING_VERIFICATION",
                              stage=stage, underlying=fixed.reason, facts=fixed.facts)
            for name in sorted(staged_assets):
                staged = reconstruction.root / name
                expected = manifest["protected_files"][name]
                if not staged.is_file() or staged.is_symlink() or sha256(staged) != expected:
                    return policy(
                        "INTEGRITY", "FAIL", "STAGED_PROTECTED_ASSET_MUTATED",
                        stage=stage, path=name, expected_sha256=expected,
                    )
            actual_candidate_sha = candidate_reconstruction.tree_sha256(
                reconstruction.root, manifest["editable_files"]
            )
            if actual_candidate_sha != original_candidate_sha:
                return policy("INTEGRITY", "FAIL", "CANDIDATE_MUTATED_DURING_VERIFICATION",
                              stage=stage, expected_sha256=original_candidate_sha,
                              actual_sha256=actual_candidate_sha)
            return None

        if args.executor == "docker":
            image = str(manifest.get("runtime", {}).get("image", ""))
            def execute(command, cwd, command_limits, env):
                root_execution = cwd.resolve() == reconstruction.root.resolve()
                candidates = (list(manifest["protected_files"])
                              if root_execution
                              else list(manifest.get("functional", {}).get("runtime_assets", [])))
                read_only = [name for name in candidates if (cwd / name).exists()]
                return run_docker(
                    command, cwd, image, command_limits, env=env,
                    read_only_paths=read_only,
                )
        else:
            execute = run_host

        receipts: list[PolicyReceipt] = []
        # Fixed data is authenticated in its isolated bundle copy; reconstruction
        # independently enforced the editable-file boundary.
        g01 = g01_integrity.verify(workspace, manifest)
        receipts.append(g01)
        objects: list[str] = []
        api_binary: str | None = None
        if g01.status == "PASS":
            preflight_results = []
            preflight_failed = False
            with TemporaryDirectory(prefix="gv2-preflight-") as preflight_temporary:
                preflight_root = Path(preflight_temporary)
                for command in manifest.get("preflight_commands", []):
                    result = execute(command, preflight_root, limits, None)
                    preflight_results.append(result_facts(result))
                    if result.launch_error or result.timed_out or result.returncode != 0:
                        receipts.append(policy(
                            "PREFLIGHT", "INVALID", "DEPENDENCY_PREFLIGHT_FAILED",
                            commands=preflight_results,
                        ))
                        receipts.extend([
                            _not_run(name, "PREFLIGHT") for name in MANDATORY[1:]
                        ])
                        preflight_failed = True
                        break
            if not preflight_failed:
                receipts.append(policy("PREFLIGHT", "PASS", "DEPENDENCIES_AVAILABLE",
                                       commands=preflight_results))
                g02, objects = g02_build.verify(reconstruction.root,
                                                reconstruction.root / ".gv2/objects",
                                                manifest, execute, limits)
                receipts.append(g02)
                if g02.status == "PASS":
                    # Candidate object compilation is over, but G03 still parses the
                    # candidate header. Expose only the public contract/caller here;
                    # hidden functional assets remain unavailable to preprocessing.
                    stage_assets(api_names & protected_names)
                    g03, api_binary = g03_api_link.verify(reconstruction.root, manifest,
                                                          objects, execute, limits)
                    receipts.append(g03)
                    if g03.status == "PASS":
                        # Candidate compilation and AST parsing are frozen. Expose only
                        # the candidate-facing probe; semantic oracle cases stay in the
                        # isolated authenticated bundle and never enter candidate cwd.
                        stage_assets(functional_bridge_names & protected_names)
                        g04 = g04_functional.verify(
                            reconstruction.root, manifest, objects, execute, limits,
                            trusted_assets=workspace,
                        )
                        receipts.append(g04)
                        integrity = post_execution_integrity("G04")
                        if integrity is not None:
                            receipts.append(integrity)
                    else:
                        receipts.append(_not_run("G04", "G03"))
                else:
                    receipts.extend([_not_run("G03", "G02"), _not_run("G04", "G02")])
        else:
            receipts.extend([_not_run(name, "G01") for name in ("G02", "G03", "G04")])

        mandatory = {item.policy: item for item in receipts}
        mandatory_pass = all(mandatory.get(name) and mandatory[name].status == "PASS" for name in MANDATORY)
        if args.full and mandatory_pass:
            receipts.append(g05_safety.verify(
                reconstruction.root, manifest, execute, limits,
                trusted_assets=workspace,
            ))
            receipts.append(g07_portability.verify(
                reconstruction.root, manifest, execute, limits,
                trusted_assets=workspace,
            ))
        elif args.full:
            receipts.extend([_not_run(name, "G04") for name in OPTIONAL])

        statuses = [item.status for item in receipts
                    if item.policy in MANDATORY or item.policy in {"PREFLIGHT", "INTEGRITY"}]
        status = ("INVALID" if "INVALID" in statuses else "FAIL" if "FAIL" in statuses
                  else "PASS" if mandatory_pass else "FAIL")
        receipts.append(g09_invalid_attribution.verify(receipts))
        final = VerificationReceipt(2, manifest["task_id"], manifest_sha,
                                    reconstruction.candidate_sha256, status, receipts,
                                    reconstruction.returned_files, reconstruction.inherited_files,
                                    reconstruction.format_valid)
        args.output.mkdir(parents=True, exist_ok=True)
        final.write(args.output / "verification_receipt.json")
        return final


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--response")
    parser.add_argument("--finish-reason")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--executor", choices=("docker", "host"), default="docker")
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    if bool(args.candidate) == bool(args.response is not None):
        parser.error("choose exactly one of --candidate or --response")
    try:
        receipt = run(args)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"INVALID: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    print(json.dumps(receipt.payload(), sort_keys=True))
    return 0 if receipt.status == "PASS" else 2 if receipt.status == "INVALID" else 1


if __name__ == "__main__":
    raise SystemExit(main())
