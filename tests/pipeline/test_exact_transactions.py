"""Synthetic WorkbookEvidence tests for the pure exact transaction mapper."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from datetime import date, time, timezone
from decimal import localcontext
from fractions import Fraction

from finjuice.pipeline.ingest.exact_transactions import (
    PARSER_VERSION,
    SERIAL_MAX_ABS_EXPONENT,
    SERIAL_MAX_DIGITS,
    SERIAL_MAX_LEXEME_LENGTH,
    TEMPORAL_POLICY,
    canonical_numeric_key,
    exact_amount_fraction,
    map_exact_transactions,
)
from finjuice.pipeline.ingest.xlsx_evidence import read_workbook_evidence
from finjuice.pipeline.storage.sqlite.exact import ExactValue

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

KR = [
    "날짜",
    "시간",
    "타입",
    "내용",
    "금액",
    "결제수단",
    "화폐",
    "비고",
    "지출",
    "수입",
    "이체",
    "카드A",
    "extra-value",
    "출금",
    "입금",
]


def _zip_bytes(members: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in members.items():
            archive.writestr(name, text)
    return buffer.getvalue()


def _sst(texts: list[str]) -> str:
    items = "".join(f"<si><t>{text}</t></si>" for text in texts)
    return f'<?xml version="1.0" encoding="UTF-8"?><sst xmlns="{MAIN_NS}">{items}</sst>'


def _sheet_xml(rows: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<worksheet xmlns="{MAIN_NS}"><sheetData>{rows}</sheetData></worksheet>'
    )


def _workbook_xml(sheets: str, *, date1904: bool = False) -> str:
    props = '<workbookPr date1904="1"/>' if date1904 else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<workbook xmlns="{MAIN_NS}" xmlns:r="{DOC_REL_NS}">'
        f"{props}<sheets>{sheets}</sheets></workbook>"
    )


def _rels(entries: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Relationships xmlns="{PKG_REL_NS}">{entries}</Relationships>'
    )


def _s(ref: str, index: int) -> str:
    return f'<c r="{ref}" t="s"><v>{index}</v></c>'


def _n(ref: str, lexical: str, *, style: str | None = None) -> str:
    styled = "" if style is None else f' s="{style}"'
    return f'<c r="{ref}"{styled}><v>{lexical}</v></c>'


def _inline(ref: str, text: str) -> str:
    return f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>'


def _formula(ref: str, text: str, cached: str | None = None) -> str:
    if cached is None:
        return f'<c r="{ref}"><f>{text}</f></c>'
    return f'<c r="{ref}"><f>{text}</f><v>{cached}</v></c>'


def _bool(ref: str, lexical: str) -> str:
    return f'<c r="{ref}" t="b"><v>{lexical}</v></c>'


def _err(ref: str, lexical: str) -> str:
    return f'<c r="{ref}" t="e"><v>{lexical}</v></c>'


def _row(number: int, *cells: str) -> str:
    return f'<row r="{number}">{"".join(cells)}</row>'


def _package(
    sheets: dict[str, str], *, shared: list[str] | None = None, date1904: bool = False
) -> bytes:
    names = list(sheets)
    sheet_tags = "".join(
        f'<sheet name="{name}" sheetId="{index}" r:id="rId{index}"/>'
        for index, name in enumerate(names, start=1)
    )
    rels = "".join(
        f'<Relationship Id="rId{index}" Type="{DOC_REL_NS}/worksheet" '
        f'Target="worksheets/sheet{index}.xml"/>'
        for index, _name in enumerate(names, start=1)
    )
    shared_rel = ""
    members: dict[str, str] = {
        "_rels/.rels": _rels(
            f'<Relationship Id="rId1" Type="{DOC_REL_NS}/officeDocument" Target="xl/workbook.xml"/>'
        ),
        "xl/workbook.xml": _workbook_xml(sheet_tags, date1904=date1904),
    }
    if shared is not None:
        shared_rel = (
            f'<Relationship Id="rIdS" Type="{DOC_REL_NS}/sharedStrings" '
            'Target="sharedStrings.xml"/>'
        )
        members["xl/sharedStrings.xml"] = _sst(shared)
    members["xl/_rels/workbook.xml.rels"] = _rels(rels + shared_rel)
    for index, rows in enumerate(sheets.values(), start=1):
        members[f"xl/worksheets/sheet{index}.xml"] = _sheet_xml(rows)
    return _zip_bytes(members)


def _map(
    sheets: dict[str, str],
    *,
    shared: list[str] | None = None,
    date1904: bool = False,
    sheet_name: str | None = None,
):
    data = _package(sheets, shared=shared, date1904=date1904)
    evidence = read_workbook_evidence(data)
    before = evidence
    result = map_exact_transactions(evidence, sheet_name=sheet_name)
    assert evidence == before
    return result, evidence


def _kr_header(row: int = 1) -> str:
    return _row(
        row,
        _s(f"A{row}", 0),
        _s(f"B{row}", 1),
        _s(f"C{row}", 2),
        _s(f"D{row}", 3),
        _s(f"E{row}", 4),
        _s(f"F{row}", 5),
        _s(f"G{row}", 6),
        _s(f"H{row}", 7),
    )


@dataclass(frozen=True)
class _Tx:
    date_cell: str
    amount: str
    time_cell: str | None = None
    type_idx: int = 8
    merchant: str = "x"
    currency: str | None = "KRW"
    extra: str | None = None


def _tx(number: int, spec: _Tx) -> str:
    cells = [spec.date_cell]
    if spec.time_cell is not None:
        cells.append(spec.time_cell)
    cells.extend(
        [
            _s(f"C{number}", spec.type_idx),
            _inline(f"D{number}", spec.merchant),
            spec.amount,
            _s(f"F{number}", 11),
        ]
    )
    if spec.currency is not None:
        cells.append(_inline(f"G{number}", spec.currency))
    if spec.extra is not None:
        cells.append(spec.extra)
    return _row(number, *cells)


def _codes(row) -> list[str]:
    return [issue.code for issue in row.issues]


def test_korean_headers_map_required_fields_and_keep_unknown_columns() -> None:
    rows = _kr_header() + _tx(
        2,
        _Tx(
            date_cell=_inline("A2", "2024-03-15"),
            time_cell=_inline("B2", "13:04:05.123+09:00"),
            merchant="카페",
            amount=_n("E2", "-1000.00"),
            extra=_s("H2", 12),
        ),
    )
    result, _evidence = _map({"가계부": rows}, shared=KR)

    assert result.status == "mapped"
    assert result.parser_version == PARSER_VERSION
    assert result.header_row == 1
    assert result.unknown_headers[0].header_text == "비고"
    row = result.rows[0]
    assert row.supported is True
    assert row.type_norm == "expense"
    assert row.source_amount is not None
    assert row.source_amount.lexical == "-1000.00"
    assert row.source_amount.currency == "KRW"
    assert row.interpreted_amount is None
    assert row.unknown_cells[0].cell.shared_text is not None
    assert row.temporal.parsed_date == date(2024, 3, 15)
    assert row.temporal.timezone_offset == "+09:00"
    assert row.temporal.timezone_state == "known"
    assert row.temporal.precision == "millisecond"
    assert row.datetime_raw is not None


def test_english_headers_match_catalog_variants() -> None:
    header = _row(
        1,
        _inline("A1", "Date"),
        _inline("B1", "Time"),
        _inline("C1", "Type"),
        _inline("D1", "Merchant"),
        _inline("E1", "Amount"),
        _inline("F1", "Account"),
        _inline("G1", "Currency"),
    )
    data = _row(
        2,
        _inline("A2", "2024-01-02"),
        _inline("B2", "09:30"),
        _inline("C2", "지출"),
        _inline("D2", "Shop"),
        _n("E2", "10.10"),
        _inline("F2", "Card"),
        _inline("G2", "USD"),
    )
    result, _evidence = _map({"Ledger": header + data})
    row = result.rows[0]
    assert result.status == "mapped"
    assert row.source_amount is not None
    assert row.source_amount.currency == "USD"
    assert row.temporal.precision == "minute"
    assert canonical_numeric_key(row.source_amount) == ("101", 1)


def test_preamble_uses_the_unique_matching_header_row() -> None:
    rows = (
        _row(1, _inline("A1", "가계부 내역"))
        + _row(2, _n("A2", "1"))
        + _kr_header(3)
        + _tx(
            4,
            _Tx(
                date_cell=_inline("A4", "2024-05-01"),
                time_cell=_inline("B4", "10:00:00"),
                merchant="상점",
                amount=_n("E4", "1"),
            ),
        )
    )
    result, _evidence = _map({"내역": rows}, shared=KR)
    assert result.header_row == 3
    assert result.rows[0].source_row == 4


def test_ambiguous_header_rows_fail_without_selecting_data() -> None:
    rows = _kr_header(1) + _kr_header(4)
    result, _evidence = _map({"내역": rows}, shared=KR)
    assert result.status == "ambiguous_headers"
    assert result.rows == ()
    assert result.issues[0].code == "AMBIGUOUS_HEADERS"


def test_duplicate_date_headers_fail_clearly() -> None:
    header = _row(
        1,
        _s("A1", 0),
        _inline("B1", "Date"),
        _s("C1", 1),
        _s("D1", 2),
        _s("E1", 3),
        _s("F1", 4),
        _s("G1", 5),
    )
    result, _evidence = _map({"내역": header}, shared=KR)
    assert result.status == "duplicate_field_mapping"
    assert result.rows == ()


def test_multiple_transaction_sheets_fail_unless_named() -> None:
    sheet = _kr_header() + _tx(
        2,
        _Tx(
            date_cell=_inline("A2", "2024-01-01"),
            time_cell=_inline("B2", "00:01"),
            merchant="A",
            amount=_n("E2", "1"),
        ),
    )
    result, evidence = _map({"하나": sheet, "둘": sheet}, shared=KR)
    assert result.status == "ambiguous_sheets"
    assert result.candidate_sheet_names == ("하나", "둘")
    named = map_exact_transactions(evidence, sheet_name="둘")
    assert named.status == "mapped"
    assert named.sheet_name == "둘"


def test_asset_only_workbook_is_explicitly_empty() -> None:
    rows = _row(1, _inline("A1", "기관"), _inline("B1", "상품명"), _n("C1", "1"))
    result, _evidence = _map({"자산": rows})
    assert result.status == "no_transaction_sheet"
    assert result.rows == ()
    assert result.issues[0].code == "NO_TRANSACTION_SHEET"


def test_blank_layout_rows_are_skipped_and_content_rows_are_kept() -> None:
    rows = (
        _kr_header()
        + _row(2, _n("A2", ""), _n("B2", ""))
        + _tx(
            3,
            _Tx(
                date_cell=_inline("A3", "not-iso"),
                time_cell=_inline("B3", "25:61"),
                amount=_err("E3", "#VALUE!"),
            ),
        )
    )
    result, _evidence = _map({"내역": rows}, shared=KR)
    assert result.skipped_blank_rows == 1
    assert len(result.rows) == 1
    assert result.rows[0].supported is False
    assert "INVALID_DATE" in _codes(result.rows[0])
    assert "INVALID_TIME" in _codes(result.rows[0])
    assert "AMOUNT_ERROR_CELL" in _codes(result.rows[0])
    assert result.rows[0].temporal.parsed_time is None
    assert result.rows[0].datetime_raw is None


def test_large_scale_signed_zero_refund_and_negative_income() -> None:
    rows = _kr_header() + "".join(
        [
            _tx(
                2,
                _Tx(
                    _inline("A2", "2024-01-01"),
                    _n("E2", "9007199254740993"),
                    _inline("B2", "10:00"),
                    merchant="huge",
                ),
            ),
            _tx(
                3,
                _Tx(
                    _inline("A3", "2024-01-01"),
                    _n("E3", "1e-255"),
                    _inline("B3", "10:00"),
                    merchant="tiny",
                ),
            ),
            _tx(
                4,
                _Tx(
                    _inline("A4", "2024-01-01"),
                    _n("E4", "1e-256"),
                    _inline("B4", "10:00"),
                    merchant="overflow",
                ),
            ),
            _tx(
                5,
                _Tx(
                    _inline("A5", "2024-01-01"),
                    _n("E5", "-0.00"),
                    _inline("B5", "10:00"),
                    merchant="zero",
                ),
            ),
            _tx(
                6,
                _Tx(
                    _inline("A6", "2024-01-01"),
                    _n("E6", "127000"),
                    _inline("B6", "10:00"),
                    merchant="refund",
                ),
            ),
            _tx(
                7,
                _Tx(
                    _inline("A7", "2024-01-01"),
                    _n("E7", "-50.10"),
                    _inline("B7", "10:00"),
                    9,
                    "income",
                ),
            ),
            _tx(
                8,
                _Tx(
                    _inline("A8", "2024-01-01"), _n("E8", "-70"), _inline("B8", "10:00"), 10, "out"
                ),
            ),
            _tx(
                9,
                _Tx(_inline("A9", "2024-01-01"), _n("E9", "70"), _inline("B9", "10:00"), 10, "in"),
            ),
        ]
    )
    with localcontext() as context:
        context.prec = 2
        result, _evidence = _map({"내역": rows}, shared=KR)
    huge, tiny, overflow, zero, refund, income, outgoing, incoming = result.rows
    assert huge.source_amount is not None
    assert huge.source_amount.coefficient == "9007199254740993"
    assert tiny.source_amount is not None
    assert tiny.source_amount.scale == 255
    assert overflow.source_amount is None
    assert "AMOUNT_SCALE_OUT_OF_RANGE" in _codes(overflow)
    assert zero.source_amount is not None
    assert zero.source_amount.coefficient == "0"
    assert zero.source_amount.lexical == "-0.00"
    assert refund.source_amount is not None
    assert refund.source_amount.coefficient == "127000"
    assert refund.interpreted_amount is None
    assert income.type_norm == "income"
    assert income.source_amount is not None
    assert income.source_amount.coefficient == "-5010"
    assert income.interpreted_amount is not None
    assert income.interpreted_amount.origin_kind == "calculated"
    assert income.interpreted_amount.lexical is None
    assert income.interpreted_amount.coefficient == "5010"
    assert income.interpreted_amount.scale == income.source_amount.scale
    assert "NEGATIVE_INCOME_NORMALIZED" in _codes(income)
    assert outgoing.source_amount is not None
    assert outgoing.source_amount.coefficient == "-70"
    assert outgoing.interpreted_amount is None
    assert incoming.source_amount is not None
    assert incoming.source_amount.coefficient == "70"


def test_missing_and_invalid_currency_are_unknown_never_krw() -> None:
    rows = _kr_header() + "".join(
        [
            _tx(
                2,
                _Tx(
                    _inline("A2", "2024-01-01"),
                    _n("E2", "1"),
                    _inline("B2", "10:00"),
                    merchant="none",
                    currency=None,
                ),
            ),
            _tx(
                3,
                _Tx(
                    _inline("A3", "2024-01-01"),
                    _n("E3", "1"),
                    _inline("B3", "10:00"),
                    merchant="bad",
                    currency="krw",
                ),
            ),
        ]
    )
    result, _evidence = _map({"내역": rows}, shared=KR)
    for row in result.rows:
        assert row.currency_unknown is True
        assert row.currency_code is None
        assert row.source_amount is not None
        assert row.source_amount.currency_unknown is True
        assert row.source_amount.currency is None
        assert "UNKNOWN_CURRENCY" in _codes(row)


def test_account_text_is_not_turned_into_an_identity() -> None:
    rows = _kr_header() + _tx(
        2, _Tx(_inline("A2", "2024-01-01"), _n("E2", "1"), _inline("B2", "10:00"))
    )
    result, _evidence = _map({"내역": rows}, shared=KR)
    row = result.rows[0]
    assert row.account_text == "카드A"
    assert not hasattr(row, "account_id")
    assert row.identity.account_text == "카드A"


def test_excel_1900_days_59_60_61_and_1904_epoch() -> None:
    rows_1900 = _kr_header() + "".join(
        [
            _tx(2, _Tx(_n("A2", "59", style="4"), _n("E2", "1"), _n("B2", "0.5"), merchant="d59")),
            _tx(3, _Tx(_n("A3", "60"), _n("E3", "1"), _n("B3", "0"), merchant="d60")),
            _tx(4, _Tx(_n("A4", "61"), _n("E4", "1"), _n("B4", "0"), merchant="d61")),
        ]
    )
    mapped_1900, _evidence = _map({"내역": rows_1900}, shared=KR)
    day59, day60, day61 = mapped_1900.rows
    assert day59.temporal.parsed_date == date(1900, 2, 28)
    assert day59.temporal.parsed_time == time(12, 0, 0)
    assert "EXCEL_FICTITIOUS_DAY_60" in _codes(day60)
    assert day60.temporal.parsed_date is None
    assert day60.supported is False
    assert day61.temporal.parsed_date == date(1900, 3, 1)
    assert day59.temporal.date_serial_lexical == "59"

    rows_1904 = _kr_header() + _tx(
        2,
        _Tx(_n("A2", "0"), _n("E2", "1"), _inline("B2", "00:00:00"), merchant="epoch"),
    )
    mapped_1904, _evidence = _map({"내역": rows_1904}, shared=KR, date1904=True)
    assert mapped_1904.date1904 is True
    assert mapped_1904.rows[0].temporal.parsed_date == date(1904, 1, 1)
    assert mapped_1904.rows[0].temporal.date1904 is True


def test_excel_fraction_policy_tie_even_day_carry_and_recurring_minute() -> None:
    rows = _kr_header() + "".join(
        [
            _tx(2, _Tx(_n("A2", "1.00000015625"), _n("E2", "1"), merchant="odd-tie")),
            _tx(3, _Tx(_n("A3", "1.00000046875"), _n("E3", "1"), merchant="even-tie")),
            _tx(4, _Tx(_n("A4", "1.999999995"), _n("E4", "1"), merchant="carry")),
            _tx(5, _Tx(_n("A5", "1.0006944444444444"), _n("E5", "1"), merchant="minute")),
            _tx(6, _Tx(_n("A6", "1"), _n("E6", "1"), merchant="date-only")),
        ]
    )
    result, _evidence = _map({"내역": rows}, shared=KR)
    odd_tie, even_tie, carry, minute, date_only = result.rows
    assert odd_tie.temporal.temporal_policy == TEMPORAL_POLICY
    assert odd_tie.temporal.parsed_date == date(1900, 1, 1)
    assert odd_tie.temporal.parsed_time == time(0, 0, 0, 14000)
    assert even_tie.temporal.parsed_time == time(0, 0, 0, 40000)
    assert carry.temporal.parsed_date == date(1900, 1, 2)
    assert carry.temporal.parsed_time == time(0, 0, 0)
    assert minute.temporal.precision == "millisecond"
    assert minute.temporal.date_serial_lexical == "1.0006944444444444"
    assert date_only.temporal.parsed_time is None
    assert date_only.datetime_raw is None
    assert "date_only" in date_only.temporal.uncertainty
    assert "missing_time" in date_only.temporal.uncertainty


def test_conflicting_embedded_time_is_not_silently_chosen() -> None:
    rows = _kr_header() + _tx(
        2,
        _Tx(_n("A2", "1.5"), _n("E2", "1"), _n("B2", "0"), merchant="conflict"),
    )
    result, _evidence = _map({"내역": rows}, shared=KR)
    row = result.rows[0]
    assert "CONFLICTING_DATE_TIME" in _codes(row)
    assert row.temporal.parsed_date == date(1900, 1, 1)
    assert row.temporal.parsed_time is None
    assert row.temporal.parsed_datetime is None
    assert row.supported is False


def test_formula_cached_amount_is_unverified_and_missing_cache_is_unsupported() -> None:
    rows = _kr_header() + "".join(
        [
            _tx(
                2,
                _Tx(
                    _inline("A2", "2024-01-01"),
                    _formula("E2", "A2", "42.5"),
                    _inline("B2", "10:00"),
                    merchant="cached",
                ),
            ),
            _tx(
                3,
                _Tx(
                    _inline("A3", "2024-01-01"),
                    _formula("E3", "A3"),
                    _inline("B3", "10:00"),
                    merchant="uncached",
                ),
            ),
            _tx(
                4,
                _Tx(
                    _inline("A4", "2024-01-01"),
                    _bool("E4", "1"),
                    _inline("B4", "10:00"),
                    merchant="bool",
                ),
            ),
            _tx(
                5,
                _Tx(
                    _inline("A5", "2024-01-01"),
                    _inline("E5", "1,000"),
                    _inline("B5", "10:00"),
                    merchant="formatted",
                ),
            ),
        ]
    )
    result, _evidence = _map({"내역": rows}, shared=KR)
    cached, uncached, boolean, formatted = result.rows
    assert cached.source_amount is not None
    assert cached.source_amount.lexical == "42.5"
    assert cached.amount_unverified is True
    assert "FORMULA_CACHED_UNVERIFIED" in _codes(cached)
    assert cached.cells[4].formula is not None
    assert uncached.source_amount is None
    assert uncached.supported is False
    assert "FORMULA_CACHE_MISSING" in _codes(uncached)
    assert "AMOUNT_BOOLEAN" in _codes(boolean)
    assert "AMOUNT_FORMATTED" in _codes(formatted)
    assert formatted.source_amount is None


def test_canonical_numeric_key_equates_scale_variants_without_changing_source() -> None:
    left = ExactValue.from_lexical("10.10", value_kind="money", currency="KRW")
    right = ExactValue.from_lexical("10.1", value_kind="money", currency="KRW")
    assert canonical_numeric_key(left) == canonical_numeric_key(right) == ("101", 1)
    assert exact_amount_fraction(left) == exact_amount_fraction(right) == Fraction(101, 10)
    assert left.lexical == "10.10"
    assert right.lexical == "10.1"


def test_named_missing_sheet_and_selected_non_transaction_sheet() -> None:
    rows = _row(1, _inline("A1", "기관"))
    result, evidence = _map({"자산": rows})
    missing = map_exact_transactions(evidence, sheet_name="없는시트")
    selected = map_exact_transactions(evidence, sheet_name="자산")
    assert missing.status == "sheet_not_found"
    assert selected.status == "not_transaction_sheet"
    assert result.status == "no_transaction_sheet"


def _kr_mapped(*rows: str):
    result, evidence = _map({"내역": _kr_header() + "".join(rows)}, shared=KR)
    assert evidence.sheets
    return result


def _simple_tx(number: int, date_text: str, time_text: str, amount: str = "1") -> str:
    date_cell = _inline(f"A{number}", date_text)
    time_cell = _inline(f"B{number}", time_text)
    return _tx(number, _Tx(date_cell, _n(f"E{number}", amount), time_cell))


def test_invalid_timezone_offsets_keep_rows_without_normalization() -> None:
    result = _kr_mapped(
        _simple_tx(2, "2026-09-01", "12:34:56Z"),
        _simple_tx(3, "2026-09-01", "12:34:56+09:00"),
        _simple_tx(4, "2026-09-01", "12:34:56+00:99"),
        _simple_tx(5, "2026-09-01", "12:34:56+99:00"),
        _simple_tx(6, "2026-09-01T12:34:56+00:99", "10:00:00"),
        _simple_tx(7, "2026-09-01", "12:34:56"),
    )
    zulu, offset, minute99, hour99, embedded, sibling = result.rows
    assert result.status == "mapped"
    assert zulu.supported is True
    assert zulu.temporal.parsed_datetime is not None
    assert zulu.temporal.parsed_datetime.tzinfo == timezone.utc
    assert offset.temporal.timezone_offset == "+09:00"
    assert offset.temporal.parsed_time == time(12, 34, 56)
    assert minute99.time_raw == "12:34:56+00:99"
    assert "INVALID_TIME" in _codes(minute99)
    assert minute99.temporal.parsed_time is None
    assert minute99.temporal.parsed_datetime is None
    assert minute99.temporal.timezone_offset is None
    assert minute99.cells
    assert "INVALID_TIME" in _codes(hour99)
    assert hour99.temporal.parsed_datetime is None
    assert "INVALID_DATE" in _codes(embedded)
    assert embedded.date_raw == "2026-09-01T12:34:56+00:99"
    assert embedded.temporal.parsed_date is None
    assert sibling.supported is True
    assert sibling.temporal.parsed_time == time(12, 34, 56)


def test_submicrosecond_text_is_unsupported_without_truncation() -> None:
    result = _kr_mapped(
        _simple_tx(2, "2026-09-01", "12:34:56.123456789"),
        _simple_tx(3, "2026-09-01", "12:34:56.123456"),
        _simple_tx(4, "2026-09-01", "12:34:56.123"),
        _simple_tx(5, "2026-09-01", "12:34:56"),
        _simple_tx(6, "2026-09-01", "12:34"),
        _simple_tx(7, "2026-09-01", "12:34:56.123456789+09:00"),
    )
    nano, micro, milli, second, minute, nano_offset = result.rows
    assert nano.supported is False
    assert "UNSUPPORTED_TIME_PRECISION" in _codes(nano)
    assert nano.time_raw == "12:34:56.123456789"
    assert nano.temporal.precision == "submicrosecond"
    assert nano.temporal.time_fraction_digits == "123456789"
    assert nano.temporal.parsed_time is None
    assert nano.temporal.parsed_datetime is None
    assert nano.datetime_raw is None
    assert "unsupported_time_precision" in nano.temporal.uncertainty
    assert nano.cells
    assert micro.supported is True
    assert micro.temporal.precision == "microsecond"
    assert micro.temporal.parsed_time == time(12, 34, 56, 123456)
    assert micro.temporal.time_fraction_digits == "123456"
    assert milli.temporal.precision == "millisecond"
    assert milli.temporal.parsed_time == time(12, 34, 56, 123000)
    assert second.temporal.precision == "second"
    assert minute.temporal.precision == "minute"
    assert nano_offset.supported is False
    assert nano_offset.temporal.parsed_time is None
    assert nano_offset.temporal.time_fraction_digits == "123456789"


def test_submicrosecond_conflict_does_not_collapse_distinct_fraction_digits() -> None:
    result = _kr_mapped(
        _tx(
            2,
            _Tx(
                _inline("A2", "2026-09-01T12:34:56.123456001"),
                _n("E2", "1"),
                _inline("B2", "12:34:56.123456002"),
            ),
        ),
        _tx(
            3,
            _Tx(
                _inline("A3", "2026-09-01T12:34:56.123456789"),
                _n("E3", "1"),
                _inline("B3", "12:34:56.123456789"),
            ),
        ),
    )
    distinct, same = result.rows
    assert "CONFLICTING_DATE_TIME" in _codes(distinct)
    assert "UNSUPPORTED_TIME_PRECISION" in _codes(distinct)
    assert distinct.temporal.parsed_time is None
    assert distinct.temporal.parsed_datetime is None
    assert distinct.supported is False
    assert distinct.date_raw == "2026-09-01T12:34:56.123456001"
    assert distinct.time_raw == "12:34:56.123456002"
    assert "CONFLICTING_DATE_TIME" not in _codes(same)
    assert "UNSUPPORTED_TIME_PRECISION" in _codes(same)
    assert same.temporal.parsed_time is None
    assert same.temporal.time_fraction_digits == "123456789"


def test_serial_bounds_reject_oversize_tokens_per_row() -> None:
    assert SERIAL_MAX_DIGITS == 512
    assert SERIAL_MAX_ABS_EXPONENT == 512
    assert SERIAL_MAX_LEXEME_LENGTH == 1024
    result = _kr_mapped(
        _tx(2, _Tx(_n("A2", "1e0"), _n("E2", "1"), _inline("B2", "00:00:00"), merchant="zero-exp")),
        _tx(3, _Tx(_n("A3", "1E+0"), _n("E3", "1"), _inline("B3", "00:00:00"))),
        _tx(4, _Tx(_n("A4", "1e-0"), _n("E4", "1"), _inline("B4", "00:00:00"))),
        _tx(5, _Tx(_n("A5", "1e513"), _n("E5", "1"), _inline("B5", "00:00:00"))),
        _tx(6, _Tx(_n("A6", "1e-513"), _n("E6", "1"), _inline("B6", "00:00:00"))),
        _tx(
            7,
            _Tx(
                _n("A7", "1" + "0" * SERIAL_MAX_DIGITS),
                _n("E7", "1"),
                _inline("B7", "00:00:00"),
            ),
        ),
        _tx(8, _Tx(_n("A8", "1"), _n("E8", "1"), _n("B8", "1e513"))),
        _simple_tx(9, "2026-09-01", "12:34:56"),
    )
    zero, plus_zero, minus_zero, pos, neg, digits, time_over, sibling = result.rows
    assert zero.temporal.parsed_date == date(1900, 1, 1)
    assert plus_zero.temporal.parsed_date == date(1900, 1, 1)
    assert minus_zero.temporal.parsed_date == date(1900, 1, 1)
    assert "UNSUPPORTED_SERIAL" in _codes(pos)
    assert pos.temporal.date_serial_lexical == "1e513"
    assert pos.temporal.parsed_date is None
    assert pos.supported is False
    assert "UNSUPPORTED_SERIAL" in _codes(neg)
    assert neg.temporal.date_serial_lexical == "1e-513"
    assert "UNSUPPORTED_SERIAL" in _codes(digits)
    assert digits.temporal.date_serial_lexical == "1" + "0" * SERIAL_MAX_DIGITS
    assert "UNSUPPORTED_SERIAL" in _codes(time_over)
    assert time_over.temporal.time_serial_lexical == "1e513"
    assert time_over.temporal.parsed_time is None
    assert sibling.supported is True
    assert sibling.temporal.parsed_date == date(2026, 9, 1)


_SUBPROCESS_MAPPER = """
import json
import sys
from finjuice.pipeline.ingest.exact_transactions import map_exact_transactions
from finjuice.pipeline.ingest.xlsx_evidence import read_workbook_evidence
result = map_exact_transactions(read_workbook_evidence(sys.stdin.buffer.read()))
print(json.dumps({
    "status": result.status,
    "supported": [row.supported for row in result.rows],
    "codes": [[issue.code for issue in row.issues] for row in result.rows],
    "serials": [row.temporal.date_serial_lexical for row in result.rows],
    "dates": [
        None if row.temporal.parsed_date is None else row.temporal.parsed_date.isoformat()
        for row in result.rows
    ],
}))
"""


def _map_in_subprocess(data: bytes, timeout: float = 1.0) -> dict:
    completed = subprocess.run(
        [sys.executable, "-c", _SUBPROCESS_MAPPER],
        input=data,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode()
    return json.loads(completed.stdout.decode())


def test_extreme_compact_serial_exponents_terminate_promptly() -> None:
    data = _package(
        {
            "내역": _kr_header()
            + _tx(2, _Tx(_n("A2", "1e10000000"), _n("E2", "1"), _inline("B2", "00:00:00")))
            + _tx(3, _Tx(_n("A3", "1e-10000000"), _n("E3", "1"), _inline("B3", "00:00:00")))
            + _tx(4, _Tx(_n("A4", "-1e10000000"), _n("E4", "1"), _inline("B4", "00:00:00")))
            + _simple_tx(5, "2026-09-01", "12:34:56")
        },
        shared=KR,
    )
    payload = _map_in_subprocess(data, timeout=1.0)
    assert payload["status"] == "mapped"
    assert payload["supported"] == [False, False, False, True]
    assert payload["codes"][0] == ["UNSUPPORTED_SERIAL"]
    assert payload["codes"][1] == ["UNSUPPORTED_SERIAL"]
    assert payload["codes"][2] == ["UNSUPPORTED_SERIAL"]
    assert payload["serials"][0] == "1e10000000"
    assert payload["serials"][1] == "1e-10000000"
    assert payload["serials"][2] == "-1e10000000"
    assert payload["dates"][0] is None
    assert payload["dates"][3] == "2026-09-01"
