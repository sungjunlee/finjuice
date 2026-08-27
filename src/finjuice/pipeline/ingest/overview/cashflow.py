"""Cashflow block parser for Banksalad overview sheets."""

from __future__ import annotations

from typing import Any

from .cells import (
    _cell_text,
    _cell_value,
    _iter_non_empty_cells,
    _normalize_cell_text,
    _parse_numeric_value,
    _parse_period_month,
)
from .constants import (
    _CASHFLOW_BLOCK_ID,
    _CASHFLOW_BLOCK_TITLE,
    _CASHFLOW_CATEGORY_HEADERS,
)
from .facts import _make_fact
from .models import (
    _Anchor,
    _CashflowFactContext,
    _FactBuildResult,
    _FactContext,
    _FactLabels,
    _OverviewBlockParseContext,
)
from .sections import _find_table_end_row, _is_cashflow_anchor


def _parse_cashflow_block(
    sheet: Any,
    block_context: _OverviewBlockParseContext,
    fact_ids: dict[tuple[int, int], str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    anchor = _find_cashflow_anchor(sheet)
    if anchor is None:
        return [], [], warnings

    header = _detect_cashflow_header(sheet, anchor.row)
    if header is None:
        fact_rows = _cashflow_facts_without_projection(
            sheet=sheet,
            block_context=block_context,
            anchor=anchor,
            fact_ids=fact_ids or {},
        )
        warnings.append(
            f"Cashflow projection skipped in {block_context.file_name}: "
            "month/category headers are ambiguous"
        )
        return [], fact_rows, warnings

    header_row, category_col, month_cols = header
    end_row = _find_table_end_row(sheet, header_row + 1, category_col, max(month_cols))
    fact_result = _cashflow_fact_result(
        _CashflowFactContext(
            sheet=sheet,
            fact_context=_FactContext(
                snapshot_date=block_context.snapshot_date,
                sheet_name=block_context.sheet_name,
                block_id=_CASHFLOW_BLOCK_ID,
                block_title=_CASHFLOW_BLOCK_TITLE,
                file_id=block_context.file_id,
            ),
            anchor_row=anchor.row,
            header_row=header_row,
            end_row=end_row,
            category_col=category_col,
            month_cols=month_cols,
        ),
        fact_ids=fact_ids or {},
    )

    rows: list[dict[str, Any]] = []
    for source_row in range(header_row + 1, end_row + 1):
        category = _cell_text(_cell_value(sheet, source_row, category_col))
        if not category:
            continue

        for source_col, period_month in month_cols.items():
            raw_value = _cell_value(sheet, source_row, source_col)
            if not _cell_text(raw_value):
                continue
            amount = _parse_numeric_value(raw_value)
            if amount is None:
                warnings.append(
                    f"Cashflow projection skipped in {block_context.file_name}: "
                    f"non-numeric value at row {source_row}, column {source_col}"
                )
                return [], fact_result.rows, warnings

            source_fact_id = fact_result.fact_ids.get((source_row, source_col))
            if source_fact_id is None:
                continue

            rows.append(
                {
                    "snapshot_date": block_context.snapshot_date,
                    "period_month": period_month,
                    "category": category,
                    "amount": amount,
                    "source_fact_id": source_fact_id,
                    "file_id": block_context.file_id,
                }
            )

    if not rows:
        warnings.append(
            f"Cashflow projection skipped in {block_context.file_name}: no numeric rows found"
        )

    return rows, fact_result.rows, warnings


def _cashflow_fact_result(
    context: _CashflowFactContext,
    fact_ids: dict[tuple[int, int], str],
) -> _FactBuildResult:
    has_projection_fact_ids = all(
        (row, col) in fact_ids
        for row in range(context.header_row + 1, context.end_row + 1)
        for col in context.month_cols
    )
    if has_projection_fact_ids:
        return _FactBuildResult(rows=[], fact_ids=fact_ids)

    return _build_cashflow_facts(context)


def _find_cashflow_anchor(sheet: Any) -> _Anchor | None:
    for row, col, value in _iter_non_empty_cells(sheet):
        if _is_cashflow_anchor(_normalize_cell_text(value)):
            return _Anchor(row=row, col=col, text=str(value).strip())
    return None


def _detect_cashflow_header(sheet: Any, anchor_row: int) -> tuple[int, int, dict[int, str]] | None:
    for row in range(anchor_row + 1, min(sheet.max_row, anchor_row + 7) + 1):
        category_col: int | None = None
        month_cols: dict[int, str] = {}

        for col in range(1, sheet.max_column + 1):
            value = _cell_value(sheet, row, col)
            normalized = _normalize_cell_text(value)
            if category_col is None and normalized in _CASHFLOW_CATEGORY_HEADERS:
                category_col = col

            period_month = _parse_period_month(value)
            if period_month is not None:
                month_cols[col] = period_month

        if (
            category_col is not None
            and month_cols
            and len(set(month_cols.values())) == len(month_cols)
        ):
            return row, category_col, month_cols

    return None


def _cashflow_facts_without_projection(
    sheet: Any,
    block_context: _OverviewBlockParseContext,
    anchor: _Anchor,
    fact_ids: dict[tuple[int, int], str],
) -> list[dict[str, Any]]:
    end_row = _find_table_end_row(sheet, anchor.row + 1, anchor.col, sheet.max_column)
    has_existing_fact_ids = any(
        (row, col) in fact_ids
        for row in range(anchor.row, end_row + 1)
        for col in range(1, sheet.max_column + 1)
    )
    if has_existing_fact_ids:
        return []

    fact_result = _build_cashflow_facts(
        _CashflowFactContext(
            sheet=sheet,
            fact_context=_FactContext(
                snapshot_date=block_context.snapshot_date,
                sheet_name=block_context.sheet_name,
                block_id=_CASHFLOW_BLOCK_ID,
                block_title=_CASHFLOW_BLOCK_TITLE,
                file_id=block_context.file_id,
            ),
            anchor_row=anchor.row,
            header_row=anchor.row,
            end_row=max(anchor.row, end_row),
            category_col=anchor.col,
            month_cols={},
        )
    )
    return fact_result.rows


def _build_cashflow_facts(context: _CashflowFactContext) -> _FactBuildResult:
    rows: list[dict[str, Any]] = []
    fact_ids: dict[tuple[int, int], str] = {}
    min_col = (
        min([context.category_col, *context.month_cols.keys()])
        if context.month_cols
        else context.category_col
    )
    max_col = (
        max([context.category_col, *context.month_cols.keys()])
        if context.month_cols
        else context.sheet.max_column
    )

    for source_row in range(context.anchor_row, context.end_row + 1):
        for source_col in range(min_col, max_col + 1):
            value = _cell_value(context.sheet, source_row, source_col)
            if not _cell_text(value):
                continue

            row_label = _cell_text(_cell_value(context.sheet, source_row, context.category_col))
            if source_row <= context.header_row:
                row_label = None

            column_label = context.month_cols.get(source_col) or _cell_text(
                _cell_value(context.sheet, context.header_row, source_col)
            )
            fact_kind = "section_label" if source_row == context.anchor_row else "table_value"
            if source_row == context.header_row:
                fact_kind = "cell"

            fact = _make_fact(
                context=context.fact_context,
                labels=_FactLabels(
                    fact_kind=fact_kind,
                    row_label=row_label,
                    column_label=column_label,
                ),
                value=value,
                source_row=source_row,
                source_col=source_col,
            )
            rows.append(fact)
            fact_ids[(source_row, source_col)] = str(fact["fact_id"])

    return _FactBuildResult(rows=rows, fact_ids=fact_ids)
