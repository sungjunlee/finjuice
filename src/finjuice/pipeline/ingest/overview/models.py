"""Internal dataclasses for Banksalad overview block parsers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class _Anchor:
    """Location of a detected worksheet anchor."""

    row: int
    col: int
    text: str


@dataclass(frozen=True)
class _SideSpec:
    """Detected balance table columns for one side."""

    side: str
    title: str
    anchor_col: int
    end_col: int
    header_row: int
    category_col: int | None
    item_col: int | None
    amount_col: int


@dataclass(frozen=True)
class _FactBuildResult:
    """Built fact rows and lookup by source cell."""

    rows: list[dict[str, Any]]
    fact_ids: dict[tuple[int, int], str]


@dataclass(frozen=True)
class _FactContext:
    """Shared metadata for overview fact rows."""

    snapshot_date: str
    sheet_name: str
    block_id: str
    block_title: str
    file_id: str


@dataclass(frozen=True)
class _FactLabels:
    """Labels that describe one overview fact cell."""

    fact_kind: str
    row_label: str | None
    column_label: str | None


@dataclass(frozen=True)
class _OverviewBlockParseContext:
    """Shared parser metadata for typed overview projections."""

    sheet_name: str
    snapshot_date: str
    file_id: str
    file_name: str


@dataclass(frozen=True)
class _BalanceFactContext:
    """Detected balance table range and metadata for fact extraction."""

    sheet: Any
    fact_context: _FactContext
    start_row: int
    end_row: int
    side_specs: tuple[_SideSpec, _SideSpec]


@dataclass(frozen=True)
class _CashflowFactContext:
    """Detected cashflow table range and metadata for fact extraction."""

    sheet: Any
    fact_context: _FactContext
    anchor_row: int
    header_row: int
    end_row: int
    category_col: int
    month_cols: dict[int, str]


@dataclass(frozen=True)
class _SectionRange:
    """Detected numbered overview section range."""

    block_id: str
    block_title: str
    anchor_row: int
    anchor_col: int
    end_row: int


@dataclass(frozen=True)
class _StructuredTableSpec:
    """Header mapping for one structured overview table."""

    section: _SectionRange
    header_row: int
    columns: dict[str, int]
