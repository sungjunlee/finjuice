"""Frozen DTOs for pure overview evidence mapping."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from finjuice.pipeline.ingest.xlsx_evidence import CellEvidence, SheetEvidence, WorkbookEvidence
from finjuice.pipeline.storage.sqlite.exact import ExactValue

MappingStatus = Literal[
    "mapped",
    "no_overview_sheet",
    "sheet_not_found",
    "not_overview_sheet",
    "ambiguous_sheets",
]
DateOrigin = Literal["explicit", "source_label", "filename", "collected_at", "missing"]
FactValueType = Literal["number", "text", "date", "empty", "unsupported"]


@dataclass(frozen=True)
class ExactOverviewIssue:
    """One structured mapping issue that never embeds private source values."""

    code: str
    field_name: str | None = None
    source_row: int | None = None
    column: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class SnapshotDateEvidence:
    """Snapshot date plus origin, coordinates, and reliability flags."""

    parsed_date: date | None
    raw: str | None
    origin: DateOrigin
    kind: str | None
    serial_lexical: str | None
    source_sheet: str | None
    source_row: int | None
    source_column: str | None
    date1904: bool
    temporal_policy: str
    uncertainty: tuple[str, ...]
    reliable: bool


@dataclass(frozen=True)
class MappedField:
    """One typed field with exact value, text, and source cell provenance."""

    field_name: str
    text: str | None
    exact_value: ExactValue | None
    parsed_date: date | None
    date_raw: str | None
    cell: CellEvidence | None
    unverified: bool
    issues: tuple[ExactOverviewIssue, ...]


@dataclass(frozen=True)
class ExactOverviewFact:
    """One nonempty source cell keyed by sheet, row, and column."""

    sheet_name: str
    source_row: int
    column: str
    cell: CellEvidence
    block_id: str | None
    block_title: str | None
    fact_kind: str
    row_label: str | None
    column_label: str | None
    value_type: FactValueType
    number_value: ExactValue | None
    text_value: str | None
    parsed_date: date | None
    unverified: bool
    issues: tuple[ExactOverviewIssue, ...]


@dataclass(frozen=True)
class ExactBalanceObservation:
    """Asset or liability snapshot row distinct from summary facts."""

    sheet_name: str
    source_row: int
    side: str
    category: MappedField
    item_name: MappedField
    amount: MappedField
    snapshot: SnapshotDateEvidence
    source_column: str
    supported: bool
    issues: tuple[ExactOverviewIssue, ...]


@dataclass(frozen=True)
class ExactCashflowObservation:
    """Monthly cashflow cell projection."""

    sheet_name: str
    source_row: int
    category: MappedField
    period_month: MappedField
    amount: MappedField
    snapshot: SnapshotDateEvidence
    source_column: str
    supported: bool
    issues: tuple[ExactOverviewIssue, ...]


@dataclass(frozen=True)
class ExactInsuranceRow:
    """Insurance projection with source text and optional paid amount."""

    sheet_name: str
    source_row: int
    institution: MappedField
    policy_name: MappedField
    contract_status: MappedField
    paid_amount: MappedField
    contract_date: MappedField
    maturity_date: MappedField
    snapshot: SnapshotDateEvidence
    source_column: str
    supported: bool
    issues: tuple[ExactOverviewIssue, ...]


@dataclass(frozen=True)
class ExactInvestmentRow:
    """Investment projection with source amounts and source-only rate."""

    sheet_name: str
    source_row: int
    product_type: MappedField
    institution: MappedField
    product_name: MappedField
    principal_amount: MappedField
    valuation_amount: MappedField
    return_rate: MappedField
    start_date: MappedField
    maturity_date: MappedField
    snapshot: SnapshotDateEvidence
    source_column: str
    supported: bool
    issues: tuple[ExactOverviewIssue, ...]


@dataclass(frozen=True)
class ExactLoanRow:
    """Loan projection with source amounts and source-only rate."""

    sheet_name: str
    source_row: int
    loan_type: MappedField
    institution: MappedField
    product_name: MappedField
    principal_amount: MappedField
    balance_amount: MappedField
    interest_rate: MappedField
    start_date: MappedField
    maturity_date: MappedField
    snapshot: SnapshotDateEvidence
    source_column: str
    supported: bool
    issues: tuple[ExactOverviewIssue, ...]


@dataclass(frozen=True)
class ExactOverviewMapping:
    """Immutable workbook-level overview mapping result."""

    status: MappingStatus
    parser_version: str
    temporal_policy: str
    source_sha256: str
    date1904: bool
    sheet_name: str | None
    snapshot: SnapshotDateEvidence
    facts: tuple[ExactOverviewFact, ...]
    balances: tuple[ExactBalanceObservation, ...]
    cashflows: tuple[ExactCashflowObservation, ...]
    insurance: tuple[ExactInsuranceRow, ...]
    investments: tuple[ExactInvestmentRow, ...]
    loans: tuple[ExactLoanRow, ...]
    candidate_sheet_names: tuple[str, ...]
    explicit_snapshot_date: str | None
    source_filename: str | None
    collected_at: str | None
    issues: tuple[ExactOverviewIssue, ...]


@dataclass(frozen=True)
class ColumnBinding:
    """Catalog field bound to one unique header cell."""

    field_name: str
    column: str
    header_text: str
    header_cell: CellEvidence


@dataclass(frozen=True)
class SectionRange:
    """Numbered overview section spanning captured rows."""

    block_id: str
    block_title: str
    anchor_row: int
    anchor_column: str
    end_row: int
    anchor_cell: CellEvidence


@dataclass(frozen=True)
class SideSpec:
    """One balance side with unique category, item, and amount columns."""

    side: str
    title: str
    anchor_column: str
    end_column: str | None
    header_row: int
    category_column: str | None
    item_column: str | None
    amount_column: str
    amount_header: str


@dataclass(frozen=True)
class BalanceTable:
    """Detected asset/liability table, or an unusable ambiguous layout."""

    asset: SideSpec | None
    liability: SideSpec | None
    start_row: int
    end_row: int
    usable: bool
    issues: tuple[ExactOverviewIssue, ...]


@dataclass(frozen=True)
class CashflowTable:
    """Detected monthly cashflow table, or an unusable ambiguous layout."""

    anchor_row: int
    anchor_column: str
    header_row: int | None
    end_row: int
    category_column: str | None
    month_columns: tuple[tuple[str, str, CellEvidence], ...]
    usable: bool
    issues: tuple[ExactOverviewIssue, ...]


@dataclass(frozen=True)
class StructuredTable:
    """Insurance, investment, or loan header mapping."""

    kind: str
    section: SectionRange
    header_row: int | None
    bindings: tuple[ColumnBinding, ...]
    usable: bool
    issues: tuple[ExactOverviewIssue, ...]


@dataclass(frozen=True)
class OverviewLayout:
    """Structural catalog matches for one selected sheet."""

    sheet: SheetEvidence
    date1904: bool
    sections: tuple[SectionRange, ...]
    balance: BalanceTable | None
    cashflow: CashflowTable | None
    insurance: StructuredTable | None
    investments: StructuredTable | None
    loans: StructuredTable | None
    issues: tuple[ExactOverviewIssue, ...]


@dataclass(frozen=True)
class SheetSelection:
    """Result of overview worksheet selection."""

    status: MappingStatus
    sheet: SheetEvidence | None
    candidates: tuple[str, ...]
    issues: tuple[ExactOverviewIssue, ...]


@dataclass(frozen=True)
class MappingRequest:
    """Caller inputs for one pure overview mapping."""

    workbook: WorkbookEvidence
    sheet_name: str | None
    snapshot_date: str | None
    source_filename: str | None
    collected_at: str | None


@dataclass(frozen=True)
class NumberSpec:
    """Exact numeric capture policy for one source field."""

    field_name: str
    value_kind: str
    currency: object | None = None
    unit: str | None = None


@dataclass(frozen=True)
class DatePart:
    """Parsed civil date plus raw evidence and issues."""

    value: date | None
    kind: str | None
    raw: str | None
    serial_lexical: str | None
    cell: CellEvidence | None
    issues: tuple[ExactOverviewIssue, ...]
    uncertainty: tuple[str, ...] = ()


@dataclass(frozen=True)
class CurrencyPart:
    """Explicit currency evidence, or unknown without a KRW default."""

    code: str | None
    unknown: bool
    issues: tuple[ExactOverviewIssue, ...]
    unverified: bool = False


@dataclass(frozen=True)
class NumericPart:
    """Exact numeric capture plus unverified/formula flags."""

    value: ExactValue | None
    unverified: bool
    issues: tuple[ExactOverviewIssue, ...]
