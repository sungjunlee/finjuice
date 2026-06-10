"""Minimal E2E regression tests for combined transaction and asset flows.

These tests lock the release gate baseline for Issue #230:
- transaction ingest/tag/transfer/export path via ``finjuice all``
- asset snapshot ingest + daily dedup path in the same pipeline run
- idempotency across reruns for both transaction and asset outputs
"""

import shutil
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.storage import csv_partition

runner = CliRunner()


def _write_tx_asset_workbook(file_path: Path) -> None:
    """Write a minimal Banksalad-like workbook with tx + asset sheets."""
    import xlsxwriter

    workbook = xlsxwriter.Workbook(file_path)

    summary_sheet = workbook.add_worksheet("요약")
    summary_sheet.write(0, 0, "요약")
    summary_sheet.write(1, 0, "Issue #230 regression fixture")

    tx_headers = [
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
    tx_rows = [
        ["2026-02-20", "09:10", "지출", "식비", "카페", "스타벅스", "", -5500, "KRW", "체크카드"],
        [
            "2026-02-20",
            "14:00",
            "이체",
            "이체",
            "계좌이체",
            "내계좌이체",
            "",
            -50000,
            "KRW",
            "계좌A",
        ],
        [
            "2026-02-20",
            "14:03",
            "이체",
            "이체",
            "계좌이체",
            "내계좌이체",
            "",
            50000,
            "KRW",
            "계좌B",
        ],
        ["2026-02-21", "08:30", "수입", "급여", "월급", "회사", "", 3000000, "KRW", "은행계좌"],
    ]

    tx_sheet = workbook.add_worksheet("가계부 내역")
    for col_idx, header in enumerate(tx_headers):
        tx_sheet.write(0, col_idx, header)
    for row_idx, row in enumerate(tx_rows, start=1):
        for col_idx, value in enumerate(row):
            tx_sheet.write(row_idx, col_idx, value)

    asset_headers = ["기준일", "계좌명", "종목명", "수량", "평가금액", "통화"]
    asset_rows = [
        ["2026-02-20", "KB Main", "AAPL", 10, 1500000, "KRW"],
        ["2026-02-20", "KB Main", "AAPL", 10, 1500000, "KRW"],  # duplicate by daily key
        ["2026-02-20", "KB Main", "MSFT", 5, 900000, "KRW"],
    ]

    asset_sheet = workbook.add_worksheet("보유 종목")
    for col_idx, header in enumerate(asset_headers):
        asset_sheet.write(0, col_idx, header)
    for row_idx, row in enumerate(asset_rows, start=1):
        for col_idx, value in enumerate(row):
            asset_sheet.write(row_idx, col_idx, value)

    workbook.close()


@pytest.fixture
def tx_asset_data_dir(tmp_path: Path) -> Path:
    """Create initialized data dir with runtime tx+asset XLSX fixture."""
    # Arrange
    data_dir = tmp_path / "data"
    init_result = runner.invoke(app, ["--data-dir", str(data_dir), "init", "--no-git"])
    assert init_result.exit_code == 0, f"init failed: {init_result.output}"

    rules_src = Path(__file__).resolve().parents[1] / "fixtures" / "sample_rules.yaml"
    shutil.copy(rules_src, data_dir / "rules.yaml")

    workbook_path = data_dir / "imports" / "tx_asset_regression.xlsx"
    _write_tx_asset_workbook(workbook_path)
    return data_dir


@pytest.mark.e2e
def test_tx_asset_minimal_e2e_flow(tx_asset_data_dir: Path) -> None:
    """finjuice all should produce transaction + asset outputs in one run."""
    # Act
    result = runner.invoke(app, ["--data-dir", str(tx_asset_data_dir), "refresh"])

    # Assert
    assert result.exit_code == 0, f"pipeline failed: {result.output}"

    tx_csv_files = list((tx_asset_data_dir / "transactions").rglob("*.csv"))
    assert tx_csv_files, "No transaction CSV partitions were generated"

    snapshot_path = tx_asset_data_dir / "assets" / "snapshots" / "2026" / "02" / "snapshots.csv"
    assert snapshot_path.exists(), "Asset snapshot partition was not generated"

    snapshot_df = pl.read_csv(snapshot_path)
    assert snapshot_df.height == 2, "Asset daily dedup should keep exactly 2 positions"
    unique_keys = snapshot_df.select(["snapshot_date", "account_id", "instrument_id"]).unique()
    assert unique_keys.height == snapshot_df.height, "Asset snapshot contains duplicate daily keys"

    exports_dir = tx_asset_data_dir / "exports"
    master_files = list(exports_dir.glob("master_*.xlsx"))
    assert master_files, "Master XLSX was not generated"

    reports_dir = exports_dir / "reports"
    for report_name in ("monthly_spend.csv", "by_tag.csv", "by_account.csv", "transfers.csv"):
        assert (reports_dir / report_name).exists(), f"Missing report: {report_name}"


@pytest.mark.e2e
def test_tx_asset_rerun_idempotent_for_tx_and_assets(tx_asset_data_dir: Path) -> None:
    """Running full pipeline twice should keep tx and asset outputs identical."""
    # Arrange + Act (run #1)
    first_result = runner.invoke(app, ["--data-dir", str(tx_asset_data_dir), "refresh"])
    assert first_result.exit_code == 0, f"first run failed: {first_result.output}"

    tx_base_dir = tx_asset_data_dir / "transactions"
    tx_first = csv_partition.get_all_transactions(tx_base_dir)
    tx_hashes_first = sorted(tx_first["row_hash"].to_list())

    snapshot_path = tx_asset_data_dir / "assets" / "snapshots" / "2026" / "02" / "snapshots.csv"
    snapshot_first = pl.read_csv(snapshot_path).sort(
        ["snapshot_date", "account_id", "instrument_id"]
    )

    # Act (run #2)
    second_result = runner.invoke(app, ["--data-dir", str(tx_asset_data_dir), "refresh"])
    assert second_result.exit_code == 0, f"second run failed: {second_result.output}"

    # Assert
    tx_second = csv_partition.get_all_transactions(tx_base_dir)
    tx_hashes_second = sorted(tx_second["row_hash"].to_list())
    assert tx_hashes_first == tx_hashes_second, "Transaction row_hash multiset changed after rerun"

    snapshot_second = pl.read_csv(snapshot_path).sort(
        ["snapshot_date", "account_id", "instrument_id"]
    )
    assert snapshot_first.rows() == snapshot_second.rows(), "Asset snapshots changed after rerun"
