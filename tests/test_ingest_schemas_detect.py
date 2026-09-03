"""Identity coverage for the ingest transaction-schema detection split."""

from __future__ import annotations

from pathlib import Path

from finjuice.pipeline.ingest import schemas, schemas_detect

INGEST_DIR = Path("src/finjuice/pipeline/ingest")

DETECT_HELPER_NAMES = (
    "ColumnSchema",
    "BANKSALAD_SCHEMAS",
    "REQUIRED_KOREAN_COLUMNS",
    "detect_schema_version",
    "_matches_schema",
)


def test_detect_helpers_live_in_sibling_module() -> None:
    """Transaction schema catalog/detection should not live in the mapping module."""
    schemas_text = (INGEST_DIR / "schemas.py").read_text(encoding="utf-8")
    helpers_text = (INGEST_DIR / "schemas_helpers.py").read_text(encoding="utf-8")
    assets_text = (INGEST_DIR / "schemas_assets.py").read_text(encoding="utf-8")
    detect_text = (INGEST_DIR / "schemas_detect.py").read_text(encoding="utf-8")

    assert "def map_columns" in schemas_text
    assert "def detect_asset_schema_version" not in schemas_text
    assert "def map_asset_columns" not in schemas_text
    assert "class ColumnSchema" not in schemas_text
    assert "BANKSALAD_SCHEMAS = " not in schemas_text
    assert "REQUIRED_KOREAN_COLUMNS: " not in schemas_text
    assert "def detect_schema_version" not in schemas_text
    assert "def _matches_schema" not in schemas_text

    assert "def normalize_sheet_name" in helpers_text
    assert "class AssetColumnSchema" in assets_text
    assert "def map_asset_columns" in assets_text
    assert "class ColumnSchema" not in helpers_text
    assert "class ColumnSchema" not in assets_text
    assert "BANKSALAD_SCHEMAS = " not in helpers_text
    assert "BANKSALAD_SCHEMAS = " not in assets_text

    assert "class ColumnSchema" in detect_text
    assert "BANKSALAD_SCHEMAS = " in detect_text
    assert "REQUIRED_KOREAN_COLUMNS: " in detect_text
    assert "def detect_schema_version" in detect_text
    assert "def _matches_schema" in detect_text
    assert "def map_columns" not in detect_text
    assert "class AssetColumnSchema" not in detect_text
    assert "def normalize_sheet_name" not in detect_text


def test_detect_helpers_reexport_from_schemas() -> None:
    """Existing schemas imports should keep resolving to the detection helpers."""
    schemas_text = (INGEST_DIR / "schemas.py").read_text(encoding="utf-8")

    for name in DETECT_HELPER_NAMES:
        assert name in schemas_text
        assert getattr(schemas, name) is getattr(schemas_detect, name)

    assert callable(schemas.map_columns)
    assert callable(schemas.detect_schema_version)
    assert callable(schemas._matches_schema)
    assert callable(schemas.detect_asset_schema_version)
    assert callable(schemas.map_asset_columns)
    assert schemas.ColumnSchema is schemas_detect.ColumnSchema
    assert schemas.BANKSALAD_SCHEMAS is schemas_detect.BANKSALAD_SCHEMAS
    assert schemas.REQUIRED_KOREAN_COLUMNS is schemas_detect.REQUIRED_KOREAN_COLUMNS
