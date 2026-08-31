"""
Column Schema Mapping for Banksalad XLSX exports (Polars-only).

Handles auto-detection of schema versions and mapping of Korean/English column names
to standardized internal field names.

Sheet-name matching helpers live in
:mod:`finjuice.pipeline.ingest.schemas_helpers`. Asset snapshot column
mapping lives in :mod:`finjuice.pipeline.ingest.schemas_assets`. Both
clusters are re-exported here so existing callers can keep importing
from this module.
"""

from dataclasses import dataclass
from typing import Final, List

import polars as pl

from finjuice.pipeline.ingest.schemas_assets import (
    ASSET_SCHEMAS,  # noqa: F401 — re-exported for existing schemas imports
    AssetColumnSchema,  # noqa: F401 — re-exported for existing schemas imports
    detect_asset_schema_version,  # noqa: F401 — re-exported for existing schemas imports
    map_asset_columns,  # noqa: F401 — re-exported for existing schemas imports
)
from finjuice.pipeline.ingest.schemas_helpers import (
    ASSET_SHEET_NAME_CANDIDATES,  # noqa: F401 — re-exported for existing schemas imports
    ASSET_SHEET_NAME_NORMALIZED,  # noqa: F401 — re-exported for existing schemas imports
    is_asset_sheet_name,  # noqa: F401 — re-exported for existing schemas imports
    normalize_sheet_name,  # noqa: F401 — re-exported for existing schemas imports
)


@dataclass
class ColumnSchema:
    """Schema definition for Banksalad export format."""

    version: str
    date: List[str]
    time: List[str]
    type: List[str]
    major_category: List[str]
    minor_category: List[str]
    merchant: List[str]
    memo: List[str]
    amount: List[str]
    currency: List[str]
    account: List[str]


# Known schema versions
BANKSALAD_SCHEMAS = {
    "v1_2024": ColumnSchema(
        version="v1_2024",
        date=["날짜", "거래일", "Date", "date"],
        time=["시간", "Time", "time", "거래시간"],
        type=["타입", "유형", "Type", "type", "구분"],
        major_category=["대분류", "카테고리(대)", "Major Category", "major_category"],
        minor_category=["중분류", "카테고리(소)", "Minor Category", "minor_category"],
        merchant=["내용", "거래처", "상호", "Merchant", "merchant", "가맹점"],
        memo=["메모", "Memo", "memo", "적요"],
        amount=["금액", "Amount", "amount", "거래금액"],
        currency=["화폐", "Currency", "currency"],
        account=["결제수단", "계좌/카드", "Account", "account"],
    ),
}

#: Canonical Korean column names required in a Banksalad v1_2024 export.
#: Single source of truth shared by ingest (column mapping) and validation
#: (pre-ingest required-column check). Kept here so a schema rename in
#: ``BANKSALAD_SCHEMAS`` cannot silently diverge from validator expectations.
REQUIRED_KOREAN_COLUMNS: Final[frozenset[str]] = frozenset(
    {"날짜", "시간", "타입", "금액", "결제수단"}
)


def detect_schema_version(df_columns: List[str]) -> ColumnSchema:
    """
    Auto-detect which schema version matches the dataframe columns.

    Args:
        df_columns: List of column names from the DataFrame

    Returns:
        ColumnSchema: Detected schema (or v1_2024 as fallback)
    """
    for schema in BANKSALAD_SCHEMAS.values():
        if _matches_schema(df_columns, schema):
            return schema

    # Fallback: use v1_2024 with lenient matching
    return BANKSALAD_SCHEMAS["v1_2024"]


def _matches_schema(df_columns: List[str], schema: ColumnSchema) -> bool:
    """
    Check if dataframe columns match a given schema.

    A schema matches if all required fields (date, amount, account) can be found
    in the dataframe columns.

    Args:
        df_columns: List of column names from the DataFrame
        schema: Schema to check against

    Returns:
        bool: True if schema matches, False otherwise
    """
    required_fields = ["date", "amount", "account"]
    matched_count = sum(
        1 for field in required_fields if any(col in df_columns for col in getattr(schema, field))
    )
    return matched_count >= len(required_fields)


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
