"""Unit tests for DuckDB analytics layer.

Tests cover:
- DuckDBAnalytics initialization
- CSV partition reading
- Optimized aggregations (monthly_spend, tag_breakdown)
- Polars integration (zero-copy conversion)
- Error handling
"""

import tempfile
from pathlib import Path

import polars as pl
import pytest

from finjuice.pipeline.analytics import DuckDBAnalytics


@pytest.fixture
def sample_csv_data():
    """Sample transaction data for testing."""
    return pl.DataFrame(
        {
            "row_hash": ["abc123", "def456", "ghi789", "jkl012"],
            "date": ["2024-10-01", "2024-10-15", "2024-11-01", "2024-11-15"],
            "time": ["10:30", "14:20", "09:15", "16:45"],
            "type_raw": ["지출", "지출", "수입", "지출"],
            "major_raw": ["식비", "쇼핑", "급여", "교통"],
            "minor_raw": ["카페", "의류", "월급", "지하철"],
            "merchant_raw": ["스타벅스", "유니클로", "회사", "서울교통공사"],
            "memo_raw": ["", "", "", ""],
            "amount": [-4500.0, -29000.0, 3000000.0, -1350.0],
            "currency": ["KRW", "KRW", "KRW", "KRW"],
            "account": ["신한카드", "삼성카드", "우리은행", "신한카드"],
            "is_transfer": [0, 0, 0, 0],
            "transfer_group_id": [None, None, None, None],
            "tags_rule": ['["카페","식비"]', '["쇼핑"]', "[]", '["교통","대중교통"]'],
            "tags_final": ['["카페","식비"]', '["쇼핑"]', "[]", '["교통","대중교통"]'],
        }
    )


@pytest.fixture
def temp_data_dir(sample_csv_data):
    """Create temporary data directory with CSV partitions."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)

        # Create partition structure: data/transactions/YYYY/MM/transactions.csv
        oct_dir = data_dir / "transactions" / "2024" / "10"
        oct_dir.mkdir(parents=True, exist_ok=True)

        nov_dir = data_dir / "transactions" / "2024" / "11"
        nov_dir.mkdir(parents=True, exist_ok=True)

        # Split data by month
        oct_data = sample_csv_data.filter(pl.col("date").str.starts_with("2024-10"))
        nov_data = sample_csv_data.filter(pl.col("date").str.starts_with("2024-11"))

        # Write CSV partitions
        oct_data.write_csv(oct_dir / "transactions.csv")
        nov_data.write_csv(nov_dir / "transactions.csv")

        yield data_dir


@pytest.fixture
def legacy_transfer_data_dir():
    """Create legacy partitions without additive transfer metadata columns."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        partition_dir = data_dir / "transactions" / "2024" / "10"
        partition_dir.mkdir(parents=True, exist_ok=True)

        pl.DataFrame(
            {
                "row_hash": ["legacy_expense", "legacy_transfer"],
                "date": ["2024-10-01", "2024-10-02"],
                "time": ["10:30", "14:20"],
                "type_raw": ["지출", "지출"],
                "type_norm": ["expense", "expense"],
                "major_raw": ["식비", "이체"],
                "minor_raw": ["카페", "계좌이체"],
                "merchant_raw": ["스타벅스", "은행이체"],
                "memo_raw": ["", ""],
                "amount": [-4500.0, -10000.0],
                "currency": ["KRW", "KRW"],
                "account": ["신한카드", "우리은행"],
                "is_transfer": [0, 1],
                "tags_rule": ['["카페","식비"]', "[]"],
                "tags_final": ['["카페","식비"]', "[]"],
            }
        ).write_csv(partition_dir / "transactions.csv")

        yield data_dir


class TestDuckDBAnalyticsInit:
    """Test DuckDBAnalytics initialization."""

    def test_init_success(self, temp_data_dir):
        """Test successful initialization."""
        analytics = DuckDBAnalytics(temp_data_dir)
        assert analytics.data_dir == temp_data_dir
        assert analytics.partitions_path == temp_data_dir / "transactions"
        assert analytics.conn is not None
        analytics.close()

    def test_init_with_memory_limit(self, temp_data_dir):
        """Test initialization with memory limit."""
        analytics = DuckDBAnalytics(temp_data_dir, memory_limit="1GB")
        assert analytics.conn is not None
        analytics.close()

    def test_init_disables_duckdb_progress_bar(self, temp_data_dir):
        """DuckDB progress output must not pollute JSON command stdout."""
        analytics = DuckDBAnalytics(temp_data_dir)
        try:
            row = analytics.conn.execute("SELECT current_setting('enable_progress_bar')").fetchone()
            enabled = row[0]
            assert enabled is False
        finally:
            analytics.close()

    def test_init_without_duckdb_fails(self, temp_data_dir, monkeypatch):
        """Test initialization fails gracefully if DuckDB not installed."""
        import finjuice.pipeline.analytics.duckdb_layer as module

        monkeypatch.setattr(module, "DUCKDB_AVAILABLE", False)

        with pytest.raises(ImportError, match="finjuice doctor"):
            module.DuckDBAnalytics(temp_data_dir)

    def test_context_manager(self, temp_data_dir):
        """Test DuckDBAnalytics as context manager."""
        with DuckDBAnalytics(temp_data_dir) as analytics:
            assert analytics.conn is not None
        # Connection should be closed after context

    def test_init_backfills_legacy_transfer_columns(self, legacy_transfer_data_dir):
        """Legacy CSV partitions should expose additive transfer columns in the view."""
        analytics = DuckDBAnalytics(legacy_transfer_data_dir)
        try:
            df = analytics.query_readonly(
                """
                SELECT
                    row_hash,
                    is_transfer_candidate,
                    transfer_group_id,
                    is_transfer_bool
                FROM transactions
                ORDER BY row_hash
                """
            ).pl()

            rows = {row["row_hash"]: row for row in df.to_dicts()}
            assert rows["legacy_expense"]["is_transfer_candidate"] == 0
            assert rows["legacy_expense"]["transfer_group_id"] is None
            assert rows["legacy_expense"]["is_transfer_bool"] is False
            assert rows["legacy_transfer"]["is_transfer_candidate"] == 1
            assert rows["legacy_transfer"]["transfer_group_id"] is None
            assert rows["legacy_transfer"]["is_transfer_bool"] is False

            monthly = analytics.monthly_spend()
            assert monthly["transaction_count"].sum() == 2
            assert monthly["total_amount"].sum() == pytest.approx(-14500.0)
        finally:
            analytics.close()


class TestDuckDBAnalyticsReadPartitions:
    """Test CSV partition reading."""

    def test_read_all_partitions(self, temp_data_dir):
        """Test reading all CSV partitions."""
        analytics = DuckDBAnalytics(temp_data_dir)
        try:
            df = analytics.read_partitions()

            # Should read all 4 rows from both partitions
            assert len(df) == 4
            assert "date" in df.columns
            assert "amount" in df.columns
            assert "merchant_raw" in df.columns
        finally:
            analytics.close()

    def test_read_specific_month(self, temp_data_dir):
        """Test reading specific month partition."""
        analytics = DuckDBAnalytics(temp_data_dir)
        try:
            df = analytics.read_partitions(pattern="2024/10/*.csv")

            # Should read only October data (2 rows)
            assert len(df) == 2
            # Convert date to string for comparison (DuckDB returns DATE type)
            assert all(df["date"].cast(pl.Utf8).str.starts_with("2024-10"))
        finally:
            analytics.close()

    def test_read_with_column_selection(self, temp_data_dir):
        """Test reading with specific columns."""
        analytics = DuckDBAnalytics(temp_data_dir)
        try:
            df = analytics.read_partitions(columns=["date", "amount", "merchant_raw"])

            # Should have only selected columns
            assert set(df.columns) == {"date", "amount", "merchant_raw"}
            assert len(df) == 4
        finally:
            analytics.close()

    @pytest.mark.parametrize(
        "pattern",
        [
            "../*.csv",
            "2024/../secrets.csv",
            "/tmp/private.csv",
            r"2024\10\*.csv",
        ],
    )
    def test_read_partitions_rejects_paths_outside_partition_root(
        self,
        temp_data_dir,
        pattern: str,
    ):
        """User-controlled DuckDB read patterns must stay under transactions/."""
        analytics = DuckDBAnalytics(temp_data_dir)
        try:
            with pytest.raises(ValueError):
                analytics.read_partitions(pattern=pattern)
        finally:
            analytics.close()


class TestDuckDBAnalyticsMonthlySpend:
    """Test monthly spending aggregation."""

    def test_monthly_spend_default(self, temp_data_dir):
        """Test monthly spend with default settings (exclude transfers & income)."""
        analytics = DuckDBAnalytics(temp_data_dir)
        try:
            df = analytics.monthly_spend()

            # Should have 2 months
            assert len(df) == 2

            # Columns check
            assert "month" in df.columns
            assert "transaction_count" in df.columns
            assert "total_amount" in df.columns

            # Should exclude income (only negative amounts)
            assert all(df["total_amount"] <= 0)

            # Check October: 2 expense transactions (-4500 + -29000 = -33500)
            oct_row = df.filter(pl.col("month") == "2024-10")
            assert len(oct_row) == 1
            assert oct_row["transaction_count"][0] == 2
            assert oct_row["total_amount"][0] == pytest.approx(-33500.0)

            # Check November: 1 expense transaction (-1350)
            nov_row = df.filter(pl.col("month") == "2024-11")
            assert len(nov_row) == 1
            assert nov_row["transaction_count"][0] == 1
            assert nov_row["total_amount"][0] == pytest.approx(-1350.0)
        finally:
            analytics.close()

    def test_monthly_spend_include_income(self, temp_data_dir):
        """Test monthly spend including income."""
        analytics = DuckDBAnalytics(temp_data_dir)
        try:
            df = analytics.monthly_spend(exclude_income=False)

            # November should now include income
            nov_row = df.filter(pl.col("month") == "2024-11")
            # 1 expense (-1350) + 1 income (+3000000)
            assert nov_row["transaction_count"][0] == 2
        finally:
            analytics.close()


class TestDuckDBAnalyticsTagBreakdown:
    """Test tag-based spending breakdown."""

    def test_tag_breakdown_default(self, temp_data_dir):
        """Test tag breakdown with default settings."""
        analytics = DuckDBAnalytics(temp_data_dir)
        try:
            df = analytics.tag_breakdown(top_n=10)

            # Columns check
            assert "tag" in df.columns
            assert "transaction_count" in df.columns
            assert "total_amount" in df.columns

            # Should have tags from expense transactions
            tags = set(df["tag"].to_list())
            expected_tags = {"카페", "식비", "쇼핑", "교통", "대중교통"}
            assert tags == expected_tags

            # Should be sorted by amount (ascending = largest expenses first)
            amounts = df["total_amount"].to_list()
            assert amounts == sorted(amounts)
        finally:
            analytics.close()

    def test_tag_breakdown_top_n(self, temp_data_dir):
        """Test tag breakdown with top_n limit."""
        analytics = DuckDBAnalytics(temp_data_dir)
        try:
            df = analytics.tag_breakdown(top_n=2)

            # Should return only top 2 tags
            assert len(df) <= 2
        finally:
            analytics.close()


class TestDuckDBAnalyticsIntegration:
    """Integration tests for DuckDBAnalytics."""

    def test_polars_conversion_roundtrip(self, temp_data_dir):
        """Test zero-copy Polars conversion works correctly."""
        analytics = DuckDBAnalytics(temp_data_dir)
        try:
            # Read as Polars DataFrame
            df = analytics.read_partitions()

            # Verify it's a Polars DataFrame
            assert isinstance(df, pl.DataFrame)

            # Verify data integrity
            assert len(df) == 4
            assert df["amount"].sum() == pytest.approx(3000000.0 - 4500.0 - 29000.0 - 1350.0)
        finally:
            analytics.close()

    def test_concurrent_queries(self, temp_data_dir):
        """Test multiple queries on same connection."""
        analytics = DuckDBAnalytics(temp_data_dir)
        try:
            # Run multiple queries
            df1 = analytics.monthly_spend()
            df2 = analytics.tag_breakdown()
            df3 = analytics.read_partitions()

            # All should succeed
            assert len(df1) > 0
            assert len(df2) > 0
            assert len(df3) > 0
        finally:
            analytics.close()


class TestDuckDBAnalyticsReadonlyFacade:
    """Test reusable read-only SQL execution boundary."""

    def test_query_readonly_returns_polars_dataframe(self, temp_data_dir):
        """Read-only SELECT queries should execute through the facade."""
        analytics = DuckDBAnalytics(temp_data_dir)
        try:
            result = analytics.query_readonly(
                "SELECT COUNT(*) AS transaction_count FROM transactions"
            ).pl()

            assert result["transaction_count"][0] == 4
        finally:
            analytics.close()

    @pytest.mark.parametrize(
        ("sql", "message"),
        [
            (
                "SELECT * FROM read_csv_auto('/tmp/private.csv')",
                "restricted DuckDB table function",
            ),
            (
                "SELECT * FROM transactions; DROP VIEW transactions",
                "Multi-statement queries are not allowed",
            ),
        ],
    )
    def test_query_readonly_rejects_unsafe_sql(
        self,
        temp_data_dir,
        sql: str,
        message: str,
    ):
        """Facade should reject file-reading table functions and multi-statements."""
        analytics = DuckDBAnalytics(temp_data_dir)
        try:
            with pytest.raises(ValueError, match=message):
                analytics.query_readonly(sql)
        finally:
            analytics.close()
