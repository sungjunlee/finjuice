"""Tests for asset snapshot ingestion path."""

import os
from datetime import datetime
from hashlib import sha256
from pathlib import Path

import polars as pl

from finjuice.pipeline.ingest.pipeline import ingest_file
from finjuice.pipeline.storage import csv_partition


def _write_banksalad_xlsx(
    tx_df: pl.DataFrame,
    file_path: Path,
    asset_df: pl.DataFrame | None = None,
    asset_sheet_name: str = "자산",
) -> None:
    """Write Banksalad-like workbook with optional asset sheet."""
    import xlsxwriter

    workbook = xlsxwriter.Workbook(file_path)

    summary_sheet = workbook.add_worksheet("요약")
    summary_sheet.write(0, 0, "요약")
    summary_sheet.write(1, 0, "테스트")

    tx_sheet = workbook.add_worksheet("가계부 내역")
    for col_idx, col_name in enumerate(tx_df.columns):
        tx_sheet.write(0, col_idx, col_name)
    for row_idx, row in enumerate(tx_df.iter_rows(named=False), start=1):
        for col_idx, value in enumerate(row):
            tx_sheet.write(row_idx, col_idx, value)

    if asset_df is not None:
        asset_sheet = workbook.add_worksheet(asset_sheet_name)
        for col_idx, col_name in enumerate(asset_df.columns):
            asset_sheet.write(0, col_idx, col_name)
        for row_idx, row in enumerate(asset_df.iter_rows(named=False), start=1):
            for col_idx, value in enumerate(row):
                asset_sheet.write(row_idx, col_idx, value)

    workbook.close()


def _sample_transaction_df() -> pl.DataFrame:
    """Create one-row transaction sheet for ingest precondition."""
    return pl.DataFrame(
        {
            "날짜": ["2026-02-20"],
            "시간": ["09:10"],
            "타입": ["지출"],
            "대분류": ["식비"],
            "중분류": ["카페"],
            "내용": ["스타벅스"],
            "메모": [""],
            "금액": [-5500],
            "화폐": ["KRW"],
            "결제수단": ["체크카드"],
        }
    )


def _asset_base_dir(csv_base_dir: Path) -> Path:
    """Get asset snapshot base dir from transaction base dir."""
    return csv_base_dir.parent / "assets" / "snapshots"


def test_asset_ingest_detect_sheet_and_map_columns(temp_csv_base_dir: Path, tmp_path: Path) -> None:
    """Asset ingest detects normalized sheet name and maps core columns."""
    # Arrange
    file_path = tmp_path / "asset_detect.xlsx"
    asset_df = pl.DataFrame(
        {
            "기준일": ["2026-02-20", "2026-02-20"],
            "계좌명": ["KB Main", "KB Main"],
            "종목명": ["AAPL", "MSFT"],
            "수량": [10, 5],
            "평가금액": [1_200_000, 800_000],
            "통화": ["KRW", "KRW"],
        }
    )
    _write_banksalad_xlsx(
        tx_df=_sample_transaction_df(),
        file_path=file_path,
        asset_df=asset_df,
        asset_sheet_name="보유 종목",
    )

    # Act
    ingest_file(file_path, temp_csv_base_dir)
    loaded = csv_partition.read_asset_snapshot_month(_asset_base_dir(temp_csv_base_dir), 2026, 2)

    # Assert
    assert loaded.height == 2
    assert set(loaded["snapshot_date"].to_list()) == {"2026-02-20"}
    assert all(str(v).startswith("acc_") for v in loaded["account_id"].to_list())
    assert all(str(v).startswith("ins_") for v in loaded["instrument_id"].to_list())


def test_asset_ingest_fallback_snapshot_date_from_mtime(
    temp_csv_base_dir: Path,
    tmp_path: Path,
) -> None:
    """Asset ingest uses file mtime date when snapshot_date column is missing."""
    # Arrange
    file_path = tmp_path / "asset_mtime_fallback.xlsx"
    asset_df = pl.DataFrame(
        {
            "계좌명": ["KB Main"],
            "종목명": ["AAPL"],
            "수량": [10],
            "평가금액": [1_000_000],
            "통화": ["KRW"],
        }
    )
    _write_banksalad_xlsx(_sample_transaction_df(), file_path, asset_df, asset_sheet_name="자산")
    ts = datetime(2026, 2, 21, 15, 30, 0).timestamp()
    os.utime(file_path, (ts, ts))

    # Act
    ingest_file(file_path, temp_csv_base_dir)
    loaded = csv_partition.read_asset_snapshot_month(_asset_base_dir(temp_csv_base_dir), 2026, 2)

    # Assert
    assert loaded.height == 1
    assert loaded["snapshot_date"].to_list() == ["2026-02-21"]


def test_asset_ingest_hybrid_id_policy_with_hash_fallback(
    temp_csv_base_dir: Path,
    tmp_path: Path,
) -> None:
    """Asset ingest preserves source IDs and derives missing IDs deterministically."""
    # Arrange
    file_path = tmp_path / "asset_hybrid_id.xlsx"
    asset_df = pl.DataFrame(
        {
            "기준일": ["2026-02-20", "2026-02-20"],
            "account_id": ["acc_source_1", None],
            "계좌명": ["Ignored Name", "KB Main"],
            "instrument_id": ["ins_source_1", None],
            "종목명": ["Ignored Ticker", "AAPL US"],
            "수량": [3, 7],
            "평가금액": [300_000, 700_000],
            "통화": ["KRW", "KRW"],
        }
    )
    _write_banksalad_xlsx(_sample_transaction_df(), file_path, asset_df, asset_sheet_name="assets")

    # Act
    ingest_file(file_path, temp_csv_base_dir)
    loaded = csv_partition.read_asset_snapshot_month(_asset_base_dir(temp_csv_base_dir), 2026, 2)
    rows = loaded.sort("market_value").iter_rows(named=True)
    low_value_row, high_value_row = rows

    # Assert
    assert low_value_row["account_id"] == "acc_source_1"
    assert low_value_row["instrument_id"] == "ins_source_1"

    expected_account = "acc_" + sha256("kbmain".encode("utf-8")).hexdigest()[:12]
    expected_instrument = "ins_" + sha256("aaplus".encode("utf-8")).hexdigest()[:12]
    assert high_value_row["account_id"] == expected_account
    assert high_value_row["instrument_id"] == expected_instrument


def test_asset_idempot_daily_dedup(temp_csv_base_dir: Path, tmp_path: Path) -> None:
    """Asset ingest enforces daily dedup and remains idempotent on re-run."""
    # Arrange
    file_path = tmp_path / "asset_idempot.xlsx"
    asset_df = pl.DataFrame(
        {
            "기준일": ["2026-02-20", "2026-02-20", "2026-02-20"],
            "계좌명": ["KB Main", "KB Main", "KB Main"],
            "종목명": ["AAPL", "AAPL", "MSFT"],
            "수량": [10, 10, 4],
            "평가금액": [1_000_000, 1_000_000, 400_000],
            "통화": ["KRW", "KRW", "KRW"],
        }
    )
    _write_banksalad_xlsx(
        _sample_transaction_df(),
        file_path,
        asset_df,
        asset_sheet_name="holdings",
    )

    # Act
    ingest_file(file_path, temp_csv_base_dir)
    first = csv_partition.read_asset_snapshot_month(_asset_base_dir(temp_csv_base_dir), 2026, 2)
    ingest_file(file_path, temp_csv_base_dir)
    second = csv_partition.read_asset_snapshot_month(_asset_base_dir(temp_csv_base_dir), 2026, 2)

    # Assert
    assert first.height == 2
    assert second.height == 2
    assert (
        first.sort(["account_id", "instrument_id"]).rows()
        == second.sort(["account_id", "instrument_id"]).rows()
    )


def test_asset_ingest_missing_sheet_warns_and_continues(
    temp_csv_base_dir: Path,
    tmp_path: Path,
    caplog,
) -> None:
    """Missing asset sheet logs warning but does not fail transaction ingest."""
    # Arrange
    file_path = tmp_path / "no_asset_sheet.xlsx"
    _write_banksalad_xlsx(_sample_transaction_df(), file_path, asset_df=None)

    # Act
    with caplog.at_level("WARNING"):
        inserted, skipped, skipped_rows = ingest_file(file_path, temp_csv_base_dir)

    # Assert
    assert inserted == 1
    assert skipped == 0
    assert skipped_rows == []
    assert any("Asset snapshot sheet not found" in record.message for record in caplog.records)
