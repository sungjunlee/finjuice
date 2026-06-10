"""
Tests for DuckDB SQL query builders.

Tests the query builder functions that generate SQL queries for:
- Monthly spend aggregation
- Tag breakdown analysis
- Top merchants analysis
- Account summary
- Date range filtering
"""

import polars as pl
import pytest

from finjuice.pipeline.analytics.query_builder import (
    build_account_summary_query,
    build_date_range_filter_query,
    build_monthly_spend_query,
    build_recent_spend_movers_query,
    build_tag_breakdown_query,
    build_top_merchants_query,
)


class TestBuildMonthlySpendQuery:
    """Tests for build_monthly_spend_query function."""

    def test_build_monthly_spend_query_basic(self) -> None:
        """Test basic monthly spend query generation."""
        # Act
        query = build_monthly_spend_query("data/transactions/*/*/*csv")

        # Assert
        assert isinstance(query, str)
        assert "SELECT" in query
        assert "month" in query
        assert "SUM(amount)" in query
        assert "GROUP BY" in query
        assert "ORDER BY" in query

    def test_build_monthly_spend_query_excludes_transfers(self) -> None:
        """Test that transfers are excluded by default."""
        # Act
        query = build_monthly_spend_query("data/*/*/*csv", exclude_transfers=True)

        # Assert
        assert "is_transfer = 0" in query

    def test_build_monthly_spend_query_excludes_income(self) -> None:
        """Test that income is excluded by default."""
        # Act
        query = build_monthly_spend_query("data/*/*/*csv", exclude_income=True)

        # Assert
        assert "amount < 0" in query

    def test_build_monthly_spend_query_include_all(self) -> None:
        """Test query with no filters."""
        # Act
        query = build_monthly_spend_query(
            "data/*/*/*csv", exclude_transfers=False, exclude_income=False
        )

        # Assert
        assert "WHERE" not in query or ("is_transfer" not in query and "amount < 0" not in query)

    def test_build_monthly_spend_query_contains_read_csv(self) -> None:
        """Test that query uses DuckDB read_csv function."""
        # Act
        query = build_monthly_spend_query("data/transactions/*/*/*csv")

        # Assert
        assert "read_csv" in query
        assert "auto_detect=true" in query
        assert "union_by_name=true" in query
        assert "parallel=true" in query

    def test_build_monthly_spend_query_month_format(self) -> None:
        """Test that month is extracted in YYYY-MM format."""
        # Act
        query = build_monthly_spend_query("data/*/*/*csv")

        # Assert
        assert "substr(date, 1, 7)" in query


class TestBuildTagBreakdownQuery:
    """Tests for build_tag_breakdown_query function."""

    def test_build_tag_breakdown_query_basic(self) -> None:
        """Test basic tag breakdown query generation."""
        # Act
        query = build_tag_breakdown_query("data/*/*/*csv")

        # Assert
        assert isinstance(query, str)
        assert "SELECT" in query
        assert "tag" in query
        assert "SUM(amount)" in query
        assert "GROUP BY" in query

    def test_build_tag_breakdown_query_top_n(self) -> None:
        """Test that LIMIT is applied with top_n."""
        # Act
        query = build_tag_breakdown_query("data/*/*/*csv", top_n=5)

        # Assert
        assert "LIMIT 5" in query

    def test_build_tag_breakdown_query_default_top_n(self) -> None:
        """Test default top_n value (10)."""
        # Act
        query = build_tag_breakdown_query("data/*/*/*csv")

        # Assert
        assert "LIMIT 10" in query

    def test_build_tag_breakdown_query_excludes_transfers(self) -> None:
        """Test that transfers are excluded by default."""
        # Act
        query = build_tag_breakdown_query("data/*/*/*csv", exclude_transfers=True)

        # Assert
        assert "is_transfer = 0" in query

    def test_build_tag_breakdown_query_json_unnest(self) -> None:
        """Test that JSON unnest is used for tags_final."""
        # Act
        query = build_tag_breakdown_query("data/*/*/*csv")

        # Assert
        assert "CROSS JOIN LATERAL" in query
        assert "unnest" in query
        assert "from_json" in query
        assert "tags_final" in query
        assert "tags_list IS NOT NULL" in query

    def test_build_tag_breakdown_query_clamps_top_n(self) -> None:
        """Test that top_n is clamped to [1, 100]."""
        # Act — zero should be clamped to 1
        query_zero = build_tag_breakdown_query("data/*/*/*csv", top_n=0)
        assert "LIMIT 1" in query_zero

        # Act — value > 100 should be clamped to 100
        query_high = build_tag_breakdown_query("data/*/*/*csv", top_n=200)
        assert "LIMIT 100" in query_high


class TestBuildTopMerchantsQuery:
    """Tests for build_top_merchants_query function."""

    def test_build_top_merchants_query_basic(self) -> None:
        """Test basic top merchants query generation."""
        # Act
        query = build_top_merchants_query("data/*/*/*csv")

        # Assert
        assert isinstance(query, str)
        assert "SELECT" in query
        assert "merchant" in query
        assert "SUM(amount)" in query
        assert "GROUP BY" in query

    def test_build_top_merchants_query_top_n(self) -> None:
        """Test that LIMIT is applied with top_n."""
        # Act
        query = build_top_merchants_query("data/*/*/*csv", top_n=20)

        # Assert
        assert "LIMIT 20" in query

    def test_build_top_merchants_query_avg_amount(self) -> None:
        """Test that average amount is calculated."""
        # Act
        query = build_top_merchants_query("data/*/*/*csv")

        # Assert
        assert "AVG(amount)" in query

    def test_build_top_merchants_query_transaction_count(self) -> None:
        """Test that transaction count is included."""
        # Act
        query = build_top_merchants_query("data/*/*/*csv")

        # Assert
        assert "COUNT(*)" in query

    def test_build_top_merchants_query_excludes_transfers(self) -> None:
        """Test that transfers are excluded by default."""
        # Act
        query = build_top_merchants_query("data/*/*/*csv", exclude_transfers=True)

        # Assert
        assert "is_transfer = 0" in query


class TestBuildAccountSummaryQuery:
    """Tests for build_account_summary_query function."""

    def test_build_account_summary_query_basic(self) -> None:
        """Test basic account summary query generation."""
        # Act
        query = build_account_summary_query("data/*/*/*csv")

        # Assert
        assert isinstance(query, str)
        assert "SELECT" in query
        assert "account" in query
        assert "GROUP BY" in query

    def test_build_account_summary_query_expenses_income_separate(self) -> None:
        """Test that expenses and income are calculated separately."""
        # Act
        query = build_account_summary_query("data/*/*/*csv")

        # Assert
        assert "total_expenses" in query
        assert "total_income" in query
        assert "amount < 0" in query
        assert "amount > 0" in query

    def test_build_account_summary_query_net_amount(self) -> None:
        """Test that net amount is calculated."""
        # Act
        query = build_account_summary_query("data/*/*/*csv")

        # Assert
        assert "net_amount" in query

    def test_build_account_summary_query_excludes_transfers(self) -> None:
        """Test that transfers are excluded by default."""
        # Act
        query = build_account_summary_query("data/*/*/*csv", exclude_transfers=True)

        # Assert
        assert "is_transfer = 0" in query


class TestBuildRecentSpendMoversQuery:
    """Tests for build_recent_spend_movers_query function."""

    def test_build_recent_spend_movers_query_basic(self) -> None:
        """The context mover query should compare recent and previous 30-day windows."""
        query = build_recent_spend_movers_query()

        assert "transactions" in query
        assert "INTERVAL 30 DAY" in query
        assert "delta_krw" in query
        assert "direction" in query

    def test_build_recent_spend_movers_query_respects_limit(self) -> None:
        """The query should apply the requested limit."""
        query = build_recent_spend_movers_query(top_n=7)

        assert "LIMIT 7" in query

    def test_build_recent_spend_movers_query_executes_with_transfer_filter(self) -> None:
        """The mover query should keep transfer_group_id available for filtering."""
        duckdb = pytest.importorskip("duckdb")
        conn = duckdb.connect()
        transactions = pl.DataFrame(
            {
                "date": ["2026-05-01", "2026-04-01", "2026-05-02"],
                "amount": [-100, -50, -200],
                "category_final": ["식비", "식비", "계좌이체"],
                "is_transfer": [0, 0, 1],
                "transfer_group_id": [None, None, "T1"],
            }
        )
        conn.register("transactions", transactions.to_arrow())

        result = conn.execute(build_recent_spend_movers_query()).pl()
        conn.close()

        assert result.to_dicts() == [{"label": "식비", "delta_krw": 50, "direction": "up"}]

    def test_build_account_summary_query_include_transfers(self) -> None:
        """Test query including transfers."""
        # Act
        query = build_account_summary_query("data/*/*/*csv", exclude_transfers=False)

        # Assert
        # When exclude_transfers=False, should not have WHERE is_transfer = 0
        assert "WHERE" not in query or "is_transfer" not in query


class TestBuildDateRangeFilterQuery:
    """Tests for build_date_range_filter_query function."""

    def test_build_date_range_filter_query_basic(self) -> None:
        """Test basic date range filter query generation."""
        # Act
        query = build_date_range_filter_query("data/*/*/*csv")

        # Assert
        assert isinstance(query, str)
        assert "SELECT" in query
        assert "read_csv" in query

    def test_build_date_range_filter_query_start_date(self) -> None:
        """Test query with start date filter."""
        # Act
        query = build_date_range_filter_query("data/*/*/*csv", start_date="2024-01-01")

        # Assert
        assert "\"date\" >= '2024-01-01'" in query

    def test_build_date_range_filter_query_end_date(self) -> None:
        """Test query with end date filter."""
        # Act
        query = build_date_range_filter_query("data/*/*/*csv", end_date="2024-12-31")

        # Assert
        assert "\"date\" <= '2024-12-31'" in query

    def test_build_date_range_filter_query_both_dates(self) -> None:
        """Test query with both start and end date."""
        # Act
        query = build_date_range_filter_query(
            "data/*/*/*csv", start_date="2024-01-01", end_date="2024-12-31"
        )

        # Assert
        assert "\"date\" >= '2024-01-01'" in query
        assert "\"date\" <= '2024-12-31'" in query
        assert "AND" in query

    def test_build_date_range_filter_query_no_dates(self) -> None:
        """Test query without date filters."""
        # Act
        query = build_date_range_filter_query("data/*/*/*csv")

        # Assert
        # Should not have WHERE clause with date filters when no dates specified
        if "WHERE" in query:
            where_clause = query.split("WHERE")[1]
            assert "date >=" not in where_clause
            assert "date <=" not in where_clause

    def test_build_date_range_filter_query_select_columns(self) -> None:
        """Test query with specific columns."""
        # Act
        query = build_date_range_filter_query(
            "data/*/*/*csv", columns=["date", "amount", "merchant_raw"]
        )

        # Assert
        assert '"date", "amount", "merchant_raw"' in query
        assert "SELECT *" not in query

    def test_build_date_range_filter_query_select_all(self) -> None:
        """Test query selecting all columns by default."""
        # Act
        query = build_date_range_filter_query("data/*/*/*csv")

        # Assert
        assert "SELECT *" in query or "SELECT\n" in query

    def test_build_date_range_filter_query_order_by(self) -> None:
        """Test that results are ordered by date and time."""
        # Act
        query = build_date_range_filter_query("data/*/*/*csv")

        # Assert
        assert "ORDER BY" in query
        assert "date" in query
        assert "DESC" in query


class TestQuerySQLInjectionPrevention:
    """Tests to verify SQL injection prevention."""

    def test_monthly_spend_query_path_is_quoted(self) -> None:
        """Test that partition path is properly quoted."""
        # Act
        query = build_monthly_spend_query("data/test'; DROP TABLE users; --")

        # Assert
        # Path should be quoted with single quotes
        assert "'" in query
        assert "data/test''; DROP TABLE users; --" in query
        assert "data/test'; DROP TABLE users; --" not in query

    @pytest.mark.parametrize(
        "partitions_path",
        [
            "../private.csv",
            "/tmp/private.csv",
            r"C:\Users\private.csv",
            r"data\transactions\*.csv",
        ],
    )
    def test_read_csv_builders_reject_paths_outside_current_root(
        self,
        partitions_path: str,
    ) -> None:
        """Legacy read_csv builders should reject traversal and absolute paths."""
        with pytest.raises(ValueError):
            build_monthly_spend_query(partitions_path)

    def test_date_range_query_dates_are_quoted(self) -> None:
        """Test that date values are properly quoted."""
        # Act
        query = build_date_range_filter_query(
            "data/*/*/*csv", start_date="2024-01-01'; DROP TABLE users; --"
        )

        # Assert
        assert "2024-01-01''; DROP TABLE users; --" in query
        assert "2024-01-01'; DROP TABLE users; --" not in query

    def test_top_merchants_query_limit_is_integer(self) -> None:
        """Test that LIMIT value is treated as integer."""
        # Act - passing valid integer
        query = build_top_merchants_query("data/*/*/*csv", top_n=10)

        # Assert
        assert "LIMIT 10" in query

    def test_tag_breakdown_query_limit_is_integer(self) -> None:
        """Test that LIMIT value is treated as integer."""
        # Act
        query = build_tag_breakdown_query("data/*/*/*csv", top_n=5)

        # Assert
        assert "LIMIT 5" in query
