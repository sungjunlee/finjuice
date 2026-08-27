"""Numbered overview section detection and generic section facts."""

from __future__ import annotations

from typing import Any

from ..schemas import normalize_sheet_name
from .cells import _cell_text, _cell_value, _iter_non_empty_cells, _normalize_cell_text
from .constants import (
    _AMOUNT_HEADERS,
    _CASHFLOW_ANCHORS,
    _CATEGORY_HEADERS,
    _ITEM_HEADERS,
    _NUMBERED_SECTION_RE,
    _ROW_BREAK_ANCHORS,
    _SECTION_BLOCKS,
    _SECTION_NUMBER_PREFIX_RE,
)
from .facts import _make_fact
from .models import _FactBuildResult, _FactContext, _FactLabels, _SectionRange


def _find_numbered_sections(sheet: Any) -> list[_SectionRange]:
    anchors: list[tuple[int, int, str, str]] = []
    for row, col, value in _iter_non_empty_cells(sheet):
        title = _numbered_section_title(value)
        if title is None:
            continue
        section = _SECTION_BLOCKS.get(normalize_sheet_name(title))
        if section is None:
            continue
        block_id, block_title = section
        anchors.append((row, col, block_id, block_title))

    sections: list[_SectionRange] = []
    for idx, (row, col, block_id, block_title) in enumerate(anchors):
        end_row = anchors[idx + 1][0] - 1 if idx + 1 < len(anchors) else sheet.max_row
        sections.append(
            _SectionRange(
                block_id=block_id,
                block_title=block_title,
                anchor_row=row,
                anchor_col=col,
                end_row=end_row,
            )
        )
    return sections


def _numbered_section_title(value: Any) -> str | None:
    text = _cell_text(value)
    if text is None:
        return None
    match = _NUMBERED_SECTION_RE.match(text)
    if match is None:
        return None
    return match.group(1).strip()


def _build_section_facts(
    sheet: Any,
    sheet_name: str,
    snapshot_date: str,
    file_id: str,
    sections: list[_SectionRange],
) -> _FactBuildResult:
    rows: list[dict[str, Any]] = []
    fact_ids: dict[tuple[int, int], str] = {}

    for section in sections:
        header_row = _detect_section_header_row(sheet, section)
        context = _FactContext(
            snapshot_date=snapshot_date,
            sheet_name=sheet_name,
            block_id=section.block_id,
            block_title=section.block_title,
            file_id=file_id,
        )
        for source_row in range(section.anchor_row, section.end_row + 1):
            row_label = _section_row_label(sheet, section, source_row, header_row)
            for source_col in range(1, sheet.max_column + 1):
                value = _cell_value(sheet, source_row, source_col)
                if not _cell_text(value):
                    continue

                fact = _make_fact(
                    context=context,
                    labels=_FactLabels(
                        fact_kind=_section_fact_kind(section, source_row, header_row),
                        row_label=row_label,
                        column_label=_section_column_label(sheet, source_col, header_row),
                    ),
                    value=value,
                    source_row=source_row,
                    source_col=source_col,
                )
                rows.append(fact)
                fact_ids[(source_row, source_col)] = str(fact["fact_id"])

    return _FactBuildResult(rows=rows, fact_ids=fact_ids)


def _detect_section_header_row(sheet: Any, section: _SectionRange) -> int | None:
    for row in range(section.anchor_row + 1, min(section.end_row, section.anchor_row + 6) + 1):
        labels = [
            _normalize_cell_text(_cell_value(sheet, row, col))
            for col in range(1, sheet.max_column + 1)
        ]
        populated = [label for label in labels if label]
        if len(populated) >= 2 and any(
            label in _CATEGORY_HEADERS | _ITEM_HEADERS | _AMOUNT_HEADERS
            or label
            in {
                normalize_sheet_name(value)
                for value in (
                    "이름",
                    "성별",
                    "금융사",
                    "보험명",
                    "투자상품종류",
                    "대출종류",
                    "대출잔액",
                    "대출금리",
                )
            }
            for label in populated
        ):
            return row
    return None


def _section_fact_kind(
    section: _SectionRange,
    source_row: int,
    header_row: int | None,
) -> str:
    if source_row == section.anchor_row:
        return "section_label"
    if header_row is not None and source_row == header_row:
        return "cell"
    return "table_value"


def _section_row_label(
    sheet: Any,
    section: _SectionRange,
    source_row: int,
    header_row: int | None,
) -> str | None:
    if source_row == section.anchor_row or (header_row is not None and source_row <= header_row):
        return None
    for col in range(1, sheet.max_column + 1):
        text = _cell_text(_cell_value(sheet, source_row, col))
        if text:
            return text
    return None


def _section_column_label(sheet: Any, source_col: int, header_row: int | None) -> str | None:
    if header_row is None:
        return None
    return _cell_text(_cell_value(sheet, header_row, source_col))


def _is_cashflow_anchor(normalized: str) -> bool:
    return _matches_numbered_anchor(normalized, _CASHFLOW_ANCHORS)


def _is_row_break_anchor(normalized: str) -> bool:
    return _matches_numbered_anchor(normalized, _ROW_BREAK_ANCHORS)


def _matches_numbered_anchor(normalized: str, anchors: set[str]) -> bool:
    if normalized in anchors:
        return True
    return _SECTION_NUMBER_PREFIX_RE.sub("", normalized) in anchors


def _find_table_end_row(sheet: Any, start_row: int, start_col: int, end_col: int) -> int:
    end_row = start_row - 1
    blank_streak = 0

    for row in range(start_row, sheet.max_row + 1):
        row_values = [_cell_value(sheet, row, col) for col in range(start_col, end_col + 1)]
        if any(_is_row_break_anchor(_normalize_cell_text(value)) for value in row_values):
            break

        if any(_cell_text(value) for value in row_values):
            end_row = row
            blank_streak = 0
            continue

        blank_streak += 1
        if blank_streak >= 2 and end_row >= start_row:
            break

    return end_row


def _section_by_block_id(
    sections: list[_SectionRange],
    block_id: str,
) -> _SectionRange | None:
    for section in sections:
        if section.block_id == block_id:
            return section
    return None
