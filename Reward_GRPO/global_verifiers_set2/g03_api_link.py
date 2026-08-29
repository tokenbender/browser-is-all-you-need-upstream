"""G03: exact manifest-driven Clang AST contract and trusted caller linkage."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Iterable

from receipt import PolicyReceipt, policy
from sandbox import CommandResult, Limits, result_facts

Execute = Callable[[list[str], Path, Limits, dict[str, str] | None], CommandResult]


def _walk(
    node: Any, scopes: tuple[str, ...] = (), access: str | None = None,
):
    """Yield declarations with lexical scope and effective member access."""

    if not isinstance(node, dict):
        return
    kind = node.get("kind")
    name = node.get("name")
    child_scopes = scopes
    if kind in {"NamespaceDecl", "CXXRecordDecl"} and name:
        child_scopes = (*scopes, str(name))
    yield node, scopes, access
    children = node.get("inner", [])
    if kind == "CXXRecordDecl":
        current_access = "private" if node.get("tagUsed") == "class" else "public"
        for child in children:
            if isinstance(child, dict) and child.get("kind") == "AccessSpecDecl":
                value = child.get("access")
                if value in {"public", "protected", "private"}:
                    current_access = value
                yield child, child_scopes, current_access
                continue
            yield from _walk(child, child_scopes, current_access)
    else:
        for child in children:
            yield from _walk(child, child_scopes, access)


def _json_documents(value: str) -> Iterable[Any]:
    decoder = json.JSONDecoder()
    offset = 0
    while offset < len(value):
        while offset < len(value) and value[offset].isspace():
            offset += 1
        if offset >= len(value):
            return
        document, offset = decoder.raw_decode(value, offset)
        yield document


def _load_contract(
    workspace: Path, manifest: dict[str, Any],
) -> tuple[list[dict[str, Any]], str | None]:
    api = manifest.get("api", {})
    contract_name = api.get("contract", "public_api.json")
    if not isinstance(contract_name, str):
        return [], "INVALID_API_CONTRACT"
    try:
        contract = json.loads((workspace / contract_name).read_text())
    except (OSError, json.JSONDecodeError):
        return [], "INVALID_API_CONTRACT"
    if contract.get("contract_version") != manifest.get("contract_version"):
        return [], "API_CONTRACT_VERSION_MISMATCH"
    declarations = contract.get("declarations")
    if not isinstance(declarations, list) or not declarations:
        return [], "INVALID_API_CONTRACT"
    return declarations, None


def _arguments(values: Any) -> list[str] | None:
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        return None
    return list(values)


def _source_offset(value: Any) -> int | None:
    if not isinstance(value, dict):
        return None
    offset = value.get("offset")
    if isinstance(offset, int):
        return offset
    for key in ("expansionLoc", "spellingLoc"):
        nested = _source_offset(value.get(key))
        if nested is not None:
            return nested
    return None


def _is_explicit(node: dict[str, Any], source: str) -> bool:
    """Recover ``explicit`` from Clang's authenticated declaration range."""

    begin = _source_offset(node.get("range", {}).get("begin"))
    location = _source_offset(node.get("loc"))
    if begin is None or location is None or not (0 <= begin <= location <= len(source)):
        return False
    tokens = re.findall(r"[A-Za-z_][A-Za-z_0-9]*", source[begin:location])
    return "explicit" in tokens


def _normalize_type(value: Any) -> str:
    return " ".join(str(value or "").split())


def _parameters(node: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        child for child in node.get("inner", [])
        if isinstance(child, dict) and child.get("kind") == "ParmVarDecl"
    ]


def _declaration_facts(
    node: dict[str, Any], scopes: tuple[str, ...], access: str | None, source: str,
) -> dict[str, Any]:
    qual_type = _normalize_type(node.get("type", {}).get("qualType", ""))
    suffix = qual_type.rsplit(")", 1)[1].strip() if ")" in qual_type else ""
    parameters = _parameters(node)
    template_kinds = {
        "TemplateTypeParmDecl", "NonTypeTemplateParmDecl", "TemplateTemplateParmDecl",
    }
    return {
        "kind": str(node.get("kind", "")),
        "name": str(node.get("name", "")),
        "namespace": "::".join(scopes),
        "type": qual_type,
        "access": access,
        "explicit": _is_explicit(node, source),
        "static": node.get("storageClass") == "static",
        "parameter_count": len(parameters),
        "parameter_types": [
            _normalize_type(parameter.get("type", {}).get("qualType", ""))
            for parameter in parameters
        ],
        "default_argument_count": sum("init" in parameter for parameter in parameters),
        "const": "const" in suffix.split(),
        "noexcept": "noexcept" in suffix.split(),
        "ref_qualifier": "&&" if "&&" in suffix else "&" if "&" in suffix else "",
        "tag": node.get("tagUsed"),
        "implicit": bool(node.get("isImplicit", False)),
        "template_parameter_count": sum(
            isinstance(child, dict) and child.get("kind") in template_kinds
            for child in node.get("inner", [])
        ),
    }


_EXACT_FIELDS = {
    "access", "explicit", "static", "parameter_count", "parameter_types",
    "default_argument_count", "const", "noexcept", "ref_qualifier", "tag",
    "template_parameter_count",
}
_BOOL_FIELDS = {"explicit", "static", "const", "noexcept"}
_COUNT_FIELDS = {"parameter_count", "default_argument_count", "template_parameter_count"}


def _valid_declaration(expected: Any) -> bool:
    if not isinstance(expected, dict):
        return False
    if not isinstance(expected.get("name"), str) or not expected["name"]:
        return False
    if not isinstance(expected.get("namespace", ""), str):
        return False
    if "kind" in expected and not isinstance(expected["kind"], str):
        return False
    for key in ("type", "type_contains", "access", "ref_qualifier", "tag", "ast_filter"):
        if key in expected and not isinstance(expected[key], str):
            return False
    for key in _BOOL_FIELDS:
        if key in expected and not isinstance(expected[key], bool):
            return False
    for key in (*_COUNT_FIELDS, "overload_count"):
        if key in expected and (
            not isinstance(expected[key], int) or isinstance(expected[key], bool)
            or expected[key] < 0
        ):
            return False
    if "overload_count" in expected and expected["overload_count"] < 1:
        return False
    if "parameter_types" in expected and (
        not isinstance(expected["parameter_types"], list)
        or not all(isinstance(value, str) for value in expected["parameter_types"])
    ):
        return False
    return True


def _matches_contract(facts: dict[str, Any], expected: dict[str, Any]) -> bool:
    # type_contains is retained as a schema-v2 compatibility alias, but matching is
    # deliberately exact; substring matching admitted extra defaulted parameters.
    expected_type = expected.get("type", expected.get("type_contains"))
    if expected_type is not None and facts["type"] != _normalize_type(expected_type):
        return False
    for key in _EXACT_FIELDS:
        if key not in expected:
            continue
        value = expected[key]
        if key == "parameter_types":
            value = [_normalize_type(item) for item in value]
        if facts[key] != value:
            return False
    return True


def verify(
    workspace: Path, manifest: dict[str, Any], objects: list[str], execute: Execute,
    limits: Limits,
) -> tuple[PolicyReceipt, str | None]:
    api = manifest.get("api", {})
    build = manifest.get("build", {})
    header = api.get("candidate_header")
    caller = api.get("caller")
    required, contract_error = _load_contract(workspace, manifest)
    clang = str(api.get("clang", "clang++"))
    includes = _arguments(build.get("include_dirs", ["."]))
    defines = _arguments(build.get("defines", []))
    flags = _arguments(api.get("ast_flags", []))
    if contract_error:
        return policy("G03", "INVALID", contract_error), None
    if (
        not isinstance(header, str) or not isinstance(caller, str)
        or any(value is None for value in (includes, defines, flags))
    ):
        return policy("G03", "INVALID", "INVALID_API_CONTRACT"), None
    try:
        header_source = (workspace / header).read_text(encoding="utf-8")
    except OSError:
        return policy("G03", "INVALID", "INVALID_API_CONTRACT"), None

    filters: list[str] = []
    for expected in required:
        if not _valid_declaration(expected):
            return policy("G03", "INVALID", "INVALID_API_DECLARATION"), None
        value = expected.get("ast_filter", expected["name"])
        if not value:
            return policy("G03", "INVALID", "INVALID_API_DECLARATION"), None
        if value not in filters:
            filters.append(value)

    nodes: list[tuple[dict[str, Any], tuple[str, ...], str | None]] = []
    ast_receipts: list[dict[str, object]] = []
    for value in filters:
        ast_command = [
            clang, f"-std={build.get('standard', 'c++17')}", *flags,
            *(f"-I{include}" for include in includes),
            *(f"-D{define}" for define in defines), "-x", "c++", "-Xclang",
            f"-ast-dump-filter={value}", "-Xclang", "-ast-dump=json",
            "-fsyntax-only", header,
        ]
        # Clang JSON for template-heavy public declarations can exceed the ordinary
        # diagnostic capture budget even with an AST filter. Use a bounded, policy-local
        # allowance so a valid candidate is not misclassified as infrastructure INVALID.
        ast_limits = replace(
            limits, output_bytes=max(limits.output_bytes, 8 * 1024 * 1024)
        )
        ast = execute(ast_command, workspace, ast_limits, None)
        ast_receipts.append(result_facts(ast))
        if ast.launch_error:
            return policy("G03", "INVALID", "CLANG_UNAVAILABLE", commands=ast_receipts), None
        if ast.timed_out:
            return policy("G03", "INVALID", "AST_TIMEOUT", commands=ast_receipts), None
        if ast.stdout_truncated:
            return policy("G03", "INVALID", "AST_OUTPUT_TRUNCATED", commands=ast_receipts), None
        if ast.returncode != 0:
            return policy("G03", "FAIL", "API_PARSE_FAIL", commands=ast_receipts), None
        try:
            documents = list(_json_documents(ast.stdout))
        except json.JSONDecodeError:
            return policy("G03", "INVALID", "MALFORMED_CLANG_AST", commands=ast_receipts), None
        if not documents:
            return policy("G03", "FAIL", "API_FAIL", ast_filter=value), None
        for document in documents:
            nodes.extend(_walk(document))

    declaration_facts = [
        _declaration_facts(node, scopes, access, header_source)
        for node, scopes, access in nodes
        if not bool(node.get("isImplicit", False))
    ]
    mismatches: list[dict[str, Any]] = []
    matched_facts: list[dict[str, Any]] = []
    for expected in required:
        namespace = expected.get("namespace", "")
        candidates = [
            facts for facts in declaration_facts
            if facts["name"] == expected["name"]
            and (not expected.get("kind") or facts["kind"] == expected["kind"])
            and facts["namespace"] == namespace
        ]
        overload_count = expected.get("overload_count")
        cardinality_ok = overload_count is None or len(candidates) == overload_count
        matched = [facts for facts in candidates if _matches_contract(facts, expected)]
        if not matched or not cardinality_ok:
            mismatches.append({
                "expected": expected,
                "observed": candidates,
                "overload_cardinality_ok": cardinality_ok,
            })
        else:
            matched_facts.append(matched[0])
    if mismatches:
        return policy(
            "G03", "FAIL", "API_FAIL", declaration_mismatches=mismatches,
            ast_commands=ast_receipts,
        ), None

    compiler = str(build.get("compiler", "g++"))
    build_flags = _arguments(build.get("flags", []))
    libraries = _arguments(build.get("libraries", []))
    link_args = _arguments(build.get("link_args", []))
    if any(value is None for value in (build_flags, libraries, link_args)):
        return policy("G03", "INVALID", "INVALID_LINK_CONTRACT"), None
    binary = ".gv2/api_link_test"
    command = [
        compiler, f"-std={build.get('standard', 'c++17')}", *build_flags,
        *(f"-I{include}" for include in includes),
        *(f"-D{define}" for define in defines), caller, *objects,
        *(f"-l{value}" for value in libraries), *link_args, "-o", binary,
    ]
    linked = execute(command, workspace, limits, None)
    if linked.launch_error or linked.timed_out:
        return policy(
            "G03", "INVALID", "LINKER_UNAVAILABLE_OR_TIMEOUT",
            command=result_facts(linked),
        ), None
    if linked.returncode != 0:
        return policy("G03", "FAIL", "LINK_FAIL", command=result_facts(linked)), None
    return policy(
        "G03", "PASS", "API_LINKED", ast_commands=ast_receipts,
        matched_declarations=matched_facts, command=result_facts(linked), binary=binary,
    ), binary
