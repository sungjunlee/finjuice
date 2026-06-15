"""Tests for privacy-safe XLSX structure inspection."""

import json
from pathlib import Path

from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app

runner = CliRunner()


def _write_private_sentinel_workbook(file_path: Path) -> None:
    import xlsxwriter

    workbook = xlsxwriter.Workbook(file_path)
    overview = workbook.add_worksheet("뱅샐현황")
    overview.write(0, 0, "기준일")
    overview.write(0, 1, "2026-06-15")
    overview.write(2, 1, "자산")
    overview.write(2, 4, "부채")
    overview.write(3, 1, "분류")
    overview.write(3, 2, "항목")
    overview.write(3, 3, "금액")
    overview.write(4, 1, "예금")
    overview.write(4, 2, "PRIVATE_ACCOUNT_SENTINEL")
    overview.write(4, 3, 987_654_321)
    overview.write(4, 4, "대출")
    overview.write(4, 5, "PRIVATE_LOAN_SENTINEL")
    overview.write(4, 6, 123_456_789)
    overview.write(7, 1, "현금흐름현황")

    tx_sheet = workbook.add_worksheet("가계부 내역")
    for col_idx, header in enumerate(["날짜", "시간", "타입", "내용", "금액", "결제수단"]):
        tx_sheet.write(0, col_idx, header)
    tx_sheet.write(1, 3, "PRIVATE_MERCHANT_SENTINEL")
    tx_sheet.write(1, 4, -55_000)
    tx_sheet.write(1, 5, "PRIVATE_CARD_SENTINEL")
    workbook.close()


def test_inspect_xlsx_json_reports_structure_without_private_values(tmp_path: Path) -> None:
    # Arrange
    workbook_path = tmp_path / "private_export.xlsx"
    _write_private_sentinel_workbook(workbook_path)

    # Act
    result = runner.invoke(app, ["inspect", "xlsx", str(workbook_path), "--json"])

    # Assert
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    output_text = result.output
    assert "PRIVATE_ACCOUNT_SENTINEL" not in output_text
    assert "PRIVATE_LOAN_SENTINEL" not in output_text
    assert "PRIVATE_MERCHANT_SENTINEL" not in output_text
    assert "PRIVATE_CARD_SENTINEL" not in output_text
    assert "987654321" not in output_text
    assert "123456789" not in output_text
    assert "55000" not in output_text
    assert payload["_meta"]["command"] == "inspect xlsx"
    assert payload["file"]["name"] == "private_export.xlsx"
    assert payload["summary"]["worksheet_count"] == 2
    assert "banksalad_overview" in payload["summary"]["detected_roles"]
    overview_sheet = payload["worksheets"][0]
    assert overview_sheet["detected_roles"] == ["banksalad_overview"]
    assert "balance_status" in overview_sheet["detected_blocks"]
    assert "cashflow_monthly" in overview_sheet["detected_blocks"]
    assert {anchor["anchor"] for anchor in overview_sheet["allowlisted_anchors"]} >= {
        "asset_anchor",
        "liability_anchor",
        "cashflow_anchor",
    }


def test_inspect_xlsx_text_reports_structure_without_private_values(tmp_path: Path) -> None:
    # Arrange
    workbook_path = tmp_path / "private_export.xlsx"
    _write_private_sentinel_workbook(workbook_path)

    # Act
    result = runner.invoke(app, ["inspect", "xlsx", str(workbook_path)])

    # Assert
    assert result.exit_code == 0, result.output
    assert "banksalad_overview" in result.output
    assert "balance_status" in result.output
    assert "cashflow_monthly" in result.output
    assert "PRIVATE_ACCOUNT_SENTINEL" not in result.output
    assert "PRIVATE_LOAN_SENTINEL" not in result.output
    assert "PRIVATE_MERCHANT_SENTINEL" not in result.output
    assert "PRIVATE_CARD_SENTINEL" not in result.output
    assert "987654321" not in result.output
    assert "123456789" not in result.output
    assert "55000" not in result.output


def test_inspect_xlsx_missing_file_uses_json_error_envelope(tmp_path: Path) -> None:
    # Act
    result = runner.invoke(app, ["inspect", "xlsx", str(tmp_path / "missing.xlsx"), "--json"])

    # Assert
    assert result.exit_code == 3
    payload = json.loads(result.output)
    assert payload["_meta"]["command"] == "inspect xlsx"
    assert payload["error"]["code"] == "FILE_NOT_FOUND"
    assert "missing.xlsx" in payload["error"]["message"]


def test_inspect_xlsx_invalid_file_uses_json_error_envelope(tmp_path: Path) -> None:
    # Arrange
    workbook_path = tmp_path / "invalid.xlsx"
    workbook_path.write_text("not an xlsx workbook", encoding="utf-8")

    # Act
    result = runner.invoke(app, ["inspect", "xlsx", str(workbook_path), "--json"])

    # Assert
    assert result.exit_code == 3
    payload = json.loads(result.output)
    assert payload["_meta"]["command"] == "inspect xlsx"
    assert payload["error"]["code"] == "INSPECTION_FAILED"
