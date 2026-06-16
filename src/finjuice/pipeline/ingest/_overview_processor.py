"""Banksalad overview worksheet parsing.

This module reads the formatted ``뱅샐현황`` worksheet into source-fidelity
facts and typed projections. It is intentionally not wired into ingest writes;
future ingest orchestration can call ``parse_banksalad_overview`` and decide
how to preview or store the returned DataFrames.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from zipfile import BadZipFile

import polars as pl
from openpyxl import load_workbook

from ..storage import csv_partition
from .schemas import normalize_sheet_name

_OVERVIEW_SHEET_NORMALIZED = normalize_sheet_name("뱅샐현황")
_ASSET_ANCHOR = normalize_sheet_name("자산")
_LIABILITY_ANCHOR = normalize_sheet_name("부채")
_BALANCE_BLOCK_ID = "balance_status"
_BALANCE_BLOCK_TITLE = "자산/부채"
_CASHFLOW_BLOCK_ID = "cashflow_monthly"
_CASHFLOW_BLOCK_TITLE = "현금흐름현황"
_CUSTOMER_BLOCK_ID = "customer_info"
_INSURANCE_BLOCK_ID = "insurance_status"
_INVESTMENT_BLOCK_ID = "investment_status"
_LOAN_BLOCK_ID = "loan_status"
_CASHFLOW_ANCHORS = {
    normalize_sheet_name(value)
    for value in ("현금흐름현황", "현금흐름", "월별현금흐름", "수입지출현황")
}
_SECTION_NUMBER_PREFIX_RE = re.compile(r"^\d+[\.)．。]?")
_NUMBERED_SECTION_RE = re.compile(r"^\s*\d+[\.)．。]?\s*(.+?)\s*$")
_CATEGORY_HEADERS = {
    normalize_sheet_name(value)
    for value in ("분류", "카테고리", "구분", "종류", "자산분류", "부채분류")
}
_ITEM_HEADERS = {
    normalize_sheet_name(value)
    for value in ("항목", "상품명", "계좌명", "계좌", "자산명", "부채명", "내용", "이름")
}
_AMOUNT_HEADERS = {
    normalize_sheet_name(value)
    for value in ("금액", "잔액", "평가금액", "현재금액", "합계", "총액")
}
_CASHFLOW_CATEGORY_HEADERS = {
    normalize_sheet_name(value) for value in ("분류", "카테고리", "항목", "구분")
}
_SNAPSHOT_DATE_LABELS = {
    normalize_sheet_name(value)
    for value in ("기준일", "조회일", "현황기준일", "자산기준일", "내보내기일")
}
_ROW_BREAK_ANCHORS = _CASHFLOW_ANCHORS | {
    normalize_sheet_name(value)
    for value in (
        "고객정보",
        "재무현황",
        "보험현황",
        "투자현황",
        "대출현황",
        "자산추이",
        "부채추이",
        "소비현황",
    )
}
_SECTION_BLOCKS = {
    normalize_sheet_name("고객정보"): (_CUSTOMER_BLOCK_ID, "고객정보"),
    normalize_sheet_name("현금흐름현황"): (_CASHFLOW_BLOCK_ID, _CASHFLOW_BLOCK_TITLE),
    normalize_sheet_name("재무현황"): (_BALANCE_BLOCK_ID, _BALANCE_BLOCK_TITLE),
    normalize_sheet_name("보험현황"): (_INSURANCE_BLOCK_ID, "보험현황"),
    normalize_sheet_name("투자현황"): (_INVESTMENT_BLOCK_ID, "투자현황"),
    normalize_sheet_name("대출현황"): (_LOAN_BLOCK_ID, "대출현황"),
}
_SUMMARY_LABELS = {normalize_sheet_name(value) for value in ("합계", "총계", "총자산", "총부채")}
_STRUCTURED_TABLE_HEADERS = {
    "insurance": {
        "institution": {normalize_sheet_name("금융사")},
        "policy_name": {normalize_sheet_name("보험명")},
        "contract_status": {normalize_sheet_name("계약상태")},
        "paid_amount": {normalize_sheet_name("총납입금")},
        "contract_date": {normalize_sheet_name("계약일자")},
        "maturity_date": {normalize_sheet_name("만기일자")},
    },
    "investments": {
        "product_type": {normalize_sheet_name("투자상품종류")},
        "institution": {normalize_sheet_name("금융사")},
        "product_name": {normalize_sheet_name("상품명")},
        "principal_amount": {normalize_sheet_name("투자원금")},
        "valuation_amount": {normalize_sheet_name("평가금액")},
        "return_rate": {normalize_sheet_name("수익률")},
        "start_date": {normalize_sheet_name("가입일자")},
        "maturity_date": {normalize_sheet_name("만기일자")},
    },
    "loans": {
        "loan_type": {normalize_sheet_name("대출종류")},
        "institution": {normalize_sheet_name("금융사")},
        "product_name": {normalize_sheet_name("상품명")},
        "principal_amount": {normalize_sheet_name("대출원금")},
        "balance_amount": {normalize_sheet_name("대출잔액")},
        "interest_rate": {normalize_sheet_name("대출금리")},
        "start_date": {normalize_sheet_name("대출신규일")},
        "maturity_date": {normalize_sheet_name("대출만기일"), normalize_sheet_name("만기일자")},
    },
}


@dataclass(frozen=True)
class BanksaladOverviewParseResult:
    """Result of parsing one Banksalad overview worksheet."""

    overview_facts: pl.DataFrame
    balance: pl.DataFrame
    cashflow: pl.DataFrame
    insurance: pl.DataFrame
    investments: pl.DataFrame
    loans: pl.DataFrame
    warnings: list[str]


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


def parse_banksalad_overview(
    file_path: Path,
    file_id: str,
    snapshot_date: str | None = None,
    file_mtime: str | None = None,
) -> BanksaladOverviewParseResult:
    """Parse a Banksalad overview worksheet without writing storage files.

    Args:
        file_path: Source XLSX workbook path.
        file_id: Import-history file identifier to attach to parsed rows.
        snapshot_date: Optional explicit ``YYYY-MM-DD`` snapshot date.
        file_mtime: Optional source file mtime ISO timestamp used as fallback.

    Returns:
        Parsed overview facts, balance projections, cashflow projections, and
        non-fatal warnings. Missing or unrecognized overview sheets return
        typed empty DataFrames.
    """
    warnings: list[str] = []

    try:
        workbook = load_workbook(file_path, read_only=True, data_only=True)
    except (OSError, BadZipFile, ValueError) as exc:
        warnings.append(f"Failed to read overview workbook {file_path.name}: {exc}")
        return _empty_result(warnings)

    try:
        sheet = _find_overview_sheet(workbook)
        if sheet is None:
            warnings.append(f"Overview sheet not found in {file_path.name}; skipped")
            return _empty_result(warnings)

        resolved_snapshot_date = _resolve_snapshot_date(
            sheet=sheet,
            file_path=file_path,
            snapshot_date=snapshot_date,
            file_mtime=file_mtime,
        )
        section_ranges = _find_numbered_sections(sheet)
        section_facts = _build_section_facts(
            sheet=sheet,
            sheet_name=str(sheet.title),
            snapshot_date=resolved_snapshot_date,
            file_id=file_id,
            sections=section_ranges,
        )
        fact_rows: list[dict[str, Any]] = list(section_facts.rows)
        block_context = _OverviewBlockParseContext(
            sheet_name=str(sheet.title),
            snapshot_date=resolved_snapshot_date,
            file_id=file_id,
            file_name=file_path.name,
        )

        balance_rows, balance_facts, balance_warnings = _parse_balance_block(
            sheet=sheet,
            block_context=block_context,
            fact_ids=section_facts.fact_ids,
        )
        fact_rows.extend(balance_facts)
        warnings.extend(balance_warnings)

        cashflow_rows, cashflow_facts, cashflow_warnings = _parse_cashflow_block(
            sheet=sheet,
            block_context=block_context,
            fact_ids=section_facts.fact_ids,
        )
        fact_rows.extend(cashflow_facts)
        warnings.extend(cashflow_warnings)
        insurance_rows = _parse_insurance_rows(
            sheet=sheet,
            snapshot_date=resolved_snapshot_date,
            file_id=file_id,
            sections=section_ranges,
            fact_ids=section_facts.fact_ids,
        )
        investment_rows = _parse_investment_rows(
            sheet=sheet,
            snapshot_date=resolved_snapshot_date,
            file_id=file_id,
            sections=section_ranges,
            fact_ids=section_facts.fact_ids,
        )
        loan_rows = _parse_loan_rows(
            sheet=sheet,
            snapshot_date=resolved_snapshot_date,
            file_id=file_id,
            sections=section_ranges,
            fact_ids=section_facts.fact_ids,
        )

        return BanksaladOverviewParseResult(
            overview_facts=_frame_from_rows(
                fact_rows,
                csv_partition.BANKSALAD_OVERVIEW_FACT_POLARS_SCHEMA,
            ).sort(["block_id", "source_row", "source_col"]),
            balance=_frame_from_rows(
                balance_rows,
                csv_partition.BANKSALAD_BALANCE_POLARS_SCHEMA,
            ).sort(["side", "category", "item_name"]),
            cashflow=_frame_from_rows(
                cashflow_rows,
                csv_partition.BANKSALAD_CASHFLOW_POLARS_SCHEMA,
            ).sort(["period_month", "category"]),
            insurance=_frame_from_rows(
                insurance_rows,
                csv_partition.BANKSALAD_INSURANCE_POLARS_SCHEMA,
            ).sort(["institution", "policy_name"]),
            investments=_frame_from_rows(
                investment_rows,
                csv_partition.BANKSALAD_INVESTMENT_POLARS_SCHEMA,
            ).sort(["institution", "product_name"]),
            loans=_frame_from_rows(
                loan_rows,
                csv_partition.BANKSALAD_LOAN_POLARS_SCHEMA,
            ).sort(["institution", "product_name"]),
            warnings=warnings,
        )
    finally:
        workbook.close()


def _empty_result(warnings: list[str]) -> BanksaladOverviewParseResult:
    return BanksaladOverviewParseResult(
        overview_facts=pl.DataFrame(schema=csv_partition.BANKSALAD_OVERVIEW_FACT_POLARS_SCHEMA),
        balance=pl.DataFrame(schema=csv_partition.BANKSALAD_BALANCE_POLARS_SCHEMA),
        cashflow=pl.DataFrame(schema=csv_partition.BANKSALAD_CASHFLOW_POLARS_SCHEMA),
        insurance=pl.DataFrame(schema=csv_partition.BANKSALAD_INSURANCE_POLARS_SCHEMA),
        investments=pl.DataFrame(schema=csv_partition.BANKSALAD_INVESTMENT_POLARS_SCHEMA),
        loans=pl.DataFrame(schema=csv_partition.BANKSALAD_LOAN_POLARS_SCHEMA),
        warnings=warnings,
    )


def _frame_from_rows(rows: list[dict[str, Any]], schema: dict[str, Any]) -> pl.DataFrame:
    if not rows:
        return pl.DataFrame(schema=schema)
    return pl.DataFrame(rows, schema=schema)


def _find_overview_sheet(workbook: Any) -> Any | None:
    for sheet_name in workbook.sheetnames:
        if normalize_sheet_name(str(sheet_name)) == _OVERVIEW_SHEET_NORMALIZED:
            return workbook[sheet_name]

    for sheet_name in workbook.sheetnames:
        sheet = workbook[sheet_name]
        if _has_overview_anchors(sheet):
            return sheet

    return None


def _has_overview_anchors(sheet: Any) -> bool:
    asset_anchors: list[_Anchor] = []
    liability_anchors: list[_Anchor] = []

    for row, col, value in _iter_non_empty_cells(sheet):
        normalized = _normalize_cell_text(value)
        if normalized == _ASSET_ANCHOR:
            asset_anchors.append(_Anchor(row=row, col=col, text=str(value).strip()))
        elif normalized == _LIABILITY_ANCHOR:
            liability_anchors.append(_Anchor(row=row, col=col, text=str(value).strip()))
        elif _is_cashflow_anchor(normalized):
            return True

    return _find_balance_anchor_pair(asset_anchors, liability_anchors) is not None


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


def _is_cashflow_anchor(normalized: str) -> bool:
    return _matches_numbered_anchor(normalized, _CASHFLOW_ANCHORS)


def _is_row_break_anchor(normalized: str) -> bool:
    return _matches_numbered_anchor(normalized, _ROW_BREAK_ANCHORS)


def _matches_numbered_anchor(normalized: str, anchors: set[str]) -> bool:
    if normalized in anchors:
        return True
    return _SECTION_NUMBER_PREFIX_RE.sub("", normalized) in anchors


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


def _parse_insurance_rows(
    sheet: Any,
    snapshot_date: str,
    file_id: str,
    sections: list[_SectionRange],
    fact_ids: dict[tuple[int, int], str],
) -> list[dict[str, Any]]:
    table = _detect_structured_table(
        sheet,
        sections,
        _INSURANCE_BLOCK_ID,
        _STRUCTURED_TABLE_HEADERS["insurance"],
    )
    if table is None:
        return []

    rows: list[dict[str, Any]] = []
    for source_row in _table_data_rows(sheet, table):
        institution = _text_at(sheet, source_row, table.columns.get("institution"))
        policy_name = _text_at(sheet, source_row, table.columns.get("policy_name"))
        if not _has_entity_identity(institution, policy_name):
            continue

        rows.append(
            {
                "snapshot_date": snapshot_date,
                "institution": institution,
                "policy_name": policy_name,
                "contract_status": _text_at(
                    sheet,
                    source_row,
                    table.columns.get("contract_status"),
                ),
                "paid_amount": _number_at(sheet, source_row, table.columns.get("paid_amount")),
                "contract_date": _date_at(sheet, source_row, table.columns.get("contract_date")),
                "maturity_date": _date_at(sheet, source_row, table.columns.get("maturity_date")),
                "currency": "KRW",
                "source_fact_id": _source_fact_id(
                    fact_ids,
                    source_row,
                    (table.columns.get("policy_name"), table.columns.get("institution")),
                ),
                "file_id": file_id,
                "source_row": source_row,
            }
        )
    return rows


def _parse_investment_rows(
    sheet: Any,
    snapshot_date: str,
    file_id: str,
    sections: list[_SectionRange],
    fact_ids: dict[tuple[int, int], str],
) -> list[dict[str, Any]]:
    table = _detect_structured_table(
        sheet,
        sections,
        _INVESTMENT_BLOCK_ID,
        _STRUCTURED_TABLE_HEADERS["investments"],
    )
    if table is None:
        return []

    rows: list[dict[str, Any]] = []
    for source_row in _table_data_rows(sheet, table):
        institution = _text_at(sheet, source_row, table.columns.get("institution"))
        product_name = _text_at(sheet, source_row, table.columns.get("product_name"))
        if not _has_entity_identity(institution, product_name):
            continue

        rows.append(
            {
                "snapshot_date": snapshot_date,
                "product_type": _text_at(sheet, source_row, table.columns.get("product_type")),
                "institution": institution,
                "product_name": product_name,
                "principal_amount": _number_at(
                    sheet,
                    source_row,
                    table.columns.get("principal_amount"),
                ),
                "valuation_amount": _number_at(
                    sheet,
                    source_row,
                    table.columns.get("valuation_amount"),
                ),
                "return_rate": _number_at(sheet, source_row, table.columns.get("return_rate")),
                "start_date": _date_at(sheet, source_row, table.columns.get("start_date")),
                "maturity_date": _date_at(sheet, source_row, table.columns.get("maturity_date")),
                "currency": "KRW",
                "source_fact_id": _source_fact_id(
                    fact_ids,
                    source_row,
                    (table.columns.get("product_name"), table.columns.get("institution")),
                ),
                "file_id": file_id,
                "source_row": source_row,
            }
        )
    return rows


def _parse_loan_rows(
    sheet: Any,
    snapshot_date: str,
    file_id: str,
    sections: list[_SectionRange],
    fact_ids: dict[tuple[int, int], str],
) -> list[dict[str, Any]]:
    table = _detect_structured_table(
        sheet,
        sections,
        _LOAN_BLOCK_ID,
        _STRUCTURED_TABLE_HEADERS["loans"],
    )
    if table is None:
        return []

    rows: list[dict[str, Any]] = []
    for source_row in _table_data_rows(sheet, table):
        institution = _text_at(sheet, source_row, table.columns.get("institution"))
        product_name = _text_at(sheet, source_row, table.columns.get("product_name"))
        if not _has_entity_identity(institution, product_name):
            continue

        rows.append(
            {
                "snapshot_date": snapshot_date,
                "loan_type": _text_at(sheet, source_row, table.columns.get("loan_type")),
                "institution": institution,
                "product_name": product_name,
                "principal_amount": _number_at(
                    sheet,
                    source_row,
                    table.columns.get("principal_amount"),
                ),
                "balance_amount": _number_at(
                    sheet,
                    source_row,
                    table.columns.get("balance_amount"),
                ),
                "interest_rate": _number_at(sheet, source_row, table.columns.get("interest_rate")),
                "start_date": _date_at(sheet, source_row, table.columns.get("start_date")),
                "maturity_date": _date_at(sheet, source_row, table.columns.get("maturity_date")),
                "currency": "KRW",
                "source_fact_id": _source_fact_id(
                    fact_ids,
                    source_row,
                    (table.columns.get("product_name"), table.columns.get("institution")),
                ),
                "file_id": file_id,
                "source_row": source_row,
            }
        )
    return rows


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


def _section_by_block_id(
    sections: list[_SectionRange],
    block_id: str,
) -> _SectionRange | None:
    for section in sections:
        if section.block_id == block_id:
            return section
    return None


def _normalized_header_map(sheet: Any, row: int) -> dict[int, str]:
    return {
        col: normalized
        for col in range(1, sheet.max_column + 1)
        if (normalized := _normalize_cell_text(_cell_value(sheet, row, col)))
    }


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


def _text_at(sheet: Any, source_row: int, source_col: int | None) -> str | None:
    return _cell_text(_cell_value(sheet, source_row, source_col))


def _number_at(sheet: Any, source_row: int, source_col: int | None) -> float | None:
    return _parse_numeric_value(_cell_value(sheet, source_row, source_col))


def _date_at(sheet: Any, source_row: int, source_col: int | None) -> str | None:
    return _parse_date_value(_cell_value(sheet, source_row, source_col))


def _has_entity_identity(institution: str | None, name: str | None) -> bool:
    if not institution or not name:
        return False
    return not _is_summary_label(institution) and not _is_summary_label(name)


def _is_summary_row(values: list[Any]) -> bool:
    return any(_is_summary_label(text) for value in values if (text := _cell_text(value)))


def _source_fact_id(
    fact_ids: dict[tuple[int, int], str],
    source_row: int,
    preferred_cols: tuple[int | None, ...],
) -> str | None:
    for source_col in preferred_cols:
        if source_col is None:
            continue
        source_fact_id = fact_ids.get((source_row, source_col))
        if source_fact_id is not None:
            return source_fact_id
    return None


def _make_fact(
    context: _FactContext,
    labels: _FactLabels,
    value: Any,
    source_row: int,
    source_col: int,
) -> dict[str, Any]:
    value_numeric = _parse_numeric_value(value)
    value_text: str | None = None
    value_type = "empty"

    if value_numeric is not None:
        value_type = "number"
    elif isinstance(value, (date, datetime)):
        value_type = "date"
        value_text = _format_date_value(value)
    else:
        value_text = _cell_text(value)
        if value_text:
            value_type = "text"

    fact_id = _build_fact_id(
        context=context,
        labels=labels,
        source_row=source_row,
        source_col=source_col,
    )

    return {
        "fact_id": fact_id,
        "snapshot_date": context.snapshot_date,
        "sheet_name": context.sheet_name,
        "block_id": context.block_id,
        "block_title": context.block_title,
        "fact_kind": labels.fact_kind,
        "row_label": labels.row_label,
        "column_label": labels.column_label,
        "value_numeric": value_numeric,
        "value_text": value_text,
        "value_type": value_type,
        "file_id": context.file_id,
        "source_row": source_row,
        "source_col": source_col,
    }


def _build_fact_id(
    context: _FactContext,
    labels: _FactLabels,
    source_row: int,
    source_col: int,
) -> str:
    key = "|".join(
        (
            context.snapshot_date,
            context.block_id,
            labels.fact_kind,
            _normalize_fact_key_part(labels.row_label),
            _normalize_fact_key_part(labels.column_label),
            str(source_row),
            str(source_col),
        )
    )
    return sha256(key.encode("utf-8")).hexdigest()[:16]


def _normalize_fact_key_part(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(value.strip().lower().split())


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

    mtime_date = _parse_date_value(file_mtime)
    if mtime_date is not None:
        return mtime_date

    return datetime.fromtimestamp(file_path.stat().st_mtime).date().isoformat()


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
    return normalize_sheet_name(label) in {
        normalize_sheet_name(value) for value in ("합계", "총계", "총자산", "총부채")
    }
