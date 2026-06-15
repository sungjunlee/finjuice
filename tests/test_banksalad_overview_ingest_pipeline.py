"""Integration tests for Banksalad overview ingestion wiring."""

import json
from pathlib import Path

from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.ingest.pipeline import ingest_file_detailed, preview_ingest_paths
from finjuice.pipeline.storage import csv_partition

runner = CliRunner()


def _write_overview_export_xlsx(file_path: Path, *, include_transaction_row: bool = True) -> None:
    """Write a privacy-safe Banksalad-like export with overview and transactions."""
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
    overview.write(3, 4, "분류")
    overview.write(3, 5, "항목")
    overview.write(3, 6, "금액")
    overview.write(4, 1, "예금")
    overview.write(4, 2, "Synthetic Deposit")
    overview.write(4, 3, 1_250_000)
    overview.write(4, 4, "대출")
    overview.write(4, 5, "Synthetic Loan")
    overview.write(4, 6, 300_000)
    overview.write(7, 1, "현금흐름현황")
    overview.write(8, 1, "분류")
    overview.write(8, 2, "2026-06")
    overview.write(9, 1, "수입")
    overview.write(9, 2, 2_000_000)

    tx_sheet = workbook.add_worksheet("가계부 내역")
    headers = [
        "날짜",
        "시간",
        "타입",
        "대분류",
        "중분류",
        "내용",
        "메모",
        "금액",
        "화폐",
        "결제수단",
    ]
    for col_idx, header in enumerate(headers):
        tx_sheet.write(0, col_idx, header)
    if include_transaction_row:
        tx_sheet.write(1, 0, "2026-06-15")
        tx_sheet.write(1, 1, "09:10")
        tx_sheet.write(1, 2, "지출")
        tx_sheet.write(1, 3, "식비")
        tx_sheet.write(1, 4, "카페")
        tx_sheet.write(1, 5, "Synthetic Merchant")
        tx_sheet.write(1, 6, "")
        tx_sheet.write(1, 7, -5500)
        tx_sheet.write(1, 8, "KRW")
        tx_sheet.write(1, 9, "Synthetic Card")
    workbook.close()


def _data_dir_with_overview_export(tmp_path: Path) -> Path:
    """Create an initialized data directory with one overview workbook import."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "transactions").mkdir()
    (data_dir / "imports").mkdir()
    (data_dir / "exports").mkdir()
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")
    _write_overview_export_xlsx(data_dir / "imports" / "overview_export.xlsx")
    return data_dir


def test_overview_ingest_writes_and_is_idempotent(tmp_path: Path) -> None:
    """Overview tables are written naturally with XLSX ingest and dedup on re-run."""
    # Arrange
    data_dir = _data_dir_with_overview_export(tmp_path)
    file_path = data_dir / "imports" / "overview_export.xlsx"

    # Act
    first = ingest_file_detailed(file_path, data_dir / "transactions")
    second = ingest_file_detailed(file_path, data_dir / "transactions")

    facts = csv_partition.read_banksalad_overview_facts_month(
        data_dir / "banksalad" / "overview_facts", 2026, 6
    )
    balance = csv_partition.read_banksalad_balance_month(
        data_dir / "banksalad" / "balance", 2026, 6
    )
    cashflow = csv_partition.read_banksalad_cashflow_month(
        data_dir / "banksalad" / "cashflow", 2026, 6
    )

    # Assert
    assert first["transactions"]["inserted"] == 1
    assert second["transactions"]["inserted"] == 0
    assert second["transactions"]["dedup_skips"] == 1
    assert first["banksalad_overview"]["overview_facts"]["inserted"] == facts.height
    assert first["banksalad_overview"]["balance"]["inserted"] == balance.height
    assert first["banksalad_overview"]["cashflow"]["inserted"] == cashflow.height
    assert second["banksalad_overview"]["overview_facts"]["dedup_skips"] == facts.height
    assert second["banksalad_overview"]["balance"]["dedup_skips"] == balance.height
    assert second["banksalad_overview"]["cashflow"]["dedup_skips"] == cashflow.height


def test_overview_ingest_without_transaction_rows(tmp_path: Path) -> None:
    """Overview tables are still imported when the transaction sheet is empty."""
    # Arrange
    data_dir = _data_dir_with_overview_export(tmp_path)
    file_path = data_dir / "imports" / "overview_export.xlsx"
    _write_overview_export_xlsx(file_path, include_transaction_row=False)

    # Act
    result = ingest_file_detailed(file_path, data_dir / "transactions")

    balance = csv_partition.read_banksalad_balance_month(
        data_dir / "banksalad" / "balance", 2026, 6
    )

    # Assert
    assert result["transactions"]["inserted"] == 0
    assert result["transactions"]["dedup_skips"] == 0
    assert result["banksalad_overview"]["balance"]["inserted"] == 2
    assert balance.height == 2


def test_overview_dry_run_reports_counts_without_writing(tmp_path: Path) -> None:
    """Dry-run preview includes overview counts and does not write overview files."""
    # Arrange
    data_dir = _data_dir_with_overview_export(tmp_path)
    file_path = data_dir / "imports" / "overview_export.xlsx"

    # Act
    preview = preview_ingest_paths([file_path], data_dir / "transactions")

    # Assert
    overview = preview["banksalad_overview"]
    assert overview["overview_facts"]["estimated_new_rows"] > 0
    assert overview["balance"]["estimated_new_rows"] == 2
    assert overview["cashflow"]["estimated_new_rows"] == 1
    assert not (data_dir / "banksalad").exists()


def test_ingest_json_includes_overview_counts_without_private_values(tmp_path: Path) -> None:
    """CLI JSON includes overview count summaries but not raw overview labels or values."""
    # Arrange
    data_dir = _data_dir_with_overview_export(tmp_path)

    # Act
    dry_run = runner.invoke(app, ["--data-dir", str(data_dir), "ingest", "--dry-run", "--json"])
    write = runner.invoke(app, ["--data-dir", str(data_dir), "ingest", "--json"])

    # Assert
    assert dry_run.exit_code == 0, dry_run.output
    assert write.exit_code == 0, write.output
    dry_run_payload = json.loads(dry_run.output)
    write_payload = json.loads(write.output)
    assert dry_run_payload["preview"]["banksalad_overview"]["balance"]["estimated_new_rows"] == 2
    assert write_payload["summary"]["banksalad_overview"]["balance"]["inserted"] == 2
    assert "Synthetic Deposit" not in dry_run.output
    assert "Synthetic Loan" not in write.output
