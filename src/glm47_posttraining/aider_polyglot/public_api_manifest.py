"""Clang-18-backed public-API manifests for clean-room Aider C++ tasks.

The public task contract is the source of truth.  This module turns its exact
C++ declaration block into a canonical AST identity, proves that the private
reference implements that identity, and verifies generated candidate files
without consulting hidden tests.  It never assigns reward weights.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePath
from tempfile import TemporaryDirectory
from typing import Any


SCHEMA_VERSION = "glm47-public-api-ast-manifest-v1"
RECEIPT_SCHEMA_VERSION = "glm47-public-api-ast-verification-v1"
CPP_SUFFIXES = frozenset({".cpp", ".cc", ".cxx"})
HEADER_SUFFIXES = frozenset({".h", ".hh", ".hpp", ".hxx"})
DECLARATION_KINDS = frozenset(
    {
        "FunctionDecl",
        "CXXMethodDecl",
        "CXXConstructorDecl",
        "CXXDestructorDecl",
        "CXXConversionDecl",
        "CXXRecordDecl",
        "FieldDecl",
        "EnumDecl",
        "EnumConstantDecl",
        "TypeAliasDecl",
        "TypedefDecl",
        "FunctionTemplateDecl",
        "ClassTemplateDecl",
        "TypeAliasTemplateDecl",
    }
)
COMMON_INCLUDES = """#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <complex>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <functional>
#include <limits>
#include <list>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <queue>
#include <set>
#include <span>
#include <string>
#include <string_view>
#include <thread>
#include <tuple>
#include <type_traits>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <variant>
#include <vector>
"""


class PublicAPIManifestError(RuntimeError):
    """Raised when a public API cannot be proved exactly."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _compiler_identity(executable: str = "clang-18") -> dict[str, Any]:
    resolved = shutil.which(executable)
    if resolved is None:
        raise PublicAPIManifestError(f"required compiler is unavailable: {executable}")
    completed = subprocess.run(
        [resolved, "--version"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    first_line = completed.stdout.splitlines()[0] if completed.stdout else ""
    match = re.search(r"clang version\s+(\d+)(?:\.|\b)", first_line, re.IGNORECASE)
    if completed.returncode != 0 or match is None or int(match.group(1)) != 18:
        raise PublicAPIManifestError(
            f"Clang 18 is required; observed returncode={completed.returncode} {first_line!r}"
        )
    return {
        "executable": executable,
        "resolved_executable": resolved,
        "version_first_line": first_line,
        "major_version": 18,
        "language_standard": "c++17",
        "ast_format": "clang-json-filtered-v1",
    }


def _json_stream(value: str) -> list[dict[str, Any]]:
    decoder = json.JSONDecoder()
    offset = 0
    documents: list[dict[str, Any]] = []
    while offset < len(value):
        while offset < len(value) and value[offset].isspace():
            offset += 1
        if offset >= len(value):
            break
        item, offset = decoder.raw_decode(value, offset)
        if not isinstance(item, dict):
            raise PublicAPIManifestError("Clang AST stream contains a non-object document")
        documents.append(item)
    return documents


def _run_clang_ast(
    path: Path,
    *,
    include_root: Path,
    compiler: str,
    timeout_s: int = 30,
) -> list[dict[str, Any]]:
    command = [
        compiler,
        "-std=c++17",
        "-x",
        "c++",
        "-fsyntax-only",
        "-Werror",
        "-Wno-pragma-once-outside-header",
        "-I",
        str(include_root),
        "-Xclang",
        "-ast-dump=json",
        "-Xclang",
        "-ast-dump-filter",
        "-Xclang",
        "charm",
        str(path),
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        raise PublicAPIManifestError(f"Clang AST timeout for {path.name}") from exc
    if completed.returncode != 0:
        raise PublicAPIManifestError(
            f"Clang AST failed for {path.name}: {(completed.stderr or '')[-4000:]}"
        )
    return _json_stream(completed.stdout)


def _default_access(record_kind: str | None) -> str:
    return "private" if record_kind == "class" else "public"


def _normalized_type(node: Mapping[str, Any]) -> str | None:
    type_value = node.get("type")
    if not isinstance(type_value, Mapping):
        return None
    value = type_value.get("desugaredQualType", type_value.get("qualType"))
    return str(value) if isinstance(value, str) and value else None


def _template_arity(node: Mapping[str, Any]) -> int:
    return sum(
        child.get("kind")
        in {"TemplateTypeParmDecl", "NonTypeTemplateParmDecl", "TemplateTemplateParmDecl"}
        for child in node.get("inner", [])
        if isinstance(child, Mapping)
    )


def _declaration_identity(
    node: Mapping[str, Any],
    *,
    namespace: tuple[str, ...],
    records: tuple[str, ...],
    access: str | None,
    template_arity: int | None = None,
) -> dict[str, Any] | None:
    kind = str(node.get("kind", ""))
    name = node.get("name")
    if kind not in DECLARATION_KINDS or not isinstance(name, str) or not name:
        return None
    if node.get("isImplicit") is True:
        return None
    if not namespace or namespace[0] != "charm":
        return None
    if kind == "CXXRecordDecl" and node.get("completeDefinition") is not True:
        return None
    qualified_name = "::".join((*namespace, *records, name))
    normalized_kind = {
        "FunctionDecl": "function",
        "CXXMethodDecl": "method",
        "CXXConstructorDecl": "constructor",
        "CXXDestructorDecl": "destructor",
        "CXXConversionDecl": "conversion",
        "CXXRecordDecl": "record",
        "FieldDecl": "field",
        "EnumDecl": "enum",
        "EnumConstantDecl": "enum_constant",
        "TypeAliasDecl": "alias",
        "TypedefDecl": "alias",
        "FunctionTemplateDecl": "function_template",
        "ClassTemplateDecl": "class_template",
        "TypeAliasTemplateDecl": "alias_template",
    }[kind]
    parameters = [
        _normalized_type(child)
        for child in node.get("inner", [])
        if isinstance(child, Mapping) and child.get("kind") == "ParmVarDecl"
    ]
    identity: dict[str, Any] = {
        "kind": normalized_kind,
        "qualified_name": qualified_name,
        "type": _normalized_type(node),
        "parameter_types": parameters,
        "access": access,
        "template_arity": template_arity,
    }
    if normalized_kind == "record":
        identity["record_kind"] = str(node.get("tagUsed", "struct"))
    return identity


def _extract_occurrences(documents: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    occurrences: list[dict[str, Any]] = []
    declarations_by_id: dict[str, dict[str, Any]] = {}

    def visit(
        node: Mapping[str, Any],
        namespace: tuple[str, ...] = (),
        records: tuple[str, ...] = (),
        access: str | None = None,
        inherited_template_arity: int | None = None,
    ) -> None:
        kind = str(node.get("kind", ""))
        name = node.get("name")
        current_namespace = namespace
        current_records = records
        current_access = access
        if kind == "NamespaceDecl" and isinstance(name, str) and name:
            current_namespace = (*namespace, name)
        if kind in {"FunctionTemplateDecl", "ClassTemplateDecl", "TypeAliasTemplateDecl"}:
            inherited_template_arity = _template_arity(node)
        previous_decl = node.get("previousDecl")
        inherited_identity = (
            declarations_by_id.get(str(previous_decl)) if isinstance(previous_decl, str) else None
        )
        identity = (
            dict(inherited_identity)
            if inherited_identity is not None
            else _declaration_identity(
                node,
                namespace=current_namespace,
                records=current_records,
                access=current_access,
                template_arity=inherited_template_arity,
            )
        )
        if identity is not None:
            declaration_id = node.get("id")
            if isinstance(declaration_id, str):
                declarations_by_id[declaration_id] = identity
            has_body = any(
                isinstance(child, Mapping) and child.get("kind") == "CompoundStmt"
                for child in node.get("inner", [])
            )
            occurrences.append({"identity": identity, "is_definition": has_body})
        if kind == "CXXRecordDecl" and node.get("completeDefinition") is True:
            record_name = str(name)
            record_kind = str(node.get("tagUsed", "struct"))
            member_access = _default_access(record_kind)
            for child in node.get("inner", []):
                if not isinstance(child, Mapping):
                    continue
                if child.get("kind") == "AccessSpecDecl":
                    member_access = str(child.get("access", member_access))
                    continue
                visit(
                    child,
                    current_namespace,
                    (*records, record_name),
                    member_access,
                    inherited_template_arity,
                )
            return
        for child in node.get("inner", []):
            if isinstance(child, Mapping):
                visit(
                    child,
                    current_namespace,
                    current_records,
                    current_access,
                    inherited_template_arity,
                )

    for document in documents:
        visit(document)
    unique: dict[tuple[bytes, bool], dict[str, Any]] = {}
    for occurrence in occurrences:
        key = (_canonical_bytes(occurrence["identity"]), occurrence["is_definition"])
        unique[key] = occurrence
    return [unique[key] for key in sorted(unique)]


def _identity_key(identity: Mapping[str, Any]) -> str:
    return _sha256_bytes(_canonical_bytes(identity))


def _analyze_files(
    root: Path,
    files: Sequence[str],
    *,
    compiler: str,
) -> dict[str, Any]:
    headers = [name for name in files if PurePath(name).suffix.lower() in HEADER_SUFFIXES]
    sources = [name for name in files if PurePath(name).suffix.lower() in CPP_SUFFIXES]
    if not headers and not sources:
        raise PublicAPIManifestError("public API verification requires C++ files")
    occurrences: dict[str, dict[str, Any]] = {}
    diagnostics: list[dict[str, Any]] = []
    for lane, names in (("header", headers), ("source", sources)):
        for name in names:
            path = root / name
            if path.is_symlink() or not path.is_file() or path.parent != root:
                raise PublicAPIManifestError(f"unsafe or missing public API file: {name}")
            documents = _run_clang_ast(path, include_root=root, compiler=compiler)
            extracted = _extract_occurrences(documents)
            diagnostics.append(
                {
                    "file": name,
                    "lane": lane,
                    "sha256": _sha256_file(path),
                    "ast_occurrences": len(extracted),
                }
            )
            for occurrence in extracted:
                identity = occurrence["identity"]
                key = _identity_key(identity)
                item = occurrences.setdefault(
                    key,
                    {
                        "identity": identity,
                        "header_declaration": False,
                        "header_definition": False,
                        "source_declaration": False,
                        "source_definition": False,
                    },
                )
                item[f"{lane}_declaration"] = True
                if occurrence["is_definition"]:
                    item[f"{lane}_definition"] = True
    return {
        "headers": headers,
        "sources": sources,
        "occurrences": occurrences,
        "files": diagnostics,
    }


def _expected_identities(public_api: Sequence[str], *, compiler: str) -> list[dict[str, Any]]:
    if not public_api or not all(isinstance(value, str) and value.strip() for value in public_api):
        raise PublicAPIManifestError("public API contract must be a nonempty string array")
    with TemporaryDirectory(prefix="glm47-public-api-contract-") as value:
        root = Path(value)
        contract = root / "public_api_contract.cpp"
        contract.write_text(COMMON_INCLUDES + "\n" + "\n".join(public_api), encoding="utf-8")
        occurrences = _extract_occurrences(
            _run_clang_ast(contract, include_root=root, compiler=compiler)
        )
    identities = {
        _identity_key(occurrence["identity"]): occurrence["identity"] for occurrence in occurrences
    }
    if not identities:
        raise PublicAPIManifestError("public API contract produced no charm declarations")
    return [identities[key] for key in sorted(identities)]


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite public API artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def build_public_api_manifest(
    *,
    task_id: str,
    public_api: Sequence[str],
    editable_files: Sequence[str],
    reference_root: str | Path,
    source_tree_sha256: str,
    compiler: str = "clang-18",
) -> dict[str, Any]:
    """Build a canonical API identity and prove the private reference implements it."""

    compiler_receipt = _compiler_identity(compiler)
    expected = _expected_identities(public_api, compiler=compiler_receipt["resolved_executable"])
    reference = _analyze_files(
        Path(reference_root).resolve(),
        list(editable_files),
        compiler=compiler_receipt["resolved_executable"],
    )
    declarations: list[dict[str, Any]] = []
    missing: list[str] = []
    for identity in expected:
        key = _identity_key(identity)
        observed = reference["occurrences"].get(key)
        if observed is None:
            missing.append(identity["qualified_name"])
            continue
        requires_definition = identity["kind"] in {
            "function",
            "method",
            "constructor",
            "destructor",
            "conversion",
            "function_template",
        }
        definition_present = bool(observed["header_definition"] or observed["source_definition"])
        if requires_definition and not definition_present:
            missing.append(f"{identity['qualified_name']}:definition")
            continue
        declarations.append(
            {
                "identity_sha256": key,
                "identity": identity,
                "require_header_declaration": bool(observed["header_declaration"]),
                "require_header_definition": bool(observed["header_definition"]),
                "require_source_definition": bool(observed["source_definition"]),
            }
        )
    if missing:
        raise PublicAPIManifestError(
            f"reference public API mismatch for {task_id}: {', '.join(missing)}"
        )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "decision": "PASS",
        "task_id": task_id,
        "source_tree_sha256": source_tree_sha256,
        "public_api_contract_sha256": _sha256_bytes(_canonical_bytes(list(public_api))),
        "editable_files": list(editable_files),
        "compiler": compiler_receipt,
        "declaration_count": len(declarations),
        "declarations": declarations,
        "reference_proof": {
            "status": "PASS",
            "headers": reference["headers"],
            "sources": reference["sources"],
            "files": reference["files"],
            "exact_declarations_present": True,
            "required_definitions_present": True,
            "standalone_header_compilation": True,
        },
        "model_facing": False,
        "hidden_test_content_used": False,
    }
    payload["manifest_sha256"] = _sha256_bytes(_canonical_bytes(payload))
    validate_public_api_manifest(payload)
    return payload


def validate_public_api_manifest(
    manifest: Mapping[str, Any],
    *,
    expected_task_id: str | None = None,
    expected_source_tree_sha256: str | None = None,
) -> dict[str, Any]:
    payload = dict(manifest)
    observed_digest = payload.pop("manifest_sha256", None)
    expected_digest = _sha256_bytes(_canonical_bytes(payload))
    declarations = payload.get("declarations")
    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("decision") != "PASS"
        or observed_digest != expected_digest
        or payload.get("model_facing") is not False
        or payload.get("hidden_test_content_used") is not False
        or not isinstance(declarations, list)
        or payload.get("declaration_count") != len(declarations)
        or len(declarations) == 0
        or payload.get("compiler", {}).get("major_version") != 18
        or payload.get("compiler", {}).get("language_standard") != "c++17"
        or payload.get("reference_proof", {}).get("status") != "PASS"
    ):
        raise PublicAPIManifestError("invalid public API manifest receipt")
    if expected_task_id is not None and payload.get("task_id") != expected_task_id:
        raise PublicAPIManifestError("public API manifest task identity drift")
    if (
        expected_source_tree_sha256 is not None
        and payload.get("source_tree_sha256") != expected_source_tree_sha256
    ):
        raise PublicAPIManifestError("public API manifest source-tree drift")
    identity_keys = [
        str(item.get("identity_sha256")) for item in declarations if isinstance(item, Mapping)
    ]
    if len(identity_keys) != len(declarations) or len(set(identity_keys)) != len(identity_keys):
        raise PublicAPIManifestError("public API manifest has duplicate declaration identities")
    return {**payload, "manifest_sha256": observed_digest}


def verify_public_api_candidate(
    manifest: Mapping[str, Any],
    *,
    candidate_root: str | Path,
    candidate_files: Sequence[str],
    compiler: str = "clang-18",
) -> dict[str, Any]:
    """Verify exact declarations, placements, and complete-file emission."""

    validated = validate_public_api_manifest(manifest)
    compiler_receipt = _compiler_identity(compiler)
    expected_files = list(validated["editable_files"])
    checks: dict[str, bool] = {
        "exact_editable_file_set": (
            set(candidate_files) == set(expected_files)
            and len(candidate_files) == len(expected_files)
        ),
        "exact_declaration_identities": False,
        "header_declarations": False,
        "required_definitions": False,
        "overload_sets": False,
        "standalone_headers": False,
        "header_source_consistency": False,
    }
    failures: list[str] = []
    if set(candidate_files) != set(expected_files) or len(candidate_files) != len(expected_files):
        failures.append("candidate did not emit every editable file exactly once")
        analysis = None
    else:
        try:
            analysis = _analyze_files(
                Path(candidate_root).resolve(),
                expected_files,
                compiler=compiler_receipt["resolved_executable"],
            )
        except PublicAPIManifestError as exc:
            failures.append(f"candidate AST analysis failed: {exc}")
            analysis = None
        checks["standalone_headers"] = analysis is not None
        if analysis is None:
            decision = "FAIL"
            receipt = {
                "schema_version": RECEIPT_SCHEMA_VERSION,
                "decision": decision,
                "task_id": validated["task_id"],
                "manifest_sha256": validated["manifest_sha256"],
                "compiler": compiler_receipt,
                "checks": checks,
                "failures": failures,
                "candidate_file_sha256": {},
                "observed_files": [],
            }
            receipt["receipt_sha256"] = _sha256_bytes(_canonical_bytes(receipt))
            return receipt
        expected_by_name: dict[str, set[str]] = {}
        observed_by_name: dict[str, set[str]] = {}
        header_ok = True
        definition_ok = True
        consistency_ok = True
        all_present = True
        for requirement in validated["declarations"]:
            identity = requirement["identity"]
            key = requirement["identity_sha256"]
            name = identity["qualified_name"]
            expected_by_name.setdefault(name, set()).add(key)
            occurrence = analysis["occurrences"].get(key)
            if occurrence is None:
                all_present = False
                failures.append(f"missing exact declaration: {name}")
                continue
            if requirement["require_header_declaration"] and not occurrence["header_declaration"]:
                header_ok = False
                failures.append(f"missing header declaration: {name}")
            if requirement["require_header_definition"] and not occurrence["header_definition"]:
                definition_ok = False
                failures.append(f"missing header definition: {name}")
            if requirement["require_source_definition"] and not occurrence["source_definition"]:
                definition_ok = False
                failures.append(f"missing source definition: {name}")
            if (
                requirement["require_header_declaration"]
                and requirement["require_source_definition"]
                and not (occurrence["header_declaration"] and occurrence["source_definition"])
            ):
                consistency_ok = False
        for key, occurrence in analysis["occurrences"].items():
            name = occurrence["identity"]["qualified_name"]
            if name in expected_by_name:
                observed_by_name.setdefault(name, set()).add(key)
        overload_ok = all(
            observed_by_name.get(name, set()) == keys for name, keys in expected_by_name.items()
        )
        if not overload_ok:
            failures.append("public overload set drift")
        checks.update(
            {
                "exact_declaration_identities": all_present,
                "header_declarations": header_ok,
                "required_definitions": definition_ok,
                "overload_sets": overload_ok,
                "header_source_consistency": consistency_ok,
            }
        )
    decision = "PASS" if all(checks.values()) and not failures else "FAIL"
    receipt: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "decision": decision,
        "task_id": validated["task_id"],
        "manifest_sha256": validated["manifest_sha256"],
        "compiler": compiler_receipt,
        "checks": checks,
        "failures": failures,
        "candidate_file_sha256": (
            {name: _sha256_file(Path(candidate_root).resolve() / name) for name in expected_files}
            if analysis is not None
            else {}
        ),
        "observed_files": analysis["files"] if analysis is not None else [],
    }
    receipt["receipt_sha256"] = _sha256_bytes(_canonical_bytes(receipt))
    return receipt


def _main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--candidate-root", required=True)
    parser.add_argument("--candidate-file", action="append", default=[])
    parser.add_argument("--compiler", default="clang-18")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    receipt = verify_public_api_candidate(
        manifest,
        candidate_root=args.candidate_root,
        candidate_files=args.candidate_file,
        compiler=args.compiler,
    )
    _write_json(Path(args.output).resolve(), receipt)
    print(json.dumps(receipt, sort_keys=True))
    if receipt["decision"] != "PASS":
        raise SystemExit(3)


if __name__ == "__main__":
    _main()


__all__ = [
    "PublicAPIManifestError",
    "SCHEMA_VERSION",
    "build_public_api_manifest",
    "validate_public_api_manifest",
    "verify_public_api_candidate",
]
