"""
Column Schema Mapping for Banksalad XLSX exports (Polars-only).

Handles auto-detection of schema versions and mapping of Korean/English column names
to standardized internal field names.
"""

from dataclasses import dataclass
from typing import Final, List

import polars as pl


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

ASSET_SHEET_NAME_CANDIDATES = ("자산", "보유종목", "assets", "holdings")


@dataclass
class AssetColumnSchema:
    """Schema definition for Banksalad asset snapshot sheet."""

    version: str
    snapshot_date: List[str]
    account_id: List[str]
    account_name: List[str]
    instrument_id: List[str]
    instrument_name: List[str]
    quantity: List[str]
    market_value: List[str]
    currency: List[str]


ASSET_SCHEMAS = {
    "snapshot_v0": AssetColumnSchema(
        version="snapshot_v0",
        snapshot_date=["기준일", "평가일", "날짜", "snapshot_date", "date"],
        account_id=["account_id", "계좌ID", "계좌id", "계좌번호"],
        account_name=["계좌", "계좌명", "account", "account_name", "결제수단"],
        instrument_id=["instrument_id", "종목ID", "종목id", "티커", "ticker", "symbol", "종목코드"],
        instrument_name=[
            "종목",
            "종목명",
            "자산명",
            "상품명",
            "instrument",
            "instrument_name",
            "name",
        ],
        quantity=["수량", "보유수량", "보유량", "잔고수량", "quantity", "qty"],
        market_value=[
            "평가금액",
            "평가액",
            "평가 금액",
            "자산가치",
            "market_value",
            "value",
            "valuation",
        ],
        currency=["화폐", "통화", "currency"],
    ),
}

ASSET_SHEET_NAME_NORMALIZED = {
    "".join(ch for ch in name.strip().lower() if ch not in {" ", "_", "-"})
    for name in ASSET_SHEET_NAME_CANDIDATES
}


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


def normalize_sheet_name(sheet_name: str) -> str:
    """
    Normalize sheet name for case/space-insensitive matching.

    Args:
        sheet_name: Raw sheet name

    Returns:
        Normalized sheet name
    """
    return "".join(ch for ch in sheet_name.strip().lower() if ch not in {" ", "_", "-"})


def is_asset_sheet_name(sheet_name: str) -> bool:
    """
    Check if a sheet name is an asset snapshot candidate.

    Args:
        sheet_name: Raw sheet name

    Returns:
        True if sheet likely contains asset snapshots
    """
    return normalize_sheet_name(sheet_name) in ASSET_SHEET_NAME_NORMALIZED


def detect_asset_schema_version(df_columns: List[str]) -> AssetColumnSchema:
    """
    Auto-detect asset schema version from dataframe columns.

    Args:
        df_columns: List of column names from the DataFrame

    Returns:
        Detected asset schema definition
    """
    for schema in ASSET_SCHEMAS.values():
        account_ok = any(col in df_columns for col in (schema.account_id + schema.account_name))
        instrument_ok = any(
            col in df_columns for col in (schema.instrument_id + schema.instrument_name)
        )
        quantity_ok = any(col in df_columns for col in schema.quantity)
        market_value_ok = any(col in df_columns for col in schema.market_value)
        if account_ok and instrument_ok and quantity_ok and market_value_ok:
            return schema

    return ASSET_SCHEMAS["snapshot_v0"]


def map_asset_columns(df: pl.DataFrame) -> pl.DataFrame:
    """
    Map asset snapshot columns to canonical names.

    Required mapped groups:
    - account identifier/name: account_id or account_name
    - instrument identifier/name: instrument_id or instrument_name
    - quantity
    - market_value

    Optional:
    - snapshot_date (falls back to file mtime in ingest pipeline)
    - currency (defaults to KRW)

    Args:
        df: Asset snapshot DataFrame

    Returns:
        DataFrame with canonical asset column names

    Raises:
        ValueError: If required columns are missing
    """
    columns = list(df.columns)
    schema = detect_asset_schema_version(columns)
    column_map: dict[str, str] = {}

    for field_name in schema.__dataclass_fields__.keys():
        if field_name == "version":
            continue

        variants = getattr(schema, field_name)
        for variant in variants:
            if variant in columns:
                column_map[variant] = field_name
                break

    mapped = set(column_map.values())
    missing: list[str] = []

    if not ({"account_id", "account_name"} & mapped):
        missing.append("account_id/account_name")
    if not ({"instrument_id", "instrument_name"} & mapped):
        missing.append("instrument_id/instrument_name")
    if "quantity" not in mapped:
        missing.append("quantity")
    if "market_value" not in mapped:
        missing.append("market_value")

    if missing:
        raise ValueError(f"Required asset columns not found: {', '.join(missing)}")

    mapped_df = df.rename(column_map)
    optional_defaults = {
        "snapshot_date": None,
        "currency": "KRW",
    }

    for col_name, default_value in optional_defaults.items():
        if col_name not in mapped_df.columns:
            mapped_df = mapped_df.with_columns(pl.lit(default_value).alias(col_name))

    return mapped_df
