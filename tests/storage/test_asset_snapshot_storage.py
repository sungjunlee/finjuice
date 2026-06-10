"""Tests for asset snapshot CSV partition storage."""

from pathlib import Path

import polars as pl
import pytest

from finjuice.pipeline.storage.csv_partition import (
    append_asset_snapshots,
    get_asset_snapshot_partition_path,
    read_asset_snapshot_month,
    write_asset_snapshot_month,
)


def _sample_asset_df() -> pl.DataFrame:
    """Create sample asset snapshot dataframe."""
    return pl.DataFrame(
        {
            "snapshot_date": ["2026-02-20", "2026-02-20"],
            "account_id": ["acc_kb", "acc_kb"],
            "instrument_id": ["ins_aapl", "ins_msft"],
            "quantity": [10.0, 5.0],
            "market_value": [1_500_000.0, 900_000.0],
            "currency": ["KRW", "KRW"],
            "file_id": ["260220_1", "260220_1"],
            "source_row": [2, 3],
        }
    )


def test_asset_snapshot_write_and_read_month_partition(tmp_path: Path) -> None:
    """Asset snapshot storage writes and reads partitioned monthly CSV."""
    # Arrange
    base_dir = tmp_path / "assets" / "snapshots"
    df = _sample_asset_df()

    # Act
    write_asset_snapshot_month(base_dir, df, 2026, 2)
    loaded = read_asset_snapshot_month(base_dir, 2026, 2)

    # Assert
    partition_path = get_asset_snapshot_partition_path(base_dir, 2026, 2)
    assert partition_path.exists()
    assert loaded.height == 2
    assert set(loaded.columns) == {
        "snapshot_date",
        "account_id",
        "instrument_id",
        "quantity",
        "market_value",
        "currency",
        "file_id",
        "source_row",
    }


def test_asset_snapshot_read_month_projects_requested_columns(tmp_path: Path) -> None:
    """Asset snapshot reads should preserve caller-requested column projection."""
    base_dir = tmp_path / "assets" / "snapshots"
    write_asset_snapshot_month(base_dir, _sample_asset_df(), 2026, 2)

    loaded = read_asset_snapshot_month(
        base_dir,
        2026,
        2,
        columns=["snapshot_date", "instrument_id", "missing_column"],
    )

    assert loaded.columns == ["snapshot_date", "instrument_id"]
    assert loaded.height == 2


def test_asset_snapshot_write_fills_optional_storage_columns(tmp_path: Path) -> None:
    """Asset snapshot writes should backfill optional schema columns for minimal rows."""
    base_dir = tmp_path / "assets" / "snapshots"
    df = pl.DataFrame(
        {
            "snapshot_date": ["2026-02-20"],
            "account_id": ["acc_kb"],
            "instrument_id": ["ins_aapl"],
            "quantity": [10.0],
            "market_value": [1_500_000.0],
        }
    )

    write_asset_snapshot_month(base_dir, df, 2026, 2)

    loaded = read_asset_snapshot_month(base_dir, 2026, 2)
    row = loaded.row(0, named=True)
    assert row["currency"] == "KRW"
    assert row["file_id"] is None
    assert row["source_row"] is None


def test_asset_snapshot_append_empty_batch_is_noop(tmp_path: Path) -> None:
    """Appending an empty asset batch should report no writes and create no partitions."""
    base_dir = tmp_path / "assets" / "snapshots"

    result = append_asset_snapshots(base_dir, pl.DataFrame())

    assert result == {
        "total_rows": 0,
        "partitions_updated": 0,
        "rows_inserted": 0,
        "rows_skipped": 0,
    }
    assert not base_dir.exists()


def test_asset_snapshot_append_requires_snapshot_date(tmp_path: Path) -> None:
    """Asset snapshot append should reject batches that cannot be month-partitioned."""
    base_dir = tmp_path / "assets" / "snapshots"
    df = pl.DataFrame({"account_id": ["acc_kb"], "instrument_id": ["ins_aapl"]})

    with pytest.raises(ValueError, match="snapshot_date"):
        append_asset_snapshots(base_dir, df)


def test_asset_snapshot_append_daily_dedup(tmp_path: Path) -> None:
    """Append removes duplicates by daily key (date + account + instrument)."""
    # Arrange
    base_dir = tmp_path / "assets" / "snapshots"
    batch1 = pl.DataFrame(
        {
            "snapshot_date": ["2026-02-20", "2026-02-20", "2026-02-20"],
            "account_id": ["acc_kb", "acc_kb", "acc_kb"],
            "instrument_id": ["ins_aapl", "ins_aapl", "ins_msft"],
            "quantity": [10.0, 10.0, 5.0],
            "market_value": [1_500_000.0, 1_500_000.0, 900_000.0],
            "currency": ["KRW", "KRW", "KRW"],
            "file_id": ["260220_1", "260220_1", "260220_1"],
            "source_row": [2, 3, 4],
        }
    )
    batch2 = pl.DataFrame(
        {
            "snapshot_date": ["2026-02-20", "2026-02-20"],
            "account_id": ["acc_kb", "acc_kb"],
            "instrument_id": ["ins_aapl", "ins_nvda"],
            "quantity": [10.0, 8.0],
            "market_value": [1_500_000.0, 2_000_000.0],
            "currency": ["KRW", "KRW"],
            "file_id": ["260220_2", "260220_2"],
            "source_row": [2, 3],
        }
    )

    # Act
    result1 = append_asset_snapshots(base_dir, batch1, deduplicate=True)
    result2 = append_asset_snapshots(base_dir, batch2, deduplicate=True)
    loaded = read_asset_snapshot_month(base_dir, 2026, 2)

    # Assert
    assert result1["rows_inserted"] == 2
    assert result1["rows_skipped"] == 1
    assert result2["rows_inserted"] == 1
    assert result2["rows_skipped"] == 1
    assert loaded.height == 3


def test_asset_snapshot_idempot_reingest_same_file_content(tmp_path: Path) -> None:
    """Re-ingesting identical daily snapshots keeps identical file result."""
    # Arrange
    base_dir = tmp_path / "assets" / "snapshots"
    df = _sample_asset_df()

    # Act
    result1 = append_asset_snapshots(base_dir, df, deduplicate=True)
    partition_path = get_asset_snapshot_partition_path(base_dir, 2026, 2)
    content_after_first = partition_path.read_text(encoding="utf-8")

    result2 = append_asset_snapshots(base_dir, df, deduplicate=True)
    content_after_second = partition_path.read_text(encoding="utf-8")

    # Assert
    assert result1["rows_inserted"] == 2
    assert result2["rows_inserted"] == 0
    assert result2["rows_skipped"] == 2
    assert content_after_first == content_after_second
