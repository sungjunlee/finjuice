"""Balance (asset/liability) block parser for Banksalad overview sheets.

Snapshot/fact assembly lives here. Anchor and table discovery lives in
:mod:`finjuice.pipeline.ingest.overview.balance_table`. Snapshot row assembly
(field mapping and missing-value policy) lives in
:mod:`finjuice.pipeline.ingest.overview.snapshot`. Both are re-exported so
existing callers can keep importing from this module.
"""

from __future__ import annotations

from typing import Any

from .balance_table import (
    _balance_anchor_pairs,  # noqa: F401 — re-exported for existing balance imports
    _collect_balance_anchors,
    _detect_side_spec,  # noqa: F401 — re-exported for existing balance imports
    _find_balance_anchor_pair,  # noqa: F401 — re-exported for existing balance imports
    _find_balance_table,
)
from .cells import (
    _cell_text,
    _cell_value,
    _normalize_cell_text,
    _parse_numeric_value,
)
from .constants import (
    _BALANCE_BLOCK_ID,
    _BALANCE_BLOCK_TITLE,
)
from .facts import _make_fact
from .models import (
    _BalanceFactContext,
    _FactBuildResult,
    _FactContext,
    _FactLabels,
    _OverviewBlockParseContext,
    _SideSpec,
)
from .sections import _is_row_break_anchor
from .snapshot import (
    _assemble_balance_snapshot_row,
    _BalanceSnapshotFields,
)


def _parse_balance_block(
    sheet: Any,
    block_context: _OverviewBlockParseContext,
    fact_ids: dict[tuple[int, int], str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    asset_anchors, liability_anchors = _collect_balance_anchors(sheet)
    balance_table = _find_balance_table(sheet, asset_anchors, liability_anchors)
    if balance_table is None:
        warnings.append(
            f"Balance block not found in overview sheet '{block_context.sheet_name}'; skipped"
        )
        return [], [], warnings

    asset_anchor, liability_anchor, asset_spec, liability_spec = balance_table

    end_row = _find_balance_end_row(
        sheet,
        min(asset_spec.header_row, liability_spec.header_row) + 1,
    )
    fact_result = _balance_fact_result(
        _BalanceFactContext(
            sheet=sheet,
            fact_context=_FactContext(
                snapshot_date=block_context.snapshot_date,
                sheet_name=block_context.sheet_name,
                block_id=_BALANCE_BLOCK_ID,
                block_title=_BALANCE_BLOCK_TITLE,
                file_id=block_context.file_id,
            ),
            start_row=asset_anchor.row,
            end_row=end_row,
            side_specs=(asset_spec, liability_spec),
        ),
        fact_ids=fact_ids or {},
    )
    rows: list[dict[str, Any]] = []
    for spec in (asset_spec, liability_spec):
        for source_row in range(spec.header_row + 1, end_row + 1):
            row = _assemble_balance_snapshot_row(
                block_context,
                _read_balance_snapshot_fields(
                    sheet,
                    spec,
                    source_row,
                    fact_result.fact_ids,
                ),
            )
            if row is not None:
                rows.append(row)

    return rows, fact_result.rows, warnings


def _read_balance_snapshot_fields(
    sheet: Any,
    spec: _SideSpec,
    source_row: int,
    fact_ids: dict[tuple[int, int], str],
) -> _BalanceSnapshotFields:
    return _BalanceSnapshotFields(
        side=spec.side,
        category=_cell_text(_cell_value(sheet, source_row, spec.category_col)),
        item_name=_cell_text(_cell_value(sheet, source_row, spec.item_col)),
        amount=_parse_numeric_value(_cell_value(sheet, source_row, spec.amount_col)),
        source_fact_id=fact_ids.get((source_row, spec.amount_col)),
        source_row=source_row,
    )


def _balance_fact_result(
    context: _BalanceFactContext,
    fact_ids: dict[tuple[int, int], str],
) -> _FactBuildResult:
    has_projection_fact_ids = all(
        (row, spec.amount_col) in fact_ids
        for spec in context.side_specs
        for row in range(spec.header_row + 1, context.end_row + 1)
    )
    if has_projection_fact_ids:
        return _FactBuildResult(rows=[], fact_ids=fact_ids)

    return _build_balance_facts(context)


def _find_balance_end_row(sheet: Any, start_row: int) -> int:
    end_row = start_row - 1
    blank_streak = 0

    for row in range(start_row, sheet.max_row + 1):
        row_values = [_cell_value(sheet, row, col) for col in range(1, sheet.max_column + 1)]
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


def _build_balance_facts(context: _BalanceFactContext) -> _FactBuildResult:
    rows: list[dict[str, Any]] = []
    fact_ids: dict[tuple[int, int], str] = {}
    min_col = min(spec.anchor_col for spec in context.side_specs)
    max_col = max(spec.end_col for spec in context.side_specs)
    header_rows = {spec.header_row for spec in context.side_specs}

    for source_row in range(context.start_row, context.end_row + 1):
        for source_col in range(min_col, max_col + 1):
            value = _cell_value(context.sheet, source_row, source_col)
            if not _cell_text(value):
                continue

            spec = _spec_for_col(context.side_specs, source_col)
            row_label = _balance_row_label(context.sheet, source_row, spec) if spec else None
            column_label = _balance_column_label(context.sheet, source_col, spec) if spec else None
            fact_kind = "section_label" if source_row == context.start_row else "table_value"
            if source_row in header_rows:
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


def _spec_for_col(side_specs: tuple[_SideSpec, _SideSpec], col: int) -> _SideSpec | None:
    for spec in side_specs:
        if spec.anchor_col <= col <= spec.end_col:
            return spec
    return None


def _balance_row_label(sheet: Any, source_row: int, spec: _SideSpec) -> str | None:
    if source_row <= spec.header_row:
        return None
    return _cell_text(_cell_value(sheet, source_row, spec.item_col)) or _cell_text(
        _cell_value(sheet, source_row, spec.category_col)
    )


def _balance_column_label(sheet: Any, source_col: int, spec: _SideSpec) -> str:
    header = _cell_text(_cell_value(sheet, spec.header_row, source_col))
    if header:
        return f"{spec.title}:{header}"
    return spec.title
