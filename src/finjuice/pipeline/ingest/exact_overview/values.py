"""Exact number, money, rate, and date capture from CellEvidence."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Final, NamedTuple

from finjuice.pipeline.ingest.exact_overview.models import (
    CurrencyPart,
    DateOrigin,
    DatePart,
    ExactOverviewIssue,
    NumberSpec,
    NumericPart,
    SnapshotDateEvidence,
)
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
from finjuice.pipeline.ingest.overview.cells import _parse_period_month_text
from finjuice.pipeline.ingest.overview.constants import _SNAPSHOT_DATE_LABELS
from finjuice.pipeline.ingest.schemas_helpers import normalize_sheet_name
from finjuice.pipeline.ingest.xlsx_evidence import CellEvidence, SheetEvidence, WorkbookEvidence
from finjuice.pipeline.storage.sqlite.errors import ExactValueError
from finjuice.pipeline.storage.sqlite.exact import UNKNOWN_CURRENCY, ExactValue


class _CallerDate(NamedTuple):
    origin: DateOrigin
    parsed: date | None
    raw: str | None
    reliable: bool
    extra: tuple[str, ...]


NUMBER_UNIT: Final = "source_number.v1"
RATE_UNIT: Final = "source_rate.v1"
_CURRENCY_RE: Final = re.compile(r"^[A-Z]{3}$")
_PLAIN_DECIMAL_RE: Final = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_DECORATION_MARKS: Final = (",", "₩", "$", "€", "원", "%", "만원")
_SLASH_DATE_RE: Final = re.compile(r"(\d{4})[./-]\s*(\d{1,2})[./-]\s*(\d{1,2})")
_KOREAN_DATE_RE: Final = re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")

_ISSUE_DETAIL: Final[dict[str, str]] = {
    "AMBIGUOUS_SHEETS": "Multiple worksheets match the overview catalog; pass sheet_name.",
    "SHEET_NOT_FOUND": "The requested sheet_name is not present in the workbook evidence.",
    "NOT_OVERVIEW_SHEET": "The selected sheet does not match the overview catalog.",
    "NO_OVERVIEW_SHEET": "No worksheet matches the overview catalog.",
    "AMBIGUOUS_HEADERS": "More than one uniquely complete header row is present.",
    "DUPLICATE_FIELD_MAPPING": "A catalog field maps to more than one header cell.",
    "AMBIGUOUS_BALANCE_ANCHORS": "Multiple equally eligible asset/liability tables are present.",
    "AMBIGUOUS_CASHFLOW_ANCHORS": "Multiple equally eligible cashflow anchors are present.",
    "AMBIGUOUS_MONTH_COLUMNS": "Duplicate cashflow period-month columns are present.",
    "NO_CASHFLOW_HEADER": "The cashflow anchor has no unique category and month headers.",
    "MISSING_SNAPSHOT_DATE": "No reliable snapshot date or documented fallback is available.",
    "CONFLICTING_LABELED_DATE": "Labeled snapshot dates disagree; none was chosen.",
    "AMBIGUOUS_LABELED_DATE": "A labeled snapshot date has multiple nearby candidates.",
    "AMBIGUOUS_FILENAME_DATE": "The source filename contains multiple distinct dates.",
    "INVALID_EXPLICIT_SNAPSHOT_DATE": (
        "Caller snapshot_date is not a supported ISO date and was not used."
    ),
    "INVALID_COLLECTED_AT": (
        "Caller collected_at is not a supported ISO date or datetime and was not used."
    ),
    "INVALID_DATE": "The date cell is not a supported ISO date or Excel serial.",
    "EXCEL_FICTITIOUS_DAY_60": "Excel 1900 serial day 60 is a fictitious leap day.",
    "DATE_OVERFLOW": "Excel serial date arithmetic overflowed the civil calendar.",
    "UNSUPPORTED_SERIAL": (
        "Excel serial lexeme exceeds the bounded serial policy; raw lexeme is retained."
    ),
    "FORMULA_CACHE_MISSING": "A formula without a cached value is unsupported.",
    "FORMULA_CACHED_UNVERIFIED": (
        "Cached formula results are captured evidence, not verified values."
    ),
    "UNKNOWN_CURRENCY": "Currency is missing or not an uppercase three-letter code.",
    "AMBIGUOUS_CURRENCY": "Multiple explicit currency markers disagree.",
    "INVALID_TEXT_CELL": "Boolean and error cells cannot establish semantic text.",
    "RATE_UNIT_UNCERTAIN": ("Rate unit is source-only; fraction versus percent was not assumed."),
    "AMOUNT_MISSING": "The amount cell is missing or empty.",
    "AMOUNT_BOOLEAN": "Boolean cells are unsupported money evidence.",
    "AMOUNT_ERROR_CELL": "Error cells are unsupported money evidence.",
    "AMOUNT_FORMATTED": "Formatted or decorated amount text is unsupported money evidence.",
    "AMOUNT_NONFINITE": "Non-finite amount lexemes are unsupported money evidence.",
    "AMOUNT_SCALE_OUT_OF_RANGE": "Amount scale is outside the ExactValue bound 0..255.",
    "UNSUPPORTED_AMOUNT": "The amount lexeme cannot be captured as ExactValue money.",
    "PAID_AMOUNT_MISSING": "The paid_amount cell is missing or empty.",
    "PAID_AMOUNT_BOOLEAN": "Boolean cells are unsupported money evidence.",
    "PAID_AMOUNT_ERROR_CELL": "Error cells are unsupported money evidence.",
    "PAID_AMOUNT_FORMATTED": "Formatted or decorated paid_amount text is unsupported.",
    "PAID_AMOUNT_NONFINITE": "Non-finite paid_amount lexemes are unsupported.",
    "PAID_AMOUNT_SCALE_OUT_OF_RANGE": "Paid amount scale is outside 0..255.",
    "UNSUPPORTED_PAID_AMOUNT": "The paid_amount lexeme cannot be captured as money.",
    "PRINCIPAL_AMOUNT_MISSING": "The principal_amount cell is missing or empty.",
    "PRINCIPAL_AMOUNT_BOOLEAN": "Boolean cells are unsupported money evidence.",
    "PRINCIPAL_AMOUNT_ERROR_CELL": "Error cells are unsupported money evidence.",
    "PRINCIPAL_AMOUNT_FORMATTED": "Formatted or decorated principal_amount text is unsupported.",
    "PRINCIPAL_AMOUNT_NONFINITE": "Non-finite principal_amount lexemes are unsupported.",
    "PRINCIPAL_AMOUNT_SCALE_OUT_OF_RANGE": "Principal amount scale is outside 0..255.",
    "UNSUPPORTED_PRINCIPAL_AMOUNT": "The principal_amount lexeme cannot be captured as money.",
    "VALUATION_AMOUNT_MISSING": "The valuation_amount cell is missing or empty.",
    "VALUATION_AMOUNT_BOOLEAN": "Boolean cells are unsupported money evidence.",
    "VALUATION_AMOUNT_ERROR_CELL": "Error cells are unsupported money evidence.",
    "VALUATION_AMOUNT_FORMATTED": "Formatted or decorated valuation_amount text is unsupported.",
    "VALUATION_AMOUNT_NONFINITE": "Non-finite valuation_amount lexemes are unsupported.",
    "VALUATION_AMOUNT_SCALE_OUT_OF_RANGE": "Valuation amount scale is outside 0..255.",
    "UNSUPPORTED_VALUATION_AMOUNT": "The valuation_amount lexeme cannot be captured as money.",
    "BALANCE_AMOUNT_MISSING": "The balance_amount cell is missing or empty.",
    "BALANCE_AMOUNT_BOOLEAN": "Boolean cells are unsupported money evidence.",
    "BALANCE_AMOUNT_ERROR_CELL": "Error cells are unsupported money evidence.",
    "BALANCE_AMOUNT_FORMATTED": "Formatted or decorated balance_amount text is unsupported.",
    "BALANCE_AMOUNT_NONFINITE": "Non-finite balance_amount lexemes are unsupported.",
    "BALANCE_AMOUNT_SCALE_OUT_OF_RANGE": "Balance amount scale is outside 0..255.",
    "UNSUPPORTED_BALANCE_AMOUNT": "The balance_amount lexeme cannot be captured as money.",
    "RETURN_RATE_MISSING": "The return_rate cell is missing or empty.",
    "RETURN_RATE_BOOLEAN": "Boolean cells are unsupported rate evidence.",
    "RETURN_RATE_ERROR_CELL": "Error cells are unsupported rate evidence.",
    "RETURN_RATE_FORMATTED": "Formatted or decorated return_rate text is unsupported.",
    "RETURN_RATE_NONFINITE": "Non-finite return_rate lexemes are unsupported.",
    "RETURN_RATE_SCALE_OUT_OF_RANGE": "Return rate scale is outside 0..255.",
    "UNSUPPORTED_RETURN_RATE": "The return_rate lexeme cannot be captured as a source rate.",
    "INTEREST_RATE_MISSING": "The interest_rate cell is missing or empty.",
    "INTEREST_RATE_BOOLEAN": "Boolean cells are unsupported rate evidence.",
    "INTEREST_RATE_ERROR_CELL": "Error cells are unsupported rate evidence.",
    "INTEREST_RATE_FORMATTED": "Formatted or decorated interest_rate text is unsupported.",
    "INTEREST_RATE_NONFINITE": "Non-finite interest_rate lexemes are unsupported.",
    "INTEREST_RATE_SCALE_OUT_OF_RANGE": "Interest rate scale is outside 0..255.",
    "UNSUPPORTED_INTEREST_RATE": "The interest_rate lexeme cannot be captured as a source rate.",
    "NUMBER_BOOLEAN": "Boolean cells are unsupported numeric evidence.",
    "NUMBER_ERROR_CELL": "Error cells are unsupported numeric evidence.",
    "NUMBER_FORMATTED": "Formatted or decorated numeric text is unsupported.",
    "NUMBER_NONFINITE": "Non-finite numeric lexemes are unsupported.",
    "NUMBER_SCALE_OUT_OF_RANGE": "Numeric scale is outside the ExactValue bound 0..255.",
    "UNSUPPORTED_NUMBER": "The lexeme cannot be captured as ExactValue number.",
}


def issue(
    code: str,
    *,
    field_name: str | None = None,
    source_row: int | None = None,
    column: str | None = None,
) -> ExactOverviewIssue:
    """Build a public issue whose detail never includes source values."""
    return ExactOverviewIssue(
        code=code,
        field_name=field_name,
        source_row=source_row,
        column=column,
        detail=_ISSUE_DETAIL[code],
    )


def column_index(column: str) -> int:
    """Convert an Excel column letter to a 1-based index."""
    value = 0
    for char in column:
        value = value * 26 + (ord(char) - 64)
    return value


def content_cells(sheet: SheetEvidence) -> tuple[CellEvidence, ...]:
    """Return captured nonempty cells in row, then column order."""
    cells = [cell for cell in sheet.cells if _cell_has_content(cell)]
    return tuple(sorted(cells, key=lambda cell: (cell.row, column_index(cell.column))))


def cell_text(cell: CellEvidence | None) -> str | None:
    """Return stripped source text, or None when empty."""
    return _optional_text(cell)


def normalized_text(cell: CellEvidence | None) -> str:
    """Return the catalog-normalized form of source cell text."""
    text = cell_text(cell)
    if text is None:
        return ""
    return normalize_sheet_name(text)


def parse_number(cell: CellEvidence | None, field_name: str = "number") -> NumericPart:
    """Capture a source number with unit ``source_number.v1``."""
    return _parse_numeric(cell, NumberSpec(field_name, "number", unit=NUMBER_UNIT))


def parse_money(cell: CellEvidence | None, field_name: str, currency: CurrencyPart) -> NumericPart:
    """Capture source money without inventing KRW."""
    money = UNKNOWN_CURRENCY if currency.unknown else currency.code
    spec = NumberSpec(field_name, "money", currency=money)
    parsed = _parse_numeric(cell, spec)
    unverified = parsed.unverified or currency.unverified
    return NumericPart(parsed.value, unverified, parsed.issues + currency.issues)


def parse_rate(cell: CellEvidence | None, field_name: str) -> NumericPart:
    """Capture a source-only rate; never assume fraction or percent."""
    parsed = _parse_numeric(cell, NumberSpec(field_name, "rate", unit=RATE_UNIT))
    if parsed.value is None:
        return parsed
    flag = issue("RATE_UNIT_UNCERTAIN", field_name=field_name, source_row=_row_of(cell))
    return NumericPart(parsed.value, parsed.unverified, (*parsed.issues, flag))


def header_currency(headers: tuple[CellEvidence, ...]) -> CurrencyPart:
    """Read explicit ISO codes or a bare 원 marker from header cells."""
    probes = tuple(_currency_from_cell(cell) for cell in headers)
    markers = tuple(item for item in probes if item.code is not None)
    unique = tuple(dict.fromkeys(item.code for item in markers))
    if len(unique) == 1:
        return _known_header_currency(markers)
    if len(unique) > 1:
        return CurrencyPart(None, True, (issue("AMBIGUOUS_CURRENCY"),), False)
    blocked = tuple(item for probe in probes for item in probe.issues)
    return CurrencyPart(None, True, (issue("UNKNOWN_CURRENCY"),) + blocked, False)


def parse_source_date(cell: CellEvidence | None, date1904: bool, field_name: str) -> DatePart:
    """Parse ISO text, t=d, or bounded Excel serial; never invent midnight."""
    if cell is None or not _cell_has_content(cell):
        return DatePart(None, None, None, None, cell, ())
    formula = formula_issues(cell, field_name)
    if any(item.code == "FORMULA_CACHE_MISSING" for item in formula):
        return DatePart(None, None, cell_text(cell), None, cell, formula)
    if cell.cell_type in {"b", "e"}:
        bad = issue("INVALID_DATE", field_name=field_name, source_row=cell.row, column=cell.column)
        return DatePart(None, None, cell_text(cell), None, cell, (bad,) + formula)
    parsed = _parse_date_payload(cell, date1904, field_name)
    return DatePart(
        parsed.value,
        parsed.kind,
        parsed.raw,
        parsed.serial_lexical,
        cell,
        parsed.issues + formula,
        parsed.uncertainty,
    )


def parse_period_month(cell: CellEvidence | None, date1904: bool) -> tuple[str | None, DatePart]:
    """Parse a cashflow month header from text or a serial date."""
    if cell is None or not _cell_has_content(cell):
        return None, DatePart(None, None, None, None, cell, ())
    formula = formula_issues(cell, "period_month")
    if any(item.code == "FORMULA_CACHE_MISSING" for item in formula):
        return None, DatePart(None, None, cell_text(cell), None, cell, formula)
    if is_date_text_cell(cell):
        return _period_from_text(cell, formula)
    return _period_from_date_or_text(cell, date1904, formula)


def formula_issues(cell: CellEvidence, field_name: str) -> tuple[ExactOverviewIssue, ...]:
    """Flag cached formulas as unverified and missing caches as unsupported."""
    if cell.formula is None:
        return ()
    row, column = cell.row, cell.column
    if cell.value_state != "present" or not cell.raw_value:
        return (
            issue("FORMULA_CACHE_MISSING", field_name=field_name, source_row=row, column=column),
        )
    return (
        issue("FORMULA_CACHED_UNVERIFIED", field_name=field_name, source_row=row, column=column),
    )


def unique_dates_in_text(text: str) -> tuple[date, ...]:
    """Return distinct civil dates found in ``text`` without last-match fallback."""
    found: list[date] = []
    iso = _parse_iso_date(text)
    if iso is not None:
        return (iso,)
    stamped = _parse_iso_datetime(text)
    if stamped is not None:
        return (stamped[0],)
    for year, month, day in _date_triples(text):
        try:
            found.append(date(year, month, day))
        except ValueError:
            continue
    return tuple(dict.fromkeys(found))


def resolve_snapshot(
    workbook: WorkbookEvidence,
    sheet: SheetEvidence | None,
    snapshot_date: str | None,
    source_filename: str | None,
    collected_at: str | None,
) -> tuple[SnapshotDateEvidence, tuple[ExactOverviewIssue, ...]]:
    """Resolve snapshot date: explicit, labeled, filename, then collected_at."""
    explicit, explicit_issues = _explicit_date(snapshot_date)
    if explicit is not None:
        spec = _CallerDate("explicit", explicit, snapshot_date, True, ())
        return _caller_snapshot(workbook, spec), explicit_issues
    labeled, labeled_issues = _labeled_snapshot(sheet, workbook.date1904)
    if labeled.value is not None:
        return _labeled_evidence(workbook, sheet, labeled), explicit_issues + labeled_issues
    filename, filename_issues = _filename_date(source_filename)
    if filename is not None:
        flags = ("filename_fallback", "not_source_observation")
        spec = _CallerDate("filename", filename, source_filename, False, flags)
        return _caller_snapshot(workbook, spec), explicit_issues + labeled_issues + filename_issues
    prior = explicit_issues + labeled_issues + filename_issues
    return _collected_snapshot(workbook, collected_at, prior)


def empty_snapshot(workbook: WorkbookEvidence, extra: tuple[str, ...] = ()) -> SnapshotDateEvidence:
    """Build a missing snapshot placeholder bound to workbook date1904."""
    return _caller_snapshot(workbook, _CallerDate("missing", None, None, False, extra))


def _parse_numeric(cell: CellEvidence | None, spec: NumberSpec) -> NumericPart:
    if cell is None:
        return NumericPart(None, False, (_missing_number(spec.field_name, None, None),))
    if cell.formula is not None:
        return _formula_number(cell, spec)
    return _plain_number(cell, spec, unverified=False)


def _formula_number(cell: CellEvidence, spec: NumberSpec) -> NumericPart:
    cached = formula_issues(cell, spec.field_name)
    if any(item.code == "FORMULA_CACHE_MISSING" for item in cached):
        return NumericPart(None, False, cached)
    parsed = _plain_number(cell, spec, unverified=True)
    return NumericPart(parsed.value, True, (*parsed.issues, *cached))


def _plain_number(cell: CellEvidence, spec: NumberSpec, *, unverified: bool) -> NumericPart:
    typed = _number_type_issue(cell, spec.field_name)
    if typed is not None:
        return NumericPart(None, unverified, (typed,))
    lexical = _cell_plain_text(cell)
    if lexical is None or lexical == "":
        missing = _missing_number(spec.field_name, cell.row, cell.column)
        return NumericPart(None, unverified, (missing,))
    return _number_from_lexical(lexical, cell, spec, unverified)


def _number_from_lexical(
    lexical: str, cell: CellEvidence, spec: NumberSpec, unverified: bool
) -> NumericPart:
    try:
        _validate_plain_decimal(lexical)
        value = ExactValue.from_lexical(
            lexical,
            value_kind=spec.value_kind,  # type: ignore[arg-type]
            origin_kind="source",
            currency=spec.currency if spec.value_kind == "money" else None,  # type: ignore[arg-type]
            unit=spec.unit,
        )
    except ExactValueError as exc:
        classified = _classify_numeric_error(exc, lexical, cell, spec.field_name)
        return NumericPart(None, unverified, (classified,))
    return NumericPart(value, unverified, ())


def _validate_plain_decimal(lexical: str) -> None:
    if _PLAIN_DECIMAL_RE.fullmatch(lexical) is not None:
        return
    if lexical.lower().lstrip("+-") in {"nan", "snan", "inf", "infinity"}:
        raise ExactValueError("Unsupported non-finite source number.")
    raise ExactValueError("Unsupported source decimal lexical form.")


def _number_type_issue(cell: CellEvidence, field_name: str) -> ExactOverviewIssue | None:
    if cell.cell_type == "b":
        code = _field_code(field_name, "BOOLEAN")
    elif cell.cell_type == "e":
        code = _field_code(field_name, "ERROR_CELL")
    else:
        return None
    return issue(code, field_name=field_name, source_row=cell.row, column=cell.column)


def _classify_numeric_error(
    exc: ExactValueError, lexical: str, cell: CellEvidence, field_name: str
) -> ExactOverviewIssue:
    message = str(exc)
    if "Scale must be between" in message:
        code = _field_code(field_name, "SCALE_OUT_OF_RANGE")
    elif "NaN" in message or "infinity" in message or "non-finite" in message:
        code = _field_code(field_name, "NONFINITE")
    elif any(mark in lexical for mark in _DECORATION_MARKS):
        code = _field_code(field_name, "FORMATTED")
    else:
        code = f"UNSUPPORTED_{field_name.upper()}"
    return issue(code, field_name=field_name, source_row=cell.row, column=cell.column)


def _missing_number(field_name: str, row: int | None, column: str | None) -> ExactOverviewIssue:
    return issue(
        _field_code(field_name, "MISSING"), field_name=field_name, source_row=row, column=column
    )


def _field_code(field_name: str, suffix: str) -> str:
    if field_name == "number":
        return f"NUMBER_{suffix}" if suffix != "MISSING" else "UNSUPPORTED_NUMBER"
    return f"{field_name.upper()}_{suffix}"


class _CurrencyProbe(NamedTuple):
    code: str | None
    issues: tuple[ExactOverviewIssue, ...]
    unverified: bool


def _currency_from_cell(cell: CellEvidence) -> _CurrencyProbe:
    formula = formula_issues(cell, "currency")
    missing = any(item.code == "FORMULA_CACHE_MISSING" for item in formula)
    if cell.cell_type in {"b", "e"} or missing:
        return _CurrencyProbe(None, formula, False)
    code = _currency_code((cell_text(cell) or "").strip())
    if code is None:
        return _CurrencyProbe(None, (), False)
    unverified = any(item.code == "FORMULA_CACHED_UNVERIFIED" for item in formula)
    return _CurrencyProbe(code, formula, unverified)


def _currency_code(text: str) -> str | None:
    if _CURRENCY_RE.fullmatch(text):
        return text
    if text == "원":
        return "KRW"
    return None


def _known_header_currency(markers: tuple[_CurrencyProbe, ...]) -> CurrencyPart:
    code = next(item.code for item in markers if item.code is not None)
    issues = tuple(item for probe in markers for item in probe.issues)
    unverified = any(probe.unverified for probe in markers)
    return CurrencyPart(code, False, issues, unverified)


def _period_from_text(
    cell: CellEvidence, formula: tuple[ExactOverviewIssue, ...]
) -> tuple[str | None, DatePart]:
    text = _cell_plain_text(cell) or ""
    period = _parse_period_month_text(text)
    extra = ("formula_cached_unverified",) if formula else ()
    return period, DatePart(None, "period_text", text, None, cell, formula, extra)


def _period_from_date_or_text(
    cell: CellEvidence, date1904: bool, formula: tuple[ExactOverviewIssue, ...]
) -> tuple[str | None, DatePart]:
    parsed = parse_source_date(cell, date1904, "period_month")
    if parsed.value is not None:
        return f"{parsed.value.year:04d}-{parsed.value.month:02d}", parsed
    text = _cell_plain_text(cell) or ""
    period = _parse_period_month_text(text)
    if period is None:
        return None, parsed
    extra = ("formula_cached_unverified",) if formula else ()
    return period, DatePart(None, "period_text", text, None, cell, formula, extra)


def _parse_date_payload(cell: CellEvidence, date1904: bool, field_name: str) -> DatePart:
    if is_date_text_cell(cell):
        return _parse_date_text(cell, field_name)
    return _parse_date_serial(cell, date1904, field_name)


def is_date_text_cell(cell: CellEvidence) -> bool:
    """Return True for shared/inline/str text or OOXML ``t=d`` date cells."""
    if cell.cell_type == "d":
        return True
    return _is_text_cell(cell)


def _parse_date_text(cell: CellEvidence, field_name: str) -> DatePart:
    raw = _cell_plain_text(cell) or ""
    dates = unique_dates_in_text(raw)
    kind = "iso_datetime" if cell.cell_type == "d" and "T" in raw else "iso_text"
    if cell.cell_type == "d":
        kind = "iso_datetime" if "T" in raw else "iso_date"
    if len(dates) == 1:
        extra = ("datetime_text_date_only",) if "T" in raw else ()
        return DatePart(dates[0], kind, raw, None, cell, (), extra)
    bad = issue("INVALID_DATE", field_name=field_name, source_row=cell.row, column=cell.column)
    return DatePart(None, kind, raw, None, cell, (bad,))


def _parse_date_serial(cell: CellEvidence, date1904: bool, field_name: str) -> DatePart:
    raw = _cell_plain_text(cell)
    if raw is None or raw == "":
        return DatePart(None, None, raw, None, cell, ())
    parsed = _split_serial(raw)
    if parsed.status != "ok":
        code = "UNSUPPORTED_SERIAL" if parsed.status == "unsupported" else "INVALID_DATE"
        bad = issue(code, field_name=field_name, source_row=cell.row, column=cell.column)
        return DatePart(None, "excel_serial", raw, raw, cell, (bad,))
    serial = (parsed.days, parsed.fraction != 0)
    return _civil_from_serial(serial, raw, date1904, cell, field_name)


def _civil_from_serial(
    serial: tuple[int, bool], raw: str, date1904: bool, cell: CellEvidence, field_name: str
) -> DatePart:
    days, has_fraction = serial
    extra = ("serial_fraction_ignored",) if has_fraction else ()
    civil = _excel_days_to_date(days, date1904, cell.row, cell.column)
    if isinstance(civil, ExactTransactionIssue):
        bad = issue(civil.code, field_name=field_name, source_row=cell.row, column=cell.column)
        return DatePart(None, "excel_serial", raw, raw, cell, (bad,), extra)
    return DatePart(civil, "excel_serial", raw, raw, cell, (), extra)


def _date_triples(text: str) -> tuple[tuple[int, int, int], ...]:
    matches = [(int(y), int(m), int(d)) for y, m, d in _SLASH_DATE_RE.findall(text)]
    matches.extend((int(y), int(m), int(d)) for y, m, d in _KOREAN_DATE_RE.findall(text))
    return tuple(matches)


def _explicit_date(raw: str | None) -> tuple[date | None, tuple[ExactOverviewIssue, ...]]:
    if raw is None or raw == "":
        return None, ()
    parsed = _parse_iso_date(raw)
    if parsed is not None:
        return parsed, ()
    return None, (issue("INVALID_EXPLICIT_SNAPSHOT_DATE"),)


def _filename_date(
    source_filename: str | None,
) -> tuple[date | None, tuple[ExactOverviewIssue, ...]]:
    if source_filename is None or source_filename == "":
        return None, ()
    dates = unique_dates_in_text(Path(source_filename).stem)
    if len(dates) == 1:
        return dates[0], ()
    if len(dates) > 1:
        return None, (issue("AMBIGUOUS_FILENAME_DATE"),)
    return None, ()


def _collected_date(raw: str | None) -> tuple[date | None, tuple[ExactOverviewIssue, ...]]:
    if raw is None or raw == "":
        return None, ()
    parsed = _parse_iso_date(raw)
    if parsed is not None:
        return parsed, ()
    stamped = _parse_iso_datetime(raw)
    if stamped is not None:
        return stamped[0], ()
    return None, (issue("INVALID_COLLECTED_AT"),)


def _labeled_snapshot(
    sheet: SheetEvidence | None, date1904: bool
) -> tuple[DatePart, tuple[ExactOverviewIssue, ...]]:
    empty = DatePart(None, None, None, None, None, ())
    if sheet is None:
        return empty, ()
    parsed = _collect_labeled_dates(sheet, date1904)
    issues = tuple(item for part in parsed for item in part.issues)
    if any(item.code == "AMBIGUOUS_LABELED_DATE" for item in issues):
        return empty, issues
    unique = tuple(dict.fromkeys(part.value for part in parsed if part.value is not None))
    if len(unique) > 1:
        return empty, issues + (issue("CONFLICTING_LABELED_DATE"),)
    if len(unique) == 1:
        return next(part for part in parsed if part.value == unique[0]), issues
    return empty, issues


def _collect_labeled_dates(sheet: SheetEvidence, date1904: bool) -> tuple[DatePart, ...]:
    grouped = _cells_by_row(sheet)
    found: list[DatePart] = []
    for cell in content_cells(sheet):
        if normalized_text(cell) not in _SNAPSHOT_DATE_LABELS:
            continue
        found.append(_nearby_labeled_date(grouped, cell, date1904))
    return tuple(found)


def _nearby_labeled_date(
    grouped: dict[int, tuple[CellEvidence, ...]],
    label: CellEvidence,
    date1904: bool,
) -> DatePart:
    nearby = _nearby_candidates(grouped, label)
    parsed = tuple(parse_source_date(cell, date1904, "snapshot_date") for cell in nearby)
    usable = tuple(part for part in parsed if part.value is not None)
    unique = tuple(dict.fromkeys(part.value for part in usable))
    if len(unique) > 1:
        bad = issue("AMBIGUOUS_LABELED_DATE", source_row=label.row, column=label.column)
        return DatePart(None, None, None, None, label, (bad,))
    if len(unique) == 1:
        chosen = next(part for part in usable if part.value == unique[0])
        return _attach_label_formula(chosen, label)
    extras = tuple(item for part in parsed for item in part.issues)
    return DatePart(None, None, None, None, label, extras + formula_issues(label, "snapshot_date"))


def _attach_label_formula(part: DatePart, label: CellEvidence) -> DatePart:
    extra_issues = formula_issues(label, "snapshot_date")
    if not extra_issues:
        return part
    extra = part.uncertainty + ("formula_label_unverified",)
    return DatePart(
        part.value,
        part.kind,
        part.raw,
        part.serial_lexical,
        part.cell,
        part.issues + extra_issues,
        extra,
    )


def _nearby_candidates(
    grouped: dict[int, tuple[CellEvidence, ...]], label: CellEvidence
) -> tuple[CellEvidence, ...]:
    start = column_index(label.column)
    same = tuple(
        cell
        for cell in grouped.get(label.row, ())
        if start < column_index(cell.column) <= start + 3
    )
    below = tuple(cell for cell in grouped.get(label.row + 1, ()) if cell.column == label.column)
    return same + below


def _labeled_evidence(
    workbook: WorkbookEvidence, sheet: SheetEvidence | None, labeled: DatePart
) -> SnapshotDateEvidence:
    cell = labeled.cell
    sheet_name = None if sheet is None else sheet.name
    extra = labeled.uncertainty + _formula_date_flags(labeled)
    extra = tuple(dict.fromkeys(extra))
    reliable = labeled.value is not None and cell is not None and cell.formula is None
    return SnapshotDateEvidence(
        parsed_date=labeled.value,
        raw=labeled.raw,
        origin="source_label",
        kind=labeled.kind,
        serial_lexical=labeled.serial_lexical,
        source_sheet=sheet_name,
        source_row=None if cell is None else cell.row,
        source_column=None if cell is None else cell.column,
        date1904=workbook.date1904,
        temporal_policy=TEMPORAL_POLICY,
        uncertainty=extra,
        reliable=reliable,
    )


def _formula_date_flags(labeled: DatePart) -> tuple[str, ...]:
    cell = labeled.cell
    if cell is None or cell.formula is None:
        return ()
    codes = {item.code for item in labeled.issues}
    if "FORMULA_CACHE_MISSING" in codes:
        return ("formula_cache_missing",)
    return ("formula_cached_unverified",)


def _collected_snapshot(
    workbook: WorkbookEvidence,
    collected_at: str | None,
    prior: tuple[ExactOverviewIssue, ...],
) -> tuple[SnapshotDateEvidence, tuple[ExactOverviewIssue, ...]]:
    collected, collected_issues = _collected_date(collected_at)
    issues = prior + collected_issues
    if collected is not None:
        flags = ("collection_fallback", "not_source_observation")
        spec = _CallerDate("collected_at", collected, collected_at, False, flags)
        return _caller_snapshot(workbook, spec), issues
    missing = issue("MISSING_SNAPSHOT_DATE", field_name="snapshot_date")
    return empty_snapshot(workbook), issues + (missing,)


def _caller_snapshot(workbook: WorkbookEvidence, spec: _CallerDate) -> SnapshotDateEvidence:
    kind = "iso_text" if spec.origin in {"explicit", "filename", "collected_at"} else None
    return SnapshotDateEvidence(
        parsed_date=spec.parsed,
        raw=spec.raw,
        origin=spec.origin,
        kind=kind,
        serial_lexical=None,
        source_sheet=None,
        source_row=None,
        source_column=None,
        date1904=workbook.date1904,
        temporal_policy=TEMPORAL_POLICY,
        uncertainty=spec.extra,
        reliable=spec.reliable,
    )


def _row_of(cell: CellEvidence | None) -> int | None:
    if cell is None:
        return None
    return cell.row
