"""Identity coverage for the ingest asset-schema helper split."""

from __future__ import annotations

from pathlib import Path

from finjuice.pipeline.ingest import schemas, schemas_assets

INGEST_DIR = Path("src/finjuice/pipeline/ingest")

ASSET_SCHEMA_HELPER_NAMES = (
    "AssetColumnSchema",
    "ASSET_SCHEMAS",
    "detect_asset_schema_version",
    "map_asset_columns",
)


def test_asset_schema_helpers_live_in_sibling_module() -> None:
    """Asset snapshot mapping should not live in the transaction-mapping module."""
    schemas_text = (INGEST_DIR / "schemas.py").read_text(encoding="utf-8")
    assets_text = (INGEST_DIR / "schemas_assets.py").read_text(encoding="utf-8")

    assert "def map_columns" in schemas_text
    assert "class AssetColumnSchema" not in schemas_text
    assert "ASSET_SCHEMAS = " not in schemas_text
    assert "def detect_asset_schema_version" not in schemas_text
    assert "def map_asset_columns" not in schemas_text

    assert "class AssetColumnSchema" in assets_text
    assert "ASSET_SCHEMAS = " in assets_text
    assert "def detect_asset_schema_version" in assets_text
    assert "def map_asset_columns" in assets_text


def test_asset_schema_helpers_reexport_from_schemas() -> None:
    """Existing schemas imports should keep resolving to the asset-schema helpers."""
    schemas_text = (INGEST_DIR / "schemas.py").read_text(encoding="utf-8")

    for name in ASSET_SCHEMA_HELPER_NAMES:
        assert name in schemas_text
        assert getattr(schemas, name) is getattr(schemas_assets, name)

    assert callable(schemas.detect_schema_version)
    assert callable(schemas.map_columns)
    assert callable(schemas.detect_asset_schema_version)
    assert callable(schemas.map_asset_columns)
    assert schemas.AssetColumnSchema is schemas_assets.AssetColumnSchema
    assert schemas.ASSET_SCHEMAS is schemas_assets.ASSET_SCHEMAS
