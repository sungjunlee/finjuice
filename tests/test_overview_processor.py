"""Tests for Banksalad overview worksheet parsing."""

from datetime import datetime
from pathlib import Path

import polars as pl

from finjuice.pipeline.ingest._overview_processor import parse_banksalad_overview
from finjuice.pipeline.storage.csv_partition import (
    BANKSALAD_BALANCE_POLARS_SCHEMA,
    BANKSALAD_CASHFLOW_POLARS_SCHEMA,
    BANKSALAD_INSURANCE_POLARS_SCHEMA,
    BANKSALAD_INVESTMENT_POLARS_SCHEMA,
    BANKSALAD_LOAN_POLARS_SCHEMA,
    BANKSALAD_OVERVIEW_FACT_POLARS_SCHEMA,
)


def _write_overview_xlsx(
    file_path: Path,
    *,
    sheet_name: str = "뱅샐현황",
    top_padding_rows: int = 0,
    include_cashflow: bool = True,
    ambiguous_cashflow: bool = False,
) -> None:
    """Write a privacy-safe synthetic Banksalad overview workbook."""
    import xlsxwriter

    workbook = xlsxwriter.Workbook(file_path)
    sheet = workbook.add_worksheet(sheet_name)

    row = top_padding_rows
    sheet.write(row, 0, "테스트 현황")
    row += 2
    row = _write_balance_block(sheet, row)

    if include_cashflow:
        _write_cashflow_block(
            workbook,
            sheet,
            row + 3,
            ambiguous_cashflow=ambiguous_cashflow,
            cashflow_header_as_excel_dates=False,
        )

    workbook.close()


def _write_balance_block(sheet: object, row: int) -> int:
    """Write the synthetic balance block and return the next row."""
    sheet.write(row, 1, "자산")
    sheet.write(row, 4, "부채")
    row += 1
    sheet.write(row, 1, "분류")
    sheet.write(row, 2, "항목")
    sheet.write(row, 3, "금액")
    sheet.write(row, 4, "분류")
    sheet.write(row, 5, "항목")
    sheet.write(row, 6, "금액")
    row += 1
    sheet.write(row, 1, "예금")
    sheet.write(row, 2, "Synthetic Deposit")
    sheet.write(row, 3, 1_250_000)
    sheet.write(row, 4, "대출")
    sheet.write(row, 5, "Synthetic Loan")
    sheet.write(row, 6, "300,000원")
    row += 1
    sheet.write(row, 1, "투자")
    sheet.write(row, 2, "Synthetic Fund")
    sheet.write(row, 3, 450_000)
    sheet.write(row, 4, "카드")
    sheet.write(row, 5, "Synthetic Card Due")
    sheet.write(row, 6, 50_000)
    return row + 1


def _write_cashflow_block(
    workbook: object,
    sheet: object,
    row: int,
    *,
    ambiguous_cashflow: bool,
    cashflow_header_as_excel_dates: bool,
) -> None:
    """Write the synthetic cashflow block."""
    sheet.write(row, 1, "2.현금흐름현황")
    row += 1
    sheet.write(row, 1, "분류")
    if ambiguous_cashflow:
        sheet.write(row, 2, "최근")
    elif cashflow_header_as_excel_dates:
        date_format = workbook.add_format({"num_format": "yyyy-mm-dd"})
        sheet.write_datetime(row, 2, datetime(2026, 5, 1), date_format)
        sheet.write_datetime(row, 3, datetime(2026, 6, 1), date_format)
    else:
        sheet.write(row, 2, "2026년 5월")
        sheet.write(row, 3, "2026-06")
    row += 1
    sheet.write(row, 1, "수입")
    sheet.write(row, 2, 2_000_000)
    if not ambiguous_cashflow:
        sheet.write(row, 3, 2_100_000)
    row += 1
    sheet.write(row, 1, "지출")
    sheet.write(row, 2, -1_400_000)
    if not ambiguous_cashflow:
        sheet.write(row, 3, -1_500_000)


def _write_non_overview_xlsx(file_path: Path) -> None:
    """Write a workbook that has transaction-like data but no overview anchors."""
    import xlsxwriter

    workbook = xlsxwriter.Workbook(file_path)
    sheet = workbook.add_worksheet("가계부 내역")
    sheet.write(0, 0, "날짜")
    sheet.write(0, 1, "금액")
    sheet.write(1, 0, "2026-06-15")
    sheet.write(1, 1, -1000)
    workbook.close()


def _write_false_anchor_before_balance_xlsx(file_path: Path) -> None:
    """Write a workbook with an invalid early asset/liability label pair."""
    import xlsxwriter

    workbook = xlsxwriter.Workbook(file_path)
    sheet = workbook.add_worksheet("뱅샐현황")
    sheet.write(0, 1, "자산")
    sheet.write(0, 4, "부채")
    _write_balance_block(sheet, 10)
    workbook.close()


def _write_excel_date_cashflow_headers_xlsx(file_path: Path) -> None:
    """Write an overview workbook whose cashflow headers are Excel date cells."""
    import xlsxwriter

    workbook = xlsxwriter.Workbook(file_path)
    sheet = workbook.add_worksheet("뱅샐현황")
    row = _write_balance_block(sheet, 2)
    _write_cashflow_block(
        workbook,
        sheet,
        row + 3,
        ambiguous_cashflow=False,
        cashflow_header_as_excel_dates=True,
    )
    workbook.close()


def _write_numbered_followup_section_xlsx(file_path: Path) -> None:
    """Write cashflow followed by another numbered overview section without blank rows."""
    import xlsxwriter

    workbook = xlsxwriter.Workbook(file_path)
    sheet = workbook.add_worksheet("뱅샐현황")
    row = _write_balance_block(sheet, 2)
    cashflow_row = row + 3
    _write_cashflow_block(
        workbook,
        sheet,
        cashflow_row,
        ambiguous_cashflow=False,
        cashflow_header_as_excel_dates=False,
    )
    sheet.write(cashflow_row + 4, 1, "3.소비현황")
    sheet.write(cashflow_row + 4, 2, "Non Numeric Followup")
    workbook.close()


def _write_full_overview_xlsx(file_path: Path) -> None:
    """Write a synthetic numbered overview workbook with all supported sections."""
    import xlsxwriter

    workbook = xlsxwriter.Workbook(file_path)
    date_format = workbook.add_format({"num_format": "yyyy-mm-dd"})
    sheet = workbook.add_worksheet("뱅샐현황")

    sheet.write(0, 0, "기준일")
    sheet.write_datetime(0, 1, datetime(2026, 6, 15), date_format)
    sheet.write(2, 0, "1.고객정보")
    sheet.write(3, 0, "이름")
    sheet.write(3, 1, "Synthetic User")
    _write_cashflow_block(
        workbook,
        sheet,
        6,
        ambiguous_cashflow=False,
        cashflow_header_as_excel_dates=False,
    )
    sheet.write(12, 0, "3.재무현황")
    _write_balance_block(sheet, 13)
    sheet.write(19, 0, "4.보험현황")
    sheet.write_row(20, 0, ["금융사", "보험명", "계약상태", "총납입금", "계약일자", "만기일자"])
    sheet.write_row(21, 0, ["Synthetic Insurer", "Synthetic Policy", "정상", 120_000])
    sheet.write_datetime(21, 4, datetime(2024, 1, 2), date_format)
    sheet.write_datetime(21, 5, datetime(2034, 1, 2), date_format)
    sheet.write_row(22, 0, ["합계", "", "", 120_000, "", ""])
    sheet.write(25, 0, "5.투자현황")
    sheet.write_row(
        26,
        0,
        [
            "투자상품종류",
            "금융사",
            "상품명",
            "투자원금",
            "평가금액",
            "수익률",
            "가입일자",
            "만기일자",
        ],
    )
    sheet.write_row(
        27,
        0,
        ["펀드", "Synthetic Securities", "Synthetic Fund A", 1_000_000, 1_050_000, 5.0],
    )
    sheet.write_datetime(27, 6, datetime(2025, 3, 1), date_format)
    sheet.write(30, 0, "6.대출현황")
    sheet.write_row(
        31,
        0,
        [
            "대출종류",
            "금융사",
            "상품명",
            "대출원금",
            "대출잔액",
            "대출금리",
            "대출신규일",
            "대출만기일",
        ],
    )
    sheet.write_row(
        32,
        0,
        ["신용", "Synthetic Bank", "Synthetic Loan A", 3_000_000, 2_500_000, 4.5],
    )
    sheet.write_datetime(32, 6, datetime(2023, 4, 1), date_format)
    sheet.write_datetime(32, 7, datetime(2028, 4, 1), date_format)
    workbook.close()


def _write_empty_structured_sections_xlsx(file_path: Path) -> None:
    """Write overview sections with headers but no entity rows."""
    import xlsxwriter

    workbook = xlsxwriter.Workbook(file_path)
    sheet = workbook.add_worksheet("뱅샐현황")
    sheet.write(0, 0, "1.고객정보")
    sheet.write(3, 0, "3.재무현황")
    _write_balance_block(sheet, 4)
    sheet.write(10, 0, "4.보험현황")
    sheet.write_row(11, 0, ["금융사", "보험명", "계약상태", "총납입금", "계약일자", "만기일자"])
    sheet.write(14, 0, "5.투자현황")
    sheet.write_row(
        15,
        0,
        [
            "투자상품종류",
            "금융사",
            "상품명",
            "투자원금",
            "평가금액",
            "수익률",
            "가입일자",
            "만기일자",
        ],
    )
    sheet.write(18, 0, "6.대출현황")
    sheet.write_row(
        19,
        0,
        [
            "대출종류",
            "금융사",
            "상품명",
            "대출원금",
            "대출잔액",
            "대출금리",
            "대출신규일",
            "대출만기일",
        ],
    )
    workbook.close()


def _balance_projection_content(df: pl.DataFrame) -> list[tuple[str, str, str, float, str]]:
    """Return stable balance content excluding source coordinates."""
    return list(
        df.sort(["side", "category", "item_name"])
        .select(["side", "category", "item_name", "amount", "currency"])
        .iter_rows()
    )


def test_overview_parser_extracts_facts_balance_and_cashflow_from_overview_sheet(
    tmp_path: Path,
) -> None:
    """Overview parser emits typed DataFrames from a synthetic real-shape sheet."""
    # Arrange
    file_path = tmp_path / "overview.xlsx"
    _write_overview_xlsx(file_path)

    # Act
    result = parse_banksalad_overview(
        file_path=file_path,
        file_id="260615_1",
        snapshot_date="2026-06-15",
    )

    # Assert
    assert result.warnings == []
    assert result.overview_facts.schema == BANKSALAD_OVERVIEW_FACT_POLARS_SCHEMA
    assert result.balance.schema == BANKSALAD_BALANCE_POLARS_SCHEMA
    assert result.cashflow.schema == BANKSALAD_CASHFLOW_POLARS_SCHEMA

    assert result.overview_facts.height > result.balance.height
    assert set(result.overview_facts["block_id"].to_list()) == {
        "balance_status",
        "cashflow_monthly",
    }
    assert _balance_projection_content(result.balance) == [
        ("asset", "예금", "Synthetic Deposit", 1_250_000.0, "KRW"),
        ("asset", "투자", "Synthetic Fund", 450_000.0, "KRW"),
        ("liability", "대출", "Synthetic Loan", 300_000.0, "KRW"),
        ("liability", "카드", "Synthetic Card Due", 50_000.0, "KRW"),
    ]
    assert result.cashflow.select(["period_month", "category", "amount"]).sort(
        ["period_month", "category"]
    ).rows() == [
        ("2026-05", "수입", 2_000_000.0),
        ("2026-05", "지출", -1_400_000.0),
        ("2026-06", "수입", 2_100_000.0),
        ("2026-06", "지출", -1_500_000.0),
    ]


def test_overview_parser_extracts_all_numbered_overview_sections(
    tmp_path: Path,
) -> None:
    """Numbered overview sections become source facts plus typed projections."""
    # Arrange
    file_path = tmp_path / "full_overview.xlsx"
    _write_full_overview_xlsx(file_path)

    # Act
    result = parse_banksalad_overview(
        file_path=file_path,
        file_id="260615_1",
    )

    # Assert
    assert result.warnings == []
    assert result.insurance.schema == BANKSALAD_INSURANCE_POLARS_SCHEMA
    assert result.investments.schema == BANKSALAD_INVESTMENT_POLARS_SCHEMA
    assert result.loans.schema == BANKSALAD_LOAN_POLARS_SCHEMA
    assert set(result.overview_facts["block_id"].to_list()) == {
        "customer_info",
        "cashflow_monthly",
        "balance_status",
        "insurance_status",
        "investment_status",
        "loan_status",
    }
    assert result.insurance.select(["institution", "policy_name", "paid_amount"]).rows() == [
        ("Synthetic Insurer", "Synthetic Policy", 120_000.0)
    ]
    assert result.investments.select(
        ["product_type", "institution", "product_name", "valuation_amount"]
    ).rows() == [("펀드", "Synthetic Securities", "Synthetic Fund A", 1_050_000.0)]
    assert result.loans.select(
        ["loan_type", "institution", "product_name", "balance_amount"]
    ).rows() == [("신용", "Synthetic Bank", "Synthetic Loan A", 2_500_000.0)]
    assert result.insurance["source_fact_id"].drop_nulls().len() == 1
    assert result.investments["source_fact_id"].drop_nulls().len() == 1
    assert result.loans["source_fact_id"].drop_nulls().len() == 1


def test_overview_parser_handles_empty_structured_sections(
    tmp_path: Path,
) -> None:
    """Empty detected sections still produce facts without typed entity rows."""
    # Arrange
    file_path = tmp_path / "empty_sections.xlsx"
    _write_empty_structured_sections_xlsx(file_path)

    # Act
    result = parse_banksalad_overview(
        file_path=file_path,
        file_id="260615_1",
        snapshot_date="2026-06-15",
    )

    # Assert
    assert result.warnings == []
    assert {"customer_info", "insurance_status", "investment_status", "loan_status"} <= set(
        result.overview_facts["block_id"].to_list()
    )
    assert result.insurance.height == 0
    assert result.investments.height == 0
    assert result.loans.height == 0


def test_overview_parser_uses_anchors_not_absolute_rows_for_balance(
    tmp_path: Path,
) -> None:
    """Balance parsing remains equivalent when the overview block drifts down."""
    # Arrange
    base_path = tmp_path / "overview_base.xlsx"
    drifted_path = tmp_path / "overview_drifted.xlsx"
    _write_overview_xlsx(base_path, top_padding_rows=0, include_cashflow=False)
    _write_overview_xlsx(drifted_path, top_padding_rows=5, include_cashflow=False)

    # Act
    base = parse_banksalad_overview(
        file_path=base_path,
        file_id="260615_1",
        snapshot_date="2026-06-15",
    )
    drifted = parse_banksalad_overview(
        file_path=drifted_path,
        file_id="260615_2",
        snapshot_date="2026-06-15",
    )

    # Assert
    assert _balance_projection_content(base.balance) == _balance_projection_content(drifted.balance)
    assert min(drifted.balance["source_row"].to_list()) > min(base.balance["source_row"].to_list())


def test_overview_parser_tries_later_balance_anchor_pairs_when_headers_fail(
    tmp_path: Path,
) -> None:
    """A false early asset/liability pair does not hide a later valid table."""
    # Arrange
    file_path = tmp_path / "overview_false_anchor.xlsx"
    _write_false_anchor_before_balance_xlsx(file_path)

    # Act
    result = parse_banksalad_overview(
        file_path=file_path,
        file_id="260615_1",
        snapshot_date="2026-06-15",
    )

    # Assert
    assert result.warnings == []
    assert result.balance.height == 4
    assert min(result.balance["source_row"].to_list()) > 10


def test_overview_parser_ignores_cashflow_month_dates_for_snapshot_date(
    tmp_path: Path,
) -> None:
    """Cashflow Excel date headers are periods, not workbook snapshot dates."""
    # Arrange
    file_path = tmp_path / "overview_excel_month_headers.xlsx"
    _write_excel_date_cashflow_headers_xlsx(file_path)

    # Act
    result = parse_banksalad_overview(
        file_path=file_path,
        file_id="260615_1",
        file_mtime="2026-06-15T12:00:00",
    )

    # Assert
    assert set(result.balance["snapshot_date"].to_list()) == {"2026-06-15"}
    assert set(result.cashflow["snapshot_date"].to_list()) == {"2026-06-15"}
    assert result.cashflow.select(["period_month", "category", "amount"]).sort(
        ["period_month", "category"]
    ).rows() == [
        ("2026-05", "수입", 2_000_000.0),
        ("2026-05", "지출", -1_400_000.0),
        ("2026-06", "수입", 2_100_000.0),
        ("2026-06", "지출", -1_500_000.0),
    ]


def test_overview_parser_stops_cashflow_at_numbered_followup_section(
    tmp_path: Path,
) -> None:
    """Numbered sections after cashflow do not poison the cashflow projection."""
    # Arrange
    file_path = tmp_path / "overview_numbered_followup.xlsx"
    _write_numbered_followup_section_xlsx(file_path)

    # Act
    result = parse_banksalad_overview(
        file_path=file_path,
        file_id="260615_1",
        snapshot_date="2026-06-15",
    )

    # Assert
    assert result.warnings == []
    assert result.cashflow.select(["period_month", "category", "amount"]).sort(
        ["period_month", "category"]
    ).rows() == [
        ("2026-05", "수입", 2_000_000.0),
        ("2026-05", "지출", -1_400_000.0),
        ("2026-06", "수입", 2_100_000.0),
        ("2026-06", "지출", -1_500_000.0),
    ]
    assert "3.소비현황" not in result.cashflow["category"].to_list()


def test_overview_parser_returns_empty_frames_and_warning_without_overview_sheet(
    tmp_path: Path,
) -> None:
    """Non-overview workbooks return typed empty frames without raising."""
    # Arrange
    file_path = tmp_path / "transactions_only.xlsx"
    _write_non_overview_xlsx(file_path)

    # Act
    result = parse_banksalad_overview(
        file_path=file_path,
        file_id="260615_1",
        snapshot_date="2026-06-15",
    )

    # Assert
    assert result.overview_facts.height == 0
    assert result.balance.height == 0
    assert result.cashflow.height == 0
    assert result.overview_facts.schema == BANKSALAD_OVERVIEW_FACT_POLARS_SCHEMA
    assert result.balance.schema == BANKSALAD_BALANCE_POLARS_SCHEMA
    assert result.cashflow.schema == BANKSALAD_CASHFLOW_POLARS_SCHEMA
    assert result.warnings == ["Overview sheet not found in transactions_only.xlsx; skipped"]


def test_overview_parser_warns_and_skips_ambiguous_cashflow_projection(
    tmp_path: Path,
) -> None:
    """Cashflow projection is skipped when month headers are not unambiguous."""
    # Arrange
    file_path = tmp_path / "ambiguous_cashflow.xlsx"
    _write_overview_xlsx(file_path, ambiguous_cashflow=True)

    # Act
    result = parse_banksalad_overview(
        file_path=file_path,
        file_id="260615_1",
        snapshot_date="2026-06-15",
    )

    # Assert
    assert result.balance.height == 4
    assert result.cashflow.height == 0
    assert any("Cashflow projection skipped" in warning for warning in result.warnings)
