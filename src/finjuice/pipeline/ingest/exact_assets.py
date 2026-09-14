"""Pure WorkbookEvidence -> exact asset-snapshot mapping.

The mapper never rereads files, never converts numbers through ``float``,
Polars, or openpyxl, never evaluates formulas, and never mints entity IDs.
Quantity uses a versioned source-quantity unit; money never defaults to KRW.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Final, Literal

from finjuice.pipeline.ingest.exact_transactions import (
    TEMPORAL_POLICY,
    ExactTransactionIssue,
    _cell_has_content,
    _cell_plain_text,
    _cells_by_row,
    _excel_days_to_date,
    _is_text_cell,
    _optional_text,
    _parse_iso_date,
    _parse_iso_datetime,
    _split_serial,
)
from finjuice.pipeline.ingest.schemas_assets import ASSET_SCHEMAS, _missing_required_asset_fields
from finjuice.pipeline.ingest.schemas_helpers import is_asset_sheet_name
from finjuice.pipeline.ingest.xlsx_evidence import CellEvidence, SheetEvidence, WorkbookEvidence
from finjuice.pipeline.storage.sqlite.errors import ExactValueError
from finjuice.pipeline.storage.sqlite.exact import (
    UNKNOWN_CURRENCY,
    CurrencyState,
    ExactValue,
    ValueKind,
)

PARSER_VERSION: Final = "finjuice.xlsx-asset-mapper.v1"
QUANTITY_UNIT: Final = "source_quantity.v1"
MappingStatus = Literal[
    "mapped",
    "no_asset_sheet",
    "sheet_not_found",
    "not_asset_sheet",
    "ambiguous_sheets",
    "ambiguous_headers",
    "duplicate_field_mapping",
]
DateSource = Literal["row", "explicit", "collected_at", "missing"]
_CURRENCY_RE: Final = re.compile(r"^[A-Z]{3}$")
_PLAIN_DECIMAL_RE: Final = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")

_HEADER_FIELD: Final[dict[str, str]] = {}
for _schema in ASSET_SCHEMAS.values():
    for _field_name in _schema.__dataclass_fields__:
        if _field_name == "version":
            continue
        for _variant in getattr(_schema, _field_name):
            _HEADER_FIELD[_variant] = _field_name

_ISSUE_DETAIL: Final[dict[str, str]] = {
    "AMBIGUOUS_SHEETS": ("Multiple worksheets match the asset snapshot catalog; pass sheet_name."),
    "AMBIGUOUS_HEADERS": "More than one uniquely complete asset header row is present.",
    "DUPLICATE_FIELD_MAPPING": "An asset field maps to more than one header cell.",
    "SHEET_NOT_FOUND": "The requested sheet_name is not present in the workbook evidence.",
    "NOT_ASSET_SHEET": "The selected sheet does not match the asset header catalog.",
    "NO_ASSET_SHEET": "No worksheet matches the asset snapshot header catalog.",
    "INVALID_EXPLICIT_SNAPSHOT_DATE": (
        "Caller snapshot_date is not a supported ISO date and was not used."
    ),
    "INVALID_COLLECTED_AT": (
        "Caller collected_at is not a supported ISO date or datetime and was not used."
    ),
    "QUANTITY_MISSING": "The quantity cell is missing or empty.",
    "QUANTITY_BOOLEAN": "Boolean cells are unsupported quantity evidence.",
    "QUANTITY_ERROR_CELL": "Error cells are unsupported quantity evidence.",
    "QUANTITY_FORMATTED": "Formatted or decorated quantity text is unsupported.",
    "QUANTITY_NONFINITE": "Non-finite quantity lexemes are unsupported.",
    "QUANTITY_SCALE_OUT_OF_RANGE": "Quantity scale is outside the ExactValue bound 0..255.",
    "UNSUPPORTED_QUANTITY": "The quantity lexeme cannot be captured as ExactValue quantity.",
    "MARKET_VALUE_MISSING": "The market_value cell is missing or empty.",
    "MARKET_VALUE_BOOLEAN": "Boolean cells are unsupported money evidence.",
    "MARKET_VALUE_ERROR_CELL": "Error cells are unsupported money evidence.",
    "MARKET_VALUE_FORMATTED": "Formatted or decorated market_value text is unsupported.",
    "MARKET_VALUE_NONFINITE": "Non-finite market_value lexemes are unsupported.",
    "MARKET_VALUE_SCALE_OUT_OF_RANGE": (
        "Market value scale is outside the ExactValue bound 0..255."
    ),
    "UNSUPPORTED_MARKET_VALUE": "The market_value lexeme cannot be captured as ExactValue money.",
    "FORMULA_CACHE_MISSING": "A formula without a cached value is unsupported.",
    "FORMULA_CACHED_UNVERIFIED": (
        "Cached formula results are captured evidence, not verified values."
    ),
    "UNKNOWN_CURRENCY": "Currency is missing or not an uppercase three-letter code.",
    "MISSING_SNAPSHOT_DATE": "No reliable snapshot date or documented fallback is available.",
    "INVALID_DATE": "The snapshot date cell is not a supported ISO date or Excel serial.",
    "EXCEL_FICTITIOUS_DAY_60": "Excel 1900 serial day 60 is a fictitious leap day.",
    "DATE_OVERFLOW": "Excel serial date arithmetic overflowed the civil calendar.",
    "UNSUPPORTED_SERIAL": (
        "Excel serial lexeme exceeds SERIAL_MAX_DIGITS, SERIAL_MAX_ABS_EXPONENT, "
        "or SERIAL_MAX_LEXEME_LENGTH; raw lexeme is retained without huge powers."
    ),
    "MISSING_ACCOUNT": "Neither source account ID nor account name is present.",
    "MISSING_INSTRUMENT": "Neither source instrument ID nor instrument name is present.",
    "INVALID_IDENTITY_CELL": "Boolean and error cells cannot establish source identity text.",
}


@dataclass(frozen=True)
class ExactAssetIssue:
    """One structured mapping issue that never silently drops evidence."""

    code: str
    field_name: str | None = None
    source_row: int | None = None
    column: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class ColumnBinding:
    """Catalog field bound to one header cell and its source coordinates."""

    field_name: str
    column: str
    header_text: str
    header_cell: CellEvidence


@dataclass(frozen=True)
class UnknownCell:
    """A source cell whose header is outside the asset snapshot catalog."""

    column: str
    header_text: str | None
    cell: CellEvidence


@dataclass(frozen=True)
class SnapshotDate:
    """Interpreted snapshot date plus provenance and uncertainty flags."""

    parsed_date: date | None
    raw: str | None
    source: DateSource
    kind: str | None
    serial_lexical: str | None
    date1904: bool
    temporal_policy: str
    uncertainty: tuple[str, ...]


@dataclass(frozen=True)
class ExactMappedAssetRow:
    """One source holding row with parsed fields, raw cells, and issues."""

    sheet_name: str
    source_row: int
    cells: tuple[CellEvidence, ...]
    unknown_cells: tuple[UnknownCell, ...]
    source_account_id: str | None
    source_account_name: str | None
    source_instrument_id: str | None
    source_instrument_name: str | None
    quantity: ExactValue | None
    market_value: ExactValue | None
    quantity_unverified: bool
    market_value_unverified: bool
    currency_code: str | None
    currency_unknown: bool
    snapshot: SnapshotDate
    issues: tuple[ExactAssetIssue, ...]
    supported: bool


@dataclass(frozen=True)
class ExactAssetMapping:
    """Immutable workbook-level asset snapshot mapping result."""

    status: MappingStatus
    parser_version: str
    temporal_policy: str
    source_sha256: str
    date1904: bool
    schema_version: str | None
    sheet_name: str | None
    header_row: int | None
    bindings: tuple[ColumnBinding, ...]
    unknown_headers: tuple[UnknownCell, ...]
    rows: tuple[ExactMappedAssetRow, ...]
    skipped_blank_rows: int
    candidate_sheet_names: tuple[str, ...]
    explicit_snapshot_date: str | None
    collected_at: str | None
    issues: tuple[ExactAssetIssue, ...]


@dataclass(frozen=True)
class _HeaderAttempt:
    row: int
    bindings: tuple[ColumnBinding, ...]
    unknown: tuple[UnknownCell, ...]
    duplicate_fields: tuple[str, ...]
    complete: bool


@dataclass(frozen=True)
class _SheetMatch:
    sheet: SheetEvidence
    status: MappingStatus
    header: _HeaderAttempt | None
    issues: tuple[ExactAssetIssue, ...]


@dataclass(frozen=True)
class _DateFallbacks:
    explicit: date | None
    explicit_raw: str | None
    collected: date | None
    collected_raw: str | None
    issues: tuple[ExactAssetIssue, ...]


@dataclass(frozen=True)
class _DatePart:
    value: date | None
    kind: str | None
    raw: str | None
    serial_lexical: str | None
    issues: tuple[ExactAssetIssue, ...]
    uncertainty: tuple[str, ...] = ()


@dataclass(frozen=True)
class _CurrencyPart:
    code: str | None
    unknown: bool
    issues: tuple[ExactAssetIssue, ...]
    unverified: bool = False


@dataclass(frozen=True)
class _NumericPart:
    value: ExactValue | None
    unverified: bool
    issues: tuple[ExactAssetIssue, ...]


@dataclass(frozen=True)
class _NumberSpec:
    field_name: str
    value_kind: ValueKind
    currency: str | CurrencyState | None = None
    unit: str | None = None


@dataclass(frozen=True)
class _TextFields:
    account_id: str | None
    account_name: str | None
    instrument_id: str | None
    instrument_name: str | None
    issues: tuple[ExactAssetIssue, ...]


@dataclass(frozen=True)
class _RowContext:
    workbook: WorkbookEvidence
    sheet: SheetEvidence
    header: _HeaderAttempt
    fallbacks: _DateFallbacks


@dataclass(frozen=True)
class _ParsedRow:
    texts: _TextFields
    currency: _CurrencyPart
    quantity: _NumericPart
    market: _NumericPart
    snapshot: SnapshotDate
    issues: tuple[ExactAssetIssue, ...]


@dataclass(frozen=True)
class _SnapshotBuild:
    parsed: date | None
    origin: DateSource
    kind: str | None
    extra: tuple[str, ...]


def map_exact_assets(
    workbook: WorkbookEvidence,
    *,
    sheet_name: str | None = None,
    snapshot_date: str | None = None,
    collected_at: str | None = None,
) -> ExactAssetMapping:
    """Map captured workbook evidence into exact asset snapshot rows.

    Args:
        workbook: Immutable evidence from the completed XLSX reader.
        sheet_name: Optional explicit worksheet name when several sheets match.
        snapshot_date: Optional ISO date used only after a row date is absent
            or unusable. Never treated as a source-observed date.
        collected_at: Optional collection timestamp used only as an uncertain
            last fallback. Timezone is never inferred.

    Returns:
        An immutable mapping result. Missing or ambiguous sheets yield a
        structured status with no rows rather than guessing a worksheet.
    """

    if not isinstance(workbook, WorkbookEvidence):
        raise TypeError("workbook must be WorkbookEvidence")
    fallbacks = _parse_fallbacks(snapshot_date, collected_at)
    if sheet_name is not None:
        return _map_named_sheet(workbook, sheet_name, fallbacks)
    return _map_default(workbook, fallbacks)


def _parse_fallbacks(snapshot_date: str | None, collected_at: str | None) -> _DateFallbacks:
    explicit, explicit_issues = _parse_caller_date(
        snapshot_date, "INVALID_EXPLICIT_SNAPSHOT_DATE", allow_datetime=False
    )
    collected, collected_issues = _parse_caller_date(
        collected_at, "INVALID_COLLECTED_AT", allow_datetime=True
    )
    return _DateFallbacks(
        explicit, snapshot_date, collected, collected_at, explicit_issues + collected_issues
    )


def _parse_caller_date(
    raw: str | None, code: str, *, allow_datetime: bool
) -> tuple[date | None, tuple[ExactAssetIssue, ...]]:
    if raw is None or raw == "":
        return None, ()
    parsed = _parse_iso_date(raw)
    if parsed is not None:
        return parsed, ()
    if allow_datetime:
        stamped = _parse_iso_datetime(raw)
        if stamped is not None:
            return stamped[0], ()
    return None, (_issue(code),)


def _map_named_sheet(
    workbook: WorkbookEvidence, sheet_name: str, fallbacks: _DateFallbacks
) -> ExactAssetMapping:
    sheet = workbook.sheet(sheet_name)
    if sheet is None:
        issues = (_issue("SHEET_NOT_FOUND"),)
        return _empty_mapping(workbook, "sheet_not_found", issues, (), fallbacks)
    return _finish_match(workbook, _match_sheet_header(sheet), fallbacks)


def _map_default(workbook: WorkbookEvidence, fallbacks: _DateFallbacks) -> ExactAssetMapping:
    named = tuple(sheet for sheet in workbook.sheets if is_asset_sheet_name(sheet.name))
    if len(named) > 1:
        names = tuple(sheet.name for sheet in named)
        issues = (_issue("AMBIGUOUS_SHEETS"),)
        return _empty_mapping(workbook, "ambiguous_sheets", issues, names, fallbacks)
    if len(named) == 1:
        return _finish_match(workbook, _match_sheet_header(named[0]), fallbacks)
    return _map_catalog(workbook, fallbacks)


def _map_catalog(workbook: WorkbookEvidence, fallbacks: _DateFallbacks) -> ExactAssetMapping:
    matches = _catalog_matches(workbook)
    if not matches:
        issues = (_issue("NO_ASSET_SHEET"),)
        return _empty_mapping(workbook, "no_asset_sheet", issues, (), fallbacks)
    if len(matches) > 1:
        names = tuple(match.sheet.name for match in matches)
        issues = (_issue("AMBIGUOUS_SHEETS"),)
        return _empty_mapping(workbook, "ambiguous_sheets", issues, names, fallbacks)
    return _finish_match(workbook, matches[0], fallbacks)


def _catalog_matches(workbook: WorkbookEvidence) -> tuple[_SheetMatch, ...]:
    matches: list[_SheetMatch] = []
    for sheet in workbook.sheets:
        match = _match_sheet_header(sheet)
        if match.status != "no_asset_sheet":
            matches.append(match)
    return tuple(matches)


def _finish_match(
    workbook: WorkbookEvidence, match: _SheetMatch, fallbacks: _DateFallbacks
) -> ExactAssetMapping:
    if match.status == "no_asset_sheet":
        issues = (_issue("NOT_ASSET_SHEET"),)
        names = (match.sheet.name,)
        return _empty_mapping(workbook, "not_asset_sheet", issues, names, fallbacks)
    if match.status != "mapped" or match.header is None:
        return _empty_mapping(workbook, match.status, match.issues, (match.sheet.name,), fallbacks)
    return _map_matched_sheet(workbook, match.sheet, match.header, fallbacks)


def _empty_mapping(
    workbook: WorkbookEvidence,
    status: MappingStatus,
    issues: tuple[ExactAssetIssue, ...],
    candidates: tuple[str, ...],
    fallbacks: _DateFallbacks,
) -> ExactAssetMapping:
    return ExactAssetMapping(
        status=status,
        parser_version=PARSER_VERSION,
        temporal_policy=TEMPORAL_POLICY,
        source_sha256=workbook.source_sha256,
        date1904=workbook.date1904,
        schema_version=None,
        sheet_name=None,
        header_row=None,
        bindings=(),
        unknown_headers=(),
        rows=(),
        skipped_blank_rows=0,
        candidate_sheet_names=candidates,
        explicit_snapshot_date=fallbacks.explicit_raw,
        collected_at=fallbacks.collected_raw,
        issues=issues + fallbacks.issues,
    )


def _match_sheet_header(sheet: SheetEvidence) -> _SheetMatch:
    attempts = tuple(item for item in _header_attempts(sheet) if item.complete)
    if not attempts:
        return _SheetMatch(sheet, "no_asset_sheet", None, ())
    if len(attempts) > 1:
        return _SheetMatch(sheet, "ambiguous_headers", None, (_issue("AMBIGUOUS_HEADERS"),))
    attempt = attempts[0]
    if attempt.duplicate_fields:
        issue = _issue("DUPLICATE_FIELD_MAPPING", field_name=attempt.duplicate_fields[0])
        return _SheetMatch(sheet, "duplicate_field_mapping", None, (issue,))
    return _SheetMatch(sheet, "mapped", attempt, ())


def _header_attempts(sheet: SheetEvidence) -> tuple[_HeaderAttempt, ...]:
    grouped = _cells_by_row(sheet)
    return tuple(_header_attempt(row, grouped[row]) for row in sorted(grouped))


def _header_attempt(row: int, cells: tuple[CellEvidence, ...]) -> _HeaderAttempt:
    fields: dict[str, list[ColumnBinding]] = {}
    unknown: list[UnknownCell] = []
    for cell in cells:
        _record_header_cell(cell, fields, unknown)
    bindings = tuple(group[0] for group in fields.values())
    duplicates = tuple(name for name, group in fields.items() if len(group) > 1)
    complete = not _missing_required_asset_fields(set(fields))
    return _HeaderAttempt(row, bindings, tuple(unknown), duplicates, complete)


def _record_header_cell(
    cell: CellEvidence,
    fields: dict[str, list[ColumnBinding]],
    unknown: list[UnknownCell],
) -> None:
    text = _cell_plain_text(cell)
    if text is None or text == "":
        return
    field_name = _HEADER_FIELD.get(text)
    if field_name is None:
        unknown.append(UnknownCell(cell.column, text, cell))
        return
    binding = ColumnBinding(field_name, cell.column, text, cell)
    fields.setdefault(field_name, []).append(binding)


def _map_matched_sheet(
    workbook: WorkbookEvidence,
    sheet: SheetEvidence,
    header: _HeaderAttempt,
    fallbacks: _DateFallbacks,
) -> ExactAssetMapping:
    context = _RowContext(workbook, sheet, header, fallbacks)
    rows, skipped = _map_data_rows(context)
    version = next(iter(ASSET_SCHEMAS))
    return ExactAssetMapping(
        status="mapped",
        parser_version=PARSER_VERSION,
        temporal_policy=TEMPORAL_POLICY,
        source_sha256=workbook.source_sha256,
        date1904=workbook.date1904,
        schema_version=version,
        sheet_name=sheet.name,
        header_row=header.row,
        bindings=header.bindings,
        unknown_headers=header.unknown,
        rows=rows,
        skipped_blank_rows=skipped,
        candidate_sheet_names=(sheet.name,),
        explicit_snapshot_date=fallbacks.explicit_raw,
        collected_at=fallbacks.collected_raw,
        issues=fallbacks.issues,
    )


def _map_data_rows(context: _RowContext) -> tuple[tuple[ExactMappedAssetRow, ...], int]:
    grouped = _cells_by_row(context.sheet)
    mapped: list[ExactMappedAssetRow] = []
    skipped = 0
    for row in sorted(grouped):
        if row <= context.header.row:
            continue
        cells = grouped[row]
        if not any(_cell_has_content(cell) for cell in cells):
            skipped += 1
            continue
        mapped.append(_map_data_row(context, cells, row))
    return tuple(mapped), skipped


def _map_data_row(
    context: _RowContext, cells: tuple[CellEvidence, ...], row: int
) -> ExactMappedAssetRow:
    parsed = _parse_row_fields(context, cells, row)
    return _assemble_row(context, cells, row, parsed)


def _parse_row_fields(
    context: _RowContext, cells: tuple[CellEvidence, ...], row: int
) -> _ParsedRow:
    bound = _bound_cells(context.header, cells)
    texts = _text_fields(bound, row)
    currency = _parse_currency(bound.get("currency"), row)
    quantity = _parse_quantity(bound.get("quantity"), row)
    market = _parse_market_value(bound.get("market_value"), currency, row)
    snapshot, date_issues = _resolve_snapshot(
        bound.get("snapshot_date"), context.workbook.date1904, row, context.fallbacks
    )
    issues = texts.issues + currency.issues + quantity.issues + market.issues + date_issues
    return _ParsedRow(texts, currency, quantity, market, snapshot, issues)


def _bound_cells(
    header: _HeaderAttempt, cells: tuple[CellEvidence, ...]
) -> dict[str, CellEvidence | None]:
    by_column = {cell.column: cell for cell in cells}
    return {item.field_name: by_column.get(item.column) for item in header.bindings}


def _assemble_row(
    context: _RowContext,
    cells: tuple[CellEvidence, ...],
    row: int,
    parsed: _ParsedRow,
) -> ExactMappedAssetRow:
    texts = parsed.texts
    by_column = {cell.column: cell for cell in cells}
    return ExactMappedAssetRow(
        sheet_name=context.sheet.name,
        source_row=row,
        cells=cells,
        unknown_cells=_unknown_data_cells(context.header, by_column),
        source_account_id=texts.account_id,
        source_account_name=texts.account_name,
        source_instrument_id=texts.instrument_id,
        source_instrument_name=texts.instrument_name,
        quantity=parsed.quantity.value,
        market_value=parsed.market.value,
        quantity_unverified=parsed.quantity.unverified,
        market_value_unverified=parsed.market.unverified,
        currency_code=parsed.currency.code,
        currency_unknown=parsed.currency.unknown,
        snapshot=parsed.snapshot,
        issues=parsed.issues,
        supported=_row_supported(texts, parsed.quantity, parsed.market, parsed.snapshot),
    )


def _text_fields(bound: dict[str, CellEvidence | None], row: int) -> _TextFields:
    account_id, account_id_issues = _identity_text(bound.get("account_id"), "account_id", row)
    account_name, account_name_issues = _identity_text(
        bound.get("account_name"), "account_name", row
    )
    instrument_id, instrument_id_issues = _identity_text(
        bound.get("instrument_id"), "instrument_id", row
    )
    instrument_name, instrument_name_issues = _identity_text(
        bound.get("instrument_name"), "instrument_name", row
    )
    issues = (
        account_id_issues
        + account_name_issues
        + instrument_id_issues
        + instrument_name_issues
        + _missing_identity_issues(account_id, account_name, instrument_id, instrument_name, row)
    )
    return _TextFields(account_id, account_name, instrument_id, instrument_name, issues)


def _identity_text(
    cell: CellEvidence | None, field_name: str, row: int
) -> tuple[str | None, tuple[ExactAssetIssue, ...]]:
    if cell is None:
        return None, ()
    formula = _formula_issues(cell, field_name, row)
    if cell.cell_type in {"b", "e"}:
        issue = _issue(
            "INVALID_IDENTITY_CELL", field_name=field_name, source_row=row, column=cell.column
        )
        return None, (issue,) + formula
    return _optional_text(cell), formula


def _missing_identity_issues(
    account_id: str | None,
    account_name: str | None,
    instrument_id: str | None,
    instrument_name: str | None,
    row: int,
) -> tuple[ExactAssetIssue, ...]:
    issues: list[ExactAssetIssue] = []
    if account_id is None and account_name is None:
        issues.append(_issue("MISSING_ACCOUNT", source_row=row))
    if instrument_id is None and instrument_name is None:
        issues.append(_issue("MISSING_INSTRUMENT", source_row=row))
    return tuple(issues)


def _row_supported(
    texts: _TextFields,
    quantity: _NumericPart,
    market: _NumericPart,
    snapshot: SnapshotDate,
) -> bool:
    if snapshot.parsed_date is None or quantity.value is None or market.value is None:
        return False
    if texts.account_id is None and texts.account_name is None:
        return False
    if texts.instrument_id is None and texts.instrument_name is None:
        return False
    return True


def _unknown_data_cells(
    header: _HeaderAttempt, by_column: dict[str, CellEvidence]
) -> tuple[UnknownCell, ...]:
    bound_columns = {item.column for item in header.bindings}
    header_text = {item.cell.column: item.header_text for item in header.unknown}
    unknown: list[UnknownCell] = []
    for column, cell in by_column.items():
        if column in bound_columns:
            continue
        unknown.append(UnknownCell(column, header_text.get(column), cell))
    return tuple(unknown)


def _parse_currency(cell: CellEvidence | None, row: int) -> _CurrencyPart:
    if cell is None:
        return _unknown_currency_part(row, None, ())
    formula = _formula_issues(cell, "currency", row)
    if _has_code(formula, "FORMULA_CACHE_MISSING") or cell.cell_type in {"b", "e"}:
        return _unknown_currency_part(row, cell.column, formula)
    text = _cell_plain_text(cell)
    if text is None or _CURRENCY_RE.fullmatch(text.strip()) is None:
        return _unknown_currency_part(row, cell.column, formula)
    unverified = _has_code(formula, "FORMULA_CACHED_UNVERIFIED")
    return _CurrencyPart(text.strip(), False, formula, unverified)


def _unknown_currency_part(
    row: int, column: str | None, extra: tuple[ExactAssetIssue, ...]
) -> _CurrencyPart:
    issue = _issue("UNKNOWN_CURRENCY", field_name="currency", source_row=row, column=column)
    return _CurrencyPart(None, True, (issue,) + extra, False)


def _parse_quantity(cell: CellEvidence | None, row: int) -> _NumericPart:
    spec = _NumberSpec("quantity", "quantity", unit=QUANTITY_UNIT)
    return _parse_number(cell, spec, row)


def _parse_market_value(
    cell: CellEvidence | None, currency: _CurrencyPart, row: int
) -> _NumericPart:
    money = UNKNOWN_CURRENCY if currency.unknown else currency.code
    spec = _NumberSpec("market_value", "money", currency=money)
    parsed = _parse_number(cell, spec, row)
    if parsed.value is None or not currency.unverified:
        return parsed
    return _NumericPart(parsed.value, True, parsed.issues)


def _parse_number(cell: CellEvidence | None, spec: _NumberSpec, row: int) -> _NumericPart:
    if cell is None:
        return _NumericPart(None, False, (_missing_number(spec.field_name, row, None),))
    if cell.formula is not None:
        return _parse_formula_number(cell, spec, row)
    return _parse_plain_number(cell, spec, row, unverified=False)


def _parse_formula_number(cell: CellEvidence, spec: _NumberSpec, row: int) -> _NumericPart:
    if cell.value_state != "present" or not cell.raw_value:
        issue = _issue(
            "FORMULA_CACHE_MISSING", field_name=spec.field_name, source_row=row, column=cell.column
        )
        return _NumericPart(None, False, (issue,))
    parsed = _parse_plain_number(cell, spec, row, unverified=True)
    cached = _issue(
        "FORMULA_CACHED_UNVERIFIED", field_name=spec.field_name, source_row=row, column=cell.column
    )
    return _NumericPart(parsed.value, True, (*parsed.issues, cached))


def _parse_plain_number(
    cell: CellEvidence, spec: _NumberSpec, row: int, *, unverified: bool
) -> _NumericPart:
    typed = _number_type_issue(cell, spec.field_name, row)
    if typed is not None:
        return _NumericPart(None, unverified, (typed,))
    lexical = _cell_plain_text(cell)
    if lexical is None or lexical == "":
        return _NumericPart(None, unverified, (_missing_number(spec.field_name, row, cell.column),))
    return _number_from_lexical(lexical, cell, spec, unverified)


def _number_from_lexical(
    lexical: str, cell: CellEvidence, spec: _NumberSpec, unverified: bool
) -> _NumericPart:
    try:
        _validate_plain_decimal(lexical)
        value = ExactValue.from_lexical(
            lexical,
            value_kind=spec.value_kind,
            origin_kind="source",
            currency=spec.currency if spec.value_kind == "money" else None,
            unit=spec.unit,
        )
    except ExactValueError as exc:
        return _NumericPart(None, unverified, (_classify_numeric_error(exc, lexical, cell, spec),))
    return _NumericPart(value, unverified, ())


def _validate_plain_decimal(lexical: str) -> None:
    if _PLAIN_DECIMAL_RE.fullmatch(lexical) is not None:
        return
    if lexical.lower().lstrip("+-") in {"nan", "snan", "inf", "infinity"}:
        raise ExactValueError("Unsupported non-finite source number.")
    raise ExactValueError("Unsupported source decimal lexical form.")


def _number_type_issue(cell: CellEvidence, field_name: str, row: int) -> ExactAssetIssue | None:
    if cell.cell_type == "b":
        code = f"{field_name.upper()}_BOOLEAN"
    elif cell.cell_type == "e":
        code = f"{field_name.upper()}_ERROR_CELL"
    else:
        return None
    return _issue(code, field_name=field_name, source_row=row, column=cell.column)


def _classify_numeric_error(
    exc: ExactValueError, lexical: str, cell: CellEvidence, spec: _NumberSpec
) -> ExactAssetIssue:
    prefix = spec.field_name.upper()
    message = str(exc)
    code = f"UNSUPPORTED_{prefix}"
    if "Scale must be between" in message:
        code = f"{prefix}_SCALE_OUT_OF_RANGE"
    elif "NaN" in message or "infinity" in message or "non-finite" in message:
        code = f"{prefix}_NONFINITE"
    elif any(mark in lexical for mark in (",", "₩", "$", "€", "원", "%", "만원")):
        code = f"{prefix}_FORMATTED"
    return _issue(code, field_name=spec.field_name, source_row=cell.row, column=cell.column)


def _missing_number(field_name: str, row: int, column: str | None) -> ExactAssetIssue:
    code = f"{field_name.upper()}_MISSING"
    return _issue(code, field_name=field_name, source_row=row, column=column)


def _resolve_snapshot(
    cell: CellEvidence | None,
    date1904: bool,
    row: int,
    fallbacks: _DateFallbacks,
) -> tuple[SnapshotDate, tuple[ExactAssetIssue, ...]]:
    source = _parse_date_cell(cell, date1904, row)
    if source.value is not None:
        build = _SnapshotBuild(source.value, "row", source.kind, ())
        return _make_snapshot(source, build, date1904), source.issues
    return _snapshot_with_fallback(source, fallbacks, date1904, row)


def _snapshot_with_fallback(
    source: _DatePart,
    fallbacks: _DateFallbacks,
    date1904: bool,
    row: int,
) -> tuple[SnapshotDate, tuple[ExactAssetIssue, ...]]:
    chosen, origin, extra = _fallback_date(fallbacks)
    flags = extra + _missing_row_flags(source)
    if chosen is None:
        build = _SnapshotBuild(None, "missing", source.kind, flags)
        return _make_snapshot(source, build, date1904), source.issues + _missing_date_issue(
            source, row
        )
    kind = "explicit" if origin == "explicit" else "collected_at"
    build = _SnapshotBuild(chosen, origin, kind, flags)
    return _make_snapshot(source, build, date1904), source.issues


def _fallback_date(
    fallbacks: _DateFallbacks,
) -> tuple[date | None, DateSource, tuple[str, ...]]:
    if fallbacks.explicit is not None:
        return fallbacks.explicit, "explicit", ("explicit_fallback",)
    if fallbacks.collected is not None:
        return fallbacks.collected, "collected_at", ("collection_fallback",)
    return None, "missing", ()


def _missing_row_flags(source: _DatePart) -> tuple[str, ...]:
    if source.raw is None and not source.issues:
        return ("row_date_absent",)
    if any(issue.code == "INVALID_DATE" for issue in source.issues):
        return ("source_date_invalid",)
    return ()


def _missing_date_issue(source: _DatePart, row: int) -> tuple[ExactAssetIssue, ...]:
    if any(issue.code == "MISSING_SNAPSHOT_DATE" for issue in source.issues):
        return ()
    return (_issue("MISSING_SNAPSHOT_DATE", field_name="snapshot_date", source_row=row),)


def _make_snapshot(source: _DatePart, build: _SnapshotBuild, date1904: bool) -> SnapshotDate:
    return SnapshotDate(
        parsed_date=build.parsed,
        raw=source.raw,
        source=build.origin,
        kind=build.kind,
        serial_lexical=source.serial_lexical,
        date1904=date1904,
        temporal_policy=TEMPORAL_POLICY,
        uncertainty=source.uncertainty + build.extra,
    )


def _parse_date_cell(cell: CellEvidence | None, date1904: bool, row: int) -> _DatePart:
    if cell is None or not _cell_has_content(cell):
        return _DatePart(None, None, None, None, ())
    formula = _formula_issues(cell, "snapshot_date", row)
    if any(item.code == "FORMULA_CACHE_MISSING" for item in formula):
        return _DatePart(None, None, _optional_text(cell), None, formula)
    if cell.cell_type in {"b", "e"}:
        issue = _issue(
            "INVALID_DATE", field_name="snapshot_date", source_row=row, column=cell.column
        )
        return _DatePart(None, None, _optional_text(cell), None, (issue,) + formula)
    parsed = _parse_date_value(cell, date1904, row)
    return _DatePart(
        parsed.value,
        parsed.kind,
        parsed.raw,
        parsed.serial_lexical,
        parsed.issues + formula,
        parsed.uncertainty,
    )


def _parse_date_value(cell: CellEvidence, date1904: bool, row: int) -> _DatePart:
    if _is_text_cell(cell):
        return _parse_date_text(cell, row)
    if cell.cell_type == "d":
        return _parse_ooxml_date(cell, row)
    return _parse_date_serial(cell, date1904, row)


def _parse_date_text(cell: CellEvidence, row: int) -> _DatePart:
    return _parse_iso_lexical(
        cell, row, date_kind="iso_text", datetime_kind="iso_text", datetime_flag="datetime_text"
    )


def _parse_ooxml_date(cell: CellEvidence, row: int) -> _DatePart:
    return _parse_iso_lexical(
        cell,
        row,
        date_kind="iso_date",
        datetime_kind="iso_datetime",
        datetime_flag="iso_datetime",
    )


def _parse_iso_lexical(
    cell: CellEvidence,
    row: int,
    *,
    date_kind: str,
    datetime_kind: str,
    datetime_flag: str,
) -> _DatePart:
    raw = _cell_plain_text(cell) or ""
    iso = _parse_iso_date(raw)
    if iso is not None:
        return _DatePart(iso, date_kind, raw, None, ())
    stamped = _parse_iso_datetime(raw)
    if stamped is not None:
        return _DatePart(stamped[0], datetime_kind, raw, None, (), (datetime_flag,))
    issue = _issue("INVALID_DATE", field_name="snapshot_date", source_row=row, column=cell.column)
    return _DatePart(None, date_kind, raw, None, (issue,))


def _parse_date_serial(cell: CellEvidence, date1904: bool, row: int) -> _DatePart:
    raw = _cell_plain_text(cell)
    if raw is None or raw == "":
        return _DatePart(None, None, raw, None, ())
    parsed = _split_serial(raw)
    if parsed.status != "ok":
        code = "UNSUPPORTED_SERIAL" if parsed.status == "unsupported" else "INVALID_DATE"
        issue = _issue(code, field_name="snapshot_date", source_row=row, column=cell.column)
        return _DatePart(None, "excel_serial", raw, raw, (issue,))
    return _civil_from_serial(parsed.days, parsed.fraction != 0, raw, date1904, cell)


def _civil_from_serial(
    days: int, has_fraction: bool, raw: str, date1904: bool, cell: CellEvidence
) -> _DatePart:
    civil = _excel_days_to_date(days, date1904, cell.row, cell.column)
    extra = ("serial_fraction_ignored",) if has_fraction else ()
    if isinstance(civil, ExactTransactionIssue):
        issue = _issue(
            civil.code, field_name="snapshot_date", source_row=cell.row, column=cell.column
        )
        return _DatePart(None, "excel_serial", raw, raw, (issue,), extra)
    return _DatePart(civil, "excel_serial", raw, raw, (), extra)


def _formula_issues(cell: CellEvidence, field_name: str, row: int) -> tuple[ExactAssetIssue, ...]:
    if cell.formula is None:
        return ()
    if cell.value_state != "present" or not cell.raw_value:
        return (
            _issue(
                "FORMULA_CACHE_MISSING", field_name=field_name, source_row=row, column=cell.column
            ),
        )
    return (
        _issue(
            "FORMULA_CACHED_UNVERIFIED", field_name=field_name, source_row=row, column=cell.column
        ),
    )


def _has_code(issues: tuple[ExactAssetIssue, ...], code: str) -> bool:
    return any(item.code == code for item in issues)


def _issue(
    code: str,
    *,
    field_name: str | None = None,
    source_row: int | None = None,
    column: str | None = None,
) -> ExactAssetIssue:
    return ExactAssetIssue(
        code=code,
        field_name=field_name,
        source_row=source_row,
        column=column,
        detail=_ISSUE_DETAIL[code],
    )
