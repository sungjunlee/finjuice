"""Tests for schema reference documentation generation."""

from pathlib import Path

from scripts.generate_schema_docs import generate_schema_docs


def test_generate_schema_docs_includes_compatibility_migration_paths(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Generated schema docs should explain runtime and manual v3 migration paths."""
    # Arrange
    repo_root = Path(__file__).resolve().parents[2]
    source_schema = repo_root / "templates" / "schema.yaml"
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    (template_dir / "schema.yaml").write_text(
        source_schema.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    # Act
    generate_schema_docs()

    # Assert
    generated_doc = tmp_path / "docs" / "reference" / "schema.md"
    content = generated_doc.read_text(encoding="utf-8")
    assert "## Schema Compatibility" in content
    assert "Compatibility Status" in content
    assert "compatible-legacy" in content
    assert "finjuice refresh" in content
    assert "scripts/migrate_schema_v3.py" in content
