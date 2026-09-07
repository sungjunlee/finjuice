"""Snapshot-date resolution and balance snapshot row assembly.

Date resolution is shared across overview blocks. Balance snapshot assembly
(field mapping and missing-value policy) lives here so tests can pin the
contract without sheet I/O. Sheet walking stays in
:mod:`finjuice.pipeline.ingest.overview.balance`, which re-exports assembly
helpers so existing callers can keep importing from that module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .cells import (
    _cell_value,
    _is_summary_label,
    _iter_non_empty_cells,
    _normalize_cell_text,
    _parse_date_text,
    _parse_date_value,
)
from .constants import _SNAPSHOT_DATE_LABELS
from .models import _OverviewBlockParseContext

_BALANCE_SNAPSHOT_CURRENCY = "KRW"


@dataclass(frozen=True)
class _BalanceSnapshotFields:
    """Extracted balance-row fields before snapshot assembly."""

    side: str
    category: str | None
    item_name: str | None
    amount: float | None
    source_fact_id: str | None
    source_row: int


def _assemble_balance_snapshot_row(
    context: _OverviewBlockParseContext,
    fields: _BalanceSnapshotFields,
) -> dict[str, Any] | None:
    """Map extracted balance fields onto one snapshot row, or skip it.

    Missing-value policy: drop rows without an amount, a non-summary item name
    (item name falls back to category), or a source fact id. Transfer-like
    labels are not excluded at this layer. Currency is always KRW.
    """
    if fields.amount is None:
        return None

    item_name = fields.item_name or fields.category
    if not item_name or _is_summary_label(item_name):
        return None

    if fields.source_fact_id is None:
        return None

    return {
        "snapshot_date": context.snapshot_date,
        "side": fields.side,
        "category": fields.category,
        "item_name": item_name,
        "amount": fields.amount,
        "currency": _BALANCE_SNAPSHOT_CURRENCY,
        "source_fact_id": fields.source_fact_id,
        "file_id": context.file_id,
        "source_row": fields.source_row,
    }


def _resolve_snapshot_date(
    sheet: Any,
    file_path: Path,
    snapshot_date: str | None,
    file_mtime: str | None,
) -> str:
    explicit = _parse_date_value(snapshot_date)
    if explicit is not None:
        return explicit

    labeled_date = _find_labeled_snapshot_date(sheet)
    if labeled_date is not None:
        return labeled_date

    filename_date = _parse_filename_snapshot_date(file_path)
    if filename_date is not None:
        return filename_date

    mtime_date = _parse_date_value(file_mtime)
    if mtime_date is not None:
        return mtime_date

    return datetime.fromtimestamp(file_path.stat().st_mtime).date().isoformat()


def _parse_filename_snapshot_date(file_path: Path) -> str | None:
    return _parse_date_text(file_path.stem)


def _find_labeled_snapshot_date(sheet: Any) -> str | None:
    for row, col, value in _iter_non_empty_cells(sheet):
        if _normalize_cell_text(value) not in _SNAPSHOT_DATE_LABELS:
            continue

        parsed = _parse_labeled_date_nearby(sheet, row, col)
        if parsed is not None:
            return parsed

    return None


def _parse_labeled_date_nearby(sheet: Any, row: int, col: int) -> str | None:
    for candidate_col in range(col + 1, min(sheet.max_column, col + 3) + 1):
        parsed = _parse_date_value(_cell_value(sheet, row, candidate_col))
        if parsed is not None:
            return parsed

    return _parse_date_value(_cell_value(sheet, row + 1, col))
