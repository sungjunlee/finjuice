"""
Unit tests for CSV partition storage layer.

Tests cover:
- Partition path generation
- Single month read/write
- Multi-month date range reads
- Append with deduplication
- Upsert operations
- Atomic writes (tmp file handling)
- JSON array serialization
- Edge cases (empty partitions, missing dates)
"""

import polars as pl
import pytest

from finjuice.pipeline.storage import csv_transactions
from finjuice.pipeline.storage.csv_partition import (
    CSV_COLUMNS,
    append_transactions,
    find_transaction_by_hash,
    get_all_transactions,
    get_partition_path,
    read_month,
    read_range,
    upsert_transaction,
    write_month,
)


@pytest.fixture
def temp_storage_dir(tmp_path):
    """Temporary directory for CSV partitions."""
    storage_dir = tmp_path / "transactions"
    storage_dir.mkdir(parents=True, exist_ok=True)
    return storage_dir


@pytest.fixture
def sample_transactions():
    """Sample transaction data for testing (v4 writer fills additive defaults)."""
    return pl.DataFrame(
        [
            {
                "row_hash": "hash001",
                "date": "2024-10-15",
                "time": "14:30",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "식비",
                "minor_raw": "카페",
                "merchant_raw": "스타벅스 강남점",
                "memo_raw": "아메리카노",
                "amount": -4500.0,
                "account": "신한카드",
                "currency": "KRW",
                "counterparty": "스타벅스",
                "datetime": "2024-10-15T14:30:00",
                "category_rule": None,
                "category_final": "카페",  # Derived from minor_raw
                "tags_rule": ["카페", "커피"],
                "tags_ai": [],
                "tags_manual": [],
                "tags_final": ["카페", "커피"],
                "confidence": 0.95,
                "needs_review": 0,
                "is_transfer": 0,
                "transfer_group_id": "",
                "file_id": "241020_1",
                "source_row": 5,
            },
            {
                "row_hash": "hash002",
                "date": "2024-10-27",
                "time": "19:24",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "생활",
                "minor_raw": "보험",
                "merchant_raw": "METLIFE",
                "memo_raw": "건강보험",
                "amount": -150000.0,
                "account": "우리카드",
                "currency": "KRW",
                "counterparty": "메트라이프",
                "datetime": "2024-10-27T19:24:00",
                "category_rule": None,
                "category_final": "보험",  # Derived from minor_raw
                "tags_rule": ["보험", "정기지출"],
                "tags_ai": [],
                "tags_manual": [],
                "tags_final": ["보험", "정기지출"],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 0,
                "transfer_group_id": "",
                "file_id": "241020_1",
                "source_row": 12,
            },
        ]
    )


class TestPartitionPath:
    """Test partition path generation."""

    def test_get_partition_path_basic(self, temp_storage_dir):
        # Arrange & Act
        path = get_partition_path(temp_storage_dir, 2024, 10)

        # Assert
        expected = temp_storage_dir / "2024" / "10" / "transactions.csv"
        assert path == expected

    def test_get_partition_path_zero_padded_month(self, temp_storage_dir):
        # Arrange & Act
        path = get_partition_path(temp_storage_dir, 2024, 1)

        # Assert
        assert path.parts[-2] == "01"  # Month should be zero-padded


class TestReadMonth:
    """Test reading single month partition."""

    def test_read_month_docstring_matches_current_collection_contract(self):
        """read_month docs should not promise projection pushdown it does not provide."""
        doc = csv_transactions.read_month.__doc__

        assert doc is not None
        assert "collects the partition into a DataFrame" in doc
        assert "projection pushdown" not in doc.lower()
        assert "only loads requested columns" not in doc.lower()

    def test_read_month_existing_partition(self, temp_storage_dir, sample_transactions):
        # Arrange
        write_month(temp_storage_dir, sample_transactions, 2024, 10)

        # Act
        df = read_month(temp_storage_dir, 2024, 10)

        # Assert
        assert len(df) == 2
        row = df.row(0, named=True)
        assert row["row_hash"] == "hash001"
        assert row["merchant_raw"] == "스타벅스 강남점"
        assert isinstance(row["tags_rule"], list)
        assert row["tags_rule"] == ["카페", "커피"]

    def test_read_month_backfills_notes_manual_for_v3_partition(self, temp_storage_dir):
        """v3 partitions without notes_manual should remain readable under v4."""
        legacy_columns = [column for column in CSV_COLUMNS if column != "notes_manual"]
        legacy_values = {
            "row_hash": "legacyv3hash0001",
            "date": "2024-10-15",
            "time": "14:30",
            "type_raw": "지출",
            "type_norm": "expense",
            "major_raw": "식비",
            "minor_raw": "카페",
            "merchant_raw": "스타벅스",
            "memo_raw": "",
            "amount": "-4500.0",
            "account": "신한카드",
            "currency": "KRW",
            "counterparty": "",
            "datetime": "2024-10-15T14:30:00",
            "category_rule": "",
            "category_final": "카페",
            "tags_rule": "[]",
            "tags_ai": "[]",
            "tags_manual": "[]",
            "tags_final": "[]",
            "confidence": "0.0",
            "needs_review": "1",
            "is_transfer_candidate": "0",
            "is_transfer": "0",
            "transfer_group_id": "",
            "file_id": "241015_1",
            "source_row": "1",
        }
        partition_path = get_partition_path(temp_storage_dir, 2024, 10)
        partition_path.parent.mkdir(parents=True)
        partition_path.write_text(
            ",".join(legacy_columns)
            + "\n"
            + ",".join(legacy_values[column] for column in legacy_columns)
            + "\n",
            encoding="utf-8",
        )

        df_read = read_month(temp_storage_dir, 2024, 10)

        assert "notes_manual" in df_read.columns
        assert df_read.row(0, named=True)["notes_manual"] == ""

    def test_read_month_nonexistent_partition(self, temp_storage_dir):
        # Act
        df = read_month(temp_storage_dir, 2024, 12)

        # Assert
        assert len(df) == 0
        assert "row_hash" in df.columns  # Schema preserved

    def test_read_month_with_column_filter(self, temp_storage_dir, sample_transactions):
        # Arrange
        write_month(temp_storage_dir, sample_transactions, 2024, 10)

        # Act
        df = read_month(temp_storage_dir, 2024, 10, columns=["row_hash", "merchant_raw", "amount"])

        # Assert
        assert len(df) == 2
        assert df.columns == ["row_hash", "merchant_raw", "amount"]

    def test_read_month_derives_midnight_datetime_when_time_column_is_absent(
        self, temp_storage_dir
    ):
        """Legacy partitions without time/datetime should still expose a sortable datetime."""
        partition_path = get_partition_path(temp_storage_dir, 2024, 10)
        partition_path.parent.mkdir(parents=True)
        partition_path.write_text(
            "\n".join(
                [
                    "row_hash,date,merchant_raw,tags_rule,tags_ai,tags_manual,tags_final",
                    "hash_no_time,2024-10-15,Legacy Row,[],[],[],[]",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        df = read_month(temp_storage_dir, 2024, 10)

        assert df.row(0, named=True)["datetime"] == "2024-10-15T00:00:00"


class TestReadRange:
    """Test reading multi-month date range."""

    def test_read_range_docstring_matches_current_eager_filter_contract(self):
        """read_range docs should describe eager per-partition reads before filtering."""
        doc = csv_transactions.read_range.__doc__

        assert doc is not None
        assert "reads each monthly partition eagerly" in doc
        assert "Filter pushdown" not in doc
        assert "streaming mode" not in doc.lower()

    def test_read_range_single_month(self, temp_storage_dir, sample_transactions):
        # Arrange
        write_month(temp_storage_dir, sample_transactions, 2024, 10)

        # Act
        df = read_range(temp_storage_dir, "2024-10-01", "2024-10-31")

        # Assert
        assert len(df) == 2
        assert df.row(0, named=True)["date"] == "2024-10-15"

    def test_read_range_across_months(self, temp_storage_dir):
        # Arrange
        oct_txs = pl.DataFrame(
            [
                {
                    "row_hash": "hash_oct",
                    "date": "2024-10-27",
                    "time": "10:00",
                    "type_norm": "expense",
                    "merchant_raw": "Test Oct",
                    "amount": -10000.0,
                    "datetime": "2024-10-27T10:00:00",
                    "tags_rule": [],
                    "tags_ai": [],
                    "tags_manual": [],
                    "tags_final": [],
                }
            ]
        )
        nov_txs = pl.DataFrame(
            [
                {
                    "row_hash": "hash_nov",
                    "date": "2024-11-05",
                    "time": "11:00",
                    "type_norm": "expense",
                    "merchant_raw": "Test Nov",
                    "amount": -20000.0,
                    "datetime": "2024-11-05T11:00:00",
                    "tags_rule": [],
                    "tags_ai": [],
                    "tags_manual": [],
                    "tags_final": [],
                }
            ]
        )

        write_month(temp_storage_dir, oct_txs, 2024, 10)
        write_month(temp_storage_dir, nov_txs, 2024, 11)

        # Act
        df = read_range(temp_storage_dir, "2024-10-20", "2024-11-10")

        # Assert
        assert len(df) == 2
        assert df.row(0, named=True)["merchant_raw"] == "Test Oct"
        assert df.row(1, named=True)["merchant_raw"] == "Test Nov"

    def test_read_range_derives_datetime_for_legacy_partition_without_time(self, temp_storage_dir):
        """Date-range reads should normalize legacy partitions before sorting."""
        partition_path = get_partition_path(temp_storage_dir, 2024, 10)
        partition_path.parent.mkdir(parents=True)
        partition_path.write_text(
            "\n".join(
                [
                    "row_hash,date,merchant_raw,tags_rule,tags_ai,tags_manual,tags_final",
                    "hash_no_time,2024-10-15,Legacy Row,[],[],[],[]",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        df = read_range(temp_storage_dir, "2024-10-01", "2024-10-31")

        assert df.row(0, named=True)["datetime"] == "2024-10-15T00:00:00"

    def test_read_range_derives_datetime_from_date_and_time_when_datetime_is_absent(
        self, temp_storage_dir
    ):
        """Date-range reads should rebuild datetime for legacy partitions with time."""
        partition_path = get_partition_path(temp_storage_dir, 2024, 10)
        partition_path.parent.mkdir(parents=True)
        partition_path.write_text(
            "\n".join(
                [
                    "row_hash,date,time,merchant_raw,tags_rule,tags_ai,tags_manual,tags_final",
                    "hash_with_time,2024-10-15,09:30,Legacy Row,[],[],[],[]",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        df = read_range(temp_storage_dir, "2024-10-01", "2024-10-31")

        assert df.row(0, named=True)["datetime"] == "2024-10-15T09:30"

    def test_read_range_partial_month(self, temp_storage_dir, sample_transactions):
        # Arrange
        write_month(temp_storage_dir, sample_transactions, 2024, 10)

        # Act
        df = read_range(temp_storage_dir, "2024-10-20", "2024-10-31")

        # Assert
        assert len(df) == 1  # Only hash002 (2024-10-27)
        assert df.row(0, named=True)["row_hash"] == "hash002"

    def test_read_range_no_data(self, temp_storage_dir):
        # Act
        df = read_range(temp_storage_dir, "2024-01-01", "2024-01-31")

        # Assert
        assert len(df) == 0


class TestWriteMonth:
    """Test writing monthly partition."""

    def test_write_month_creates_directory(self, temp_storage_dir, sample_transactions):
        # Act
        result = write_month(temp_storage_dir, sample_transactions, 2024, 10)

        # Assert
        partition_path = get_partition_path(temp_storage_dir, 2024, 10)
        assert partition_path.exists()
        assert result["row_count"] == 2
        assert result["file_size_bytes"] > 0

    def test_write_month_sorts_by_datetime(self, temp_storage_dir):
        # Arrange - Unsorted data
        unsorted_df = pl.DataFrame(
            [
                {
                    "row_hash": "hash_late",
                    "date": "2024-10-27",
                    "datetime": "2024-10-27T19:24:00",
                    "merchant_raw": "Late",
                    "tags_rule": [],
                    "tags_ai": [],
                    "tags_manual": [],
                    "tags_final": [],
                },
                {
                    "row_hash": "hash_early",
                    "date": "2024-10-15",
                    "datetime": "2024-10-15T14:30:00",
                    "merchant_raw": "Early",
                    "tags_rule": [],
                    "tags_ai": [],
                    "tags_manual": [],
                    "tags_final": [],
                },
            ]
        )

        # Act
        write_month(temp_storage_dir, unsorted_df, 2024, 10)
        df_read = read_month(temp_storage_dir, 2024, 10)

        # Assert - Should be sorted by datetime
        assert df_read.row(0, named=True)["merchant_raw"] == "Early"
        assert df_read.row(1, named=True)["merchant_raw"] == "Late"

    def test_write_month_atomic_operation(self, temp_storage_dir, sample_transactions):
        # Arrange
        partition_path = get_partition_path(temp_storage_dir, 2024, 10)
        tmp_path = partition_path.with_suffix(".tmp")

        # Act
        write_month(temp_storage_dir, sample_transactions, 2024, 10)

        # Assert - Temp file should be removed
        assert partition_path.exists()
        assert not tmp_path.exists()

    def test_write_month_empty_dataframe_writes_schema_header(self, temp_storage_dir):
        """Writing an empty DataFrame should still create a schema-compatible partition."""
        result = write_month(temp_storage_dir, pl.DataFrame(), 2024, 10)

        partition_path = get_partition_path(temp_storage_dir, 2024, 10)
        header = partition_path.read_text(encoding="utf-8").splitlines()[0]
        assert result["row_count"] == 0
        assert header.split(",") == CSV_COLUMNS

    def test_write_month_json_array_serialization(self, temp_storage_dir, sample_transactions):
        # Act
        write_month(temp_storage_dir, sample_transactions, 2024, 10)

        # Assert - Read back and verify JSON arrays are preserved
        df_read = read_month(temp_storage_dir, 2024, 10)
        row = df_read.row(0, named=True)
        assert row["tags_rule"] == ["카페", "커피"]
        assert row["tags_final"] == ["카페", "커피"]

    def test_write_month_serializes_empty_preencoded_and_scalar_tags(self, temp_storage_dir):
        """Tag columns should be normalized to JSON strings before CSV persistence."""
        tx_df = pl.DataFrame(
            [
                {
                    "row_hash": "hash_tag_shapes",
                    "date": "2024-10-15",
                    "datetime": "2024-10-15T10:00:00",
                    "merchant_raw": "Tag Shapes",
                    "tags_rule": "",
                    "tags_ai": "",
                    "tags_manual": '["manual"]',
                    "tags_final": 7,
                }
            ]
        )

        write_month(temp_storage_dir, tx_df, 2024, 10)

        raw = pl.read_csv(get_partition_path(temp_storage_dir, 2024, 10), infer_schema=False)
        row = raw.row(0, named=True)
        assert row["tags_rule"] == "[]"
        assert row["tags_ai"] == "[]"
        assert row["tags_manual"] == '["manual"]'
        assert row["tags_final"] == "[7]"

    def test_write_month_fills_null_is_transfer_only(self, temp_storage_dir):
        # Arrange
        df = pl.DataFrame(
            [
                {
                    "row_hash": "hash_null_transfer",
                    "date": "2024-10-15",
                    "time": "10:00",
                    "datetime": "2024-10-15T10:00:00",
                    "merchant_raw": "Legacy Row",
                    "type_norm": "expense",
                    "amount": -1000.0,
                    "currency": "KRW",
                    "needs_review": None,
                    "is_transfer": None,
                    "source_row": 7,
                    "tags_rule": [],
                    "tags_ai": [],
                    "tags_manual": [],
                    "tags_final": [],
                }
            ]
        )

        # Act
        write_month(temp_storage_dir, df, 2024, 10)
        df_read = read_month(temp_storage_dir, 2024, 10)

        # Assert
        row = df_read.row(0, named=True)
        assert row["is_transfer"] == 0
        assert row["needs_review"] is None
        assert row["source_row"] == 7

    def test_write_month_backfills_v3_category_columns_for_legacy_rows(self, temp_storage_dir):
        # Arrange - v2-style rows can reach write_month through refresh transfer detection.
        df = pl.DataFrame(
            [
                {
                    "row_hash": "hash_minor",
                    "date": "2024-10-15",
                    "time": "10:00",
                    "type_norm": "expense",
                    "major_raw": "식비",
                    "minor_raw": "카페",
                    "merchant_raw": "Legacy Cafe",
                    "amount": -5000.0,
                    "currency": "KRW",
                    "datetime": "2024-10-15T10:00:00",
                    "needs_review": 0,
                    "is_transfer": 0,
                    "tags_rule": [],
                    "tags_ai": [],
                    "tags_manual": [],
                    "tags_final": [],
                },
                {
                    "row_hash": "hash_default",
                    "date": "2024-10-16",
                    "time": "11:00",
                    "type_norm": "expense",
                    "major_raw": None,
                    "minor_raw": None,
                    "merchant_raw": "Legacy Unknown",
                    "amount": -100.0,
                    "currency": "KRW",
                    "datetime": "2024-10-16T11:00:00",
                    "needs_review": 0,
                    "is_transfer": 0,
                    "tags_rule": [],
                    "tags_ai": [],
                    "tags_manual": [],
                    "tags_final": [],
                },
            ]
        )

        # Act
        write_month(temp_storage_dir, df, 2024, 10)
        df_read = read_month(temp_storage_dir, 2024, 10)

        # Assert
        assert df_read.columns == CSV_COLUMNS
        by_hash = {row["row_hash"]: row for row in df_read.to_dicts()}
        assert by_hash["hash_minor"]["category_rule"] is None
        assert by_hash["hash_minor"]["category_final"] == "카페"
        assert by_hash["hash_default"]["category_rule"] is None
        assert by_hash["hash_default"]["category_final"] == "미분류"


class TestAppendTransactions:
    """Test appending transactions to partitions."""

    def test_append_to_empty_partition(self, temp_storage_dir, sample_transactions):
        # Act
        result = append_transactions(temp_storage_dir, sample_transactions)

        # Assert
        assert result["total_rows"] == 2
        assert result["partitions_updated"] == 1
        assert result["rows_inserted"] == 2
        assert result["rows_skipped"] == 0

        df = read_month(temp_storage_dir, 2024, 10)
        assert len(df) == 2

    def test_append_with_deduplication(self, temp_storage_dir, sample_transactions):
        # Arrange - Write initial data
        append_transactions(temp_storage_dir, sample_transactions)

        # Act - Try to append same data again
        result = append_transactions(temp_storage_dir, sample_transactions, deduplicate=True)

        # Assert - Should skip duplicates
        assert result["rows_skipped"] == 2
        assert result["rows_inserted"] == 0

        df = read_month(temp_storage_dir, 2024, 10)
        assert len(df) == 2  # Still only 2 rows

    def test_append_without_deduplication(self, temp_storage_dir, sample_transactions):
        # Arrange
        append_transactions(temp_storage_dir, sample_transactions)

        # Act
        result = append_transactions(temp_storage_dir, sample_transactions, deduplicate=False)

        # Assert - Should insert duplicates
        assert result["rows_inserted"] == 2

        df = read_month(temp_storage_dir, 2024, 10)
        assert len(df) == 4  # Duplicates allowed

    def test_append_deduplicates_within_batch(self, temp_storage_dir):
        """Test that duplicate row_hashes within the same batch are deduplicated.

        This tests the fix for Issue where same XLSX file may contain
        duplicate transactions with identical row_hash values.
        """
        # Arrange - DataFrame with duplicate row_hash within same batch
        df_with_dupes = pl.DataFrame(
            [
                {
                    "row_hash": "hash_dupe",
                    "date": "2024-10-15",
                    "time": "10:00",
                    "datetime": "2024-10-15T10:00:00",
                    "merchant_raw": "First",
                    "type_norm": "expense",
                    "amount": -10000.0,
                    "currency": "KRW",
                    "needs_review": 0,
                    "is_transfer": 0,
                    "tags_rule": [],
                    "tags_ai": [],
                    "tags_manual": [],
                    "tags_final": [],
                },
                {
                    "row_hash": "hash_dupe",  # Same row_hash - duplicate!
                    "date": "2024-10-15",
                    "time": "10:00",
                    "datetime": "2024-10-15T10:00:00",
                    "merchant_raw": "Second",  # Different merchant to verify first wins
                    "type_norm": "expense",
                    "amount": -20000.0,
                    "currency": "KRW",
                    "needs_review": 0,
                    "is_transfer": 0,
                    "tags_rule": [],
                    "tags_ai": [],
                    "tags_manual": [],
                    "tags_final": [],
                },
                {
                    "row_hash": "hash_unique",
                    "date": "2024-10-15",
                    "time": "11:00",
                    "datetime": "2024-10-15T11:00:00",
                    "merchant_raw": "Third",
                    "type_norm": "expense",
                    "amount": -30000.0,
                    "currency": "KRW",
                    "needs_review": 0,
                    "is_transfer": 0,
                    "tags_rule": [],
                    "tags_ai": [],
                    "tags_manual": [],
                    "tags_final": [],
                },
            ]
        )

        # Act
        result = append_transactions(temp_storage_dir, df_with_dupes, deduplicate=True)

        # Assert - Should have 2 unique rows, 1 skipped within-batch duplicate
        assert result["rows_inserted"] == 2
        assert result["rows_skipped"] == 1

        df = read_month(temp_storage_dir, 2024, 10)
        assert len(df) == 2

        # Verify first occurrence wins (merchant_raw = "First")
        dupe_row = df.filter(pl.col("row_hash") == "hash_dupe")
        assert dupe_row.row(0, named=True)["merchant_raw"] == "First"

    def test_append_across_multiple_months(self, temp_storage_dir):
        # Arrange - Transactions in different months with all required columns
        multi_month_df = pl.DataFrame(
            [
                {
                    "row_hash": "hash_sep",
                    "date": "2024-09-15",
                    "time": "10:00",
                    "datetime": "2024-09-15T10:00:00",
                    "merchant_raw": "Sep",
                    "type_norm": "expense",
                    "amount": -10000.0,
                    "currency": "KRW",
                    "needs_review": 0,
                    "is_transfer": 0,
                    "tags_rule": [],
                    "tags_ai": [],
                    "tags_manual": [],
                    "tags_final": [],
                },
                {
                    "row_hash": "hash_oct",
                    "date": "2024-10-20",
                    "time": "11:00",
                    "datetime": "2024-10-20T11:00:00",
                    "merchant_raw": "Oct",
                    "type_norm": "expense",
                    "amount": -20000.0,
                    "currency": "KRW",
                    "needs_review": 0,
                    "is_transfer": 0,
                    "tags_rule": [],
                    "tags_ai": [],
                    "tags_manual": [],
                    "tags_final": [],
                },
                {
                    "row_hash": "hash_nov",
                    "date": "2024-11-05",
                    "time": "12:00",
                    "datetime": "2024-11-05T12:00:00",
                    "merchant_raw": "Nov",
                    "type_norm": "expense",
                    "amount": -30000.0,
                    "currency": "KRW",
                    "needs_review": 0,
                    "is_transfer": 0,
                    "tags_rule": [],
                    "tags_ai": [],
                    "tags_manual": [],
                    "tags_final": [],
                },
            ]
        )

        # Act
        result = append_transactions(temp_storage_dir, multi_month_df)

        # Assert
        assert result["partitions_updated"] == 3
        assert result["rows_inserted"] == 3

        assert len(read_month(temp_storage_dir, 2024, 9)) == 1
        assert len(read_month(temp_storage_dir, 2024, 10)) == 1
        assert len(read_month(temp_storage_dir, 2024, 11)) == 1

    def test_append_empty_dataframe(self, temp_storage_dir):
        # Act
        result = append_transactions(temp_storage_dir, pl.DataFrame())

        # Assert
        assert result["total_rows"] == 0
        assert result["partitions_updated"] == 0

    def test_append_missing_date_column(self, temp_storage_dir):
        # Arrange - DataFrame without 'date' column
        invalid_df = pl.DataFrame([{"row_hash": "hash001", "merchant_raw": "Test"}])

        # Act & Assert
        with pytest.raises(ValueError, match="must have 'date' column"):
            append_transactions(temp_storage_dir, invalid_df)

    def test_append_backfills_v3_category_columns_for_legacy_rows(self, temp_storage_dir):
        """Should backfill category_rule/category_final for v2-style rows."""
        # Arrange - v2-style rows without category columns
        legacy_df = pl.DataFrame(
            [
                {
                    "row_hash": "hash_minor",
                    "date": "2024-10-15",
                    "time": "10:00",
                    "type_norm": "expense",
                    "major_raw": "식비",
                    "minor_raw": "카페",
                    "merchant_raw": "Cafe",
                    "amount": -5000.0,
                    "currency": "KRW",
                    "datetime": "2024-10-15T10:00:00",
                    "needs_review": 0,
                    "is_transfer": 0,
                    "tags_rule": [],
                    "tags_ai": [],
                    "tags_manual": [],
                    "tags_final": [],
                },
                {
                    "row_hash": "hash_major",
                    "date": "2024-10-16",
                    "time": "11:00",
                    "type_norm": "expense",
                    "major_raw": "교통",
                    "minor_raw": None,
                    "merchant_raw": "Bus",
                    "amount": -1300.0,
                    "currency": "KRW",
                    "datetime": "2024-10-16T11:00:00",
                    "needs_review": 0,
                    "is_transfer": 0,
                    "tags_rule": [],
                    "tags_ai": [],
                    "tags_manual": [],
                    "tags_final": [],
                },
                {
                    "row_hash": "hash_rule",
                    "date": "2024-10-16",
                    "time": "11:30",
                    "type_norm": "expense",
                    "major_raw": "식비",
                    "minor_raw": "카페",
                    "merchant_raw": "Rule Cafe",
                    "amount": -7000.0,
                    "currency": "KRW",
                    "datetime": "2024-10-16T11:30:00",
                    "category_rule": "규칙카테고리",
                    "needs_review": 0,
                    "is_transfer": 0,
                    "tags_rule": [],
                    "tags_ai": [],
                    "tags_manual": [],
                    "tags_final": [],
                },
                {
                    "row_hash": "hash_blank_rule",
                    "date": "2024-10-16",
                    "time": "11:40",
                    "type_norm": "expense",
                    "major_raw": "식비",
                    "minor_raw": "분식",
                    "merchant_raw": "Blank Rule",
                    "amount": -3000.0,
                    "currency": "KRW",
                    "datetime": "2024-10-16T11:40:00",
                    "category_rule": "   ",
                    "needs_review": 0,
                    "is_transfer": 0,
                    "tags_rule": [],
                    "tags_ai": [],
                    "tags_manual": [],
                    "tags_final": [],
                },
                {
                    "row_hash": "hash_default",
                    "date": "2024-10-17",
                    "time": "12:00",
                    "type_norm": "expense",
                    "major_raw": None,
                    "minor_raw": None,
                    "merchant_raw": "Unknown",
                    "amount": -100.0,
                    "currency": "KRW",
                    "datetime": "2024-10-17T12:00:00",
                    "needs_review": 0,
                    "is_transfer": 0,
                    "tags_rule": [],
                    "tags_ai": [],
                    "tags_manual": [],
                    "tags_final": [],
                },
            ]
        )

        # Act
        append_transactions(temp_storage_dir, legacy_df)
        result_df = read_month(temp_storage_dir, 2024, 10)

        # Assert
        assert "category_rule" in result_df.columns
        assert "category_final" in result_df.columns
        assert result_df.columns == CSV_COLUMNS

        by_hash = {row["row_hash"]: row for row in result_df.to_dicts()}
        assert by_hash["hash_minor"]["category_rule"] is None
        assert by_hash["hash_minor"]["category_final"] == "카페"
        assert by_hash["hash_major"]["category_final"] == "교통"
        assert by_hash["hash_rule"]["category_rule"] == "규칙카테고리"
        assert by_hash["hash_rule"]["category_final"] == "규칙카테고리"
        assert by_hash["hash_blank_rule"]["category_rule"] is None
        assert by_hash["hash_blank_rule"]["category_final"] == "분식"
        assert by_hash["hash_default"]["category_final"] == "미분류"

    def test_append_preserves_existing_v3_category_values(self, temp_storage_dir):
        """Should keep existing v3 category values when category columns already exist."""
        # Arrange
        v3_df = pl.DataFrame(
            [
                {
                    "row_hash": "hash_v3",
                    "date": "2024-10-18",
                    "time": "13:00",
                    "type_norm": "expense",
                    "major_raw": "생활",
                    "minor_raw": "보험",
                    "merchant_raw": "METLIFE",
                    "amount": -150000.0,
                    "currency": "KRW",
                    "datetime": "2024-10-18T13:00:00",
                    "category_rule": "보험료",
                    "category_final": "보험료",
                    "needs_review": 0,
                    "is_transfer": 0,
                    "tags_rule": [],
                    "tags_ai": [],
                    "tags_manual": [],
                    "tags_final": [],
                }
            ]
        )

        # Act
        append_transactions(temp_storage_dir, v3_df)
        result_df = read_month(temp_storage_dir, 2024, 10)

        # Assert
        row = result_df.filter(pl.col("row_hash") == "hash_v3").row(0, named=True)
        assert row["category_rule"] == "보험료"
        assert row["category_final"] == "보험료"
        assert len(CSV_COLUMNS) == 28


class TestUpsertTransaction:
    """Test upserting single transaction."""

    def test_upsert_insert_new(self, temp_storage_dir):
        # Arrange
        new_tx = {
            "row_hash": "hash_new",
            "date": "2024-10-15",
            "time": "10:00",
            "datetime": "2024-10-15T10:00:00",
            "merchant_raw": "New Merchant",
            "amount": -5000.0,
            "type_norm": "expense",
            "currency": "KRW",
            "needs_review": 0,
            "is_transfer": 0,
            "tags_rule": ["test"],
            "tags_ai": [],
            "tags_manual": [],
            "tags_final": ["test"],
        }

        # Act
        was_updated = upsert_transaction(temp_storage_dir, new_tx)

        # Assert
        assert not was_updated  # New insert
        df = read_month(temp_storage_dir, 2024, 10)
        assert len(df) == 1
        assert df.row(0, named=True)["row_hash"] == "hash_new"

    def test_upsert_update_existing(self, temp_storage_dir, sample_transactions):
        # Arrange
        append_transactions(temp_storage_dir, sample_transactions)

        # Read existing row to get all fields
        existing_df = read_month(temp_storage_dir, 2024, 10)
        existing_row = existing_df.filter(pl.col("row_hash") == "hash001").row(0, named=True)

        # Update specific fields - create a mutable dict
        existing_row = dict(existing_row)
        existing_row["merchant_raw"] = "Updated Merchant"
        existing_row["amount"] = -9999.0
        existing_row["tags_rule"] = ["updated"]
        existing_row["tags_final"] = ["updated"]

        # Act
        was_updated = upsert_transaction(temp_storage_dir, existing_row)

        # Assert
        assert was_updated
        df = read_month(temp_storage_dir, 2024, 10)
        assert len(df) == 2  # Still 2 rows
        updated_row = df.filter(pl.col("row_hash") == "hash001").row(0, named=True)
        assert updated_row["merchant_raw"] == "Updated Merchant"
        assert updated_row["amount"] == -9999.0

    def test_upsert_insert_into_existing_partition(self, temp_storage_dir, sample_transactions):
        """Inserting a new row into an existing month should preserve existing rows."""
        append_transactions(temp_storage_dir, sample_transactions)
        existing_df = read_month(temp_storage_dir, 2024, 10)
        new_tx = dict(existing_df.row(0, named=True))
        new_tx.update(
            {
                "row_hash": "hash003",
                "date": "2024-10-28",
                "time": "12:00",
                "datetime": "2024-10-28T12:00:00",
                "merchant_raw": "New Merchant",
                "amount": -12000.0,
                "tags_rule": ["new"],
                "tags_final": ["new"],
            }
        )

        was_updated = upsert_transaction(temp_storage_dir, new_tx)

        df = read_month(temp_storage_dir, 2024, 10)
        assert was_updated is False
        assert df.height == 3
        assert df.filter(pl.col("row_hash") == "hash003").height == 1

    def test_upsert_missing_date(self, temp_storage_dir):
        # Arrange
        invalid_tx = {"row_hash": "hash001", "merchant_raw": "Test"}

        # Act & Assert
        with pytest.raises(ValueError, match="must have 'date' field"):
            upsert_transaction(temp_storage_dir, invalid_tx)

    def test_upsert_missing_key_field(self, temp_storage_dir):
        # Arrange
        invalid_tx = {"date": "2024-10-15", "merchant_raw": "Test"}

        # Act & Assert
        with pytest.raises(ValueError, match="must have 'row_hash' field"):
            upsert_transaction(temp_storage_dir, invalid_tx)


class TestGetAllTransactions:
    """Test loading all transactions."""

    def test_get_all_single_partition(self, temp_storage_dir, sample_transactions):
        # Arrange
        write_month(temp_storage_dir, sample_transactions, 2024, 10)

        # Act
        df = get_all_transactions(temp_storage_dir)

        # Assert
        assert len(df) == 2
        assert df.row(0, named=True)["row_hash"] == "hash001"

    def test_get_all_multiple_partitions(self, temp_storage_dir):
        # Arrange
        for month in range(1, 4):  # Jan, Feb, Mar
            month_df = pl.DataFrame(
                [
                    {
                        "row_hash": f"hash_{month:02d}",
                        "date": f"2024-{month:02d}-15",
                        "datetime": f"2024-{month:02d}-15T10:00:00",
                        "merchant_raw": f"Month {month}",
                        "tags_rule": [],
                        "tags_ai": [],
                        "tags_manual": [],
                        "tags_final": [],
                    }
                ]
            )
            write_month(temp_storage_dir, month_df, 2024, month)

        # Act
        df = get_all_transactions(temp_storage_dir)

        # Assert
        assert len(df) == 3
        assert df.row(0, named=True)["merchant_raw"] == "Month 1"
        assert df.row(2, named=True)["merchant_raw"] == "Month 3"

    def test_get_all_empty_storage(self, temp_storage_dir):
        # Act
        df = get_all_transactions(temp_storage_dir)

        # Assert
        assert len(df) == 0
        assert "row_hash" in df.columns

    def test_get_all_with_column_filter(self, temp_storage_dir, sample_transactions):
        # Arrange
        write_month(temp_storage_dir, sample_transactions, 2024, 10)

        # Act
        df = get_all_transactions(temp_storage_dir, columns=["row_hash", "merchant_raw"])

        # Assert
        assert len(df) == 2
        assert df.columns == ["row_hash", "merchant_raw"]

    def test_get_all_projects_datetime_for_sort_when_projection_omits_datetime(
        self, temp_storage_dir, monkeypatch
    ):
        # Arrange
        month_df = pl.DataFrame(
            [
                {
                    "row_hash": "hash_late",
                    "date": "2024-10-16",
                    "time": "11:00",
                    "datetime": "2024-10-16T11:00:00",
                    "merchant_raw": "Late Merchant",
                    "tags_rule": [],
                    "tags_ai": [],
                    "tags_manual": [],
                    "tags_final": [],
                },
                {
                    "row_hash": "hash_early",
                    "date": "2024-10-15",
                    "time": "10:00",
                    "datetime": "2024-10-15T10:00:00",
                    "merchant_raw": "Early Merchant",
                    "tags_rule": [],
                    "tags_ai": [],
                    "tags_manual": [],
                    "tags_final": [],
                },
            ]
        )
        write_month(temp_storage_dir, month_df, 2024, 10, sort_by="row_hash")
        read_columns = []
        original_read_csv = csv_transactions.pl.read_csv

        def record_read_csv(*args, **kwargs):
            read_columns.append(kwargs.get("columns"))
            return original_read_csv(*args, **kwargs)

        monkeypatch.setattr(csv_transactions.pl, "read_csv", record_read_csv)

        # Act
        df = get_all_transactions(temp_storage_dir, columns=["row_hash", "merchant_raw"])

        # Assert
        assert read_columns == [["row_hash", "merchant_raw", "datetime"]]
        assert df.columns == ["row_hash", "merchant_raw"]
        assert df["row_hash"].to_list() == ["hash_early", "hash_late"]


class TestFindTransactionByHash:
    """Test locating transaction partitions by row hash."""

    def test_find_transaction_rejects_blank_hash(self, temp_storage_dir):
        """Blank row_hash lookup should fail before scanning storage."""
        with pytest.raises(ValueError, match="row_hash cannot be empty"):
            find_transaction_by_hash(temp_storage_dir, "   ")

    def test_find_transaction_rejects_missing_base_dir(self, tmp_path):
        """Missing transaction root should produce a file access error."""
        with pytest.raises(FileNotFoundError, match="Transactions directory not found"):
            find_transaction_by_hash(tmp_path / "missing", "hash001")


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_tags_arrays(self, temp_storage_dir):
        # Arrange - Transaction with empty tags
        tx_df = pl.DataFrame(
            [
                {
                    "row_hash": "hash_empty",
                    "date": "2024-10-15",
                    "datetime": "2024-10-15T10:00:00",
                    "merchant_raw": "Test",
                    "tags_rule": [],
                    "tags_ai": [],
                    "tags_manual": [],
                    "tags_final": [],
                }
            ]
        )

        # Act
        write_month(temp_storage_dir, tx_df, 2024, 10)
        df_read = read_month(temp_storage_dir, 2024, 10)

        # Assert
        row = df_read.row(0, named=True)
        assert row["tags_rule"] == []
        assert row["tags_final"] == []

    def test_none_values_in_optional_fields(self, temp_storage_dir):
        # Arrange
        tx_df = pl.DataFrame(
            [
                {
                    "row_hash": "hash_none",
                    "date": "2024-10-15",
                    "datetime": "2024-10-15T10:00:00",
                    "merchant_raw": "Test",
                    "memo_raw": None,
                    "counterparty": None,
                    "transfer_group_id": None,
                    "tags_rule": [],
                    "tags_ai": [],
                    "tags_manual": [],
                    "tags_final": [],
                }
            ]
        )

        # Act
        write_month(temp_storage_dir, tx_df, 2024, 10)
        df_read = read_month(temp_storage_dir, 2024, 10)

        # Assert - Should handle None values gracefully
        assert len(df_read) == 1

    def test_special_characters_in_merchant_name(self, temp_storage_dir):
        # Arrange - Merchant with quotes, commas, newlines
        tx_df = pl.DataFrame(
            [
                {
                    "row_hash": "hash_special",
                    "date": "2024-10-15",
                    "datetime": "2024-10-15T10:00:00",
                    "merchant_raw": 'Test "Quotes", Commas\nNewlines',
                    "tags_rule": [],
                    "tags_ai": [],
                    "tags_manual": [],
                    "tags_final": [],
                }
            ]
        )

        # Act
        write_month(temp_storage_dir, tx_df, 2024, 10)
        df_read = read_month(temp_storage_dir, 2024, 10)

        # Assert - CSV escaping should preserve special characters
        assert df_read.row(0, named=True)["merchant_raw"] == 'Test "Quotes", Commas\nNewlines'
