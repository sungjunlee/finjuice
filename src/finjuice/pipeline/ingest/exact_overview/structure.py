"""Sparse-cell overview sheet selection and catalog structure detection."""

from __future__ import annotations

from finjuice.pipeline.ingest.exact_overview.models import (
    BalanceTable,
    CashflowTable,
    ColumnBinding,
    ExactOverviewIssue,
    OverviewLayout,
    SectionRange,
    SheetSelection,
    SideSpec,
    StructuredTable,
)
from finjuice.pipeline.ingest.exact_overview.values import (
    cell_text,
    column_index,
    content_cells,
    issue,
    normalized_text,
    parse_period_month,
)
from finjuice.pipeline.ingest.exact_transactions import _cells_by_row
from finjuice.pipeline.ingest.overview.cells import _is_summary_label
from finjuice.pipeline.ingest.overview.constants import (
    _AMOUNT_HEADERS,
    _ASSET_ANCHOR,
    _CASHFLOW_CATEGORY_HEADERS,
    _CATEGORY_HEADERS,
    _INSURANCE_BLOCK_ID,
    _INVESTMENT_BLOCK_ID,
    _ITEM_HEADERS,
    _LIABILITY_ANCHOR,
    _LOAN_BLOCK_ID,
    _OVERVIEW_SHEET_NORMALIZED,
    _SECTION_BLOCKS,
    _STRUCTURED_TABLE_HEADERS,
)
from finjuice.pipeline.ingest.overview.sections import (
    _is_cashflow_anchor,
    _is_row_break_anchor,
    _numbered_section_title,
)
from finjuice.pipeline.ingest.schemas_helpers import normalize_sheet_name
from finjuice.pipeline.ingest.xlsx_evidence import CellEvidence, SheetEvidence, WorkbookEvidence

_REQUIRED_STRUCTURED: dict[str, frozenset[str]] = {
    "insurance": frozenset({"institution", "policy_name"}),
    "investments": frozenset({"institution", "product_name"}),
    "loans": frozenset({"institution", "product_name"}),
}
_STRUCTURED_BLOCKS: tuple[tuple[str, str], ...] = (
    ("insurance", _INSURANCE_BLOCK_ID),
    ("investments", _INVESTMENT_BLOCK_ID),
    ("loans", _LOAN_BLOCK_ID),
)


def select_overview_sheet(workbook: WorkbookEvidence, sheet_name: str | None) -> SheetSelection:
    """Select an overview sheet without choosing an arbitrary first match."""
    if sheet_name is not None:
        return _named_sheet(workbook, sheet_name)
    named = tuple(sheet for sheet in workbook.sheets if _is_named_overview(sheet.name))
    if len(named) > 1:
        names = tuple(sheet.name for sheet in named)
        return SheetSelection("ambiguous_sheets", None, names, (issue("AMBIGUOUS_SHEETS"),))
    if len(named) == 1:
        return SheetSelection("mapped", named[0], (named[0].name,), ())
    return _anchor_sheet(workbook)


def detect_layout(sheet: SheetEvidence, date1904: bool) -> OverviewLayout:
    """Detect numbered sections and typed tables from captured cells."""
    sections = find_sections(sheet)
    balance = detect_balance(sheet)
    cashflow = detect_cashflow(sheet, date1904)
    structured = tuple(
        _detect_structured(sheet, sections, kind, block) for kind, block in _STRUCTURED_BLOCKS
    )
    tables = {table.kind: table for table in structured if table is not None}
    issues = _layout_issues(balance, cashflow, tables)
    return OverviewLayout(
        sheet=sheet,
        date1904=date1904,
        sections=sections,
        balance=balance,
        cashflow=cashflow,
        insurance=tables.get("insurance"),
        investments=tables.get("investments"),
        loans=tables.get("loans"),
        issues=issues,
    )


def find_sections(sheet: SheetEvidence) -> tuple[SectionRange, ...]:
    """Find numbered catalog sections using sparse nonempty cells."""
    anchors = _section_anchors(sheet)
    if not anchors:
        return ()
    last_row = max(cell.row for cell in content_cells(sheet))
    ranges: list[SectionRange] = []
    for index, cell in enumerate(anchors):
        end_row = anchors[index + 1].row - 1 if index + 1 < len(anchors) else last_row
        title = _numbered_section_title(cell_text(cell) or "")
        block_id, block_title = _SECTION_BLOCKS[normalize_sheet_name(title or "")]
        ranges.append(SectionRange(block_id, block_title, cell.row, cell.column, end_row, cell))
    return tuple(ranges)


def detect_balance(sheet: SheetEvidence) -> BalanceTable | None:
    """Detect a unique asset/liability table, or flag equally eligible pairs."""
    pairs = _geometric_balance_pairs(sheet)
    if not pairs:
        return None
    if len(pairs) > 1:
        return BalanceTable(None, None, 0, 0, False, (issue("AMBIGUOUS_BALANCE_ANCHORS"),))
    return _balance_from_pair(sheet, pairs[0])


def detect_cashflow(sheet: SheetEvidence, date1904: bool) -> CashflowTable | None:
    """Detect a unique cashflow table, or flag equally eligible anchors."""
    anchors = tuple(
        cell for cell in content_cells(sheet) if _is_cashflow_anchor(normalized_text(cell))
    )
    if not anchors:
        return None
    if len(anchors) > 1:
        return CashflowTable(
            0, "", None, 0, None, (), False, (issue("AMBIGUOUS_CASHFLOW_ANCHORS"),)
        )
    return _cashflow_from_anchor(sheet, anchors[0], date1904)


def looks_like_overview(sheet: SheetEvidence) -> bool:
    """Return whether a sheet is named or structurally an overview worksheet."""
    if _is_named_overview(sheet.name):
        return True
    if find_sections(sheet):
        return True
    return bool(_geometric_balance_pairs(sheet) or _cashflow_anchor_cells(sheet))


def row_is_summary(cells: tuple[CellEvidence, ...]) -> bool:
    """Return whether any captured cell in the row is a summary label."""
    return any(_is_summary_label(text) for cell in cells if (text := cell_text(cell)))


def cells_in_row(sheet: SheetEvidence, row: int) -> tuple[CellEvidence, ...]:
    """Return captured cells for one row in column order."""
    grouped = _cells_by_row(sheet)
    cells = grouped.get(row, ())
    return tuple(sorted(cells, key=lambda cell: column_index(cell.column)))


def side_header_cells(sheet: SheetEvidence, spec: SideSpec) -> tuple[CellEvidence, ...]:
    """Return header-row cells in this balance side's column band."""
    return _cells_in_band(cells_in_row(sheet, spec.header_row), spec.anchor_column, spec.end_column)


def side_row_cells(cells: tuple[CellEvidence, ...], spec: SideSpec) -> tuple[CellEvidence, ...]:
    """Limit a balance row to the selected asset or liability column band."""
    return _cells_in_band(cells, spec.anchor_column, spec.end_column)


def cell_in_column(cells: tuple[CellEvidence, ...], column: str | None) -> CellEvidence | None:
    """Return the cell in ``column`` if it was captured."""
    if column is None:
        return None
    for cell in cells:
        if cell.column == column:
            return cell
    return None


def binding_map(table: StructuredTable) -> dict[str, str]:
    """Map catalog field names to unique header columns."""
    return {item.field_name: item.column for item in table.bindings}


def populated_rows_between(sheet: SheetEvidence, start: int, end: int) -> tuple[int, ...]:
    """Return captured row numbers in ``(start, end]`` without scanning empties."""
    rows = sorted({cell.row for cell in content_cells(sheet) if start < cell.row <= end})
    clipped: list[int] = []
    for row in rows:
        if _row_breaks(sheet, row):
            break
        clipped.append(row)
    return tuple(clipped)


def _named_sheet(workbook: WorkbookEvidence, sheet_name: str) -> SheetSelection:
    sheet = workbook.sheet(sheet_name)
    if sheet is None:
        return SheetSelection("sheet_not_found", None, (), (issue("SHEET_NOT_FOUND"),))
    if not looks_like_overview(sheet):
        return SheetSelection(
            "not_overview_sheet", sheet, (sheet.name,), (issue("NOT_OVERVIEW_SHEET"),)
        )
    return SheetSelection("mapped", sheet, (sheet.name,), ())


def _anchor_sheet(workbook: WorkbookEvidence) -> SheetSelection:
    matches = tuple(sheet for sheet in workbook.sheets if looks_like_overview(sheet))
    names = tuple(sheet.name for sheet in matches)
    if not matches:
        return SheetSelection("no_overview_sheet", None, (), (issue("NO_OVERVIEW_SHEET"),))
    if len(matches) > 1:
        return SheetSelection("ambiguous_sheets", None, names, (issue("AMBIGUOUS_SHEETS"),))
    return SheetSelection("mapped", matches[0], names, ())


def _is_named_overview(name: str) -> bool:
    return normalize_sheet_name(name) == _OVERVIEW_SHEET_NORMALIZED


def _section_anchors(sheet: SheetEvidence) -> tuple[CellEvidence, ...]:
    found: list[CellEvidence] = []
    for cell in content_cells(sheet):
        title = _numbered_section_title(cell_text(cell) or "")
        if title is None:
            continue
        if normalize_sheet_name(title) in _SECTION_BLOCKS:
            found.append(cell)
    return tuple(found)


def _cashflow_anchor_cells(sheet: SheetEvidence) -> tuple[CellEvidence, ...]:
    return tuple(
        cell for cell in content_cells(sheet) if _is_cashflow_anchor(normalized_text(cell))
    )


def _geometric_balance_pairs(sheet: SheetEvidence) -> tuple[tuple[CellEvidence, CellEvidence], ...]:
    assets, liabilities = _balance_anchors(sheet)
    pairs: list[tuple[CellEvidence, CellEvidence]] = []
    for asset in assets:
        for liability in liabilities:
            if column_index(liability.column) <= column_index(asset.column):
                continue
            if abs(liability.row - asset.row) > 1:
                continue
            pairs.append((asset, liability))
    return tuple(pairs)


def _balance_anchors(
    sheet: SheetEvidence,
) -> tuple[tuple[CellEvidence, ...], tuple[CellEvidence, ...]]:
    assets = tuple(cell for cell in content_cells(sheet) if normalized_text(cell) == _ASSET_ANCHOR)
    liabilities = tuple(
        cell for cell in content_cells(sheet) if normalized_text(cell) == _LIABILITY_ANCHOR
    )
    return assets, liabilities


def _balance_from_pair(
    sheet: SheetEvidence, pair: tuple[CellEvidence, CellEvidence]
) -> BalanceTable:
    asset_cell, liability_cell = pair
    asset, asset_issues = _side_spec(
        sheet, "asset", asset_cell, _column_before(liability_cell.column)
    )
    liability, liability_issues = _side_spec(sheet, "liability", liability_cell, None)
    issues = asset_issues + liability_issues
    if asset is None or liability is None:
        code = "DUPLICATE_FIELD_MAPPING" if issues else "AMBIGUOUS_HEADERS"
        extra = issues or (issue(code),)
        return BalanceTable(None, None, 0, 0, False, extra)
    start = min(asset_cell.row, liability_cell.row)
    end = _table_end(sheet, max(asset.header_row, liability.header_row))
    return BalanceTable(asset, liability, start, end, True, issues)


def _side_spec(
    sheet: SheetEvidence, side: str, anchor: CellEvidence, end_column: str | None
) -> tuple[SideSpec | None, tuple[ExactOverviewIssue, ...]]:
    rows = populated_rows_between(sheet, anchor.row, anchor.row + 6)
    matches = [_try_side_header(sheet, side, anchor, end_column, row) for row in rows]
    usable = [item for item in matches if isinstance(item, SideSpec)]
    duplicated = [item for item in matches if item == "duplicate"]
    if duplicated:
        return None, (issue("DUPLICATE_FIELD_MAPPING", field_name="amount"),)
    if len(usable) != 1:
        return None, ()
    return usable[0], ()


def _try_side_header(
    sheet: SheetEvidence,
    side: str,
    anchor: CellEvidence,
    end_column: str | None,
    row: int,
) -> SideSpec | str | None:
    band = _cells_in_band(cells_in_row(sheet, row), anchor.column, end_column)
    amount = _unique_header(band, _AMOUNT_HEADERS)
    if amount == "duplicate":
        return "duplicate"
    if amount is None:
        return None
    category = _unique_header(band, _CATEGORY_HEADERS)
    item = _unique_header(band, _ITEM_HEADERS)
    if category == "duplicate" or item == "duplicate":
        return "duplicate"
    if not isinstance(amount, CellEvidence):
        return None
    category_cell = category if isinstance(category, CellEvidence) else None
    item_cell = item if isinstance(item, CellEvidence) else None
    if category_cell is None and item_cell is None:
        return None
    return SideSpec(
        side=side,
        title=cell_text(anchor) or side,
        anchor_column=anchor.column,
        end_column=end_column,
        header_row=row,
        category_column=None if category_cell is None else category_cell.column,
        item_column=None if item_cell is None else item_cell.column,
        amount_column=amount.column,
        amount_header=cell_text(amount) or "",
    )


def _unique_header(cells: tuple[CellEvidence, ...], catalog: set[str]) -> CellEvidence | str | None:
    matches = tuple(cell for cell in cells if normalized_text(cell) in catalog)
    if len(matches) > 1:
        return "duplicate"
    if not matches:
        return None
    return matches[0]


def _cells_in_band(
    cells: tuple[CellEvidence, ...], start: str, end: str | None
) -> tuple[CellEvidence, ...]:
    start_idx = column_index(start)
    end_idx = None if end is None else column_index(end)
    band: list[CellEvidence] = []
    for cell in cells:
        index = column_index(cell.column)
        if index < start_idx:
            continue
        if end_idx is not None and index > end_idx:
            continue
        band.append(cell)
    return tuple(band)


def _column_before(column: str) -> str | None:
    index = column_index(column)
    if index <= 1:
        return None
    return _column_letter(index - 1)


def _column_letter(index: int) -> str:
    chars: list[str] = []
    remaining = index
    while remaining:
        remaining, rem = divmod(remaining - 1, 26)
        chars.append(chr(65 + rem))
    return "".join(reversed(chars))


def _cashflow_from_anchor(
    sheet: SheetEvidence, anchor: CellEvidence, date1904: bool
) -> CashflowTable:
    rows = populated_rows_between(sheet, anchor.row, anchor.row + 7)
    headers = [_try_cashflow_header(sheet, row, date1904) for row in rows]
    usable = [item for item in headers if item is not None]
    if len(usable) > 1:
        issues = (issue("AMBIGUOUS_HEADERS"),)
        return CashflowTable(anchor.row, anchor.column, None, 0, None, (), False, issues)
    if not usable:
        end = _table_end(sheet, anchor.row)
        issues = (issue("NO_CASHFLOW_HEADER"),)
        return CashflowTable(anchor.row, anchor.column, None, end, None, (), False, issues)
    header_row, category, months, header_issues = usable[0]
    end = _table_end(sheet, header_row)
    ok = not header_issues
    return CashflowTable(
        anchor.row, anchor.column, header_row, end, category, months, ok, header_issues
    )


def _try_cashflow_header(
    sheet: SheetEvidence, row: int, date1904: bool
) -> (
    tuple[int, str, tuple[tuple[str, str, CellEvidence], ...], tuple[ExactOverviewIssue, ...]]
    | None
):
    cells = cells_in_row(sheet, row)
    categories = tuple(
        cell for cell in cells if normalized_text(cell) in _CASHFLOW_CATEGORY_HEADERS
    )
    if len(categories) != 1:
        return None
    months, month_issues = _month_columns(cells, categories[0].column, date1904)
    if not months and not month_issues:
        return None
    return row, categories[0].column, months, month_issues


def _month_columns(
    cells: tuple[CellEvidence, ...], category_column: str, date1904: bool
) -> tuple[tuple[tuple[str, str, CellEvidence], ...], tuple[ExactOverviewIssue, ...]]:
    months: list[tuple[str, str, CellEvidence]] = []
    for cell in cells:
        if cell.column == category_column:
            continue
        period, _parsed = parse_period_month(cell, date1904)
        if period is None:
            continue
        months.append((cell.column, period, cell))
    periods = tuple(item[1] for item in months)
    if len(periods) != len(set(periods)):
        return (), (issue("AMBIGUOUS_MONTH_COLUMNS"),)
    return tuple(months), ()


def _detect_structured(
    sheet: SheetEvidence, sections: tuple[SectionRange, ...], kind: str, block_id: str
) -> StructuredTable | None:
    section = next((item for item in sections if item.block_id == block_id), None)
    if section is None:
        return None
    catalog = _STRUCTURED_TABLE_HEADERS[kind]
    rows = populated_rows_between(
        sheet, section.anchor_row, min(section.end_row, section.anchor_row + 8)
    )
    attempts = [_structured_attempt(sheet, section, kind, catalog, row) for row in rows]
    complete = [item for item in attempts if item is not None]
    return _choose_structured(kind, section, complete)


def _structured_attempt(
    sheet: SheetEvidence,
    section: SectionRange,
    kind: str,
    catalog: dict[str, set[str]],
    row: int,
) -> StructuredTable | None:
    bindings, duplicates = _bindings_for_row(cells_in_row(sheet, row), catalog)
    names = {item.field_name for item in bindings}
    if not _REQUIRED_STRUCTURED[kind] <= names and not duplicates:
        return None
    issues: tuple[ExactOverviewIssue, ...] = ()
    usable = True
    if duplicates:
        issues = (issue("DUPLICATE_FIELD_MAPPING", field_name=duplicates[0]),)
        usable = False
    elif not _REQUIRED_STRUCTURED[kind] <= names:
        return None
    return StructuredTable(kind, section, row, bindings, usable, issues)


def _choose_structured(
    kind: str, section: SectionRange, complete: list[StructuredTable]
) -> StructuredTable:
    if len(complete) > 1:
        issues = (issue("AMBIGUOUS_HEADERS"),)
        return StructuredTable(kind, section, None, (), False, issues)
    if not complete:
        return StructuredTable(kind, section, None, (), False, ())
    return complete[0]


def _bindings_for_row(
    cells: tuple[CellEvidence, ...], catalog: dict[str, set[str]]
) -> tuple[tuple[ColumnBinding, ...], tuple[str, ...]]:
    groups: dict[str, list[ColumnBinding]] = {}
    for cell in cells:
        field_name = _field_for_header(normalized_text(cell), catalog)
        if field_name is None:
            continue
        binding = ColumnBinding(field_name, cell.column, cell_text(cell) or "", cell)
        groups.setdefault(field_name, []).append(binding)
    duplicates = tuple(name for name, items in groups.items() if len(items) > 1)
    unique = tuple(items[0] for items in groups.values() if len(items) == 1)
    return unique, duplicates


def _field_for_header(normalized: str, catalog: dict[str, set[str]]) -> str | None:
    for field_name, variants in catalog.items():
        if normalized in variants:
            return field_name
    return None


def _table_end(sheet: SheetEvidence, start_row: int) -> int:
    rows = populated_rows_between(
        sheet, start_row, max((cell.row for cell in content_cells(sheet)), default=start_row)
    )
    if not rows:
        return start_row
    return rows[-1]


def _row_breaks(sheet: SheetEvidence, row: int) -> bool:
    return any(_is_row_break_anchor(normalized_text(cell)) for cell in cells_in_row(sheet, row))


def _layout_issues(
    balance: BalanceTable | None,
    cashflow: CashflowTable | None,
    tables: dict[str, StructuredTable],
) -> tuple[ExactOverviewIssue, ...]:
    issues: list[ExactOverviewIssue] = []
    if balance is not None:
        issues.extend(balance.issues)
    if cashflow is not None:
        issues.extend(cashflow.issues)
    for table in tables.values():
        issues.extend(table.issues)
    return tuple(issues)
