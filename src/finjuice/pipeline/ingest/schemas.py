"""
Column Schema Mapping for Banksalad XLSX exports (Polars-only).

Handles auto-detection of schema versions and mapping of Korean/English column names
to standardized internal field names.

Sheet-name matching helpers live in
:mod:`finjuice.pipeline.ingest.schemas_helpers`. Asset snapshot column
mapping lives in :mod:`finjuice.pipeline.ingest.schemas_assets`. Transaction
schema catalog and version detection live in
:mod:`finjuice.pipeline.ingest.schemas_detect`. These clusters are
re-exported here so existing callers can keep importing from this module.
"""

import polars as pl

from finjuice.pipeline.ingest.schemas_assets import (
    ASSET_SCHEMAS,  # noqa: F401 — re-exported for existing schemas imports
    AssetColumnSchema,  # noqa: F401 — re-exported for existing schemas imports
    detect_asset_schema_version,  # noqa: F401 — re-exported for existing schemas imports
    map_asset_columns,  # noqa: F401 — re-exported for existing schemas imports
)
from finjuice.pipeline.ingest.schemas_detect import (
    BANKSALAD_SCHEMAS,  # noqa: F401 — re-exported for existing schemas imports
    REQUIRED_KOREAN_COLUMNS,  # noqa: F401 — re-exported for existing schemas imports
    ColumnSchema,  # noqa: F401 — re-exported for existing schemas imports
    _matches_schema,  # noqa: F401 — re-exported for existing schemas imports
    detect_schema_version,
)
from finjuice.pipeline.ingest.schemas_helpers import (
    ASSET_SHEET_NAME_CANDIDATES,  # noqa: F401 — re-exported for existing schemas imports
    ASSET_SHEET_NAME_NORMALIZED,  # noqa: F401 — re-exported for existing schemas imports
    is_asset_sheet_name,  # noqa: F401 — re-exported for existing schemas imports
    normalize_sheet_name,  # noqa: F401 — re-exported for existing schemas imports
)


def map_columns(df: pl.DataFrame) -> pl.DataFrame:
    """
    Map dataframe columns to standard names using auto-detected schema (Polars-only).

    The function detects the schema version from the dataframe columns,
    then renames columns to standard internal names (e.g., '날짜' -> 'date').

    Extra columns not in the schema are preserved unchanged.

    Args:
        df: Polars DataFrame with Banksalad columns

    Returns:
        Polars DataFrame with standardized column names

    Raises:
        ValueError: If required columns are missing
    """
    columns = list(df.columns)
    schema = detect_schema_version(columns)
    column_map = {}

    # Build mapping from source column names to standard field names
    for field_name in schema.__dataclass_fields__.keys():
        if field_name == "version":
            continue

        variants = getattr(schema, field_name)
        for variant in variants:
            if variant in columns:
                column_map[variant] = field_name
                break  # Use first matching variant only

    # Validate required fields are mapped
    required = {"date", "time", "type", "merchant", "amount", "account"}
    mapped = set(column_map.values())
    missing = required - mapped

    if missing:
        from finjuice.pipeline.validation.validators import ValidationError

        korean_hints: dict[str, str] = {}
        for field_name in schema.__dataclass_fields__.keys():
            if field_name != "version":
                name_field = getattr(schema, field_name)
                if isinstance(name_field, list) and name_field:
                    korean_hints[field_name] = name_field[0]

        missing_display = sorted(
            korean_hints.get(f, f) for f in missing if f in korean_hints or f not in korean_hints
        )
        raise ValidationError(f"필수 컬럼이 누락되었습니다: {', '.join(missing_display)}")

    # Rename columns (Polars)
    return df.rename(column_map)
