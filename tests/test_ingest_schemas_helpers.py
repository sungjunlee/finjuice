"""Identity coverage for the ingest schema sheet-name helper split."""

from __future__ import annotations

from pathlib import Path

from finjuice.pipeline.ingest import schemas, schemas_helpers

INGEST_DIR = Path("src/finjuice/pipeline/ingest")

SHEET_NAME_HELPER_NAMES = (
    "ASSET_SHEET_NAME_CANDIDATES",
    "ASSET_SHEET_NAME_NORMALIZED",
    "normalize_sheet_name",
    "is_asset_sheet_name",
)


def test_sheet_name_helpers_live_in_sibling_module() -> None:
    """Sheet-name matching helpers should not live in the column-mapping module."""
    schemas_text = (INGEST_DIR / "schemas.py").read_text(encoding="utf-8")
    helpers_text = (INGEST_DIR / "schemas_helpers.py").read_text(encoding="utf-8")

    assert "def map_columns" in schemas_text
    assert "def normalize_sheet_name" not in schemas_text
    assert "def is_asset_sheet_name" not in schemas_text
    assert "ASSET_SHEET_NAME_CANDIDATES = " not in schemas_text
    assert "ASSET_SHEET_NAME_NORMALIZED = " not in schemas_text

    assert "def normalize_sheet_name" in helpers_text
    assert "def is_asset_sheet_name" in helpers_text
    assert "ASSET_SHEET_NAME_CANDIDATES = " in helpers_text
    assert "ASSET_SHEET_NAME_NORMALIZED = " in helpers_text


def test_sheet_name_helpers_reexport_from_schemas() -> None:
    """Existing schemas imports should keep resolving to the sheet-name helpers."""
    schemas_text = (INGEST_DIR / "schemas.py").read_text(encoding="utf-8")

    for name in SHEET_NAME_HELPER_NAMES:
        assert name in schemas_text
        assert getattr(schemas, name) is getattr(schemas_helpers, name)

    assert callable(schemas.detect_schema_version)
    assert callable(schemas.map_columns)
    assert callable(schemas.normalize_sheet_name)
    assert callable(schemas.is_asset_sheet_name)
