"""Shared cell, text, number, and date helpers for overview parsers."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from ..schemas import normalize_sheet_name
from .constants import _SUMMARY_LABELS


def _header_map_for_row(sheet: Any, row: int, start_col: int, end_col: int) -> dict[int, str]:
    headers: dict[int, str] = {}
    for col in range(start_col, end_col + 1):
        normalized = _normalize_cell_text(_cell_value(sheet, row, col))
        if normalized:
            headers[col] = normalized
    return headers


def _first_header_col(header_map: dict[int, str], candidates: set[str]) -> int | None:
    for col, header in header_map.items():
        if header in candidates:
            return col
    return None


def _normalized_header_map(sheet: Any, row: int) -> dict[int, str]:
    return {
        col: normalized
        for col in range(1, sheet.max_column + 1)
        if (normalized := _normalize_cell_text(_cell_value(sheet, row, col)))
    }


def _text_at(sheet: Any, source_row: int, source_col: int | None) -> str | None:
    return _cell_text(_cell_value(sheet, source_row, source_col))


def _number_at(sheet: Any, source_row: int, source_col: int | None) -> float | None:
    return _parse_numeric_value(_cell_value(sheet, source_row, source_col))


def _date_at(sheet: Any, source_row: int, source_col: int | None) -> str | None:
    return _parse_date_value(_cell_value(sheet, source_row, source_col))


def _iter_non_empty_cells(sheet: Any) -> list[tuple[int, int, Any]]:
    cells: list[tuple[int, int, Any]] = []
    for row in sheet.iter_rows():
        for cell in row:
            if _cell_text(cell.value):
                cells.append((int(cell.row), int(cell.column), cell.value))
    return cells


def _cell_value(sheet: Any, row: int, col: int | None) -> Any:
    if col is None:
        return None
    return sheet.cell(row=row, column=col).value


def _cell_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
    elif isinstance(value, (date, datetime)):
        text = _format_date_value(value)
    else:
        text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none", "null"}:
        return None
    return text


def _normalize_cell_text(value: Any) -> str:
    text = _cell_text(value)
    if text is None:
        return ""
    return normalize_sheet_name(text)


def _parse_numeric_value(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, (date, datetime)):
        return None

    text = str(value).strip()
    if not text:
        return None

    multiplier = 1.0
    if "만원" in text:
        multiplier = 10_000.0
    cleaned = (
        text.replace(",", "")
        .replace("₩", "")
        .replace("KRW", "")
        .replace("krw", "")
        .replace("만원", "")
        .replace("원", "")
        .strip()
    )
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = f"-{cleaned[1:-1]}"
    if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", cleaned):
        return None

    return float(cleaned) * multiplier


def _parse_date_value(value: Any) -> str | None:
    parsed_date: str | None = None
    if value is None:
        pass
    elif isinstance(value, datetime):
        parsed_date = value.date().isoformat()
    elif isinstance(value, date):
        parsed_date = value.isoformat()
    else:
        parsed_date = _parse_date_text(str(value).strip())

    return parsed_date


def _parse_date_text(text: str) -> str | None:
    if not text:
        return None
    normalized = text.split("T", maxsplit=1)[0] if "T" in text else text
    matches = _date_text_matches(normalized)
    if not matches:
        return None
    return _safe_iso_date(*matches[-1])


def _date_text_matches(text: str) -> list[tuple[int, int, int]]:
    matches = [
        (int(year), int(month), int(day))
        for year, month, day in re.findall(r"(\d{4})[./-]\s*(\d{1,2})[./-]\s*(\d{1,2})", text)
    ]
    matches.extend(
        (int(year), int(month), int(day))
        for year, month, day in re.findall(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일", text)
    )
    return matches


def _safe_iso_date(year: int, month: int, day: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _parse_period_month(value: Any) -> str | None:
    period_month: str | None = None
    if value is None:
        pass
    elif isinstance(value, (date, datetime)):
        period_month = f"{value.year:04d}-{value.month:02d}"
    else:
        period_month = _parse_period_month_text(str(value).strip())

    return period_month


def _parse_period_month_text(text: str) -> str | None:
    if not text:
        return None

    match = re.fullmatch(r"(\d{4})\s*년\s*(\d{1,2})\s*월", text)
    match = match or re.fullmatch(r"(\d{4})[./-](\d{1,2})", text)
    if match is None:
        return None

    return _format_period_month(int(match.group(1)), int(match.group(2)))


def _format_period_month(year: int, month: int) -> str | None:
    if not 1 <= month <= 12:
        return None
    return f"{year:04d}-{month:02d}"


def _format_date_value(value: date | datetime) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return value.isoformat()


def _is_summary_label(label: str) -> bool:
    return normalize_sheet_name(label) in _SUMMARY_LABELS
