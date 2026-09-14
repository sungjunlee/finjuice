"""Synthetic WorkbookEvidence tests for the pure exact overview mapper."""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from datetime import date
from decimal import localcontext

import pytest

from finjuice.pipeline.ingest.exact_overview import (
    NUMBER_UNIT,
    PARSER_VERSION,
    RATE_UNIT,
    map_exact_overview,
)
from finjuice.pipeline.ingest.exact_transactions import TEMPORAL_POLICY
from finjuice.pipeline.ingest.xlsx_evidence import read_workbook_evidence

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


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


def _n(ref: str, lexical: str) -> str:
    return f'<c r="{ref}"><v>{lexical}</v></c>'


def _inline(ref: str, text: str) -> str:
    return f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>'


def _td(ref: str, value: str) -> str:
    return f'<c r="{ref}" t="d"><v>{value}</v></c>'


def _formula(ref: str, text: str, cached: str | None = None, cell_type: str | None = None) -> str:
    typed = "" if cell_type is None else f' t="{cell_type}"'
    if cached is None:
        return f'<c r="{ref}"{typed}><f>{text}</f></c>'
    return f'<c r="{ref}"{typed}><f>{text}</f><v>{cached}</v></c>'


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
    source_filename: str | None = None
    collected_at: str | None = None


def _map(sheets: dict[str, str], opts: _Opts | None = None):
    cfg = opts or _Opts()
    data = _package(sheets, shared=cfg.shared, date1904=cfg.date1904)
    evidence = read_workbook_evidence(data)
    before = evidence
    result = map_exact_overview(
        evidence,
        sheet_name=cfg.sheet_name,
        snapshot_date=cfg.snapshot_date,
        source_filename=cfg.source_filename,
        collected_at=cfg.collected_at,
    )
    assert evidence == before
    again = map_exact_overview(
        evidence,
        sheet_name=cfg.sheet_name,
        snapshot_date=cfg.snapshot_date,
        source_filename=cfg.source_filename,
        collected_at=cfg.collected_at,
    )
    assert again == result
    return result, evidence


def _codes(issues) -> list[str]:
    return [item.code for item in issues]


def _full_overview(*, extra: dict[int, tuple[str, ...]] | None = None) -> str:
    extra = extra or {}
    return "".join(
        [
            _row(
                1,
                _inline("A1", "기준일"),
                _inline("B1", "2026-06-15"),
                _inline("Z1", "unknown-note"),
                *extra.get(1, ()),
            ),
            _row(3, _inline("A3", "1.고객정보")),
            _row(4, _inline("A4", "이름"), _inline("B4", "Synthetic User")),
            _row(7, _inline("A7", "2.현금흐름현황")),
            _row(
                8,
                _inline("A8", "분류"),
                _inline("B8", "2026년 5월"),
                _inline("C8", "2026-06"),
                *extra.get(8, ()),
            ),
            _row(9, _inline("A9", "수입"), _n("B9", "2000000"), _n("C9", "2100000")),
            _row(10, _inline("A10", "지출"), _n("B10", "-1400000"), _n("C10", "-1500000")),
            _row(13, _inline("A13", "3.재무현황")),
            _row(14, _inline("B14", "자산"), _inline("E14", "부채")),
            _row(
                15,
                _inline("B15", "분류"),
                _inline("C15", "항목"),
                _inline("D15", "금액"),
                _inline("E15", "분류"),
                _inline("F15", "항목"),
                _inline("G15", "금액"),
                *extra.get(15, ()),
            ),
            _row(
                16,
                _inline("B16", "예금"),
                _inline("C16", "Synthetic Deposit"),
                _n("D16", "1250000"),
                _inline("E16", "대출"),
                _inline("F16", "Synthetic Loan"),
                _n("G16", "300000"),
            ),
            _row(
                17,
                _inline("B17", "투자"),
                _inline("C17", "Synthetic Fund"),
                _n("D17", "450000"),
                _inline("E17", "카드"),
                _inline("F17", "Synthetic Card Due"),
                _n("G17", "50000"),
            ),
            _row(20, _inline("A20", "4.보험현황")),
            _row(
                21,
                _inline("A21", "금융사"),
                _inline("B21", "보험명"),
                _inline("C21", "계약상태"),
                _inline("D21", "총납입금"),
                _inline("E21", "계약일자"),
                _inline("F21", "만기일자"),
                *extra.get(21, ()),
            ),
            _row(
                22,
                _inline("A22", "Synthetic Insurer"),
                _inline("B22", "Synthetic Policy"),
                _inline("C22", "정상"),
                _n("D22", "120000"),
                _inline("E22", "2024-01-02"),
                _inline("F22", "2034-01-02"),
                *extra.get(22, ()),
            ),
            _row(23, _inline("A23", "합계"), _n("D23", "120000")),
            _row(26, _inline("A26", "5.투자현황")),
            _row(
                27,
                _inline("A27", "투자상품종류"),
                _inline("B27", "금융사"),
                _inline("C27", "상품명"),
                _inline("D27", "투자원금"),
                _inline("E27", "평가금액"),
                _inline("F27", "수익률"),
                _inline("G27", "가입일자"),
                _inline("H27", "만기일자"),
                *extra.get(27, ()),
            ),
            _row(
                28,
                _inline("A28", "펀드"),
                _inline("B28", "Synthetic Securities"),
                _inline("C28", "Synthetic Fund A"),
                _n("D28", "1000000"),
                _n("E28", "1050000"),
                _n("F28", "5.0"),
                _inline("G28", "2025-03-01"),
            ),
            _row(31, _inline("A31", "6.대출현황")),
            _row(
                32,
                _inline("A32", "대출종류"),
                _inline("B32", "금융사"),
                _inline("C32", "상품명"),
                _inline("D32", "대출원금"),
                _inline("E32", "대출잔액"),
                _inline("F32", "대출금리"),
                _inline("G32", "대출신규일"),
                _inline("H32", "대출만기일"),
                *extra.get(32, ()),
            ),
            _row(
                33,
                _inline("A33", "신용"),
                _inline("B33", "Synthetic Bank"),
                _inline("C33", "Synthetic Loan A"),
                _n("D33", "3000000"),
                _n("E33", "2500000"),
                _n("F33", "4.5"),
                _inline("G33", "2023-04-01"),
                _inline("H33", "2028-04-01"),
            ),
        ]
    )


def test_full_overview_maps_six_categories_and_preserves_facts() -> None:
    result, evidence = _map({"뱅샐현황": _full_overview()})
    _assert_mapping_meta(result, evidence)
    _assert_section_facts(result)
    _assert_balance_and_cashflow(result)
    _assert_structured_rows(result)


def _assert_mapping_meta(result, evidence) -> None:
    assert result.status == "mapped"
    assert result.parser_version == PARSER_VERSION
    assert result.temporal_policy == TEMPORAL_POLICY
    assert result.source_sha256 == evidence.source_sha256
    assert result.sheet_name == "뱅샐현황"
    assert result.snapshot.parsed_date == date(2026, 6, 15)
    assert result.snapshot.origin == "source_label"
    assert result.snapshot.reliable is True
    assert not hasattr(result, "account_id")


def _assert_section_facts(result) -> None:
    anchors = {fact.text_value for fact in result.facts if fact.fact_kind == "section_label"}
    assert anchors >= {
        "1.고객정보",
        "2.현금흐름현황",
        "3.재무현황",
        "4.보험현황",
        "5.투자현황",
        "6.대출현황",
    }
    unknown = next(fact for fact in result.facts if fact.column == "Z" and fact.source_row == 1)
    assert unknown.text_value == "unknown-note"
    summary = next(fact for fact in result.facts if fact.text_value == "합계")
    assert summary.fact_kind == "summary"
    assert all(row.policy_name.text != "합계" for row in result.insurance)
    number_facts = [fact for fact in result.facts if fact.value_type == "number"]
    assert number_facts
    assert number_facts[0].number_value is not None
    assert number_facts[0].number_value.unit == NUMBER_UNIT


def _assert_balance_and_cashflow(result) -> None:
    assert len(result.balances) == 4
    deposit = next(row for row in result.balances if row.item_name.text == "Synthetic Deposit")
    assert deposit.side == "asset"
    assert deposit.category.text == "예금"
    assert deposit.amount.exact_value is not None
    assert deposit.amount.exact_value.lexical == "1250000"
    assert deposit.amount.exact_value.currency_unknown is True
    assert deposit.source_column == "D"
    assert deposit.supported is True
    assert all(not hasattr(row, "account_id") for row in result.balances)
    assert len(result.cashflows) == 4
    income = next(
        row
        for row in result.cashflows
        if row.category.text == "수입" and row.period_month.text == "2026-05"
    )
    assert income.amount.exact_value is not None
    assert income.amount.exact_value.coefficient == "2000000"


def _assert_structured_rows(result) -> None:
    assert len(result.insurance) == 1
    policy = result.insurance[0]
    assert policy.institution.text == "Synthetic Insurer"
    assert policy.policy_name.text == "Synthetic Policy"
    assert policy.contract_status.text == "정상"
    assert policy.paid_amount.exact_value is not None
    assert policy.contract_date.parsed_date == date(2024, 1, 2)
    assert policy.maturity_date.parsed_date == date(2034, 1, 2)
    fund = result.investments[0]
    assert fund.institution.text == "Synthetic Securities"
    assert fund.product_name.text == "Synthetic Fund A"
    assert fund.product_type.text == "펀드"
    assert fund.principal_amount.exact_value is not None
    assert fund.valuation_amount.exact_value is not None
    assert fund.return_rate.exact_value is not None
    assert fund.return_rate.exact_value.value_kind == "rate"
    assert fund.return_rate.exact_value.unit == RATE_UNIT
    assert "RATE_UNIT_UNCERTAIN" in _codes(fund.return_rate.issues)
    loan = result.loans[0]
    assert loan.institution.text == "Synthetic Bank"
    assert loan.product_name.text == "Synthetic Loan A"
    assert loan.loan_type.text == "신용"
    assert loan.principal_amount.exact_value is not None
    assert loan.balance_amount.exact_value is not None
    assert loan.interest_rate.exact_value is not None
    assert loan.interest_rate.exact_value.unit == RATE_UNIT


def test_fact_coordinates_are_one_to_one_with_source_cells() -> None:
    result, evidence = _map({"뱅샐현황": _full_overview()})
    sheet = evidence.sheets[0]
    keys = {(fact.source_row, fact.column) for fact in result.facts}
    assert keys == {
        (cell.row, cell.column) for cell in sheet.cells if cell.inline_text or cell.raw_value
    }
    assert len(result.facts) == len(keys)
    by_ref = {(fact.source_row, fact.column): fact for fact in result.facts}
    sample = by_ref[(16, "D")]
    assert sample.cell.raw_value == "1250000"
    assert sample.block_id == "balance_status"


def test_duplicate_headers_fail_balance_projection_and_keep_facts() -> None:
    rows = (
        _row(1, _inline("A1", "기준일"), _inline("B1", "2026-06-15"))
        + _row(2, _inline("B2", "자산"), _inline("E2", "부채"))
        + _row(
            3,
            _inline("B3", "분류"),
            _inline("C3", "항목"),
            _inline("D3", "금액"),
            _inline("E3", "금액"),
            _inline("F3", "항목"),
            _inline("G3", "금액"),
        )
    )
    result, _evidence = _map({"뱅샐현황": rows})
    assert result.status == "mapped"
    assert result.facts
    assert result.balances == ()
    assert "DUPLICATE_FIELD_MAPPING" in _codes(result.issues)


def test_ambiguous_sheets_do_not_choose_first() -> None:
    rows = _row(1, _inline("A1", "2.현금흐름현황")) + _row(
        2, _inline("A2", "분류"), _inline("B2", "2026-06")
    )
    result, _evidence = _map({"현황A": rows, "현황B": rows})
    assert result.status == "ambiguous_sheets"
    assert result.facts == ()
    assert result.sheet_name is None
    assert set(result.candidate_sheet_names) == {"현황A", "현황B"}
    assert "AMBIGUOUS_SHEETS" in _codes(result.issues)


def test_explicit_sheet_wins_over_named_overview() -> None:
    named = _row(1, _inline("A1", "기준일"), _inline("B1", "2026-01-01"))
    other = (
        _row(1, _inline("B1", "자산"), _inline("E1", "부채"))
        + _row(
            2,
            _inline("B2", "항목"),
            _inline("C2", "금액"),
            _inline("E2", "항목"),
            _inline("F2", "금액"),
        )
        + _row(
            3, _inline("B3", "Synthetic Only"), _n("C3", "1"), _inline("E3", "Loan"), _n("F3", "2")
        )
    )
    result, _evidence = _map({"뱅샐현황": named, "기타": other}, _Opts(sheet_name="기타"))
    assert result.status == "mapped"
    assert result.sheet_name == "기타"
    assert result.balances


def test_date_priority_explicit_then_label_filename_collected() -> None:
    labeled = _row(1, _inline("A1", "기준일"), _inline("B1", "2026-06-15")) + _row(
        2, _inline("A2", "1.고객정보")
    )
    result, _ = _map(
        {"뱅샐현황": labeled},
        _Opts(
            snapshot_date="2026-01-02",
            source_filename="export_2025-12-01.xlsx",
            collected_at="2024-01-01T13:45:00Z",
        ),
    )
    assert result.snapshot.origin == "explicit"
    assert result.snapshot.parsed_date == date(2026, 1, 2)
    assert result.snapshot.raw == "2026-01-02"
    unlabeled = _row(1, _inline("A1", "1.고객정보"), _inline("B1", "Synthetic User"))
    from_file, _ = _map(
        {"뱅샐현황": unlabeled},
        _Opts(source_filename="overview_2025-11-03.xlsx", collected_at="2024-01-01"),
    )
    assert from_file.snapshot.origin == "filename"
    assert from_file.snapshot.parsed_date == date(2025, 11, 3)
    assert "not_source_observation" in from_file.snapshot.uncertainty
    assert from_file.snapshot.reliable is False
    collected, _ = _map({"뱅샐현황": unlabeled}, _Opts(collected_at="2024-02-03T08:00:00Z"))
    assert collected.snapshot.origin == "collected_at"
    assert collected.snapshot.parsed_date == date(2024, 2, 3)
    assert collected.snapshot.raw == "2024-02-03T08:00:00Z"
    missing, _ = _map({"뱅샐현황": unlabeled})
    assert missing.snapshot.origin == "missing"
    assert missing.snapshot.parsed_date is None
    assert "MISSING_SNAPSHOT_DATE" in _codes(missing.issues)


def test_conflicting_labeled_and_ambiguous_filename_dates() -> None:
    rows = (
        _row(1, _inline("A1", "기준일"), _inline("B1", "2026-06-15"))
        + _row(2, _inline("A2", "조회일"), _inline("B2", "2026-07-01"))
        + _row(3, _inline("A3", "1.고객정보"))
    )
    conflict, _ = _map({"뱅샐현황": rows})
    assert "CONFLICTING_LABELED_DATE" in _codes(conflict.issues)
    assert conflict.snapshot.origin != "source_label"
    unlabeled = _row(1, _inline("A1", "1.고객정보"))
    filename, _ = _map(
        {"뱅샐현황": unlabeled},
        _Opts(source_filename="export_2026-01-01_and_2026-02-02.xlsx", collected_at="2023-03-03"),
    )
    assert "AMBIGUOUS_FILENAME_DATE" in _codes(filename.issues)
    assert filename.snapshot.origin == "collected_at"


def test_precise_values_under_low_decimal_context() -> None:
    rows = (
        _row(1, _inline("A1", "기준일"), _inline("B1", "2026-06-15"))
        + _row(2, _inline("B2", "자산"), _inline("E2", "부채"))
        + _row(
            3,
            _inline("B3", "항목"),
            _inline("C3", "금액"),
            _inline("E3", "항목"),
            _inline("F3", "금액"),
        )
        + _row(
            4,
            _inline("B4", "Huge"),
            _n("C4", "9007199254740993"),
            _inline("E4", "Tiny"),
            _n("F4", "1e-255"),
        )
        + _row(
            5,
            _inline("B5", "Overflow"),
            _n("C5", "1e-256"),
            _inline("E5", "Zero"),
            _n("F5", "-0.00"),
        )
    )
    with localcontext() as context:
        context.prec = 2
        result, _ = _map({"뱅샐현황": rows})
    huge = next(row for row in result.balances if row.item_name.text == "Huge")
    tiny = next(row for row in result.balances if row.item_name.text == "Tiny")
    overflow = next(row for row in result.balances if row.item_name.text == "Overflow")
    zero = next(row for row in result.balances if row.item_name.text == "Zero")
    assert huge.amount.exact_value is not None
    assert huge.amount.exact_value.coefficient == "9007199254740993"
    assert tiny.amount.exact_value is not None
    assert tiny.amount.exact_value.scale == 255
    assert overflow.amount.exact_value is None
    assert "AMOUNT_SCALE_OUT_OF_RANGE" in _codes(overflow.amount.issues)
    assert zero.amount.exact_value is not None
    assert zero.amount.exact_value.coefficient == "0"
    assert zero.amount.exact_value.lexical == "-0.00"


def test_formulas_missing_cache_nonfinite_decorated_unknown_currency() -> None:
    rows = (
        _row(1, _inline("A1", "기준일"), _inline("B1", "2026-06-15"))
        + _row(2, _inline("B2", "자산"), _inline("E2", "부채"))
        + _row(
            3,
            _inline("B3", "항목"),
            _inline("C3", "금액"),
            _inline("E3", "항목"),
            _inline("F3", "금액"),
        )
        + _row(
            4,
            _inline("B4", "Cached"),
            _formula("C4", "A1", "9.25"),
            _inline("E4", "Missing"),
            _formula("F4", "A1"),
        )
        + _row(
            5, _inline("B5", "Bool"), _bool("C5", "1"), _inline("E5", "Err"), _err("F5", "#VALUE!")
        )
        + _row(
            6,
            _inline("B6", "Decorated"),
            _inline("C6", "1,000원"),
            _inline("E6", "Nonfinite"),
            _n("F6", "NaN"),
        )
    )
    result, _ = _map({"뱅샐현황": rows})
    cached = next(row for row in result.balances if row.item_name.text == "Cached")
    missing = next(row for row in result.balances if row.item_name.text == "Missing")
    boolean = next(row for row in result.balances if row.item_name.text == "Bool")
    error = next(row for row in result.balances if row.item_name.text == "Err")
    decorated = next(row for row in result.balances if row.item_name.text == "Decorated")
    nonfinite = next(row for row in result.balances if row.item_name.text == "Nonfinite")
    assert cached.amount.exact_value is not None
    assert cached.amount.unverified is True
    assert "FORMULA_CACHED_UNVERIFIED" in _codes(cached.amount.issues)
    assert cached.amount.cell is not None
    assert cached.amount.cell.formula is not None
    assert missing.amount.exact_value is None
    assert "FORMULA_CACHE_MISSING" in _codes(missing.amount.issues)
    assert "AMOUNT_BOOLEAN" in _codes(boolean.amount.issues)
    assert "AMOUNT_ERROR_CELL" in _codes(error.amount.issues)
    assert decorated.amount.exact_value is None
    assert "AMOUNT_FORMATTED" in _codes(decorated.amount.issues)
    assert "AMOUNT_NONFINITE" in _codes(nonfinite.amount.issues)
    assert all(
        row.amount.exact_value is None or row.amount.exact_value.currency_unknown
        for row in result.balances
    )
    assert "UNKNOWN_CURRENCY" in _codes(cached.amount.issues)
    assert all("KRW" not in item.detail for item in result.issues)


def test_date1904_and_type_d_cells() -> None:
    serial_1904 = str((date(2026, 6, 15) - date(1904, 1, 1)).days)
    rows = _row(1, _inline("A1", "기준일"), _n("B1", serial_1904)) + _row(
        2, _inline("A2", "1.고객정보")
    )
    serial, _ = _map({"뱅샐현황": rows}, _Opts(date1904=True))
    assert serial.snapshot.parsed_date == date(2026, 6, 15)
    assert serial.snapshot.kind == "excel_serial"
    assert serial.date1904 is True
    typed = _row(1, _inline("A1", "기준일"), _td("B1", "2026-06-15")) + _row(
        2, _inline("A2", "1.고객정보")
    )
    iso, _ = _map({"뱅샐현황": typed})
    assert iso.snapshot.parsed_date == date(2026, 6, 15)
    assert iso.snapshot.kind in {"iso_date", "iso_text"}
    stamped = _row(1, _inline("A1", "기준일"), _td("B1", "2026-06-15T13:45:00")) + _row(
        2, _inline("A2", "1.고객정보")
    )
    clock, _ = _map({"뱅샐현황": stamped})
    assert clock.snapshot.parsed_date == date(2026, 6, 15)
    assert "datetime_text_date_only" in clock.snapshot.uncertainty


def _balance_pair_rows(*body: str) -> str:
    return (
        _row(1, _inline("A1", "기준일"), _inline("B1", "2026-06-15"))
        + _row(2, _inline("B2", "자산"), _inline("F2", "부채"))
        + _row(
            3,
            _inline("B3", "항목"),
            _inline("C3", "금액"),
            _inline("F3", "항목"),
            _inline("G3", "금액"),
        )
        + "".join(body)
    )


def _fact_at(result, row: int, column: str):
    return next(fact for fact in result.facts if fact.source_row == row and fact.column == column)


@pytest.mark.parametrize("lexical", ["1_000", "３５１", " 42"])
def test_plain_decimal_rejects_underscore_unicode_and_whitespace(lexical: str) -> None:
    rows = _balance_pair_rows(
        _row(4, _inline("B4", "Odd"), _n("C4", lexical), _inline("F4", "Keep"), _n("G4", "1"))
    )
    result, _ = _map({"뱅샐현황": rows})
    odd = next(row for row in result.balances if row.item_name.text == "Odd")
    assert odd.amount.exact_value is None
    assert "UNSUPPORTED_AMOUNT" in _codes(odd.amount.issues)
    fact = _fact_at(result, 4, "C")
    assert fact.cell.raw_value == lexical
    assert fact.number_value is None


@pytest.mark.parametrize(
    ("institution", "expect_row", "issue_code"),
    [
        (_err("A22", "#VALUE!"), False, "NUMBER_ERROR_CELL"),
        (_bool("A22", "1"), False, "NUMBER_BOOLEAN"),
        (_formula("A22", "X", "Synthetic Insurer", "str"), True, "FORMULA_CACHED_UNVERIFIED"),
        (_formula("A22", "X", None, "str"), False, "FORMULA_CACHE_MISSING"),
    ],
)
def test_semantic_text_rejects_error_and_flags_formula(
    institution: str, expect_row: bool, issue_code: str
) -> None:
    rows = (
        _row(1, _inline("A1", "기준일"), _inline("B1", "2026-06-15"))
        + _row(20, _inline("A20", "4.보험현황"))
        + _row(21, _inline("A21", "금융사"), _inline("B21", "보험명"), _inline("D21", "총납입금"))
        + _row(22, institution, _inline("B22", "Synthetic Policy"), _n("D22", "10"))
    )
    result, _ = _map({"뱅샐현황": rows})
    fact = _fact_at(result, 22, "A")
    assert fact.cell is not None
    if expect_row:
        assert len(result.insurance) == 1
        policy = result.insurance[0]
        assert policy.institution.text == "Synthetic Insurer"
        assert policy.institution.unverified is True
        assert issue_code in _codes(policy.institution.issues)
        assert issue_code in _codes(policy.issues)
        assert policy.institution.cell is not None
        assert policy.institution.cell.formula is not None
        return
    assert result.insurance == ()
    assert issue_code in _codes(fact.issues)
    if fact.cell.cell_type == "e":
        assert fact.text_value == "#VALUE!" or fact.cell.raw_value == "#VALUE!"


@pytest.mark.parametrize(
    ("unit_cell", "currency_unknown", "unverified", "issue_code"),
    [
        (_inline("G21", "USD"), False, False, None),
        (_formula("G21", "X", "USD", "str"), False, True, "FORMULA_CACHED_UNVERIFIED"),
        (_formula("G21", "X", None, "str"), True, False, "FORMULA_CACHE_MISSING"),
        (_err("G21", "#VALUE!"), True, False, "UNKNOWN_CURRENCY"),
    ],
)
def test_header_currency_formula_and_error_do_not_silently_verify(
    unit_cell: str, currency_unknown: bool, unverified: bool, issue_code: str | None
) -> None:
    result, _ = _map({"뱅샐현황": _full_overview(extra={21: (unit_cell,)})})
    paid = result.insurance[0].paid_amount
    assert paid.exact_value is not None
    assert paid.exact_value.currency_unknown is currency_unknown
    if not currency_unknown:
        assert paid.exact_value.currency == "USD"
    assert paid.unverified is unverified
    if issue_code is not None:
        assert issue_code in _codes(paid.issues)
    assert paid.cell is not None
    assert paid.cell.formula is None
    assert paid.cell.raw_value == "120000"


def test_period_month_formula_issues_reach_cashflow_row() -> None:
    def _cashflow(month: str) -> str:
        return (
            _row(1, _inline("A1", "기준일"), _inline("B1", "2026-06-15"))
            + _row(7, _inline("A7", "2.현금흐름현황"))
            + _row(8, _inline("A8", "분류"), month)
            + _row(9, _inline("A9", "수입"), _n("B9", "10"))
        )

    result, _ = _map({"뱅샐현황": _cashflow(_formula("B8", "A1", "2026-09", "str"))})
    row = next(item for item in result.cashflows if item.period_month.text == "2026-09")
    assert row.period_month.unverified is True
    assert "FORMULA_CACHED_UNVERIFIED" in _codes(row.period_month.issues)
    assert "FORMULA_CACHED_UNVERIFIED" in _codes(row.issues)
    assert row.period_month.cell is not None
    assert row.period_month.cell.formula is not None
    assert row.period_month.cell.raw_value == "2026-09"
    skipped, _ = _map({"뱅샐현황": _cashflow(_formula("B8", "A1", None, "str"))})
    assert skipped.cashflows == ()
    header = _fact_at(skipped, 8, "B")
    assert header.cell.formula is not None
    assert "FORMULA_CACHE_MISSING" in _codes(header.issues)


@pytest.mark.parametrize(
    ("label", "value", "reliable", "flag"),
    [
        (_inline("A1", "기준일"), _inline("B1", "2026-09-10"), True, None),
        (
            _inline("A1", "기준일"),
            _formula("B1", "TODAY()", "2026-09-10", "d"),
            False,
            "formula_cached_unverified",
        ),
        (
            _formula("A1", "X", "기준일", "str"),
            _inline("B1", "2026-09-10"),
            True,
            "formula_label_unverified",
        ),
    ],
)
def test_labeled_formula_date_reliability_and_uncertainty(
    label: str, value: str, reliable: bool, flag: str | None
) -> None:
    rows = _row(1, label, value) + _row(2, _inline("A2", "1.고객정보"))
    result, _ = _map({"뱅샐현황": rows})
    assert result.snapshot.origin == "source_label"
    assert result.snapshot.parsed_date == date(2026, 9, 10)
    assert result.snapshot.reliable is reliable
    assert result.snapshot.date1904 is False
    if flag is not None:
        assert flag in result.snapshot.uncertainty
        assert "FORMULA_CACHED_UNVERIFIED" in _codes(result.issues)
    else:
        assert "formula_cached_unverified" not in result.snapshot.uncertainty
        assert "FORMULA_CACHED_UNVERIFIED" not in _codes(result.issues)


@pytest.mark.parametrize(
    ("header_row", "unit_ref", "group", "field"),
    [
        (21, "G21", "insurance", "paid_amount"),
        (27, "I27", "investments", "principal_amount"),
        (32, "I32", "loans", "principal_amount"),
        (8, "D8", "cashflows", "amount"),
    ],
)
def test_unbound_header_unit_sets_known_currency_through_mapper(
    header_row: int, unit_ref: str, group: str, field: str
) -> None:
    result, _ = _map({"뱅샐현황": _full_overview(extra={header_row: (_inline(unit_ref, "USD"),)})})
    typed = getattr(result, group)[0]
    amount = getattr(typed, field)
    assert amount.exact_value is not None
    assert amount.exact_value.currency == "USD"
    assert amount.exact_value.currency_unknown is False
    assert amount.unverified is False


def test_balance_side_scoped_header_units_do_not_cross() -> None:
    rows = (
        _row(1, _inline("A1", "기준일"), _inline("B1", "2026-06-15"))
        + _row(2, _inline("B2", "자산"), _inline("F2", "부채"))
        + _row(
            3,
            _inline("B3", "항목"),
            _inline("C3", "금액"),
            _inline("D3", "USD"),
            _inline("F3", "항목"),
            _inline("G3", "금액"),
            _inline("H3", "원"),
        )
        + _row(
            4,
            _inline("B4", "Deposit"),
            _n("C4", "10"),
            _inline("F4", "Loan"),
            _n("G4", "20"),
        )
    )
    result, _ = _map({"뱅샐현황": rows})
    asset = next(row for row in result.balances if row.side == "asset")
    liability = next(row for row in result.balances if row.side == "liability")
    assert asset.amount.exact_value is not None
    assert asset.amount.exact_value.currency == "USD"
    assert asset.amount.exact_value.currency_unknown is False
    assert liability.amount.exact_value is not None
    assert liability.amount.exact_value.currency == "KRW"
    assert liability.amount.exact_value.currency_unknown is False
    assert "AMBIGUOUS_CURRENCY" not in _codes(asset.amount.issues)
    assert "AMBIGUOUS_CURRENCY" not in _codes(liability.amount.issues)


@pytest.mark.parametrize("summary_side", ["asset", "liability"])
def test_balance_summary_does_not_hide_opposite_side_detail(summary_side: str) -> None:
    rows = (
        _row(1, _inline("A1", "기준일"), _inline("B1", "2026-06-15"))
        + _row(2, _inline("B2", "자산"), _inline("F2", "부채"))
        + _row(
            3,
            _inline("B3", "항목"),
            _inline("C3", "금액"),
            _inline("F3", "항목"),
            _inline("G3", "금액"),
        )
        + _row(
            4,
            _inline("B4", "합계" if summary_side == "asset" else "Deposit"),
            _n("C4", "10"),
            _inline("F4", "합계" if summary_side == "liability" else "Loan"),
            _n("G4", "20"),
        )
    )

    result, _ = _map({"뱅샐현황": rows})

    assert len(result.balances) == 1
    assert result.balances[0].side != summary_side
    detail_column = "G" if summary_side == "asset" else "C"
    summary_column = "C" if summary_side == "asset" else "G"
    assert _fact_at(result, 4, detail_column).fact_kind == "table_value"
    assert _fact_at(result, 4, summary_column).fact_kind == "summary"
