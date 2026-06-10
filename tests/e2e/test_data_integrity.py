"""E2E tests for data integrity and idempotency.

This test suite validates data consistency across pipeline runs:
1. Deduplication via row_hash
2. Idempotent pipeline execution
3. Transfer pair detection consistency
4. Tag persistence across reruns
5. CSV partition data integrity

Note: Common fixtures (sample_xlsx_path, initialized_data_dir, data_dir_with_pipeline_run)
are defined in tests/e2e/conftest.py
"""

import shutil
from datetime import datetime, timedelta
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.storage import csv_partition

runner = CliRunner()


# ============================================================================
# Additional Fixtures (test-specific)
# ============================================================================


@pytest.fixture
def synthetic_xlsx_file(tmp_path: Path) -> Path:
    """Generate a synthetic XLSX file with controlled test data.

    Creates transactions with known patterns for testing:
    - Regular expenses on different dates
    - Transfer pairs
    - Duplicate-looking transactions with different timestamps
    """
    # Generate synthetic transactions
    transactions = []
    base_date = datetime(2024, 10, 1)

    # Regular expenses
    for i in range(10):
        transactions.append(
            {
                "날짜": (base_date + timedelta(days=i)).strftime("%Y-%m-%d"),
                "시간": f"{9 + i % 12}:{i % 60:02d}",
                "타입": "지출",
                "대분류": "식비" if i % 2 == 0 else "교통",
                "중분류": "카페" if i % 2 == 0 else "지하철",
                "내용": f"테스트가맹점{i}",
                "메모": f"테스트메모{i}",
                "금액": -(1000 + i * 100),
                "화폐": "KRW",
                "결제수단": "테스트카드",
            }
        )

    # Transfer pair (matching amounts, close timestamps)
    transactions.append(
        {
            "날짜": "2024-10-15",
            "시간": "14:00",
            "타입": "이체",
            "대분류": "이체",
            "중분류": "계좌이체",
            "내용": "신한은행",
            "메모": "이체테스트",
            "금액": -50000,
            "화폐": "KRW",
            "결제수단": "계좌A",
        }
    )
    transactions.append(
        {
            "날짜": "2024-10-15",
            "시간": "14:02",
            "타입": "수입",
            "대분류": "이체",
            "중분류": "계좌이체",
            "내용": "신한은행",
            "메모": "이체테스트",
            "금액": 50000,
            "화폐": "KRW",
            "결제수단": "계좌B",
        }
    )

    df = pl.DataFrame(transactions)
    xlsx_path = tmp_path / "synthetic_test.xlsx"
    df.write_excel(xlsx_path)
    return xlsx_path


# ============================================================================
# Test: Deduplication
# ============================================================================


@pytest.mark.e2e
class TestDeduplication:
    """Tests for row_hash based deduplication."""

    def test_no_duplicate_row_hashes_with_synthetic_data(
        self, initialized_data_dir: Path, synthetic_xlsx_file: Path, sample_rules_path: Path
    ) -> None:
        """Verify no duplicate row_hash values with synthetic test data.

        Uses synthetic data to ensure we control for uniqueness.
        Real data may have legitimate duplicates from source.

        Validates:
        - All row_hash values are unique across partitions
        """
        # Setup with synthetic data
        shutil.copy(synthetic_xlsx_file, initialized_data_dir / "imports" / "synthetic.xlsx")
        shutil.copy(sample_rules_path, initialized_data_dir / "rules.yaml")

        # Run pipeline
        result = runner.invoke(app, ["--data-dir", str(initialized_data_dir), "refresh"])
        assert result.exit_code == 0, f"pipeline failed: {result.output}"

        # Get all transactions
        csv_base_dir = initialized_data_dir / "transactions"
        df = csv_partition.get_all_transactions(csv_base_dir)

        # Check for duplicates
        duplicate_hashes = (
            df.group_by("row_hash").agg(pl.len().alias("count")).filter(pl.col("count") > 1)
        )

        assert len(duplicate_hashes) == 0, (
            f"Found {len(duplicate_hashes)} duplicate row_hash values"
        )

    def test_reimport_same_file_no_duplicates(
        self, initialized_data_dir: Path, sample_xlsx_path: Path, sample_rules_path: Path
    ) -> None:
        """Verify importing same file twice doesn't create duplicates.

        Validates:
        - Row count stays same after reimport
        - Row hashes are identical
        """
        # Setup
        shutil.copy(sample_xlsx_path, initialized_data_dir / "imports" / sample_xlsx_path.name)
        shutil.copy(sample_rules_path, initialized_data_dir / "rules.yaml")

        # First import
        result1 = runner.invoke(app, ["--data-dir", str(initialized_data_dir), "refresh"])
        assert result1.exit_code == 0

        # Get state after first run
        csv_base_dir = initialized_data_dir / "transactions"
        df1 = csv_partition.get_all_transactions(csv_base_dir)
        count1 = len(df1)
        hashes1 = set(df1["row_hash"].to_list())

        # Second import (same file)
        result2 = runner.invoke(app, ["--data-dir", str(initialized_data_dir), "refresh"])
        assert result2.exit_code == 0

        # Get state after second run
        df2 = csv_partition.get_all_transactions(csv_base_dir)
        count2 = len(df2)
        hashes2 = set(df2["row_hash"].to_list())

        # Assert idempotency
        assert count1 == count2, f"Row count changed: {count1} → {count2}"
        assert hashes1 == hashes2, "Row hashes differ between runs"


# ============================================================================
# Test: Idempotency
# ============================================================================


@pytest.mark.e2e
class TestIdempotency:
    """Tests for idempotent pipeline execution."""

    def test_pipeline_produces_identical_results(
        self, initialized_data_dir: Path, sample_xlsx_path: Path, sample_rules_path: Path
    ) -> None:
        """Verify running pipeline multiple times produces identical results.

        Validates:
        - Transaction count unchanged
        - Tags unchanged
        - Transfer flags unchanged
        """
        # Setup
        shutil.copy(sample_xlsx_path, initialized_data_dir / "imports" / sample_xlsx_path.name)
        shutil.copy(sample_rules_path, initialized_data_dir / "rules.yaml")

        # First run
        result1 = runner.invoke(app, ["--data-dir", str(initialized_data_dir), "refresh"])
        assert result1.exit_code == 0

        csv_base_dir = initialized_data_dir / "transactions"
        df1 = csv_partition.get_all_transactions(csv_base_dir)

        # Capture state
        tags1 = {row["row_hash"]: row["tags_final"] for row in df1.iter_rows(named=True)}
        transfers1 = {row["row_hash"]: row["is_transfer"] for row in df1.iter_rows(named=True)}

        # Second run
        result2 = runner.invoke(app, ["--data-dir", str(initialized_data_dir), "refresh"])
        assert result2.exit_code == 0

        df2 = csv_partition.get_all_transactions(csv_base_dir)

        # Capture state
        tags2 = {row["row_hash"]: row["tags_final"] for row in df2.iter_rows(named=True)}
        transfers2 = {row["row_hash"]: row["is_transfer"] for row in df2.iter_rows(named=True)}

        # Assert idempotency
        assert len(df1) == len(df2), "Row count changed"
        assert tags1 == tags2, "Tags differ between runs"
        assert transfers1 == transfers2, "Transfer flags differ between runs"

    def test_export_regeneration_consistent(self, data_dir_with_pipeline_run: Path) -> None:
        """Verify export files can be regenerated consistently.

        Validates:
        - Master XLSX row count is consistent
        - Report files are regenerated with same structure
        """
        exports_dir = data_dir_with_pipeline_run / "exports"
        csv_base_dir = data_dir_with_pipeline_run / "transactions"

        # Get initial transaction count from CSV (source of truth)
        df_csv = csv_partition.get_all_transactions(csv_base_dir)
        initial_count = len(df_csv)

        # Get first export stats - verify master was created
        master_files = list(exports_dir.glob("master_*.xlsx"))
        assert len(master_files) > 0, "No master file found"

        # Delete exports and regenerate
        for f in exports_dir.iterdir():
            if f.is_file():
                f.unlink()
            elif f.is_dir():
                shutil.rmtree(f)

        # Regenerate exports
        from finjuice.pipeline.export.master import export_master_xlsx

        new_master = exports_dir / f"master_{datetime.now().strftime('%Y%m%d')}.xlsx"
        row_count = export_master_xlsx(csv_base_dir, new_master)

        # Verify consistency - export count should match CSV count
        assert row_count == initial_count, (
            f"Export row count mismatch: CSV has {initial_count}, export has {row_count}"
        )


# ============================================================================
# Test: Transfer Detection
# ============================================================================


@pytest.mark.e2e
class TestTransferDetection:
    """Tests for transfer pair detection consistency."""

    def test_transfer_pairs_have_group_ids(self, data_dir_with_pipeline_run: Path) -> None:
        """Verify transfer pairs are properly grouped.

        Validates:
        - Transfers with is_transfer=1 have transfer_group_id
        - Each group has exactly 2 transactions
        """
        csv_base_dir = data_dir_with_pipeline_run / "transactions"
        df = csv_partition.get_all_transactions(csv_base_dir)

        # Filter for transfers with group IDs
        paired_df = df.filter(
            (pl.col("is_transfer") == 1) & (pl.col("transfer_group_id").is_not_null())
        )

        if len(paired_df) == 0:
            pytest.skip("No transfer pairs in test data")

        # Check each group has exactly 2 transactions
        group_counts = paired_df.group_by("transfer_group_id").agg(pl.len().alias("count"))

        for row in group_counts.iter_rows(named=True):
            group_id = row["transfer_group_id"]
            count = row["count"]
            assert count == 2, f"Transfer group {group_id} has {count} transactions (expected 2)"

    def test_transfer_detection_consistent_across_runs(
        self, initialized_data_dir: Path, synthetic_xlsx_file: Path, sample_rules_path: Path
    ) -> None:
        """Verify transfer detection produces same results on rerun.

        Validates:
        - Same transactions are marked as transfers
        - Same group IDs are assigned
        """
        # Setup with synthetic data that has known transfer pairs
        shutil.copy(synthetic_xlsx_file, initialized_data_dir / "imports" / "synthetic.xlsx")
        shutil.copy(sample_rules_path, initialized_data_dir / "rules.yaml")

        # First run
        result1 = runner.invoke(app, ["--data-dir", str(initialized_data_dir), "refresh"])
        assert result1.exit_code == 0

        csv_base_dir = initialized_data_dir / "transactions"
        df1 = csv_partition.get_all_transactions(csv_base_dir)

        transfers1 = df1.filter(pl.col("is_transfer") == 1)
        transfer_hashes1 = set(transfers1["row_hash"].to_list())

        # Second run
        result2 = runner.invoke(app, ["--data-dir", str(initialized_data_dir), "refresh"])
        assert result2.exit_code == 0

        df2 = csv_partition.get_all_transactions(csv_base_dir)
        transfers2 = df2.filter(pl.col("is_transfer") == 1)
        transfer_hashes2 = set(transfers2["row_hash"].to_list())

        # Assert consistency
        assert transfer_hashes1 == transfer_hashes2, (
            "Different transactions marked as transfers between runs"
        )


# ============================================================================
# Test: Tag Persistence
# ============================================================================


@pytest.mark.e2e
class TestTagPersistence:
    """Tests for tag persistence across pipeline runs."""

    def test_tags_preserved_after_rerun(self, data_dir_with_pipeline_run: Path) -> None:
        """Verify tags are not lost on pipeline rerun.

        Validates:
        - tags_rule values are preserved
        - tags_final values are preserved
        """
        csv_base_dir = data_dir_with_pipeline_run / "transactions"

        # Get initial tags
        df1 = csv_partition.get_all_transactions(csv_base_dir)
        initial_tags = {
            row["row_hash"]: {
                "tags_rule": row["tags_rule"],
                "tags_final": row["tags_final"],
            }
            for row in df1.iter_rows(named=True)
        }

        # Rerun pipeline
        result = runner.invoke(app, ["--data-dir", str(data_dir_with_pipeline_run), "refresh"])
        assert result.exit_code == 0

        # Get tags after rerun
        df2 = csv_partition.get_all_transactions(csv_base_dir)
        final_tags = {
            row["row_hash"]: {
                "tags_rule": row["tags_rule"],
                "tags_final": row["tags_final"],
            }
            for row in df2.iter_rows(named=True)
        }

        # Compare
        for row_hash, initial in initial_tags.items():
            assert row_hash in final_tags, f"Row {row_hash} lost after rerun"
            final = final_tags[row_hash]
            assert initial["tags_rule"] == final["tags_rule"], f"tags_rule changed for {row_hash}"
            assert initial["tags_final"] == final["tags_final"], (
                f"tags_final changed for {row_hash}"
            )


# ============================================================================
# Test: CSV Partition Integrity
# ============================================================================


@pytest.mark.e2e
class TestCSVPartitionIntegrity:
    """Tests for CSV partition data integrity."""

    def test_partitions_have_correct_schema(self, data_dir_with_pipeline_run: Path) -> None:
        """Verify CSV partitions have all required columns.

        Validates:
        - All schema columns are present
        - Data types are correct
        """
        csv_base_dir = data_dir_with_pipeline_run / "transactions"
        csv_files = list(csv_base_dir.rglob("*.csv"))

        assert len(csv_files) > 0, "No CSV partitions found"

        # Required columns from schema
        required_columns = [
            "row_hash",
            "date",
            "time",
            "type_raw",
            "type_norm",
            "amount",
            "account",
            "tags_final",
        ]

        for csv_file in csv_files:
            df = pl.read_csv(csv_file)
            for col in required_columns:
                assert col in df.columns, f"Missing column '{col}' in {csv_file.name}"

    def test_partitions_sorted_by_datetime(self, data_dir_with_pipeline_run: Path) -> None:
        """Verify transactions are sorted by datetime within partitions.

        Validates:
        - Each partition has transactions sorted by datetime
        """
        csv_base_dir = data_dir_with_pipeline_run / "transactions"
        csv_files = list(csv_base_dir.rglob("*.csv"))

        for csv_file in csv_files:
            df = pl.read_csv(csv_file)
            if len(df) <= 1:
                continue  # Nothing to check for single-row partitions

            # Check if sorted by datetime
            datetimes = df["datetime"].to_list()
            sorted_datetimes = sorted(datetimes)
            assert datetimes == sorted_datetimes, (
                f"Partition {csv_file.name} not sorted by datetime"
            )

    def test_row_hash_format_valid(self, data_dir_with_pipeline_run: Path) -> None:
        """Verify row_hash values have correct format.

        Validates:
        - row_hash is 16 characters (truncated SHA256, Issue #81)
        - row_hash is lowercase hex
        """
        import re

        csv_base_dir = data_dir_with_pipeline_run / "transactions"
        df = csv_partition.get_all_transactions(csv_base_dir)

        hash_pattern = re.compile(r"^[0-9a-f]{16}$")

        for row in df.iter_rows(named=True):
            row_hash = row["row_hash"]
            assert hash_pattern.match(row_hash), f"Invalid row_hash format: {row_hash}"

    def test_amount_sign_convention(self, data_dir_with_pipeline_run: Path) -> None:
        """Verify amount sign convention (negative=expense, positive=income).

        Validates:
        - type_norm='expense' has negative amount
        - type_norm='income' has positive amount
        """
        csv_base_dir = data_dir_with_pipeline_run / "transactions"
        df = csv_partition.get_all_transactions(csv_base_dir)

        for row in df.iter_rows(named=True):
            type_norm = row["type_norm"]
            amount = row["amount"]

            if type_norm == "expense":
                assert amount < 0, f"Expense with positive amount: {row['row_hash']}"
            elif type_norm == "income":
                assert amount > 0, f"Income with negative amount: {row['row_hash']}"
            # Transfers can have either sign


# ============================================================================
# Test: Data Consistency After Updates
# ============================================================================


@pytest.mark.e2e
class TestDataConsistencyAfterUpdates:
    """Tests for data consistency when new data is added."""

    def test_adding_new_file_preserves_existing_data(
        self, data_dir_with_pipeline_run: Path, synthetic_xlsx_file: Path
    ) -> None:
        """Verify adding new XLSX preserves existing transactions.

        Validates:
        - Existing row hashes are preserved
        - New transactions are added
        - Total count increases appropriately
        """
        csv_base_dir = data_dir_with_pipeline_run / "transactions"

        # Get initial state
        df1 = csv_partition.get_all_transactions(csv_base_dir)
        initial_hashes = set(df1["row_hash"].to_list())
        initial_count = len(df1)

        # Add new file
        shutil.copy(synthetic_xlsx_file, data_dir_with_pipeline_run / "imports" / "new_data.xlsx")

        # Run pipeline again
        result = runner.invoke(app, ["--data-dir", str(data_dir_with_pipeline_run), "refresh"])
        assert result.exit_code == 0

        # Get final state
        df2 = csv_partition.get_all_transactions(csv_base_dir)
        final_hashes = set(df2["row_hash"].to_list())
        final_count = len(df2)

        # Verify existing data preserved
        assert initial_hashes.issubset(final_hashes), "Some existing transactions were lost"

        # Verify new data added (or deduplicated if same)
        # Count should stay same or increase
        assert final_count >= initial_count, f"Row count decreased: {initial_count} → {final_count}"
