"""
Transaction loading and DataFrame building.

Handles reading Banksalad XLSX sheets, mapping columns, and building canonical
transaction DataFrames with row hashes and normalized fields.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl

from ..storage.csv_schema import POLARS_SCHEMA
from ._helpers import _empty_transactions_dataframe, _read_excel_sheet
from ._normalize import _normalize_amount, _normalize_type
from .deduplication import calculate_row_hash
from .schemas import map_columns

logger = logging.getLogger(__name__)


def _load_transaction_source(file_path: Path) -> tuple[pl.DataFrame, int, str]:
    """
    Load the transaction worksheet from a Banksalad XLSX export.

    Returns:
        Tuple of (mapped_dataframe, source_row_count, file_mtime_iso)
    """
    logger.info("Ingesting source workbook (Polars backend)")

    try:
        df = _read_excel_sheet(file_path, sheet_id=2)
        logger.debug(f"Read from sheet 2 (가계부 내역): {len(df)} rows")
    except Exception:
        df = _read_excel_sheet(file_path, sheet_id=1)
        logger.debug(f"Read from sheet 1: {len(df)} rows")

    logger.info("Read %s rows from source workbook", len(df))

    file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime).isoformat()

    if len(df) == 0 or len(df.columns) == 0:
        logger.info("Empty source workbook (0 rows)")
        return _empty_transactions_dataframe(), 0, file_mtime

    mapped_df = map_columns(df)
    return mapped_df, len(mapped_df), file_mtime


def _build_transaction_dataframe(
    file_path: Path, df: pl.DataFrame, file_id: str
) -> tuple[pl.DataFrame, list[str]]:
    """Convert mapped transaction rows into the canonical transaction DataFrame."""
    if df.height == 0:
        return _empty_transactions_dataframe(), []

    transactions: list[dict[str, Any]] = []
    skipped_rows: list[str] = []

    for idx, row_dict in enumerate(df.iter_rows(named=True), start=2):
        try:
            row_hash = calculate_row_hash(row_dict)

            date_val = row_dict["date"]
            if hasattr(date_val, "date"):
                date_str = date_val.date().isoformat()
            else:
                date_str = str(date_val)

            time_raw = row_dict.get("time")
            time_str = str(time_raw or "00:00")
            if time_str.lower() in {"nat", "nan", "none", "null"}:
                time_str = "00:00"
            if time_str.count(":") >= 2:
                time_str = ":".join(time_str.split(":")[:2])
            if ":" not in time_str:
                time_str = "00:00"

            datetime_str = f"{date_str}T{time_str}:00"
            type_norm = _normalize_type(row_dict["type"])
            amount = _normalize_amount(row_dict["amount"], row_dict["type"], row_idx=idx)

            transactions.append(
                {
                    "row_hash": row_hash,
                    "date": date_str,
                    "time": time_str,
                    "type_raw": row_dict["type"],
                    "type_norm": type_norm,
                    "major_raw": row_dict.get("major_category", ""),
                    "minor_raw": row_dict.get("minor_category", ""),
                    "merchant_raw": row_dict["merchant"],
                    "memo_raw": row_dict.get("memo", ""),
                    "notes_manual": "",
                    "amount": amount,
                    "currency": row_dict.get("currency", "KRW"),
                    "account": row_dict["account"],
                    "datetime": datetime_str,
                    "tags_rule": "[]",
                    "tags_ai": "[]",
                    "tags_manual": "[]",
                    "tags_final": "[]",
                    "confidence": None,
                    "needs_review": None,
                    "is_transfer": None,
                    "transfer_group_id": None,
                    "counterparty": None,
                    "file_id": file_id,
                    "source_row": idx,
                }
            )
        except ValueError as e:
            logger.warning("Skipping row %s in source workbook (%s)", idx, type(e).__name__)
            skipped_rows.append(f"Row {idx}: {e}")
            continue

    return pl.DataFrame(transactions, schema=POLARS_SCHEMA), skipped_rows
