"""Synthetic WorkbookEvidence tests for the pure exact asset-snapshot mapper."""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from datetime import date
from decimal import localcontext

import pytest

from finjuice.pipeline.ingest.exact_assets import (
    PARSER_VERSION,
    QUANTITY_UNIT,
    map_exact_assets,
)
from finjuice.pipeline.ingest.exact_transactions import TEMPORAL_POLICY
from finjuice.pipeline.ingest.xlsx_evidence import read_workbook_evidence

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

KR = [
    "기준일",
    "계좌ID",
    "계좌명",
    "종목ID",
    "종목명",
    "수량",
    "평가금액",
    "화폐",
    "비고",
    "extra-note",
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


def _formula(
    ref: str, text: str, cached: str | None = None, *, cell_type: str | None = None
) -> str:
    typed = "" if cell_type is None else f' t="{cell_type}"'
    if cached is None:
        return f'<c r="{ref}"{typed}><f>{text}</f></c>'
    return f'<c r="{ref}"{typed}><f>{text}</f><v>{cached}</v></c>'


def _d(ref: str, value: str) -> str:
    return f'<c r="{ref}" t="d"><v>{value}</v></c>'


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


@dataclass(frozen=True)
class _Opts:
    shared: list[str] | None = None
    date1904: bool = False
    sheet_name: str | None = None
    snapshot_date: str | None = None
    collected_at: str | None = None


def _map(sheets: dict[str, str], opts: _Opts | None = None):
    cfg = opts or _Opts()
    data = _package(sheets, shared=cfg.shared, date1904=cfg.date1904)
    evidence = read_workbook_evidence(data)
    before = evidence
    result = map_exact_assets(
        evidence,
        sheet_name=cfg.sheet_name,
        snapshot_date=cfg.snapshot_date,
        collected_at=cfg.collected_at,
    )
    assert evidence == before
    assert (
        map_exact_assets(
            evidence,
            sheet_name=cfg.sheet_name,
            snapshot_date=cfg.snapshot_date,
            collected_at=cfg.collected_at,
        )
        == result
    )
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
        _s(f"I{row}", 8),
    )


@dataclass(frozen=True)
class _Hold:
    date_cell: str | None
    quantity: str
    market_value: str
    account_id: str | None = None
    account_name: str = "계좌A"
    instrument_id: str | None = None
    instrument_name: str = "종목A"
    currency: str | None = "USD"
    currency_cell: str | None = None
    extra: str | None = None


def _hold(number: int, spec: _Hold) -> str:
    cells: list[str] = []
    if spec.date_cell is not None:
        cells.append(spec.date_cell)
    if spec.account_id is not None:
        cells.append(spec.account_id)
    else:
        cells.append(_inline(f"B{number}", "acct-1"))
    cells.append(_inline(f"C{number}", spec.account_name))
    if spec.instrument_id is not None:
        cells.append(spec.instrument_id)
    else:
        cells.append(_inline(f"D{number}", "inst-1"))
    cells.append(_inline(f"E{number}", spec.instrument_name))
    cells.append(spec.quantity)
    cells.append(spec.market_value)
    if spec.currency_cell is not None:
        cells.append(spec.currency_cell)
    elif spec.currency is not None:
        cells.append(_inline(f"H{number}", spec.currency))
    if spec.extra is not None:
        cells.append(spec.extra)
    return _row(number, *cells)


def _codes(row) -> list[str]:
    return [issue.code for issue in row.issues]


def _field_codes(row, field_name: str) -> list[str]:
    return [issue.code for issue in row.issues if issue.field_name == field_name]


def _iso(number: int, value: str) -> str:
    return _inline(f"A{number}", value)


def test_korean_headers_map_required_fields_and_keep_unknown_columns() -> None:
    rows = _kr_header() + _hold(
        2,
        _Hold(
            date_cell=_iso(2, "2024-03-15"),
            quantity=_n("F2", "1.250"),
            market_value=_n("G2", "1000.00"),
            extra=_s("I2", 9),
        ),
    )
    result, _evidence = _map({"자산": rows}, _Opts(shared=KR))

    assert result.status == "mapped"
    assert result.parser_version == PARSER_VERSION
    assert result.temporal_policy == TEMPORAL_POLICY
    assert result.schema_version == "snapshot_v0"
    assert result.header_row == 1
    assert result.unknown_headers[0].header_text == "비고"
    row = result.rows[0]
    assert row.supported is True
    assert row.source_account_id == "acct-1"
    assert row.source_account_name == "계좌A"
    assert row.source_instrument_id == "inst-1"
    assert row.source_instrument_name == "종목A"
    assert row.quantity is not None
    assert row.quantity.lexical == "1.250"
    assert row.quantity.value_kind == "quantity"
    assert row.quantity.unit == QUANTITY_UNIT
    assert row.market_value is not None
    assert row.market_value.lexical == "1000.00"
    assert row.market_value.currency == "USD"
    assert row.snapshot.parsed_date == date(2024, 3, 15)
    assert row.snapshot.source == "row"
    assert row.snapshot.kind == "iso_text"
    assert row.unknown_cells[0].cell.shared_text is not None
    assert not hasattr(row, "account_id")


def test_english_headers_match_catalog_without_recognized_sheet_name() -> None:
    header = _row(
        1,
        _inline("A1", "snapshot_date"),
        _inline("B1", "account_id"),
        _inline("C1", "instrument_name"),
        _inline("D1", "quantity"),
        _inline("E1", "market_value"),
        _inline("F1", "currency"),
        _inline("G1", "note"),
    )
    data = _row(
        2,
        _inline("A2", "2024-01-02"),
        _inline("B2", "001234"),
        _inline("C2", "Fund"),
        _n("D2", "10.10"),
        _n("E2", "20.20"),
        _inline("F2", "USD"),
        _inline("G2", "kept"),
    )
    result, _evidence = _map({"Ledger": header + data})
    row = result.rows[0]
    assert result.status == "mapped"
    assert result.sheet_name == "Ledger"
    assert row.source_account_id == "001234"
    assert row.source_account_name is None
    assert row.source_instrument_name == "Fund"
    assert row.quantity is not None
    assert row.quantity.unit == QUANTITY_UNIT
    assert row.unknown_cells[0].header_text == "note"


def test_large_tiny_signed_zero_and_low_decimal_precision() -> None:
    rows = _kr_header() + "".join(
        [
            _hold(
                2,
                _Hold(
                    _iso(2, "2024-01-01"),
                    _n("F2", "9007199254740993"),
                    _n("G2", "9007199254740993"),
                ),
            ),
            _hold(3, _Hold(_iso(3, "2024-01-01"), _n("F3", "1e-255"), _n("G3", "1e-255"))),
            _hold(4, _Hold(_iso(4, "2024-01-01"), _n("F4", "1e-256"), _n("G4", "1e-256"))),
            _hold(5, _Hold(_iso(5, "2024-01-01"), _n("F5", "-0.00"), _n("G5", "-0.00"))),
        ]
    )
    with localcontext() as context:
        context.prec = 2
        result, _evidence = _map({"보유종목": rows}, _Opts(shared=KR))
    huge, tiny, overflow, zero = result.rows
    assert huge.quantity is not None
    assert huge.quantity.coefficient == "9007199254740993"
    assert huge.market_value is not None
    assert huge.market_value.coefficient == "9007199254740993"
    assert tiny.quantity is not None
    assert tiny.quantity.scale == 255
    assert tiny.market_value is not None
    assert tiny.market_value.scale == 255
    assert overflow.quantity is None
    assert overflow.market_value is None
    assert "QUANTITY_SCALE_OUT_OF_RANGE" in _codes(overflow)
    assert "MARKET_VALUE_SCALE_OUT_OF_RANGE" in _codes(overflow)
    assert zero.quantity is not None
    assert zero.quantity.coefficient == "0"
    assert zero.quantity.lexical == "-0.00"
    assert zero.market_value is not None
    assert zero.market_value.lexical == "-0.00"


def test_known_and_unknown_currency_never_default_to_krw() -> None:
    rows = _kr_header() + "".join(
        [
            _hold(2, _Hold(_iso(2, "2024-01-01"), _n("F2", "1"), _n("G2", "1"), currency="USD")),
            _hold(3, _Hold(_iso(3, "2024-01-01"), _n("F3", "1"), _n("G3", "1"), currency=None)),
            _hold(4, _Hold(_iso(4, "2024-01-01"), _n("F4", "1"), _n("G4", "1"), currency="krw")),
        ]
    )
    result, _evidence = _map({"assets": rows}, _Opts(shared=KR))
    known, missing, lower = result.rows
    assert known.currency_code == "USD"
    assert known.currency_unknown is False
    assert known.market_value is not None
    assert known.market_value.currency == "USD"
    for row in (missing, lower):
        assert row.currency_unknown is True
        assert row.currency_code is None
        assert row.market_value is not None
        assert row.market_value.currency is None
        assert row.market_value.currency_unknown is True
        assert "UNKNOWN_CURRENCY" in _codes(row)


def test_numeric_account_ids_stay_exact_text_and_are_not_merged() -> None:
    rows = _kr_header() + _hold(
        2,
        _Hold(
            _iso(2, "2024-01-01"),
            _n("F2", "1"),
            _n("G2", "1"),
            account_id=_n("B2", "9007199254740993"),
            account_name="표시명",
            instrument_id=_inline("D2", "00123"),
        ),
    )
    result, _evidence = _map({"자산": rows}, _Opts(shared=KR))
    row = result.rows[0]
    assert row.source_account_id == "9007199254740993"
    assert row.source_account_name == "표시명"
    assert row.source_instrument_id == "00123"
    assert row.source_account_id != row.source_account_name


def test_formula_cached_unverified_missing_boolean_error_and_decorated() -> None:
    rows = _kr_header() + "".join(
        [
            _hold(
                2,
                _Hold(
                    _iso(2, "2024-01-01"), _formula("F2", "A2", "3.5"), _formula("G2", "B2", "9.25")
                ),
            ),
            _hold(3, _Hold(_iso(3, "2024-01-01"), _formula("F3", "A3"), _formula("G3", "B3"))),
            _hold(4, _Hold(_iso(4, "2024-01-01"), _bool("F4", "1"), _err("G4", "#VALUE!"))),
            _hold(
                5, _Hold(_iso(5, "2024-01-01"), _inline("F5", "1,000"), _inline("G5", "1,000원"))
            ),
            _hold(6, _Hold(_iso(6, "2024-01-01"), _n("F6", "NaN"), _n("G6", "Infinity"))),
        ]
    )
    result, _evidence = _map({"자산": rows}, _Opts(shared=KR))
    cached, missing, typed, decorated, nonfinite = result.rows
    assert cached.quantity is not None
    assert cached.quantity.lexical == "3.5"
    assert cached.quantity_unverified is True
    assert cached.market_value_unverified is True
    assert "FORMULA_CACHED_UNVERIFIED" in _codes(cached)
    assert cached.supported is True
    assert missing.quantity is None
    assert missing.market_value is None
    assert "FORMULA_CACHE_MISSING" in _codes(missing)
    assert missing.supported is False
    assert "QUANTITY_BOOLEAN" in _codes(typed)
    assert "MARKET_VALUE_ERROR_CELL" in _codes(typed)
    assert "QUANTITY_FORMATTED" in _codes(decorated)
    assert "MARKET_VALUE_FORMATTED" in _codes(decorated)
    assert decorated.quantity is None
    assert "QUANTITY_NONFINITE" in _codes(nonfinite)
    assert "MARKET_VALUE_NONFINITE" in _codes(nonfinite)


def test_ambiguous_headers_duplicate_mixed_variants_and_blank_rows() -> None:
    duplicate = _row(
        1,
        _inline("A1", "계좌명"),
        _inline("B1", "종목명"),
        _inline("C1", "수량"),
        _inline("D1", "qty"),
        _inline("E1", "평가금액"),
    )
    mixed, _evidence = _map({"자산": duplicate})
    assert mixed.status == "duplicate_field_mapping"
    assert mixed.rows == ()
    assert mixed.issues[0].code == "DUPLICATE_FIELD_MAPPING"

    two_headers = _kr_header(1) + _kr_header(4)
    ambiguous, _evidence = _map({"자산": two_headers}, _Opts(shared=KR))
    assert ambiguous.status == "ambiguous_headers"
    assert ambiguous.rows == ()

    rows = (
        _kr_header()
        + _row(2, _n("A2", ""), _n("B2", ""))
        + _hold(3, _Hold(_iso(3, "not-a-date"), _n("F3", "1"), _n("G3", "1")))
    )
    result, _evidence = _map({"자산": rows}, _Opts(shared=KR))
    assert result.skipped_blank_rows == 1
    assert len(result.rows) == 1
    assert "INVALID_DATE" in _codes(result.rows[0])
    assert result.rows[0].snapshot.parsed_date is None
    assert result.rows[0].snapshot.source == "missing"


def test_missing_ambiguous_and_named_sheets() -> None:
    empty = _row(1, _inline("A1", "기관"), _inline("B1", "상품명"))
    none, evidence = _map({"내역": empty})
    assert none.status == "no_asset_sheet"
    assert none.rows == ()
    missing = map_exact_assets(evidence, sheet_name="없는시트")
    assert missing.status == "sheet_not_found"
    selected = map_exact_assets(evidence, sheet_name="내역")
    assert selected.status == "not_asset_sheet"

    sheet = _kr_header() + _hold(2, _Hold(_iso(2, "2024-01-01"), _n("F2", "1"), _n("G2", "1")))
    both, both_evidence = _map({"자산": sheet, "holdings": sheet}, _Opts(shared=KR))
    assert both.status == "ambiguous_sheets"
    assert both.candidate_sheet_names == ("자산", "holdings")
    named = map_exact_assets(both_evidence, sheet_name="holdings")
    assert named.status == "mapped"
    assert named.sheet_name == "holdings"


def test_recognized_name_is_preferred_over_another_complete_catalog_sheet() -> None:
    asset = _kr_header() + _hold(2, _Hold(_iso(2, "2024-01-01"), _n("F2", "1"), _n("G2", "1")))
    other = _row(
        1,
        _inline("A1", "account_name"),
        _inline("B1", "instrument_name"),
        _inline("C1", "quantity"),
        _inline("D1", "market_value"),
    ) + _row(2, _inline("A2", "X"), _inline("B2", "Y"), _n("C2", "1"), _n("D2", "1"))
    result, _evidence = _map(
        {"자산": asset, "Ledger": other},
        _Opts(shared=KR, snapshot_date="2024-01-01"),
    )
    assert result.status == "mapped"
    assert result.sheet_name == "자산"


def test_iso_date1904_and_fallback_provenance() -> None:
    rows_1900 = _kr_header() + "".join(
        [
            _hold(2, _Hold(_n("A2", "61", style="4"), _n("F2", "1"), _n("G2", "1"))),
            _hold(3, _Hold(_n("A3", "60"), _n("F3", "1"), _n("G3", "1"))),
            _hold(4, _Hold(_n("A4", "1.999999995"), _n("F4", "1"), _n("G4", "1"))),
        ]
    )
    mapped_1900, _evidence = _map({"자산": rows_1900}, _Opts(shared=KR))
    day61, day60, fraction = mapped_1900.rows
    assert day61.snapshot.parsed_date == date(1900, 3, 1)
    assert day61.snapshot.kind == "excel_serial"
    assert "EXCEL_FICTITIOUS_DAY_60" in _codes(day60)
    assert day60.snapshot.parsed_date is None
    assert fraction.snapshot.parsed_date == date(1900, 1, 1)
    assert "serial_fraction_ignored" in fraction.snapshot.uncertainty
    assert not hasattr(fraction.snapshot, "parsed_time")

    rows_1904 = _kr_header() + _hold(2, _Hold(_n("A2", "0"), _n("F2", "1"), _n("G2", "1")))
    mapped_1904, _evidence = _map({"자산": rows_1904}, _Opts(shared=KR, date1904=True))
    assert mapped_1904.date1904 is True
    assert mapped_1904.rows[0].snapshot.parsed_date == date(1904, 1, 1)
    assert mapped_1904.rows[0].snapshot.date1904 is True


def test_explicit_and_collection_fallbacks_never_claim_source_or_today() -> None:
    rows = _kr_header() + "".join(
        [
            _hold(2, _Hold(_iso(2, "2024-03-15"), _n("F2", "1"), _n("G2", "1"))),
            _hold(3, _Hold(None, _n("F3", "1"), _n("G3", "1"))),
            _hold(4, _Hold(_iso(4, "not-iso"), _n("F4", "1"), _n("G4", "1"))),
        ]
    )
    preferred, _evidence = _map(
        {"자산": rows},
        _Opts(
            shared=KR,
            snapshot_date="2024-02-01",
            collected_at="2024-01-01T23:59:59+09:00",
        ),
    )
    source, explicit, invalid = preferred.rows
    assert source.snapshot.source == "row"
    assert source.snapshot.parsed_date == date(2024, 3, 15)
    assert explicit.snapshot.source == "explicit"
    assert explicit.snapshot.parsed_date == date(2024, 2, 1)
    assert "explicit_fallback" in explicit.snapshot.uncertainty
    assert "row_date_absent" in explicit.snapshot.uncertainty
    assert invalid.snapshot.source == "explicit"
    assert invalid.snapshot.parsed_date == date(2024, 2, 1)
    assert "source_date_invalid" in invalid.snapshot.uncertainty
    assert invalid.snapshot.raw == "not-iso"

    collected, _evidence = _map(
        {"자산": _kr_header() + _hold(2, _Hold(None, _n("F2", "1"), _n("G2", "1")))},
        _Opts(shared=KR, collected_at="2024-05-06T12:00:00+09:00"),
    )
    row = collected.rows[0]
    assert row.snapshot.source == "collected_at"
    assert row.snapshot.parsed_date == date(2024, 5, 6)
    assert "collection_fallback" in row.snapshot.uncertainty
    assert row.snapshot.kind == "collected_at"

    missing, _evidence = _map(
        {"자산": _kr_header() + _hold(2, _Hold(None, _n("F2", "1"), _n("G2", "1")))},
        _Opts(shared=KR),
    )
    assert missing.rows[0].snapshot.parsed_date is None
    assert missing.rows[0].snapshot.source == "missing"
    assert "MISSING_SNAPSHOT_DATE" in _codes(missing.rows[0])
    assert missing.rows[0].snapshot.parsed_date != date.today()


def test_invalid_caller_dates_are_issues_and_do_not_crash() -> None:
    rows = _kr_header() + _hold(2, _Hold(None, _n("F2", "1"), _n("G2", "1")))
    result, _evidence = _map(
        {"자산": rows},
        _Opts(shared=KR, snapshot_date="yesterday", collected_at="also-bad"),
    )
    assert result.status == "mapped"
    assert {issue.code for issue in result.issues} == {
        "INVALID_EXPLICIT_SNAPSHOT_DATE",
        "INVALID_COLLECTED_AT",
    }
    assert result.rows[0].snapshot.parsed_date is None
    assert "MISSING_SNAPSHOT_DATE" in _codes(result.rows[0])


def test_rejects_non_workbook_evidence() -> None:
    with pytest.raises(TypeError, match="WorkbookEvidence"):
        map_exact_assets(object())  # type: ignore[arg-type]


def test_ooxml_iso_date_type_cells() -> None:
    rows = _kr_header() + "".join(
        [
            _hold(2, _Hold(_d("A2", "2026-09-10"), _n("F2", "1"), _n("G2", "1"))),
            _hold(
                3,
                _Hold(_d("A3", "2026-09-10T12:34:56+09:00"), _n("F3", "1"), _n("G3", "1")),
            ),
            _hold(4, _Hold(_d("A4", "not-an-iso-date"), _n("F4", "1"), _n("G4", "1"))),
            _hold(
                5,
                _Hold(
                    _formula("A5", "TODAY()", "2026-09-10", cell_type="d"),
                    _n("F5", "1"),
                    _n("G5", "1"),
                ),
            ),
        ]
    )
    result, _evidence = _map({"자산": rows}, _Opts(shared=KR))
    valid, offset, invalid, cached = result.rows
    assert valid.snapshot.parsed_date == date(2026, 9, 10)
    assert valid.snapshot.kind == "iso_date"
    assert valid.snapshot.raw == "2026-09-10"
    assert valid.snapshot.source == "row"
    assert "INVALID_DATE" not in _codes(valid)
    assert offset.snapshot.parsed_date == date(2026, 9, 10)
    assert offset.snapshot.kind == "iso_datetime"
    assert offset.snapshot.raw == "2026-09-10T12:34:56+09:00"
    assert "iso_datetime" in offset.snapshot.uncertainty
    assert not hasattr(offset.snapshot, "parsed_time")
    assert invalid.snapshot.parsed_date is None
    assert invalid.snapshot.kind == "iso_date"
    assert invalid.snapshot.raw == "not-an-iso-date"
    assert "INVALID_DATE" in _codes(invalid)
    assert cached.snapshot.parsed_date == date(2026, 9, 10)
    assert cached.snapshot.kind == "iso_date"
    assert cached.snapshot.raw == "2026-09-10"
    assert "FORMULA_CACHED_UNVERIFIED" in _field_codes(cached, "snapshot_date")


def test_formula_currency_and_identity_uncertainty() -> None:
    rows = _kr_header() + "".join(
        [
            _hold(
                2,
                _Hold(
                    _iso(2, "2024-01-01"),
                    _n("F2", "1"),
                    _n("G2", "10.00"),
                    currency_cell=_formula("H2", "H1", "USD", cell_type="str"),
                ),
            ),
            _hold(
                3,
                _Hold(
                    _iso(3, "2024-01-01"),
                    _n("F3", "1"),
                    _n("G3", "10.00"),
                    currency_cell=_formula("H3", "H1"),
                ),
            ),
            _hold(
                4,
                _Hold(
                    _iso(4, "2024-01-01"),
                    _n("F4", "1"),
                    _n("G4", "10.00"),
                    currency_cell=_bool("H4", "1"),
                ),
            ),
            _hold(
                5,
                _Hold(
                    _iso(5, "2024-01-01"),
                    _n("F5", "1"),
                    _n("G5", "10.00"),
                    currency_cell=_err("H5", "#VALUE!"),
                ),
            ),
            _hold(
                6,
                _Hold(
                    _iso(6, "2024-01-01"),
                    _n("F6", "1"),
                    _n("G6", "10.00"),
                    account_id=_formula("B6", "B1", "acct-1", cell_type="str"),
                    instrument_id=_formula("D6", "D1"),
                ),
            ),
        ]
    )
    result, _evidence = _map({"자산": rows}, _Opts(shared=KR))
    cached, missing, boolean, error, identity = result.rows
    assert cached.currency_code == "USD"
    assert cached.currency_unknown is False
    assert "FORMULA_CACHED_UNVERIFIED" in _field_codes(cached, "currency")
    assert "UNKNOWN_CURRENCY" not in _field_codes(cached, "currency")
    assert cached.market_value is not None
    assert cached.market_value.lexical == "10.00"
    assert cached.market_value.currency == "USD"
    assert cached.market_value_unverified is True
    assert cached.quantity_unverified is False
    currency_cell = next(cell for cell in cached.cells if cell.column == "H")
    assert currency_cell.formula is not None
    assert currency_cell.formula.text == "H1"
    assert currency_cell.raw_value == "USD"
    assert missing.currency_code is None
    assert missing.currency_unknown is True
    assert "UNKNOWN_CURRENCY" in _field_codes(missing, "currency")
    assert "FORMULA_CACHE_MISSING" in _field_codes(missing, "currency")
    assert missing.market_value is not None
    assert missing.market_value.currency_unknown is True
    assert missing.market_value_unverified is False
    assert boolean.currency_code is None
    assert boolean.currency_unknown is True
    assert "UNKNOWN_CURRENCY" in _field_codes(boolean, "currency")
    assert "FORMULA_CACHED_UNVERIFIED" not in _field_codes(boolean, "currency")
    assert error.currency_code is None
    assert error.currency_unknown is True
    assert "UNKNOWN_CURRENCY" in _field_codes(error, "currency")
    assert identity.source_account_id == "acct-1"
    assert "FORMULA_CACHED_UNVERIFIED" in _field_codes(identity, "account_id")
    assert identity.source_instrument_id is None
    assert "FORMULA_CACHE_MISSING" in _field_codes(identity, "instrument_id")
    assert identity.source_instrument_name == "종목A"
    assert not hasattr(identity, "account_id")


@pytest.mark.parametrize("kind,raw", [("e", "#VALUE!"), ("b", "1")])
@pytest.mark.parametrize(
    "field,column,partner",
    [
        ("account_id", "B", "C"),
        ("account_name", "C", "B"),
        ("instrument_id", "D", "E"),
        ("instrument_name", "E", "D"),
    ],
)
def test_invalid_identity_cells_remain_raw_without_establishing_identity(
    kind: str, raw: str, field: str, column: str, partner: str
) -> None:
    cells = {
        "A": _iso(2, "2026-09-10"),
        "B": _inline("B2", "account"),
        "C": _inline("C2", "account name"),
        "D": _inline("D2", "instrument"),
        "E": _inline("E2", "instrument name"),
        "F": _n("F2", "1"),
        "G": _n("G2", "10"),
        "H": _inline("H2", "USD"),
    }
    cells[column] = f'<c r="{column}2" t="{kind}"><v>{raw}</v></c>'
    cells.pop(partner)
    result, _ = _map({"자산": _kr_header() + _row(2, *cells.values())}, _Opts(shared=KR))

    mapped = result.rows[0]
    assert getattr(mapped, f"source_{field}") is None
    assert mapped.supported is False
    assert "INVALID_IDENTITY_CELL" in _field_codes(mapped, field)
    evidence = next(cell for cell in mapped.cells if cell.column == column)
    assert evidence.raw_value == raw
    assert evidence.cell_type == kind


@pytest.mark.parametrize("lexical", ["1_000", "１２", " 42 "])
@pytest.mark.parametrize("field,column", [("quantity", "F"), ("market_value", "G")])
def test_non_ascii_or_decorated_decimal_is_not_silently_normalized(
    lexical: str, field: str, column: str
) -> None:
    quantity = _n("F2", lexical if column == "F" else "1")
    market = _n("G2", lexical if column == "G" else "10")
    rows = _kr_header() + _hold(2, _Hold(_iso(2, "2026-09-10"), quantity, market))

    result, _ = _map({"자산": rows}, _Opts(shared=KR))

    mapped = result.rows[0]
    assert getattr(mapped, field) is None
    assert mapped.supported is False
    assert f"UNSUPPORTED_{field.upper()}" in _field_codes(mapped, field)
    assert next(cell for cell in mapped.cells if cell.column == column).raw_value == lexical
