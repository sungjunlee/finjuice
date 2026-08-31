"""Balance (asset/liability) block parser for Banksalad overview sheets."""

from __future__ import annotations

from typing import Any

from .cells import (
    _cell_text,
    _cell_value,
    _first_header_col,
    _header_map_for_row,
    _is_summary_label,
    _iter_non_empty_cells,
    _normalize_cell_text,
    _parse_numeric_value,
)
from .constants import (
    _AMOUNT_HEADERS,
    _ASSET_ANCHOR,
    _BALANCE_BLOCK_ID,
    _BALANCE_BLOCK_TITLE,
    _CATEGORY_HEADERS,
    _ITEM_HEADERS,
    _LIABILITY_ANCHOR,
)
from .facts import _make_fact
from .models import (
    _Anchor,
    _BalanceFactContext,
    _FactBuildResult,
    _FactContext,
    _FactLabels,
    _OverviewBlockParseContext,
    _SideSpec,
)
from .sections import _is_row_break_anchor


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
            amount = _parse_numeric_value(_cell_value(sheet, source_row, spec.amount_col))
            if amount is None:
                continue

            category = _cell_text(_cell_value(sheet, source_row, spec.category_col))
            item_name = _cell_text(_cell_value(sheet, source_row, spec.item_col))
            if not item_name:
                item_name = category
            if not item_name or _is_summary_label(item_name):
                continue

            source_fact_id = fact_result.fact_ids.get((source_row, spec.amount_col))
            if source_fact_id is None:
                continue

            rows.append(
                {
                    "snapshot_date": block_context.snapshot_date,
                    "side": spec.side,
                    "category": category,
                    "item_name": item_name,
                    "amount": amount,
                    "currency": "KRW",
                    "source_fact_id": source_fact_id,
                    "file_id": block_context.file_id,
                    "source_row": source_row,
                }
            )

    return rows, fact_result.rows, warnings


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


def _find_balance_table(
    sheet: Any,
    asset_anchors: list[_Anchor],
    liability_anchors: list[_Anchor],
) -> tuple[_Anchor, _Anchor, _SideSpec, _SideSpec] | None:
    for asset_anchor, liability_anchor in _balance_anchor_pairs(asset_anchors, liability_anchors):
        asset_spec = _detect_side_spec(
            sheet=sheet,
            side="asset",
            title=asset_anchor.text,
            anchor=asset_anchor,
            end_col=liability_anchor.col - 1,
        )
        liability_spec = _detect_side_spec(
            sheet=sheet,
            side="liability",
            title=liability_anchor.text,
            anchor=liability_anchor,
            end_col=sheet.max_column,
        )
        if asset_spec is not None and liability_spec is not None:
            return asset_anchor, liability_anchor, asset_spec, liability_spec

    return None


def _collect_balance_anchors(sheet: Any) -> tuple[list[_Anchor], list[_Anchor]]:
    asset_anchors: list[_Anchor] = []
    liability_anchors: list[_Anchor] = []

    for row, col, value in _iter_non_empty_cells(sheet):
        normalized = _normalize_cell_text(value)
        if normalized == _ASSET_ANCHOR:
            asset_anchors.append(_Anchor(row=row, col=col, text=str(value).strip()))
        elif normalized == _LIABILITY_ANCHOR:
            liability_anchors.append(_Anchor(row=row, col=col, text=str(value).strip()))

    return asset_anchors, liability_anchors


def _find_balance_anchor_pair(
    asset_anchors: list[_Anchor],
    liability_anchors: list[_Anchor],
) -> tuple[_Anchor, _Anchor] | None:
    pairs = _balance_anchor_pairs(asset_anchors, liability_anchors)
    if not pairs:
        return None
    return pairs[0]


def _balance_anchor_pairs(
    asset_anchors: list[_Anchor],
    liability_anchors: list[_Anchor],
) -> list[tuple[_Anchor, _Anchor]]:
    candidates: list[tuple[int, int, _Anchor, _Anchor]] = []
    for asset_anchor in asset_anchors:
        for liability_anchor in liability_anchors:
            if liability_anchor.col <= asset_anchor.col:
                continue
            row_delta = abs(liability_anchor.row - asset_anchor.row)
            if row_delta <= 1:
                candidates.append(
                    (
                        row_delta,
                        liability_anchor.col - asset_anchor.col,
                        asset_anchor,
                        liability_anchor,
                    )
                )

    ordered = sorted(candidates, key=lambda item: (item[0], item[1], item[2].row, item[2].col))
    return [(asset_anchor, liability_anchor) for _, _, asset_anchor, liability_anchor in ordered]


def _detect_side_spec(
    sheet: Any,
    side: str,
    title: str,
    anchor: _Anchor,
    end_col: int,
) -> _SideSpec | None:
    for row in range(anchor.row + 1, min(sheet.max_row, anchor.row + 6) + 1):
        header_map = _header_map_for_row(sheet, row, anchor.col, end_col)
        amount_col = _first_header_col(header_map, _AMOUNT_HEADERS)
        if amount_col is None:
            continue

        return _SideSpec(
            side=side,
            title=title,
            anchor_col=anchor.col,
            end_col=end_col,
            header_row=row,
            category_col=_first_header_col(header_map, _CATEGORY_HEADERS),
            item_col=_first_header_col(header_map, _ITEM_HEADERS),
            amount_col=amount_col,
        )

    return None


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
