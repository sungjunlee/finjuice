"""
Asset snapshot processing for the ingest pipeline.

Handles reading asset snapshot sheets from Banksalad XLSX files and building
canonical asset snapshot DataFrames with derived IDs and deduplication.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, List, Tuple

import polars as pl

from ..constants import ASSET_ACCOUNT_ID_PREFIX, ASSET_INSTRUMENT_ID_PREFIX
from ..storage import csv_partition
from ._helpers import (
    _build_derived_asset_id,
    _empty_asset_snapshot_dataframe,
    _find_asset_sheet_name,
    _has_value,
    _parse_snapshot_date,
    _parse_snapshot_float,
)
from .schemas import map_asset_columns

logger = logging.getLogger(__name__)


def _build_asset_snapshot_dataframe(
    file_path: Path,
    file_id: str,
    file_mtime: str,
) -> tuple[pl.DataFrame, list[str]]:
    """Build a best-effort asset snapshot DataFrame without writing it."""
    warnings: List[str] = []

    sheet_name = _find_asset_sheet_name(file_path)
    if sheet_name is None:
        warnings.append(f"Asset snapshot sheet not found in {file_path.name}; skipped")
        return _empty_asset_snapshot_dataframe(), warnings

    try:
        raw_df = pl.read_excel(
            file_path,
            sheet_name=sheet_name,
            engine="openpyxl",
            raise_if_empty=False,
        )
    except (OSError, pl.exceptions.PolarsError) as exc:
        warnings.append(f"Failed to read asset sheet '{sheet_name}' in {file_path.name}: {exc}")
        return _empty_asset_snapshot_dataframe(), warnings

    if raw_df.height == 0 or len(raw_df.columns) == 0:
        warnings.append(f"Asset sheet '{sheet_name}' is empty in {file_path.name}; skipped")
        return _empty_asset_snapshot_dataframe(), warnings

    try:
        df = map_asset_columns(raw_df)
    except ValueError as exc:
        warnings.append(f"Asset sheet mapping failed for {file_path.name}: {exc}")
        return _empty_asset_snapshot_dataframe(), warnings

    fallback_date = datetime.fromisoformat(file_mtime).date().isoformat()
    rows: list[dict[str, Any]] = []

    for idx, row in enumerate(df.iter_rows(named=True), start=2):
        try:
            raw_account_id = row.get("account_id")
            raw_account_name = row.get("account_name")
            raw_instrument_id = row.get("instrument_id")
            raw_instrument_name = row.get("instrument_name")

            account_source = raw_account_id if _has_value(raw_account_id) else raw_account_name
            instrument_source = (
                raw_instrument_id if _has_value(raw_instrument_id) else raw_instrument_name
            )

            if not _has_value(account_source):
                raise ValueError("account_id/account_name is missing")
            if not _has_value(instrument_source):
                raise ValueError("instrument_id/instrument_name is missing")

            account_id = (
                str(raw_account_id).strip()
                if _has_value(raw_account_id)
                else _build_derived_asset_id(ASSET_ACCOUNT_ID_PREFIX, account_source)
            )
            instrument_id = (
                str(raw_instrument_id).strip()
                if _has_value(raw_instrument_id)
                else _build_derived_asset_id(ASSET_INSTRUMENT_ID_PREFIX, instrument_source)
            )
            snapshot_date = _parse_snapshot_date(row.get("snapshot_date"), fallback_date)
            quantity = _parse_snapshot_float(row.get("quantity"), "quantity")
            market_value = _parse_snapshot_float(row.get("market_value"), "market_value")
            currency = str(row.get("currency") or "KRW").strip() or "KRW"

            rows.append(
                {
                    "snapshot_date": snapshot_date,
                    "account_id": account_id,
                    "instrument_id": instrument_id,
                    "quantity": quantity,
                    "market_value": market_value,
                    "currency": currency,
                    "file_id": file_id,
                    "source_row": idx,
                }
            )
        except ValueError as exc:
            warnings.append(f"Skipping asset row {idx} in {file_path.name}: {exc}")
            continue

    if not rows:
        warnings.append(f"No valid asset snapshot rows found in {file_path.name}")
        return _empty_asset_snapshot_dataframe(), warnings

    return pl.DataFrame(rows, schema=csv_partition.ASSET_SNAPSHOT_POLARS_SCHEMA), warnings


def ingest_asset_snapshots(
    file_path: Path,
    csv_base_dir: Path,
    file_id: str,
    file_mtime: str,
) -> Tuple[int, int, List[str]]:
    """
    Best-effort asset snapshot ingest from a single XLSX file.

    This function never raises for expected sheet/column mismatch cases.
    It returns warning messages and allows transaction ingest to continue.

    Args:
        file_path: Source XLSX file path
        csv_base_dir: Transaction CSV base dir (used to locate data root)
        file_id: Recorded file_id from import history
        file_mtime: Source file mtime in ISO format

    Returns:
        Tuple of (inserted_count, skipped_count, warnings)
    """
    snapshot_df, warnings = _build_asset_snapshot_dataframe(
        file_path=file_path,
        file_id=file_id,
        file_mtime=file_mtime,
    )
    if snapshot_df.height == 0:
        return 0, 0, warnings

    asset_base_dir = csv_base_dir.parent / "assets" / "snapshots"
    result = csv_partition.append_asset_snapshots(asset_base_dir, snapshot_df, deduplicate=True)
    return int(result["rows_inserted"]), int(result["rows_skipped"]), warnings
