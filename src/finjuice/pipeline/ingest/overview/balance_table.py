"""Balance table and anchor discovery for Banksalad overview sheets.

Anchor collection, two-sided table detection, and header-column mapping live
here. Snapshot/fact assembly stays in
:mod:`finjuice.pipeline.ingest.overview.balance`, which re-exports these
helpers so existing callers can keep importing from that module.
"""

from __future__ import annotations

from typing import Any

from .cells import (
    _first_header_col,
    _header_map_for_row,
    _iter_non_empty_cells,
    _normalize_cell_text,
)
from .constants import (
    _AMOUNT_HEADERS,
    _ASSET_ANCHOR,
    _CATEGORY_HEADERS,
    _ITEM_HEADERS,
    _LIABILITY_ANCHOR,
)
from .models import _Anchor, _SideSpec


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
