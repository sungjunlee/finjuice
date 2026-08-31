"""Transaction schema catalog and version detection for Banksalad ingest.

Owns ColumnSchema, known Banksalad versions, required Korean column names,
and header matching. Column renaming stays in
:mod:`finjuice.pipeline.ingest.schemas`, which re-exports these names so
existing callers can keep importing from that module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, List


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
