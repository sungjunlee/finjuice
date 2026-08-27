"""Shared structured-table detection for insurance, investment, and loan blocks."""

from __future__ import annotations

from typing import Any

from .cells import (
    _cell_text,
    _cell_value,
    _first_header_col,
    _is_summary_label,
    _normalized_header_map,
)
from .constants import _INSURANCE_BLOCK_ID
from .models import _SectionRange, _StructuredTableSpec
from .sections import _section_by_block_id


def _detect_structured_table(
    sheet: Any,
    sections: list[_SectionRange],
    block_id: str,
    header_candidates: dict[str, set[str]],
) -> _StructuredTableSpec | None:
    section = _section_by_block_id(sections, block_id)
    if section is None:
        return None

    for row in range(section.anchor_row + 1, min(section.end_row, section.anchor_row + 8) + 1):
        normalized_headers = _normalized_header_map(sheet, row)
        columns: dict[str, int] = {}
        for output_name, candidates in header_candidates.items():
            col = _first_header_col(normalized_headers, candidates)
            if col is not None:
                columns[output_name] = col

        if _has_required_structured_columns(block_id, columns):
            return _StructuredTableSpec(section=section, header_row=row, columns=columns)

    return None


def _has_required_structured_columns(block_id: str, columns: dict[str, int]) -> bool:
    if block_id == _INSURANCE_BLOCK_ID:
        return {"institution", "policy_name"} <= columns.keys()
    return {"institution", "product_name"} <= columns.keys()


def _table_data_rows(sheet: Any, table: _StructuredTableSpec) -> list[int]:
    rows: list[int] = []
    first_data_row = table.header_row + 1
    for source_row in range(first_data_row, table.section.end_row + 1):
        values = [
            _cell_value(sheet, source_row, source_col)
            for source_col in sorted(set(table.columns.values()))
        ]
        if not any(_cell_text(value) for value in values):
            continue
        if _is_summary_row(values):
            continue
        rows.append(source_row)
    return rows


def _has_entity_identity(institution: str | None, name: str | None) -> bool:
    if not institution or not name:
        return False
    return not _is_summary_label(institution) and not _is_summary_label(name)


def _is_summary_row(values: list[Any]) -> bool:
    return any(_is_summary_label(text) for value in values if (text := _cell_text(value)))
