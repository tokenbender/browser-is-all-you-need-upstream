"""Regression tests for the R8 effective-source inventory."""

from glm47_posttraining.aider_polyglot import effective_source


def test_effective_source_excludes_editor_and_reject_backups(
    tmp_path, monkeypatch
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "kept.py").write_text("kept = True\n", encoding="utf-8")
    (source_root / "editor.py.orig").write_text("private backup\n", encoding="utf-8")
    (source_root / "failed.py.rej").write_text("failed patch\n", encoding="utf-8")
    (source_root / "bytecode.pyc").write_bytes(b"not bytecode")
    monkeypatch.setattr(effective_source, "SOURCE_INPUTS", ("source",))

    manifest = effective_source.build_effective_source_manifest(tmp_path)

    assert [entry["path"] for entry in manifest["files"]] == ["source/kept.py"]
    assert manifest["file_count"] == 1
