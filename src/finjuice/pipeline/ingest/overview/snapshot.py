"""Snapshot-date resolution for Banksalad overview worksheets."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .cells import (
    _cell_value,
    _iter_non_empty_cells,
    _normalize_cell_text,
    _parse_date_text,
    _parse_date_value,
)
from .constants import _SNAPSHOT_DATE_LABELS


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
