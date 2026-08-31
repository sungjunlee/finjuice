"""Asset snapshot column mapping for Banksalad ingest schemas.

Owns asset schema versions, required-field matching, and canonical column
renames. Transaction column mapping stays in
:mod:`finjuice.pipeline.ingest.schemas`, which re-exports these names so
existing callers can keep importing from that module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import polars as pl


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


def _missing_required_asset_fields(mapped: set[str]) -> list[str]:
    """Return required asset field labels that were not mapped."""
    missing: list[str] = []
    if not ({"account_id", "account_name"} & mapped):
        missing.append("account_id/account_name")
    if not ({"instrument_id", "instrument_name"} & mapped):
        missing.append("instrument_id/instrument_name")
    if "quantity" not in mapped:
        missing.append("quantity")
    if "market_value" not in mapped:
        missing.append("market_value")
    return missing


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

    missing = _missing_required_asset_fields(set(column_map.values()))
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
