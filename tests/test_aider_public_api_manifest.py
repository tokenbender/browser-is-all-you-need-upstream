from __future__ import annotations

from pathlib import Path

import pytest

from glm47_posttraining.aider_polyglot.public_api_manifest import (
    PublicAPIManifestError,
    build_public_api_manifest,
    validate_public_api_manifest,
    verify_public_api_candidate,
)


PUBLIC_API = [
    """namespace charm::api_demo {
struct Counter { int value; int get() const; };
int add(int left, int right);
}"""
]
HEADER = """#pragma once
namespace charm::api_demo {
struct Counter { int value; int get() const; };
int add(int left, int right);
}
"""
SOURCE = """#include "api.h"
namespace charm::api_demo {
int Counter::get() const { return value; }
int add(int left, int right) { return left + right; }
}
"""


def _write_reference(root: Path) -> None:
    root.mkdir()
    (root / "api.h").write_text(HEADER, encoding="utf-8")
    (root / "api.cpp").write_text(SOURCE, encoding="utf-8")


def _manifest(tmp_path: Path) -> dict[str, object]:
    reference = tmp_path / "reference"
    _write_reference(reference)
    return build_public_api_manifest(
        task_id="api-demo",
        public_api=PUBLIC_API,
        editable_files=["api.h", "api.cpp"],
        reference_root=reference,
        source_tree_sha256="a" * 64,
    )


def test_public_api_manifest_proves_reference_and_candidate(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    candidate = tmp_path / "candidate"
    _write_reference(candidate)

    receipt = verify_public_api_candidate(
        manifest,
        candidate_root=candidate,
        candidate_files=["api.cpp", "api.h"],
    )

    assert manifest["decision"] == "PASS"
    assert manifest["reference_proof"]["status"] == "PASS"
    assert receipt["decision"] == "PASS"
    assert all(receipt["checks"].values())


def test_public_api_candidate_rejects_signature_drift_with_receipt(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "api.h").write_text(
        HEADER.replace("int get() const", "unsigned get() const"),
        encoding="utf-8",
    )
    (candidate / "api.cpp").write_text(
        SOURCE.replace("int Counter::get() const", "unsigned Counter::get() const"),
        encoding="utf-8",
    )

    receipt = verify_public_api_candidate(
        manifest,
        candidate_root=candidate,
        candidate_files=["api.h", "api.cpp"],
    )

    assert receipt["decision"] == "FAIL"
    assert receipt["checks"]["exact_declaration_identities"] is False
    assert any("missing exact declaration" in value for value in receipt["failures"])


def test_public_api_candidate_records_clang_failure_and_missing_file(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "api.h").write_text(HEADER + "this is not C++;\n", encoding="utf-8")
    (candidate / "api.cpp").write_text(SOURCE, encoding="utf-8")

    syntax_receipt = verify_public_api_candidate(
        manifest,
        candidate_root=candidate,
        candidate_files=["api.h", "api.cpp"],
    )
    missing_receipt = verify_public_api_candidate(
        manifest,
        candidate_root=candidate,
        candidate_files=["api.h"],
    )

    assert syntax_receipt["decision"] == "FAIL"
    assert any("candidate AST analysis failed" in value for value in syntax_receipt["failures"])
    assert missing_receipt["decision"] == "FAIL"
    assert missing_receipt["checks"]["exact_editable_file_set"] is False


def test_public_api_manifest_digest_tamper_is_rejected(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    manifest["task_id"] = "tampered"

    with pytest.raises(PublicAPIManifestError, match="invalid public API manifest"):
        validate_public_api_manifest(manifest)
