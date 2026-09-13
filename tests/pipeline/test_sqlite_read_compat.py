"""Unit tests for the SQLite read-compatibility adapter (#436).

The adapter projects authoritative repository rows into the legacy CSV
transaction frame contract so ``show``/``status``/``query``/``explain`` keep
their output contracts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from finjuice.pipeline.storage.csv_schema import CSV_COLUMNS
from finjuice.pipeline.storage.csv_transactions import get_all_transactions
from finjuice.pipeline.storage.sqlite import RepositoryReader
from finjuice.pipeline.storage.sqlite.read_compat import (
    GENERATION_ENV_VAR,
    SqliteReadSourceError,
    configured_transactions_frame,
    distinct_month_count,
    latest_month_label,
    read_month_frame,
    read_transactions_frame,
    resolve_generation_database,
)
from tests.sqlite_compat_data import build_generation, logical_rows, write_csv_mirror


@pytest.fixture
def mirrored_dataset(tmp_path: Path) -> dict[str, Path]:
    """Build the same logical dataset as CSV partitions and a SQLite generation."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    write_csv_mirror(data_dir)
    database = build_generation(tmp_path / "generation")
    return {"data_dir": data_dir, "database": database, "root": tmp_path}


def test_resolve_generation_database_unset_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without runtime configuration the read path stays on CSV partitions."""
    # Arrange
    monkeypatch.delenv(GENERATION_ENV_VAR, raising=False)

    # Act
    resolved = resolve_generation_database()

    # Assert
    assert resolved is None


def test_resolve_generation_database_missing_database_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured generation without a published database fails explicitly."""
    # Arrange
    monkeypatch.setenv(GENERATION_ENV_VAR, str(tmp_path / "absent-generation"))

    # Act / Assert
    with pytest.raises(SqliteReadSourceError):
        resolve_generation_database()


def test_resolve_generation_database_returns_published_database(
    mirrored_dataset: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured generation resolves to its published database file."""
    # Arrange
    monkeypatch.setenv(GENERATION_ENV_VAR, str(mirrored_dataset["database"].parent))

    # Act
    resolved = resolve_generation_database()

    # Assert
    assert resolved == mirrored_dataset["database"]


def test_configured_transactions_frame_unset_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without runtime configuration the query/explain path stays on CSV."""
    # Arrange
    monkeypatch.delenv(GENERATION_ENV_VAR, raising=False)

    # Act
    frame = configured_transactions_frame()

    # Assert
    assert frame is None


def test_configured_transactions_frame_returns_projected_rows(
    mirrored_dataset: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured generation returns the same projected frame as a direct read."""
    # Arrange
    monkeypatch.setenv(GENERATION_ENV_VAR, str(mirrored_dataset["database"].parent))

    # Act
    configured = configured_transactions_frame()
    direct = read_transactions_frame(mirrored_dataset["database"])

    # Assert
    assert configured is not None
    assert_frame_equal(configured, direct)


def test_frame_matches_csv_read_contract(mirrored_dataset: dict[str, Path]) -> None:
    """The projected SQLite frame equals the CSV read frame on the same data."""
    # Arrange
    csv_frame = get_all_transactions(mirrored_dataset["data_dir"] / "transactions")

    # Act
    sqlite_frame = read_transactions_frame(mirrored_dataset["database"])

    # Assert
    assert sqlite_frame.columns == CSV_COLUMNS
    assert_frame_equal(sqlite_frame, csv_frame)


def test_frame_preserves_manual_category_sentinel(mirrored_dataset: dict[str, Path]) -> None:
    """category_manual is re-encoded into the persisted tags_manual contract."""
    # Arrange / Act
    frame = read_transactions_frame(mirrored_dataset["database"])
    row = frame.filter(pl.col("row_hash") == "abc1234567890006").to_dicts()[0]

    # Assert
    assert row["tags_manual"] == ["__finjuice_category_override__:수동분류"]
    assert row["category_final"] == "수동분류"


def test_month_frame_and_month_helpers(mirrored_dataset: dict[str, Path]) -> None:
    """Month filtering and month aggregation helpers follow the frame contract."""
    # Arrange
    database = mirrored_dataset["database"]

    # Act
    october = read_month_frame(database, 2024, 10)
    frame = read_transactions_frame(database)

    # Assert
    assert len(october) == 4
    assert october["date"].str.slice(0, 7).unique().to_list() == ["2024-10"]
    assert latest_month_label(frame) == "2024-11"
    assert distinct_month_count(frame) == 2
    assert latest_month_label(read_month_frame(database, 2025, 1)) is None
    assert distinct_month_count(read_month_frame(database, 2025, 1)) == 0


def test_reads_are_idempotent_for_one_revision(mirrored_dataset: dict[str, Path]) -> None:
    """Re-reading the same revision is deterministic and leaves it unchanged."""
    # Arrange
    database = mirrored_dataset["database"]

    # Act
    first = read_transactions_frame(database)
    second = read_transactions_frame(database)
    with RepositoryReader(database) as reader_before, RepositoryReader(database) as reader_after:
        revision_before = reader_before.info.dataset_revision
        revision_after = reader_after.info.dataset_revision

    # Assert
    assert_frame_equal(first, second)
    assert revision_before == revision_after == 0


def test_frame_rows_match_logical_dataset(mirrored_dataset: dict[str, Path]) -> None:
    """Projected rows carry the logical values, including legacy coordinates."""
    # Arrange
    rows: list[dict[str, Any]] = logical_rows()

    # Act
    frame = read_transactions_frame(mirrored_dataset["database"])

    # Assert
    projected = {row["row_hash"]: row for row in frame.to_dicts()}
    assert set(projected) == {row["row_hash"] for row in rows}
    for expected in rows:
        actual = projected[expected["row_hash"]]
        assert actual["amount"] == pytest.approx(expected["amount"])
        assert actual["file_id"] == expected["file_id"]
        assert actual["source_row"] == expected["source_row"]
        assert actual["datetime"] == expected["datetime"]
