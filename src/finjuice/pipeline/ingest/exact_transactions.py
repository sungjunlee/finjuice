"""Pure WorkbookEvidence -> exact transaction mapping.

The mapper never rereads files, never converts numbers through ``float``,
Polars, or openpyxl, never evaluates formulas, and never mints entity IDs.
Source ``ExactValue`` objects keep their captured lexical; the only extra
amount is a calculated positive magnitude for negative income/deposit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from fractions import Fraction
from typing import Final, Literal

from finjuice.pipeline.ingest._normalize import _normalize_type
from finjuice.pipeline.ingest.schemas_detect import BANKSALAD_SCHEMAS
from finjuice.pipeline.ingest.xlsx_evidence import CellEvidence, SheetEvidence, WorkbookEvidence
from finjuice.pipeline.storage.sqlite.errors import ExactValueError
from finjuice.pipeline.storage.sqlite.exact import UNKNOWN_CURRENCY, ExactValue

PARSER_VERSION: Final = "finjuice.xlsx-transaction-mapper.v1"
TEMPORAL_POLICY: Final = "finjuice.xlsx-temporal.ms-half-even.v1"
SERIAL_MAX_DIGITS: Final = 512
SERIAL_MAX_ABS_EXPONENT: Final = 512
SERIAL_MAX_LEXEME_LENGTH: Final = 1024
REQUIRED_TRANSACTION_FIELDS: Final[frozenset[str]] = frozenset(
    {"date", "time", "type", "merchant", "amount", "account"}
)
MS_PER_DAY: Final = 86_400_000
MappingStatus = Literal[
    "mapped",
    "no_transaction_sheet",
    "sheet_not_found",
    "not_transaction_sheet",
    "ambiguous_sheets",
    "ambiguous_headers",
    "duplicate_field_mapping",
]
TimezoneState = Literal["known", "unknown"]

_ISO_DATE_RE: Final = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_ISO_TIME_RE: Final = re.compile(r"^(\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?(Z|[+-]\d{2}:\d{2})?$")
_ISO_DATETIME_RE: Final = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?(Z|[+-]\d{2}:\d{2})?$"
)
_CURRENCY_RE: Final = re.compile(r"^[A-Z]{3}$")
_SERIAL_LEXEME_RE: Final = re.compile(r"^([+-])?(\d+)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$")
_HEADER_FIELD: Final[dict[str, str]] = {}
for _schema in BANKSALAD_SCHEMAS.values():
    for _field_name in _schema.__dataclass_fields__:
        if _field_name == "version":
            continue
        for _variant in getattr(_schema, _field_name):
            _HEADER_FIELD[_variant] = _field_name

_ISSUE_DETAIL: Final[dict[str, str]] = {
    "AMBIGUOUS_SHEETS": (
        "Multiple worksheets match the transaction header catalog; pass sheet_name."
    ),
    "AMBIGUOUS_HEADERS": "More than one uniquely complete transaction header row is present.",
    "DUPLICATE_FIELD_MAPPING": "A required transaction field maps to more than one header cell.",
    "SHEET_NOT_FOUND": "The requested sheet_name is not present in the workbook evidence.",
    "NOT_TRANSACTION_SHEET": "The selected sheet does not match the transaction header catalog.",
    "NO_TRANSACTION_SHEET": "No worksheet matches the transaction header catalog.",
    "AMOUNT_MISSING": "The amount cell is missing or empty.",
    "AMOUNT_BOOLEAN": "Boolean cells are unsupported money evidence.",
    "AMOUNT_ERROR_CELL": "Error cells are unsupported money evidence.",
    "AMOUNT_FORMATTED": "Formatted or decorated amount text is unsupported money evidence.",
    "AMOUNT_NONFINITE": "Non-finite amount lexemes are unsupported money evidence.",
    "AMOUNT_SCALE_OUT_OF_RANGE": "Amount scale is outside the ExactValue bound 0..255.",
    "UNSUPPORTED_AMOUNT": "The amount lexeme cannot be captured as ExactValue money.",
    "FORMULA_CACHE_MISSING": "A formula amount without a cached value is unsupported.",
    "FORMULA_CACHED_UNVERIFIED": (
        "Cached formula results are captured evidence, not verified values."
    ),
    "UNKNOWN_CURRENCY": "Currency is missing or not an uppercase three-letter code.",
    "NEGATIVE_INCOME_NORMALIZED": (
        "Negative income/deposit source amount is retained; "
        "calculated magnitude uses the absolute coefficient."
    ),
    "MISSING_DATE": "The date cell is missing or empty.",
    "INVALID_DATE": "The date cell is not a supported ISO date or Excel serial.",
    "EXCEL_FICTITIOUS_DAY_60": "Excel 1900 serial day 60 is a fictitious leap day.",
    "DATE_OVERFLOW": "Excel serial date arithmetic overflowed the civil calendar.",
    "MISSING_TIME": "The time cell is missing or empty; 00:00 was not invented.",
    "INVALID_TIME": "The time cell is not a supported ISO time or Excel serial fraction.",
    "UNSUPPORTED_TIME_PRECISION": (
        "Textual fractional seconds finer than microseconds are not representable "
        "as a typed clock; source digits are retained without truncation."
    ),
    "UNSUPPORTED_SERIAL": (
        "Excel serial lexeme exceeds SERIAL_MAX_DIGITS, SERIAL_MAX_ABS_EXPONENT, "
        "or SERIAL_MAX_LEXEME_LENGTH; raw lexeme is retained without huge powers."
    ),
    "CONFLICTING_DATE_TIME": (
        "Non-zero time embedded in the date cell conflicts with the time cell."
    ),
    "MISSING_TYPE": "The type cell is missing or empty.",
    "MISSING_MERCHANT": "The merchant cell is missing or empty.",
    "MISSING_ACCOUNT": "The account cell is missing or empty.",
}


@dataclass(frozen=True)
class ExactTransactionIssue:
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
    """A source cell whose header is outside the transaction catalog."""

    column: str
    header_text: str | None
    cell: CellEvidence


@dataclass(frozen=True)
class TemporalState:
    """Interpreted civil date/time plus raw serials, precision, and uncertainty."""

    parsed_date: date | None
    parsed_time: time | None
    parsed_datetime: datetime | None
    date_kind: str | None
    time_kind: str | None
    timezone_state: TimezoneState
    timezone_offset: str | None
    precision: str | None
    time_fraction_digits: str | None
    uncertainty: tuple[str, ...]
    temporal_policy: str
    date_serial_lexical: str | None
    time_serial_lexical: str | None
    date1904: bool


@dataclass(frozen=True)
class TransactionIdentityIngredients:
    """Source identity inputs for a later handler; this mapper does not hash."""

    sheet_name: str
    source_row: int
    date_raw: str | None
    time_raw: str | None
    type_raw: str | None
    merchant_raw: str | None
    account_text: str | None
    amount_key: tuple[str, int] | None
    currency_code: str | None
    currency_unknown: bool
    temporal_precision: str | None
    temporal_uncertainty: tuple[str, ...]
    amount_unverified: bool


@dataclass(frozen=True)
class ExactMappedRow:
    """One source row with parsed fields, raw cells, and structured issues."""

    sheet_name: str
    source_row: int
    cells: tuple[CellEvidence, ...]
    unknown_cells: tuple[UnknownCell, ...]
    date_raw: str | None
    time_raw: str | None
    datetime_raw: str | None
    type_raw: str | None
    type_norm: str
    merchant_raw: str | None
    memo_raw: str | None
    major_raw: str | None
    minor_raw: str | None
    account_text: str | None
    source_amount: ExactValue | None
    interpreted_amount: ExactValue | None
    amount_unverified: bool
    currency_code: str | None
    currency_unknown: bool
    temporal: TemporalState
    identity: TransactionIdentityIngredients
    issues: tuple[ExactTransactionIssue, ...]
    supported: bool


@dataclass(frozen=True)
class ExactTransactionMapping:
    """Immutable workbook-level mapping result for a later MutationContext."""

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
    rows: tuple[ExactMappedRow, ...]
    skipped_blank_rows: int
    candidate_sheet_names: tuple[str, ...]
    issues: tuple[ExactTransactionIssue, ...]


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
    issues: tuple[ExactTransactionIssue, ...]


@dataclass(frozen=True)
class _Clock:
    hour: int
    minute: int
    second: int
    microsecond: int
    precision: str
    offset: str | None
    timezone_state: TimezoneState
    kind: str
    lexical: str
    day_offset: int = 0
    fraction_digits: str | None = None
    representable: bool = True


@dataclass(frozen=True)
class _DatePart:
    value: date | None
    kind: str | None
    raw: str | None
    serial_lexical: str | None
    embedded: _Clock | None
    source_row: int | None
    issues: tuple[ExactTransactionIssue, ...]


@dataclass(frozen=True)
class _TimePart:
    clock: _Clock | None
    raw: str | None
    serial_lexical: str | None
    issues: tuple[ExactTransactionIssue, ...]


@dataclass(frozen=True)
class _CurrencyPart:
    code: str | None
    unknown: bool
    issues: tuple[ExactTransactionIssue, ...]


@dataclass(frozen=True)
class _AmountPart:
    source: ExactValue | None
    interpreted: ExactValue | None
    unverified: bool
    issues: tuple[ExactTransactionIssue, ...]


@dataclass(frozen=True)
class _SerialParse:
    status: Literal["ok", "invalid", "unsupported"]
    days: int = 0
    fraction: Fraction = Fraction(0)


@dataclass(frozen=True)
class _FractionParts:
    microsecond: int
    precision: str
    digits: str | None
    representable: bool


def canonical_numeric_key(value: ExactValue) -> tuple[str, int]:
    """Return trailing-zero-stripped ``(coefficient, scale)`` for numeric equality."""

    digits = value.coefficient
    sign = ""
    if digits.startswith("-"):
        sign = "-"
        digits = digits[1:]
    scale = value.scale
    while scale > 0 and digits.endswith("0"):
        digits = digits[:-1]
        scale -= 1
    digits = digits.lstrip("0") or "0"
    if digits == "0":
        return ("0", 0)
    return (f"{sign}{digits}", scale)


def exact_amount_fraction(value: ExactValue) -> Fraction:
    """Return the exact rational of an amount without changing the source value."""

    return Fraction(int(value.coefficient), 10**value.scale)


def map_exact_transactions(
    workbook: WorkbookEvidence,
    *,
    sheet_name: str | None = None,
) -> ExactTransactionMapping:
    """Map captured workbook evidence into exact transaction rows.

    Args:
        workbook: Immutable evidence from the completed XLSX reader.
        sheet_name: Optional explicit worksheet name when several sheets match.

    Returns:
        An immutable mapping result. Asset-only workbooks yield
        ``no_transaction_sheet`` with no rows rather than guessing a sheet.
    """

    if not isinstance(workbook, WorkbookEvidence):
        raise TypeError("workbook must be WorkbookEvidence")
    if sheet_name is not None:
        return _map_named_sheet(workbook, sheet_name)
    matches = _candidate_matches(workbook)
    if not matches:
        return _status_mapping(workbook, "no_transaction_sheet", "NO_TRANSACTION_SHEET")
    if len(matches) > 1:
        return _ambiguous_sheet_mapping(workbook, matches)
    return _finish_match(workbook, matches[0])


def _map_named_sheet(workbook: WorkbookEvidence, sheet_name: str) -> ExactTransactionMapping:
    sheet = workbook.sheet(sheet_name)
    if sheet is None:
        return _status_mapping(workbook, "sheet_not_found", "SHEET_NOT_FOUND")
    return _finish_match(workbook, _match_sheet_header(sheet))


def _candidate_matches(workbook: WorkbookEvidence) -> tuple[_SheetMatch, ...]:
    matches: list[_SheetMatch] = []
    for sheet in workbook.sheets:
        match = _match_sheet_header(sheet)
        if match.status != "no_transaction_sheet":
            matches.append(match)
    return tuple(matches)


def _finish_match(workbook: WorkbookEvidence, match: _SheetMatch) -> ExactTransactionMapping:
    if match.status == "no_transaction_sheet":
        return _status_mapping(workbook, "not_transaction_sheet", "NOT_TRANSACTION_SHEET")
    if match.status != "mapped" or match.header is None:
        return _status_mapping(workbook, match.status, match.issues[0].code, (match.sheet.name,))
    return _map_matched_sheet(workbook, match.sheet, match.header)


def _ambiguous_sheet_mapping(
    workbook: WorkbookEvidence,
    matches: tuple[_SheetMatch, ...],
) -> ExactTransactionMapping:
    names = tuple(match.sheet.name for match in matches)
    return _status_mapping(workbook, "ambiguous_sheets", "AMBIGUOUS_SHEETS", names)


def _status_mapping(
    workbook: WorkbookEvidence,
    status: MappingStatus,
    code: str,
    candidates: tuple[str, ...] = (),
) -> ExactTransactionMapping:
    return ExactTransactionMapping(
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
        issues=(_issue(code),),
    )


def _match_sheet_header(sheet: SheetEvidence) -> _SheetMatch:
    attempts = tuple(item for item in _header_attempts(sheet) if item.complete)
    if not attempts:
        return _SheetMatch(sheet, "no_transaction_sheet", None, ())
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
        text = _cell_plain_text(cell)
        if text is None or text == "":
            continue
        field_name = _HEADER_FIELD.get(text)
        if field_name is None:
            unknown.append(UnknownCell(cell.column, text, cell))
            continue
        binding = ColumnBinding(field_name, cell.column, text, cell)
        fields.setdefault(field_name, []).append(binding)
    bindings = tuple(group[0] for group in fields.values())
    duplicates = tuple(name for name, group in fields.items() if len(group) > 1)
    present = set(fields)
    complete = REQUIRED_TRANSACTION_FIELDS <= present
    return _HeaderAttempt(row, bindings, tuple(unknown), duplicates, complete)


def _map_matched_sheet(
    workbook: WorkbookEvidence,
    sheet: SheetEvidence,
    header: _HeaderAttempt,
) -> ExactTransactionMapping:
    rows, skipped = _map_data_rows(workbook, sheet, header)
    version = next(iter(BANKSALAD_SCHEMAS))
    return ExactTransactionMapping(
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
        issues=(),
    )


def _map_data_rows(
    workbook: WorkbookEvidence,
    sheet: SheetEvidence,
    header: _HeaderAttempt,
) -> tuple[tuple[ExactMappedRow, ...], int]:
    grouped = _cells_by_row(sheet)
    mapped: list[ExactMappedRow] = []
    skipped = 0
    for row in sorted(grouped):
        if row <= header.row:
            continue
        cells = grouped[row]
        if not any(_cell_has_content(cell) for cell in cells):
            skipped += 1
            continue
        mapped.append(_map_data_row(workbook, sheet.name, header, cells, row))
    return tuple(mapped), skipped


def _map_data_row(
    workbook: WorkbookEvidence,
    sheet_name: str,
    header: _HeaderAttempt,
    cells: tuple[CellEvidence, ...],
    row: int,
) -> ExactMappedRow:
    by_column = {cell.column: cell for cell in cells}
    bound = {item.field_name: by_column.get(item.column) for item in header.bindings}
    currency = _parse_currency(bound.get("currency"), row)
    amount = _parse_amount(bound.get("amount"), bound.get("type"), currency, row)
    texts = _text_fields(bound, row)
    temporal, temporal_issues = _parse_temporal(
        bound.get("date"), bound.get("time"), workbook.date1904, row
    )
    issues = texts.issues + currency.issues + amount.issues + temporal_issues
    parsed = _ParsedParts(texts, amount, currency, temporal)
    identity = _identity(sheet_name, row, parsed)
    return _mapped_row(
        _RowBuild(
            sheet_name,
            row,
            cells,
            _unknown_data_cells(header, by_column),
            texts,
            amount,
            currency,
            temporal,
            identity,
            issues,
        )
    )


@dataclass(frozen=True)
class _ParsedParts:
    texts: _TextFields
    amount: _AmountPart
    currency: _CurrencyPart
    temporal: TemporalState


@dataclass(frozen=True)
class _TextFields:
    date_raw: str | None
    time_raw: str | None
    type_raw: str | None
    type_norm: str
    merchant_raw: str | None
    memo_raw: str | None
    major_raw: str | None
    minor_raw: str | None
    account_text: str | None
    issues: tuple[ExactTransactionIssue, ...]


@dataclass(frozen=True)
class _RowBuild:
    sheet_name: str
    row: int
    cells: tuple[CellEvidence, ...]
    unknown: tuple[UnknownCell, ...]
    texts: _TextFields
    amount: _AmountPart
    currency: _CurrencyPart
    temporal: TemporalState
    identity: TransactionIdentityIngredients
    issues: tuple[ExactTransactionIssue, ...]


def _text_fields(bound: dict[str, CellEvidence | None], row: int) -> _TextFields:
    type_raw = _optional_text(bound.get("type"))
    merchant = _optional_text(bound.get("merchant"))
    account = _optional_text(bound.get("account"))
    issues: list[ExactTransactionIssue] = []
    if type_raw is None:
        issues.append(_issue("MISSING_TYPE", field_name="type", source_row=row))
    if merchant is None:
        issues.append(_issue("MISSING_MERCHANT", field_name="merchant", source_row=row))
    if account is None:
        issues.append(_issue("MISSING_ACCOUNT", field_name="account", source_row=row))
    return _TextFields(
        date_raw=_optional_text(bound.get("date")),
        time_raw=_optional_text(bound.get("time")),
        type_raw=type_raw,
        type_norm=_normalize_type(type_raw or ""),
        merchant_raw=merchant,
        memo_raw=_optional_text(bound.get("memo")),
        major_raw=_optional_text(bound.get("major_category")),
        minor_raw=_optional_text(bound.get("minor_category")),
        account_text=account,
        issues=tuple(issues),
    )


def _mapped_row(build: _RowBuild) -> ExactMappedRow:
    texts = build.texts
    datetime_raw = _datetime_raw(build.temporal)
    return ExactMappedRow(
        sheet_name=build.sheet_name,
        source_row=build.row,
        cells=build.cells,
        unknown_cells=build.unknown,
        date_raw=texts.date_raw,
        time_raw=texts.time_raw,
        datetime_raw=datetime_raw,
        type_raw=texts.type_raw,
        type_norm=texts.type_norm,
        merchant_raw=texts.merchant_raw,
        memo_raw=texts.memo_raw,
        major_raw=texts.major_raw,
        minor_raw=texts.minor_raw,
        account_text=texts.account_text,
        source_amount=build.amount.source,
        interpreted_amount=build.amount.interpreted,
        amount_unverified=build.amount.unverified,
        currency_code=build.currency.code,
        currency_unknown=build.currency.unknown,
        temporal=build.temporal,
        identity=build.identity,
        issues=build.issues,
        supported=_row_supported(build),
    )


def _datetime_raw(temporal: TemporalState) -> str | None:
    if temporal.parsed_datetime is None:
        return None
    return temporal.parsed_datetime.isoformat()


def _row_supported(build: _RowBuild) -> bool:
    if build.temporal.parsed_date is None or build.amount.source is None:
        return False
    if build.texts.account_text is None:
        return False
    blocked = {
        "FORMULA_CACHE_MISSING",
        "EXCEL_FICTITIOUS_DAY_60",
        "DATE_OVERFLOW",
        "CONFLICTING_DATE_TIME",
        "UNSUPPORTED_TIME_PRECISION",
        "UNSUPPORTED_SERIAL",
    }
    return not any(issue.code in blocked for issue in build.issues)


def _identity(
    sheet_name: str,
    row: int,
    parsed: _ParsedParts,
) -> TransactionIdentityIngredients:
    amount = parsed.amount
    texts = parsed.texts
    amount_key = None if amount.source is None else canonical_numeric_key(amount.source)
    return TransactionIdentityIngredients(
        sheet_name=sheet_name,
        source_row=row,
        date_raw=texts.date_raw,
        time_raw=texts.time_raw,
        type_raw=texts.type_raw,
        merchant_raw=texts.merchant_raw,
        account_text=texts.account_text,
        amount_key=amount_key,
        currency_code=parsed.currency.code,
        currency_unknown=parsed.currency.unknown,
        temporal_precision=parsed.temporal.precision,
        temporal_uncertainty=parsed.temporal.uncertainty,
        amount_unverified=amount.unverified,
    )


def _unknown_data_cells(
    header: _HeaderAttempt,
    by_column: dict[str, CellEvidence],
) -> tuple[UnknownCell, ...]:
    bound_columns = {item.column for item in header.bindings}
    unknown: list[UnknownCell] = []
    header_text = {item.cell.column: item.header_text for item in header.unknown}
    for column, cell in by_column.items():
        if column in bound_columns:
            continue
        unknown.append(UnknownCell(column, header_text.get(column), cell))
    return tuple(unknown)


def _parse_currency(cell: CellEvidence | None, row: int) -> _CurrencyPart:
    issue = _issue("UNKNOWN_CURRENCY", field_name="currency", source_row=row)
    if cell is None:
        return _CurrencyPart(None, True, (issue,))
    issue = _issue("UNKNOWN_CURRENCY", field_name="currency", source_row=row, column=cell.column)
    text = _cell_plain_text(cell)
    if text is None:
        return _CurrencyPart(None, True, (issue,))
    stripped = text.strip()
    if _CURRENCY_RE.fullmatch(stripped) is None:
        return _CurrencyPart(None, True, (issue,))
    return _CurrencyPart(stripped, False, ())


def _parse_amount(
    cell: CellEvidence | None,
    type_cell: CellEvidence | None,
    currency: _CurrencyPart,
    row: int,
) -> _AmountPart:
    type_raw = _optional_text(type_cell) or ""
    if cell is None:
        return _AmountPart(None, None, False, (_missing_amount(row, None),))
    if cell.formula is not None:
        return _parse_formula_amount(cell, type_raw, currency, row)
    return _parse_plain_amount(cell, type_raw, currency, row, unverified=False)


def _parse_formula_amount(
    cell: CellEvidence,
    type_raw: str,
    currency: _CurrencyPart,
    row: int,
) -> _AmountPart:
    if cell.value_state != "present" or not cell.raw_value:
        issue = _issue(
            "FORMULA_CACHE_MISSING", field_name="amount", source_row=row, column=cell.column
        )
        return _AmountPart(None, None, False, (issue,))
    parsed = _parse_plain_amount(cell, type_raw, currency, row, unverified=True)
    cached = _issue(
        "FORMULA_CACHED_UNVERIFIED", field_name="amount", source_row=row, column=cell.column
    )
    return _AmountPart(parsed.source, parsed.interpreted, True, (*parsed.issues, cached))


def _parse_plain_amount(
    cell: CellEvidence,
    type_raw: str,
    currency: _CurrencyPart,
    row: int,
    *,
    unverified: bool,
) -> _AmountPart:
    typed = _amount_type_issue(cell, row)
    if typed is not None:
        return _AmountPart(None, None, unverified, (typed,))
    lexical = _cell_plain_text(cell)
    if lexical is None or lexical == "":
        return _AmountPart(None, None, unverified, (_missing_amount(row, cell.column),))
    return _amount_from_lexical(lexical, cell, type_raw, currency, unverified)


def _amount_from_lexical(
    lexical: str,
    cell: CellEvidence,
    type_raw: str,
    currency: _CurrencyPart,
    unverified: bool,
) -> _AmountPart:
    try:
        source = ExactValue.from_lexical(
            lexical,
            value_kind="money",
            origin_kind="source",
            currency=UNKNOWN_CURRENCY if currency.unknown else currency.code,
        )
    except ExactValueError as exc:
        issue = _classify_amount_error(exc, lexical, cell)
        return _AmountPart(None, None, unverified, (issue,))
    interpreted, income_issue = _negative_income_amount(source, type_raw, cell)
    issues = () if income_issue is None else (income_issue,)
    return _AmountPart(source, interpreted, unverified, issues)


def _negative_income_amount(
    source: ExactValue,
    type_raw: str,
    cell: CellEvidence,
) -> tuple[ExactValue | None, ExactTransactionIssue | None]:
    if _normalize_type(type_raw) != "income" or not source.coefficient.startswith("-"):
        return None, None
    calculated = ExactValue(
        coefficient=source.coefficient.removeprefix("-"),
        scale=source.scale,
        lexical=None,
        value_kind="money",
        origin_kind="calculated",
        currency=source.currency,
        currency_unknown=source.currency_unknown,
    )
    issue = _issue(
        "NEGATIVE_INCOME_NORMALIZED",
        field_name="amount",
        source_row=cell.row,
        column=cell.column,
    )
    return calculated, issue


def _amount_type_issue(cell: CellEvidence, row: int) -> ExactTransactionIssue | None:
    if cell.cell_type == "b":
        return _issue("AMOUNT_BOOLEAN", field_name="amount", source_row=row, column=cell.column)
    if cell.cell_type == "e":
        return _issue("AMOUNT_ERROR_CELL", field_name="amount", source_row=row, column=cell.column)
    return None


def _classify_amount_error(
    exc: ExactValueError,
    lexical: str,
    cell: CellEvidence,
) -> ExactTransactionIssue:
    message = str(exc)
    code = "UNSUPPORTED_AMOUNT"
    if "Scale must be between" in message:
        code = "AMOUNT_SCALE_OUT_OF_RANGE"
    elif "NaN" in message or "infinity" in message or "non-finite" in message:
        code = "AMOUNT_NONFINITE"
    elif any(mark in lexical for mark in (",", "₩", "$", "€", "원")):
        code = "AMOUNT_FORMATTED"
    return _issue(code, field_name="amount", source_row=cell.row, column=cell.column)


def _missing_amount(row: int, column: str | None) -> ExactTransactionIssue:
    return _issue("AMOUNT_MISSING", field_name="amount", source_row=row, column=column)


def _parse_temporal(
    date_cell: CellEvidence | None,
    time_cell: CellEvidence | None,
    date1904: bool,
    row: int,
) -> tuple[TemporalState, tuple[ExactTransactionIssue, ...]]:
    date_part = _parse_date_cell(date_cell, date1904, row)
    time_part = _select_time_part(date_part, time_cell, row)
    return _combine_temporal(date_part, time_part, date1904)


def _select_time_part(
    date_part: _DatePart,
    time_cell: CellEvidence | None,
    row: int,
) -> _TimePart:
    time_present = time_cell is not None and _cell_has_content(time_cell)
    if date_part.embedded is not None and not time_present:
        return _TimePart(None, None, None, ())
    return _parse_time_cell(time_cell, row)


def _parse_date_cell(cell: CellEvidence | None, date1904: bool, row: int) -> _DatePart:
    if cell is None or not _cell_has_content(cell):
        issue = _issue("MISSING_DATE", field_name="date", source_row=row)
        return _DatePart(None, None, None, None, None, row, (issue,))
    cached = _formula_cache_issue(cell, "date", row)
    if cached is not None and cell.value_state != "present":
        return _DatePart(None, None, _optional_text(cell), None, None, row, (cached,))
    if cell.cell_type in {"b", "e"}:
        issue = _issue("INVALID_DATE", field_name="date", source_row=row, column=cell.column)
        return _DatePart(None, None, _optional_text(cell), None, None, row, (issue,))
    if _is_text_cell(cell):
        parsed = _parse_date_text(cell, row)
    else:
        parsed = _parse_date_serial(cell, date1904, row)
    extra = () if cached is None else (cached,)
    return _DatePart(
        parsed.value,
        parsed.kind,
        parsed.raw,
        parsed.serial_lexical,
        parsed.embedded,
        row,
        parsed.issues + extra,
    )


def _formula_cache_issue(
    cell: CellEvidence, field_name: str, row: int
) -> ExactTransactionIssue | None:
    if cell.formula is None:
        return None
    if cell.value_state != "present" or not cell.raw_value:
        return _issue(
            "FORMULA_CACHE_MISSING", field_name=field_name, source_row=row, column=cell.column
        )
    return _issue(
        "FORMULA_CACHED_UNVERIFIED", field_name=field_name, source_row=row, column=cell.column
    )


def _parse_date_text(cell: CellEvidence, row: int) -> _DatePart:
    raw = _cell_plain_text(cell) or ""
    parsed = _parse_iso_datetime(raw)
    if parsed is not None:
        value, clock = parsed
        issues = _precision_issues(clock, "date", row, cell.column)
        return _DatePart(value, "iso_text", raw, None, clock, row, issues)
    parsed_date = _parse_iso_date(raw)
    if parsed_date is not None:
        return _DatePart(parsed_date, "iso_text", raw, None, None, row, ())
    issue = _issue("INVALID_DATE", field_name="date", source_row=row, column=cell.column)
    return _DatePart(None, "iso_text", raw, None, None, row, (issue,))


def _parse_date_serial(cell: CellEvidence, date1904: bool, row: int) -> _DatePart:
    raw = _cell_plain_text(cell)
    if raw is None or raw == "":
        issue = _issue("MISSING_DATE", field_name="date", source_row=row, column=cell.column)
        return _DatePart(None, None, raw, None, None, row, (issue,))
    parsed = _split_serial(raw)
    failed = _serial_date_failure(parsed, raw, cell, row)
    if failed is not None:
        return failed
    return _date_from_serial_parts(parsed, raw, date1904, cell)


def _serial_date_failure(
    parsed: _SerialParse, raw: str, cell: CellEvidence, row: int
) -> _DatePart | None:
    if parsed.status == "ok":
        return None
    code = "UNSUPPORTED_SERIAL" if parsed.status == "unsupported" else "INVALID_DATE"
    issue = _issue(code, field_name="date", source_row=row, column=cell.column)
    return _DatePart(None, "excel_serial", raw, raw, None, row, (issue,))


def _date_from_serial_parts(
    parsed: _SerialParse, raw: str, date1904: bool, cell: CellEvidence
) -> _DatePart:
    clock = None
    if parsed.fraction != 0:
        clock = _clock_from_fraction(parsed.fraction, raw, "excel_serial")
    extra = 0 if clock is None else clock.day_offset
    civil = _excel_days_to_date(parsed.days + extra, date1904, cell.row, cell.column)
    if isinstance(civil, ExactTransactionIssue):
        return _DatePart(None, "excel_serial", raw, raw, clock, cell.row, (civil,))
    if clock is not None:
        clock = _clock_with_day_offset(clock, 0)
    return _DatePart(civil, "excel_serial", raw, raw, clock, cell.row, ())


def _parse_time_cell(cell: CellEvidence | None, row: int) -> _TimePart:
    if cell is None or not _cell_has_content(cell):
        issue = _issue("MISSING_TIME", field_name="time", source_row=row)
        return _TimePart(None, None, None, (issue,))
    cached = _formula_cache_issue(cell, "time", row)
    if cached is not None and cell.value_state != "present":
        return _TimePart(None, _optional_text(cell), None, (cached,))
    extra = () if cached is None else (cached,)
    if cell.cell_type in {"b", "e"}:
        issue = _issue("INVALID_TIME", field_name="time", source_row=row, column=cell.column)
        return _TimePart(None, _optional_text(cell), None, (issue,) + extra)
    if _is_text_cell(cell):
        parsed = _parse_time_text(cell, row)
    else:
        parsed = _parse_time_serial(cell, row)
    return _TimePart(parsed.clock, parsed.raw, parsed.serial_lexical, parsed.issues + extra)


def _parse_time_text(cell: CellEvidence, row: int) -> _TimePart:
    raw = _cell_plain_text(cell) or ""
    clock = _parse_iso_time(raw, "iso_text")
    if clock is not None:
        return _TimePart(clock, raw, None, _precision_issues(clock, "time", row, cell.column))
    parsed = _parse_iso_datetime(raw)
    if parsed is not None:
        _, embedded = parsed
        issues = _precision_issues(embedded, "time", row, cell.column)
        return _TimePart(embedded, raw, None, issues)
    issue = _issue("INVALID_TIME", field_name="time", source_row=row, column=cell.column)
    return _TimePart(None, raw, None, (issue,))


def _parse_time_serial(cell: CellEvidence, row: int) -> _TimePart:
    raw = _cell_plain_text(cell)
    if raw is None or raw == "":
        issue = _issue("MISSING_TIME", field_name="time", source_row=row, column=cell.column)
        return _TimePart(None, raw, None, (issue,))
    parsed = _split_serial(raw)
    failed = _serial_time_failure(parsed, raw, cell, row)
    if failed is not None:
        return failed
    clock = _clock_from_fraction(parsed.fraction, raw, "excel_serial")
    clock = _clock_with_day_offset(clock, parsed.days + clock.day_offset)
    return _TimePart(clock, raw, raw, ())


def _serial_time_failure(
    parsed: _SerialParse, raw: str, cell: CellEvidence, row: int
) -> _TimePart | None:
    if parsed.status == "ok":
        return None
    code = "UNSUPPORTED_SERIAL" if parsed.status == "unsupported" else "INVALID_TIME"
    issue = _issue(code, field_name="time", source_row=row, column=cell.column)
    return _TimePart(None, raw, raw, (issue,))


def _precision_issues(
    clock: _Clock, field_name: str, row: int, column: str
) -> tuple[ExactTransactionIssue, ...]:
    if clock.representable:
        return ()
    return (
        _issue("UNSUPPORTED_TIME_PRECISION", field_name=field_name, source_row=row, column=column),
    )


def _combine_temporal(
    date_part: _DatePart,
    time_part: _TimePart,
    date1904: bool,
) -> tuple[TemporalState, tuple[ExactTransactionIssue, ...]]:
    conflict = _temporal_conflict(date_part, time_part)
    clock = _chosen_clock(date_part, time_part, conflict)
    state = _temporal_state(date_part, time_part, clock, date1904, conflict=bool(conflict))
    return state, date_part.issues + time_part.issues + conflict


def _temporal_state(
    date_part: _DatePart,
    time_part: _TimePart,
    clock: _Clock | None,
    date1904: bool,
    *,
    conflict: bool,
) -> TemporalState:
    typed = clock is not None and clock.representable and not conflict
    flags: tuple[object, ...] = (object(),) if conflict else ()
    return TemporalState(
        parsed_date=date_part.value,
        parsed_time=None if clock is None or not typed else _clock_time(clock),
        parsed_datetime=_combine_datetime(date_part.value, clock, conflict),
        date_kind=date_part.kind,
        time_kind=None if clock is None else clock.kind,
        timezone_state="unknown" if clock is None else clock.timezone_state,
        timezone_offset=None if clock is None else clock.offset,
        precision=_temporal_precision(date_part, clock),
        time_fraction_digits=None if clock is None else clock.fraction_digits,
        uncertainty=_temporal_uncertainty(date_part, time_part, clock, flags),
        temporal_policy=TEMPORAL_POLICY,
        date_serial_lexical=date_part.serial_lexical,
        time_serial_lexical=time_part.serial_lexical,
        date1904=date1904,
    )


def _temporal_conflict(
    date_part: _DatePart,
    time_part: _TimePart,
) -> tuple[ExactTransactionIssue, ...]:
    embedded = date_part.embedded
    clock = time_part.clock
    if embedded is None or clock is None or _clocks_agree(embedded, clock):
        return ()
    issue = _issue("CONFLICTING_DATE_TIME", field_name="time", source_row=date_part.source_row)
    return (issue,)


def _chosen_clock(
    date_part: _DatePart, time_part: _TimePart, conflict: tuple[object, ...]
) -> _Clock | None:
    if conflict:
        return None
    if time_part.clock is not None:
        return time_part.clock
    return date_part.embedded


def _temporal_uncertainty(
    date_part: _DatePart,
    time_part: _TimePart,
    clock: _Clock | None,
    conflict: tuple[object, ...],
) -> tuple[str, ...]:
    flags: list[str] = []
    if date_part.value is None:
        flags.append("invalid_or_missing_date")
    if conflict:
        flags.append("conflicting_embedded_time")
    elif clock is None:
        flags.append("date_only")
        flags.append("missing_time")
    if any(issue.code == "INVALID_TIME" for issue in time_part.issues):
        flags.append("invalid_time")
    if clock is not None and not clock.representable:
        flags.append("unsupported_time_precision")
    return tuple(flags)


def _temporal_precision(date_part: _DatePart, clock: _Clock | None) -> str | None:
    if clock is not None:
        return clock.precision
    if date_part.value is not None:
        return "day"
    return None


def _combine_datetime(
    parsed_date: date | None,
    clock: _Clock | None,
    conflict: bool,
) -> datetime | None:
    if parsed_date is None or clock is None or conflict or not clock.representable:
        return None
    try:
        civil = parsed_date + timedelta(days=clock.day_offset)
        combined = datetime.combine(civil, _clock_time(clock))
        if clock.offset is None:
            return combined
        return combined.replace(tzinfo=_offset_tzinfo(clock.offset))
    except (OverflowError, ValueError):
        return None


def _clocks_agree(left: _Clock, right: _Clock) -> bool:
    left_key = (left.hour, left.minute, left.second, left.microsecond, left.fraction_digits)
    right_key = (right.hour, right.minute, right.second, right.microsecond, right.fraction_digits)
    return left_key == right_key and left.offset == right.offset


def _clock_time(clock: _Clock) -> time:
    return time(clock.hour, clock.minute, clock.second, clock.microsecond)


def _clock_with_day_offset(clock: _Clock, day_offset: int) -> _Clock:
    return replace(clock, day_offset=day_offset)


def _parse_iso_date(raw: str) -> date | None:
    match = _ISO_DATE_RE.fullmatch(raw)
    if match is None:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _parse_iso_time(raw: str, kind: str) -> _Clock | None:
    match = _ISO_TIME_RE.fullmatch(raw)
    if match is None:
        return None
    return _clock_from_iso_match(match, raw, kind, date_groups=False)


def _parse_iso_datetime(raw: str) -> tuple[date, _Clock] | None:
    match = _ISO_DATETIME_RE.fullmatch(raw)
    if match is None:
        return None
    try:
        value = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None
    clock = _clock_from_iso_match(match, raw, "iso_text", date_groups=True)
    if clock is None:
        return None
    return value, clock


def _clock_from_iso_match(
    match: re.Match[str],
    raw: str,
    kind: str,
    *,
    date_groups: bool,
) -> _Clock | None:
    shift = 3 if date_groups else 0
    hour, minute = int(match.group(1 + shift)), int(match.group(2 + shift))
    second_text, fraction, offset = match.group(3 + shift, 4 + shift, 5 + shift)
    second = 0 if second_text is None else int(second_text)
    parts = _iso_fraction_parts(second_text, fraction)
    if not _valid_hms(hour, minute, second, parts.microsecond) or not _valid_offset(offset):
        return None
    return _iso_clock((hour, minute, second), parts, offset, kind, raw)


def _iso_clock(
    hms: tuple[int, int, int],
    parts: _FractionParts,
    offset: str | None,
    kind: str,
    raw: str,
) -> _Clock:
    tz_state: TimezoneState = "known" if offset else "unknown"
    return _Clock(
        hms[0],
        hms[1],
        hms[2],
        parts.microsecond,
        parts.precision,
        offset,
        tz_state,
        kind,
        raw,
        fraction_digits=parts.digits,
        representable=parts.representable,
    )


def _iso_fraction_parts(second_text: str | None, fraction: str | None) -> _FractionParts:
    if second_text is None:
        return _FractionParts(0, "minute", None, True)
    if fraction is None:
        return _FractionParts(0, "second", None, True)
    if len(fraction) > 6:
        return _FractionParts(0, "submicrosecond", fraction, False)
    precision = "millisecond" if len(fraction) <= 3 else "microsecond"
    return _FractionParts(int(fraction.ljust(6, "0")), precision, fraction, True)


def _valid_hms(hour: int, minute: int, second: int, microsecond: int) -> bool:
    return (
        0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59 and 0 <= microsecond <= 999999
    )


def _valid_offset(token: str | None) -> bool:
    if token is None or token == "Z":
        return True
    hours = int(token[1:3])
    minutes = int(token[4:6])
    return hours < 24 and minutes < 60


def _offset_tzinfo(token: str) -> timezone:
    if token == "Z":
        return timezone.utc
    sign = 1 if token[0] == "+" else -1
    hours = int(token[1:3])
    minutes = int(token[4:6])
    return timezone(timedelta(hours=sign * hours, minutes=sign * minutes))


def _split_serial(lexical: str) -> _SerialParse:
    if len(lexical) > SERIAL_MAX_LEXEME_LENGTH:
        return _SerialParse("unsupported")
    match = _SERIAL_LEXEME_RE.fullmatch(lexical)
    if match is None:
        return _SerialParse("invalid")
    return _serial_from_match(match)


def _serial_from_match(match: re.Match[str]) -> _SerialParse:
    sign, int_part, frac_part, exp_part = match.groups()
    frac_part = frac_part or ""
    digits = int_part + frac_part
    if len(digits) > SERIAL_MAX_DIGITS or _exponent_out_of_range(exp_part):
        return _SerialParse("unsupported")
    fraction = _signed_serial_fraction(sign, digits, len(frac_part), exp_part)
    if fraction < 0:
        return _SerialParse("invalid")
    days = fraction.numerator // fraction.denominator
    return _SerialParse("ok", days, fraction - days)


def _exponent_out_of_range(exp_part: str | None) -> bool:
    if exp_part is None:
        return False
    magnitude = exp_part.lstrip("+-").lstrip("0") or "0"
    if len(magnitude) > len(str(SERIAL_MAX_ABS_EXPONENT)):
        return True
    return abs(int(exp_part)) > SERIAL_MAX_ABS_EXPONENT


def _signed_serial_fraction(
    sign: str | None, digits: str, frac_len: int, exp_part: str | None
) -> Fraction:
    exponent = 0 if exp_part is None else int(exp_part)
    power = exponent - frac_len
    numerator = int(digits or "0")
    if sign == "-":
        numerator = -numerator
    if power >= 0:
        return Fraction(numerator * (10**power), 1)
    return Fraction(numerator, 10 ** (-power))


def _clock_from_fraction(day_fraction: Fraction, lexical: str, kind: str) -> _Clock:
    rounded = _round_half_even(day_fraction * MS_PER_DAY)
    extra_days, millis = divmod(rounded, MS_PER_DAY)
    hour, rem = divmod(millis, 3_600_000)
    minute, rem = divmod(rem, 60_000)
    second, milli = divmod(rem, 1000)
    return _Clock(
        hour,
        minute,
        second,
        milli * 1000,
        "millisecond",
        None,
        "unknown",
        kind,
        lexical,
        extra_days,
    )


def _round_half_even(value: Fraction) -> int:
    integer = value.numerator // value.denominator
    remainder = value.numerator % value.denominator
    twice = remainder * 2
    if twice < value.denominator:
        return integer
    if twice > value.denominator:
        return integer + 1
    if integer % 2 == 0:
        return integer
    return integer + 1


def _excel_days_to_date(
    days: int,
    date1904: bool,
    row: int,
    column: str,
) -> date | ExactTransactionIssue:
    if date1904:
        return _shift_origin(date(1904, 1, 1), days, row, column)
    if days == 60:
        return _issue("EXCEL_FICTITIOUS_DAY_60", field_name="date", source_row=row, column=column)
    if days < 1:
        return _issue("INVALID_DATE", field_name="date", source_row=row, column=column)
    origin = date(1899, 12, 31) if days < 60 else date(1899, 12, 30)
    return _shift_origin(origin, days, row, column)


def _shift_origin(origin: date, days: int, row: int, column: str) -> date | ExactTransactionIssue:
    try:
        return origin + timedelta(days=days)
    except OverflowError:
        return _issue("DATE_OVERFLOW", field_name="date", source_row=row, column=column)


def _cells_by_row(sheet: SheetEvidence) -> dict[int, tuple[CellEvidence, ...]]:
    grouped: dict[int, list[CellEvidence]] = {}
    for cell in sheet.cells:
        grouped.setdefault(cell.row, []).append(cell)
    return {row: tuple(cells) for row, cells in grouped.items()}


def _cell_plain_text(cell: CellEvidence | None) -> str | None:
    if cell is None:
        return None
    if cell.inline_text is not None:
        return cell.inline_text.plain_text
    if cell.shared_text is not None:
        return cell.shared_text.plain_text
    if cell.value_state == "present":
        return cell.raw_value
    if cell.value_state == "empty":
        return ""
    return None


def _optional_text(cell: CellEvidence | None) -> str | None:
    text = _cell_plain_text(cell)
    if text is None or text == "":
        return None
    return text


def _cell_has_content(cell: CellEvidence) -> bool:
    if cell.formula is not None:
        return True
    if cell.inline_text is not None and cell.inline_text.plain_text != "":
        return True
    if cell.shared_text is not None and cell.shared_text.plain_text != "":
        return True
    return cell.value_state == "present" and bool(cell.raw_value)


def _is_text_cell(cell: CellEvidence) -> bool:
    if cell.inline_text is not None or cell.shared_text is not None:
        return True
    return cell.cell_type in {"s", "inlineStr", "str"}


def _issue(
    code: str,
    *,
    field_name: str | None = None,
    source_row: int | None = None,
    column: str | None = None,
) -> ExactTransactionIssue:
    return ExactTransactionIssue(
        code=code,
        field_name=field_name,
        source_row=source_row,
        column=column,
        detail=_ISSUE_DETAIL[code],
    )
