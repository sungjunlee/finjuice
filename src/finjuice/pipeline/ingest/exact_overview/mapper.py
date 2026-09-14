"""Pure WorkbookEvidence -> exact overview mapping."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from finjuice.pipeline.ingest.exact_overview.models import (
    BalanceTable,
    CashflowTable,
    CurrencyPart,
    ExactBalanceObservation,
    ExactCashflowObservation,
    ExactInsuranceRow,
    ExactInvestmentRow,
    ExactLoanRow,
    ExactOverviewFact,
    ExactOverviewIssue,
    ExactOverviewMapping,
    MappedField,
    MappingRequest,
    OverviewLayout,
    SheetSelection,
    SideSpec,
    SnapshotDateEvidence,
    StructuredTable,
)
from finjuice.pipeline.ingest.exact_overview.structure import (
    binding_map,
    cell_in_column,
    cells_in_row,
    detect_layout,
    populated_rows_between,
    row_is_summary,
    select_overview_sheet,
    side_header_cells,
    side_row_cells,
)
from finjuice.pipeline.ingest.exact_overview.values import (
    cell_text,
    content_cells,
    formula_issues,
    header_currency,
    is_date_text_cell,
    issue,
    parse_money,
    parse_number,
    parse_period_month,
    parse_rate,
    parse_source_date,
    resolve_snapshot,
)
from finjuice.pipeline.ingest.exact_transactions import TEMPORAL_POLICY
from finjuice.pipeline.ingest.overview.constants import (
    _BALANCE_BLOCK_ID,
    _BALANCE_BLOCK_TITLE,
    _CASHFLOW_BLOCK_ID,
    _CASHFLOW_BLOCK_TITLE,
)
from finjuice.pipeline.ingest.xlsx_evidence import CellEvidence, WorkbookEvidence

PARSER_VERSION: Final = "finjuice.xlsx-overview-mapper.v1"


@dataclass(frozen=True)
class _Built:
    request: MappingRequest
    selection: SheetSelection
    layout: OverviewLayout
    snapshot: SnapshotDateEvidence
    facts: tuple[ExactOverviewFact, ...]
    date_issues: tuple[ExactOverviewIssue, ...]


@dataclass(frozen=True)
class _PayCtx:
    sheet_name: str
    snapshot: SnapshotDateEvidence
    currency: CurrencyPart
    date1904: bool


@dataclass(frozen=True)
class _StructCtx:
    layout: OverviewLayout
    snapshot: SnapshotDateEvidence
    currency: CurrencyPart
    columns: dict[str, str]


@dataclass(frozen=True)
class _ValueView:
    value_type: str
    number_value: object
    text_value: str | None
    parsed_date: object
    unverified: bool
    issues: tuple[ExactOverviewIssue, ...]


def map_exact_overview(
    workbook: WorkbookEvidence,
    *,
    sheet_name: str | None = None,
    snapshot_date: str | None = None,
    source_filename: str | None = None,
    collected_at: str | None = None,
) -> ExactOverviewMapping:
    """Map captured workbook evidence into exact overview facts and projections.

    Args:
        workbook: Immutable evidence from the completed XLSX reader.
        sheet_name: Optional explicit worksheet name when several sheets match.
        snapshot_date: Optional ISO date. Highest priority; never a clock.
        source_filename: Optional filename used only as a dated fallback.
        collected_at: Optional collection timestamp used last and as uncertain.

    Returns:
        An immutable mapping. Ambiguous sheets yield a structured status and
        no facts rather than choosing an arbitrary worksheet.
    """
    if not isinstance(workbook, WorkbookEvidence):
        raise TypeError("workbook must be WorkbookEvidence")
    request = MappingRequest(workbook, sheet_name, snapshot_date, source_filename, collected_at)
    return _map_request(request)


def _map_request(request: MappingRequest) -> ExactOverviewMapping:
    selection = select_overview_sheet(request.workbook, request.sheet_name)
    if selection.status != "mapped" or selection.sheet is None:
        snapshot, date_issues = resolve_snapshot(
            request.workbook,
            None,
            request.snapshot_date,
            request.source_filename,
            request.collected_at,
        )
        return _empty_mapping(request, selection, snapshot, date_issues)
    return _map_sheet(request, selection)


def _map_sheet(request: MappingRequest, selection: SheetSelection) -> ExactOverviewMapping:
    sheet = selection.sheet
    if sheet is None:
        snapshot, date_issues = resolve_snapshot(
            request.workbook,
            None,
            request.snapshot_date,
            request.source_filename,
            request.collected_at,
        )
        return _empty_mapping(request, selection, snapshot, date_issues)
    layout = detect_layout(sheet, request.workbook.date1904)
    snapshot, date_issues = resolve_snapshot(
        request.workbook,
        sheet,
        request.snapshot_date,
        request.source_filename,
        request.collected_at,
    )
    facts = _build_facts(layout)
    built = _Built(request, selection, layout, snapshot, facts, date_issues)
    return _mapping_result(built)


def _mapping_result(built: _Built) -> ExactOverviewMapping:
    request, selection, layout, snapshot = (
        built.request,
        built.selection,
        built.layout,
        built.snapshot,
    )
    issues = selection.issues + layout.issues + built.date_issues
    return ExactOverviewMapping(
        status="mapped",
        parser_version=PARSER_VERSION,
        temporal_policy=TEMPORAL_POLICY,
        source_sha256=request.workbook.source_sha256,
        date1904=request.workbook.date1904,
        sheet_name=layout.sheet.name,
        snapshot=snapshot,
        facts=built.facts,
        balances=_map_balances(layout, snapshot),
        cashflows=_map_cashflows(layout, snapshot),
        insurance=_map_insurance(layout, snapshot),
        investments=_map_investments(layout, snapshot),
        loans=_map_loans(layout, snapshot),
        candidate_sheet_names=selection.candidates,
        explicit_snapshot_date=request.snapshot_date,
        source_filename=request.source_filename,
        collected_at=request.collected_at,
        issues=issues,
    )


def _empty_mapping(
    request: MappingRequest,
    selection: SheetSelection,
    snapshot: SnapshotDateEvidence,
    extra: tuple[ExactOverviewIssue, ...],
) -> ExactOverviewMapping:
    return ExactOverviewMapping(
        status=selection.status,
        parser_version=PARSER_VERSION,
        temporal_policy=TEMPORAL_POLICY,
        source_sha256=request.workbook.source_sha256,
        date1904=request.workbook.date1904,
        sheet_name=None if selection.sheet is None else selection.sheet.name,
        snapshot=snapshot,
        facts=(),
        balances=(),
        cashflows=(),
        insurance=(),
        investments=(),
        loans=(),
        candidate_sheet_names=selection.candidates,
        explicit_snapshot_date=request.snapshot_date,
        source_filename=request.source_filename,
        collected_at=request.collected_at,
        issues=selection.issues + extra,
    )


def _build_facts(layout: OverviewLayout) -> tuple[ExactOverviewFact, ...]:
    return tuple(_fact_from_cell(layout, cell) for cell in content_cells(layout.sheet))


def _fact_from_cell(layout: OverviewLayout, cell: CellEvidence) -> ExactOverviewFact:
    block_id, block_title = _block_for(layout, cell)
    kind = _fact_kind(layout, cell)
    row_label, column_label = _labels_for(layout, cell, kind)
    view = _cell_value_view(cell)
    return ExactOverviewFact(
        sheet_name=layout.sheet.name,
        source_row=cell.row,
        column=cell.column,
        cell=cell,
        block_id=block_id,
        block_title=block_title,
        fact_kind=kind,
        row_label=row_label,
        column_label=column_label,
        value_type=view.value_type,  # type: ignore[arg-type]
        number_value=view.number_value,  # type: ignore[arg-type]
        text_value=view.text_value,
        parsed_date=view.parsed_date,  # type: ignore[arg-type]
        unverified=view.unverified,
        issues=view.issues,
    )


def _cell_value_view(cell: CellEvidence) -> _ValueView:
    if cell.cell_type in {"b", "e"}:
        code = "NUMBER_BOOLEAN" if cell.cell_type == "b" else "NUMBER_ERROR_CELL"
        bad = issue(code, field_name="number", source_row=cell.row, column=cell.column)
        extra = formula_issues(cell, "number")
        return _ValueView("unsupported", None, cell_text(cell), None, False, (bad,) + extra)
    dated = _date_value_view(cell)
    if dated is not None:
        return dated
    return _number_or_text_view(cell)


def _date_value_view(cell: CellEvidence) -> _ValueView | None:
    if not is_date_text_cell(cell):
        return None
    parsed = parse_source_date(cell, False, "number")
    if parsed.value is None:
        return None
    unverified = any(item.code == "FORMULA_CACHED_UNVERIFIED" for item in parsed.issues)
    return _ValueView("date", None, cell_text(cell), parsed.value, unverified, parsed.issues)


def _number_or_text_view(cell: CellEvidence) -> _ValueView:
    parsed = parse_number(cell)
    text = cell_text(cell)
    if parsed.value is not None:
        return _ValueView("number", parsed.value, text, None, parsed.unverified, parsed.issues)
    if text:
        return _ValueView("text", None, text, None, parsed.unverified, parsed.issues)
    return _ValueView("unsupported", None, text, None, parsed.unverified, parsed.issues)


def _block_for(layout: OverviewLayout, cell: CellEvidence) -> tuple[str | None, str | None]:
    for section in layout.sections:
        if section.anchor_row <= cell.row <= section.end_row:
            return section.block_id, section.block_title
    cashflow = layout.cashflow
    if cashflow is not None and cashflow.anchor_row <= cell.row <= cashflow.end_row:
        return _CASHFLOW_BLOCK_ID, _CASHFLOW_BLOCK_TITLE
    balance = layout.balance
    if balance is not None and balance.start_row <= cell.row <= balance.end_row:
        return _BALANCE_BLOCK_ID, _BALANCE_BLOCK_TITLE
    return None, None


def _fact_kind(layout: OverviewLayout, cell: CellEvidence) -> str:
    if row_is_summary(_summary_cells(layout, cell)):
        return "summary"
    if _is_section_anchor(layout, cell):
        return "section_label"
    if cell.row in _header_rows(layout):
        return "cell"
    if _in_table_body(layout, cell.row):
        return "table_value"
    return "cell"


def _summary_cells(layout: OverviewLayout, cell: CellEvidence) -> tuple[CellEvidence, ...]:
    cells = cells_in_row(layout.sheet, cell.row)
    balance = layout.balance
    if balance is None or not balance.start_row <= cell.row <= balance.end_row:
        return cells
    for spec in (balance.asset, balance.liability):
        if spec is not None:
            band = side_row_cells(cells, spec)
            if cell in band:
                return band
    return (cell,)


def _is_section_anchor(layout: OverviewLayout, cell: CellEvidence) -> bool:
    for section in layout.sections:
        if section.anchor_cell.reference == cell.reference:
            return True
    cashflow = layout.cashflow
    if cashflow is None:
        return False
    return cashflow.anchor_row == cell.row and cashflow.anchor_column == cell.column


def _header_rows(layout: OverviewLayout) -> frozenset[int]:
    rows: list[int] = []
    if layout.balance is not None and layout.balance.asset is not None:
        rows.append(layout.balance.asset.header_row)
    if layout.balance is not None and layout.balance.liability is not None:
        rows.append(layout.balance.liability.header_row)
    if layout.cashflow is not None and layout.cashflow.header_row is not None:
        rows.append(layout.cashflow.header_row)
    for table in (layout.insurance, layout.investments, layout.loans):
        if table is not None and table.header_row is not None:
            rows.append(table.header_row)
    return frozenset(rows)


def _in_table_body(layout: OverviewLayout, row: int) -> bool:
    if layout.balance is not None and layout.balance.usable:
        headers = _header_rows(layout)
        if layout.balance.start_row < row <= layout.balance.end_row and row not in headers:
            return True
    cashflow = layout.cashflow
    if cashflow is not None and cashflow.usable and cashflow.header_row is not None:
        if cashflow.header_row < row <= cashflow.end_row:
            return True
    return _in_structured_body(layout, row)


def _in_structured_body(layout: OverviewLayout, row: int) -> bool:
    for table in (layout.insurance, layout.investments, layout.loans):
        if table is None or not table.usable or table.header_row is None:
            continue
        if table.header_row < row <= table.section.end_row:
            return True
    return False


def _labels_for(
    layout: OverviewLayout, cell: CellEvidence, kind: str
) -> tuple[str | None, str | None]:
    row_label = None
    if kind in {"table_value", "summary"}:
        row_label = _first_row_text(cells_in_row(layout.sheet, cell.row))
    return row_label, _column_label(layout, cell)


def _first_row_text(cells: tuple[CellEvidence, ...]) -> str | None:
    for cell in cells:
        text = cell_text(cell)
        if text:
            return text
    return None


def _column_label(layout: OverviewLayout, cell: CellEvidence) -> str | None:
    balance = layout.balance
    if balance is not None and balance.asset is not None and balance.liability is not None:
        label = _balance_column_label(layout, balance, cell)
        if label is not None:
            return label
    return _header_text_at(layout, cell)


def _balance_column_label(
    layout: OverviewLayout, table: BalanceTable, cell: CellEvidence
) -> str | None:
    for spec in (table.asset, table.liability):
        if spec is None:
            continue
        header = cell_in_column(cells_in_row(layout.sheet, spec.header_row), cell.column)
        if header is None:
            continue
        text = cell_text(header)
        if text:
            return f"{spec.title}:{text}"
    return None


def _header_text_at(layout: OverviewLayout, cell: CellEvidence) -> str | None:
    for header_row in _header_rows(layout):
        header = cell_in_column(cells_in_row(layout.sheet, header_row), cell.column)
        if header is not None:
            return cell_text(header)
    return None


def _map_balances(
    layout: OverviewLayout, snapshot: SnapshotDateEvidence
) -> tuple[ExactBalanceObservation, ...]:
    table = layout.balance
    if table is None or not table.usable or table.asset is None or table.liability is None:
        return ()
    rows: list[ExactBalanceObservation] = []
    for spec in (table.asset, table.liability):
        rows.extend(_map_balance_side(layout, spec, table.end_row, snapshot))
    return tuple(rows)


def _map_balance_side(
    layout: OverviewLayout, spec: SideSpec, end_row: int, snapshot: SnapshotDateEvidence
) -> tuple[ExactBalanceObservation, ...]:
    currency = header_currency(side_header_cells(layout.sheet, spec))
    ctx = _PayCtx(layout.sheet.name, snapshot, currency, layout.date1904)
    rows: list[ExactBalanceObservation] = []
    for row in populated_rows_between(layout.sheet, spec.header_row, end_row):
        cells = side_row_cells(cells_in_row(layout.sheet, row), spec)
        if row_is_summary(cells):
            continue
        mapped = _balance_row(ctx, spec, cells)
        if mapped is not None:
            rows.append(mapped)
    return tuple(rows)


def _balance_row(
    ctx: _PayCtx, spec: SideSpec, cells: tuple[CellEvidence, ...]
) -> ExactBalanceObservation | None:
    category = _text_field("category", cell_in_column(cells, spec.category_column))
    item = _item_field(category, cell_in_column(cells, spec.item_column))
    if item.text is None:
        return None
    amount = _money_field("amount", cell_in_column(cells, spec.amount_column), ctx.currency)
    issues = category.issues + item.issues + amount.issues + _date_required(ctx.snapshot)
    supported = ctx.snapshot.parsed_date is not None and amount.exact_value is not None
    return ExactBalanceObservation(
        sheet_name=ctx.sheet_name,
        source_row=cells[0].row,
        side=spec.side,
        category=category,
        item_name=item,
        amount=amount,
        snapshot=ctx.snapshot,
        source_column=spec.amount_column,
        supported=supported,
        issues=issues,
    )


def _map_cashflows(
    layout: OverviewLayout, snapshot: SnapshotDateEvidence
) -> tuple[ExactCashflowObservation, ...]:
    table = layout.cashflow
    if table is None or not table.usable or table.header_row is None:
        return ()
    currency = header_currency(cells_in_row(layout.sheet, table.header_row))
    ctx = _PayCtx(layout.sheet.name, snapshot, currency, layout.date1904)
    rows: list[ExactCashflowObservation] = []
    for row in populated_rows_between(layout.sheet, table.header_row, table.end_row):
        cells = cells_in_row(layout.sheet, row)
        if row_is_summary(cells):
            continue
        rows.extend(_cashflow_row(ctx, table, cells))
    return tuple(rows)


def _cashflow_row(
    ctx: _PayCtx, table: CashflowTable, cells: tuple[CellEvidence, ...]
) -> tuple[ExactCashflowObservation, ...]:
    category = _text_field("category", cell_in_column(cells, table.category_column))
    if category.text is None:
        return ()
    mapped = [_cashflow_amount(ctx, category, month, cells) for month in table.month_columns]
    return tuple(item for item in mapped if item is not None)


def _cashflow_amount(
    ctx: _PayCtx,
    category: MappedField,
    month: tuple[str, str, CellEvidence],
    cells: tuple[CellEvidence, ...],
) -> ExactCashflowObservation | None:
    column, period, header = month
    amount_cell = cell_in_column(cells, column)
    if amount_cell is None:
        return None
    period_field = _period_field(period, header, ctx.date1904)
    amount = _money_field("amount", amount_cell, ctx.currency)
    issues = category.issues + period_field.issues + amount.issues + _date_required(ctx.snapshot)
    supported = ctx.snapshot.parsed_date is not None and amount.exact_value is not None
    return ExactCashflowObservation(
        sheet_name=ctx.sheet_name,
        source_row=cells[0].row,
        category=category,
        period_month=period_field,
        amount=amount,
        snapshot=ctx.snapshot,
        source_column=column,
        supported=supported,
        issues=issues,
    )


def _struct_ctx(
    layout: OverviewLayout, snapshot: SnapshotDateEvidence, table: StructuredTable
) -> _StructCtx:
    columns = binding_map(table)
    header_row = table.header_row
    headers = () if header_row is None else cells_in_row(layout.sheet, header_row)
    currency = header_currency(headers)
    return _StructCtx(layout, snapshot, currency, columns)


def _map_insurance(
    layout: OverviewLayout, snapshot: SnapshotDateEvidence
) -> tuple[ExactInsuranceRow, ...]:
    table = layout.insurance
    if table is None or not table.usable or table.header_row is None:
        return ()
    ctx = _struct_ctx(layout, snapshot, table)
    rows = [
        _insurance_row(ctx, row)
        for row in populated_rows_between(layout.sheet, table.header_row, table.section.end_row)
    ]
    return tuple(item for item in rows if item is not None)


def _insurance_row(ctx: _StructCtx, row: int) -> ExactInsuranceRow | None:
    cells = cells_in_row(ctx.layout.sheet, row)
    if row_is_summary(cells):
        return None
    institution, policy = _named_pair(cells, ctx.columns, "institution", "policy_name")
    if institution is None or policy is None:
        return None
    paid = _optional_money(
        "paid_amount", cell_in_column(cells, ctx.columns.get("paid_amount")), ctx.currency
    )
    status = _text_field(
        "contract_status", cell_in_column(cells, ctx.columns.get("contract_status"))
    )
    contract = _date_field(
        "contract_date", cell_in_column(cells, ctx.columns.get("contract_date")), ctx
    )
    maturity = _date_field(
        "maturity_date", cell_in_column(cells, ctx.columns.get("maturity_date")), ctx
    )
    issues = (
        institution.issues
        + policy.issues
        + status.issues
        + paid.issues
        + contract.issues
        + maturity.issues
        + _date_required(ctx.snapshot)
    )
    return ExactInsuranceRow(
        sheet_name=ctx.layout.sheet.name,
        source_row=row,
        institution=institution,
        policy_name=policy,
        contract_status=status,
        paid_amount=paid,
        contract_date=contract,
        maturity_date=maturity,
        snapshot=ctx.snapshot,
        source_column=ctx.columns.get("policy_name") or ctx.columns["institution"],
        supported=ctx.snapshot.parsed_date is not None,
        issues=issues,
    )


def _map_investments(
    layout: OverviewLayout, snapshot: SnapshotDateEvidence
) -> tuple[ExactInvestmentRow, ...]:
    table = layout.investments
    if table is None or not table.usable or table.header_row is None:
        return ()
    ctx = _struct_ctx(layout, snapshot, table)
    rows = [
        _investment_row(ctx, row)
        for row in populated_rows_between(layout.sheet, table.header_row, table.section.end_row)
    ]
    return tuple(item for item in rows if item is not None)


def _investment_row(ctx: _StructCtx, row: int) -> ExactInvestmentRow | None:
    cells = cells_in_row(ctx.layout.sheet, row)
    pair = _named_pair(cells, ctx.columns, "institution", "product_name")
    if row_is_summary(cells) or pair[0] is None or pair[1] is None:
        return None
    amounts = _investment_amounts(ctx, cells)
    start = _date_field("start_date", cell_in_column(cells, ctx.columns.get("start_date")), ctx)
    maturity = _date_field(
        "maturity_date", cell_in_column(cells, ctx.columns.get("maturity_date")), ctx
    )
    product_type = _text_field(
        "product_type", cell_in_column(cells, ctx.columns.get("product_type"))
    )
    issues = (
        pair[0].issues
        + pair[1].issues
        + product_type.issues
        + amounts[0].issues
        + amounts[1].issues
        + amounts[2].issues
        + start.issues
        + maturity.issues
    )
    return ExactInvestmentRow(
        sheet_name=ctx.layout.sheet.name,
        source_row=row,
        product_type=product_type,
        institution=pair[0],
        product_name=pair[1],
        principal_amount=amounts[0],
        valuation_amount=amounts[1],
        return_rate=amounts[2],
        start_date=start,
        maturity_date=maturity,
        snapshot=ctx.snapshot,
        source_column=ctx.columns.get("product_name") or ctx.columns["institution"],
        supported=ctx.snapshot.parsed_date is not None,
        issues=issues + _date_required(ctx.snapshot),
    )


def _investment_amounts(
    ctx: _StructCtx, cells: tuple[CellEvidence, ...]
) -> tuple[MappedField, ...]:
    principal = _optional_money(
        "principal_amount", cell_in_column(cells, ctx.columns.get("principal_amount")), ctx.currency
    )
    valuation = _optional_money(
        "valuation_amount", cell_in_column(cells, ctx.columns.get("valuation_amount")), ctx.currency
    )
    rate = _optional_rate("return_rate", cell_in_column(cells, ctx.columns.get("return_rate")))
    return principal, valuation, rate


def _map_loans(layout: OverviewLayout, snapshot: SnapshotDateEvidence) -> tuple[ExactLoanRow, ...]:
    table = layout.loans
    if table is None or not table.usable or table.header_row is None:
        return ()
    ctx = _struct_ctx(layout, snapshot, table)
    rows = [
        _loan_row(ctx, row)
        for row in populated_rows_between(layout.sheet, table.header_row, table.section.end_row)
    ]
    return tuple(item for item in rows if item is not None)


def _loan_row(ctx: _StructCtx, row: int) -> ExactLoanRow | None:
    cells = cells_in_row(ctx.layout.sheet, row)
    pair = _named_pair(cells, ctx.columns, "institution", "product_name")
    if row_is_summary(cells) or pair[0] is None or pair[1] is None:
        return None
    amounts = _loan_amounts(ctx, cells)
    start = _date_field("start_date", cell_in_column(cells, ctx.columns.get("start_date")), ctx)
    maturity = _date_field(
        "maturity_date", cell_in_column(cells, ctx.columns.get("maturity_date")), ctx
    )
    loan_type = _text_field("loan_type", cell_in_column(cells, ctx.columns.get("loan_type")))
    issues = (
        pair[0].issues
        + pair[1].issues
        + loan_type.issues
        + amounts[0].issues
        + amounts[1].issues
        + amounts[2].issues
        + start.issues
        + maturity.issues
    )
    return ExactLoanRow(
        sheet_name=ctx.layout.sheet.name,
        source_row=row,
        loan_type=loan_type,
        institution=pair[0],
        product_name=pair[1],
        principal_amount=amounts[0],
        balance_amount=amounts[1],
        interest_rate=amounts[2],
        start_date=start,
        maturity_date=maturity,
        snapshot=ctx.snapshot,
        source_column=ctx.columns.get("product_name") or ctx.columns["institution"],
        supported=ctx.snapshot.parsed_date is not None,
        issues=issues + _date_required(ctx.snapshot),
    )


def _loan_amounts(ctx: _StructCtx, cells: tuple[CellEvidence, ...]) -> tuple[MappedField, ...]:
    principal = _optional_money(
        "principal_amount", cell_in_column(cells, ctx.columns.get("principal_amount")), ctx.currency
    )
    balance = _optional_money(
        "balance_amount", cell_in_column(cells, ctx.columns.get("balance_amount")), ctx.currency
    )
    rate = _optional_rate("interest_rate", cell_in_column(cells, ctx.columns.get("interest_rate")))
    return principal, balance, rate


def _named_pair(
    cells: tuple[CellEvidence, ...], columns: dict[str, str], left: str, right: str
) -> tuple[MappedField | None, MappedField | None]:
    first = _text_field(left, cell_in_column(cells, columns.get(left)))
    second = _text_field(right, cell_in_column(cells, columns.get(right)))
    if first.text is None or second.text is None:
        return None, None
    return first, second


def _item_field(category: MappedField, cell: CellEvidence | None) -> MappedField:
    item = _text_field("item_name", cell)
    if item.text is not None:
        return item
    if cell is not None and item.issues:
        return item
    if category.text is None:
        return item
    return MappedField("item_name", category.text, None, None, None, item.cell, False, ())


def _text_field(name: str, cell: CellEvidence | None) -> MappedField:
    if cell is None:
        return MappedField(name, None, None, None, None, None, False, ())
    formula = formula_issues(cell, name)
    unverified = any(item.code == "FORMULA_CACHED_UNVERIFIED" for item in formula)
    if cell.cell_type in {"b", "e"}:
        bad = issue("INVALID_TEXT_CELL", field_name=name, source_row=cell.row, column=cell.column)
        return MappedField(name, None, None, None, None, cell, unverified, (bad,) + formula)
    if any(item.code == "FORMULA_CACHE_MISSING" for item in formula):
        return MappedField(name, None, None, None, None, cell, False, formula)
    return MappedField(name, cell_text(cell), None, None, None, cell, unverified, formula)


def _period_field(period: str, header: CellEvidence, date1904: bool) -> MappedField:
    _text, parsed = parse_period_month(header, date1904)
    unverified = any(item.code == "FORMULA_CACHED_UNVERIFIED" for item in parsed.issues)
    return MappedField(
        "period_month", period, None, None, period, header, unverified, parsed.issues
    )


def _optional_money(name: str, cell: CellEvidence | None, currency: CurrencyPart) -> MappedField:
    if cell is None:
        return _text_field(name, None)
    return _money_field(name, cell, currency)


def _optional_rate(name: str, cell: CellEvidence | None) -> MappedField:
    if cell is None:
        return _text_field(name, None)
    return _rate_field(name, cell)


def _money_field(name: str, cell: CellEvidence | None, currency: CurrencyPart) -> MappedField:
    parsed = parse_money(cell, name, currency)
    return MappedField(
        name, cell_text(cell), parsed.value, None, None, cell, parsed.unverified, parsed.issues
    )


def _rate_field(name: str, cell: CellEvidence | None) -> MappedField:
    parsed = parse_rate(cell, name)
    return MappedField(
        name, cell_text(cell), parsed.value, None, None, cell, parsed.unverified, parsed.issues
    )


def _date_field(name: str, cell: CellEvidence | None, ctx: _StructCtx) -> MappedField:
    parsed = parse_source_date(cell, ctx.layout.date1904, name)
    unverified = any(item.code == "FORMULA_CACHED_UNVERIFIED" for item in parsed.issues)
    return MappedField(
        name, cell_text(cell), None, parsed.value, parsed.raw, cell, unverified, parsed.issues
    )


def _date_required(snapshot: SnapshotDateEvidence) -> tuple[ExactOverviewIssue, ...]:
    if snapshot.parsed_date is not None:
        return ()
    return (issue("MISSING_SNAPSHOT_DATE", field_name="snapshot_date"),)
