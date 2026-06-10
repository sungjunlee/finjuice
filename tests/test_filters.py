"""Tests for transaction filtering expressions.

Tests cover:
- Polars expression filters (exclude_transfers, only_transfers)
- SQL expression filters (exclude_transfers_sql, only_transfers_sql)
- NULL handling behavior (critical for data integrity)
"""

import polars as pl
import pytest

from finjuice.pipeline.filters import (
    exclude_transfers,
    exclude_transfers_for,
    exclude_transfers_sql,
    only_transfers,
    only_transfers_sql,
)


class TestExcludeTransfers:
    """Tests for exclude_transfers() Polars expression."""

    def test_excludes_transfers(self):
        """Should exclude rows where is_transfer == 1 and group id is present."""
        df = pl.DataFrame(
            {"is_transfer": [0, 1, 0, 1], "transfer_group_id": [None, "T1", None, "T2"]}
        )
        result = df.filter(exclude_transfers())
        assert len(result) == 2
        assert result["is_transfer"].to_list() == [0, 0]

    def test_keeps_unconfirmed_transfer_candidates(self):
        """Rows flagged transfer without a group id should remain included."""
        df = pl.DataFrame({"is_transfer": [1, 1], "transfer_group_id": [None, ""]})
        result = df.filter(exclude_transfers())
        assert len(result) == 2

    def test_includes_null_as_non_transfer(self):
        """NULL values should be treated as non-transfers (included).

        This is critical: transactions without transfer detection
        should not be excluded from reports.
        """
        df = pl.DataFrame(
            {
                "is_transfer": [0, 1, None, 0, None],
                "transfer_group_id": [None, "T1", None, None, None],
            }
        )
        result = df.filter(exclude_transfers())
        # Should include: 0, None, 0, None (4 rows)
        assert len(result) == 4

    def test_all_nulls_included(self):
        """All NULL rows should be included."""
        df = pl.DataFrame({"is_transfer": [None, None, None], "transfer_group_id": [None] * 3})
        result = df.filter(exclude_transfers())
        assert len(result) == 3

    def test_all_transfers_excluded(self):
        """All transfer rows should be excluded."""
        df = pl.DataFrame({"is_transfer": [1, 1, 1], "transfer_group_id": ["T1", "T2", "T3"]})
        result = df.filter(exclude_transfers())
        assert len(result) == 0

    def test_composable_with_other_filters(self):
        """Filter should be composable with other Polars expressions."""
        df = pl.DataFrame(
            {
                "is_transfer": [0, 1, 0, None],
                "transfer_group_id": [None, "T1", None, None],
                "amount": [-100, -200, 100, -50],
            }
        )
        # Exclude transfers AND only expenses (negative amounts)
        result = df.filter(exclude_transfers() & (pl.col("amount") < 0))
        assert len(result) == 2  # rows 0 and 3


class TestExcludeTransfersFor:
    """Tests for schema-aware transfer exclusion."""

    def test_legacy_schema_without_group_id_preserves_is_transfer_filtering(self):
        """Legacy/minimal frames should fall back to excluding is_transfer rows."""
        df = pl.DataFrame({"is_transfer": [0, 1, None], "amount": [-100, -200, -50]})

        result = df.filter(exclude_transfers_for(df))

        assert result["amount"].to_list() == [-100, -50]

    def test_new_schema_keeps_unconfirmed_candidates(self):
        """New frames should exclude only confirmed pairs with group ids."""
        df = pl.DataFrame(
            {
                "is_transfer": [1, 1, 0],
                "transfer_group_id": [None, "T1", None],
                "amount": [-100, -200, -50],
            }
        )

        result = df.filter(exclude_transfers_for(df))

        assert result["amount"].to_list() == [-100, -50]

    def test_missing_is_transfer_column_includes_all_rows(self):
        """Frames without transfer metadata should remain reportable."""
        df = pl.DataFrame({"amount": [-100, -200]})

        result = df.filter(exclude_transfers_for(df))

        assert result["amount"].to_list() == [-100, -200]


class TestOnlyTransfers:
    """Tests for only_transfers() Polars expression."""

    def test_selects_transfers(self):
        """Should select only rows where is_transfer == 1 and group id is present."""
        df = pl.DataFrame(
            {"is_transfer": [0, 1, 0, 1], "transfer_group_id": [None, "T1", None, "T2"]}
        )
        result = df.filter(only_transfers())
        assert len(result) == 2
        assert result["is_transfer"].to_list() == [1, 1]

    def test_excludes_null(self):
        """NULL values should not be selected as transfers."""
        df = pl.DataFrame(
            {"is_transfer": [0, 1, None, 1], "transfer_group_id": [None, "T1", None, "T2"]}
        )
        result = df.filter(only_transfers())
        assert len(result) == 2

    def test_no_transfers(self):
        """Empty result when no transfers exist."""
        df = pl.DataFrame({"is_transfer": [0, 0, None], "transfer_group_id": [None] * 3})
        result = df.filter(only_transfers())
        assert len(result) == 0


class TestExcludeTransfersSql:
    """Tests for exclude_transfers_sql() SQL expression."""

    def test_returns_null_safe_sql(self):
        """Should return SQL with proper NULL handling."""
        sql = exclude_transfers_sql()
        assert "IS NULL" in sql
        assert "is_transfer = 0" in sql
        assert "transfer_group_id" in sql
        assert "OR" in sql

    def test_sql_format(self):
        """Should return valid SQL fragment."""
        sql = exclude_transfers_sql()
        assert "is_transfer IS NULL OR is_transfer = 0" in sql
        assert "TRIM(CAST(transfer_group_id AS VARCHAR)) = ''" in sql

    def test_usable_in_where_clause(self):
        """Should be usable in SQL WHERE clause."""
        sql = exclude_transfers_sql()
        full_query = f"SELECT * FROM transactions WHERE {sql}"
        assert "WHERE (is_transfer IS NULL OR is_transfer = 0" in full_query

    def test_composable_with_other_conditions(self):
        """Should be composable with other SQL conditions."""
        sql = exclude_transfers_sql()
        full_query = f"SELECT * FROM transactions WHERE {sql} AND amount < 0"
        assert "transfer_group_id" in full_query
        assert "AND amount < 0" in full_query


class TestOnlyTransfersSql:
    """Tests for only_transfers_sql() SQL expression."""

    def test_returns_simple_equality(self):
        """Should return confirmed-transfer predicate."""
        sql = only_transfers_sql()
        assert "is_transfer = 1" in sql
        assert "transfer_group_id IS NOT NULL" in sql

    def test_usable_in_where_clause(self):
        """Should be usable in SQL WHERE clause."""
        sql = only_transfers_sql()
        full_query = f"SELECT * FROM transactions WHERE {sql}"
        assert "WHERE (is_transfer = 1" in full_query


class TestNullHandlingConsistency:
    """Tests for consistency between Polars and SQL NULL handling."""

    def test_exclude_filters_match_semantically(self):
        """Polars and SQL exclude filters should have matching semantics.

        Both should:
        - EXCLUDE is_transfer = 1 with a transfer_group_id
        - INCLUDE is_transfer = 0
        - INCLUDE is_transfer IS NULL
        """
        # Polars behavior
        df = pl.DataFrame({"is_transfer": [0, 1, None], "transfer_group_id": [None, "T1", None]})
        polars_result = df.filter(exclude_transfers())
        polars_included = set(polars_result["is_transfer"].to_list())

        # SQL semantics (manual verification)
        _sql = exclude_transfers_sql()  # noqa: F841
        # SQL exclude_transfers_sql() includes:
        # - NULL -> True (IS NULL)
        # - 0 -> True (= 0)
        # - 1 with group id -> False

        # Verify Polars matches SQL semantics
        assert 0 in polars_included or polars_result.filter(pl.col("is_transfer") == 0).height > 0
        assert 1 not in polars_included
        # NULL handling
        null_count = polars_result.filter(pl.col("is_transfer").is_null()).height
        assert null_count == 1  # NULL should be included


class TestEmptyDataFrame:
    """Tests for empty DataFrame edge cases."""

    def test_exclude_transfers_empty_dataframe(self):
        """Filter should handle empty DataFrame gracefully."""
        df = pl.DataFrame({"is_transfer": []}, schema={"is_transfer": pl.Int64})
        df = df.with_columns(pl.lit(None).cast(pl.Utf8).alias("transfer_group_id"))
        result = df.filter(exclude_transfers())
        assert len(result) == 0
        assert result.columns == ["is_transfer", "transfer_group_id"]

    def test_only_transfers_empty_dataframe(self):
        """Filter should handle empty DataFrame gracefully."""
        df = pl.DataFrame({"is_transfer": []}, schema={"is_transfer": pl.Int64})
        df = df.with_columns(pl.lit(None).cast(pl.Utf8).alias("transfer_group_id"))
        result = df.filter(only_transfers())
        assert len(result) == 0
        assert result.columns == ["is_transfer", "transfer_group_id"]

    def test_exclude_transfers_empty_with_other_columns(self):
        """Filter should preserve all columns on empty DataFrame."""
        df = pl.DataFrame(
            {"is_transfer": [], "transfer_group_id": [], "amount": [], "date": []},
            schema={
                "is_transfer": pl.Int64,
                "transfer_group_id": pl.Utf8,
                "amount": pl.Float64,
                "date": pl.Utf8,
            },
        )
        result = df.filter(exclude_transfers())
        assert len(result) == 0
        assert result.columns == ["is_transfer", "transfer_group_id", "amount", "date"]


# Check if DuckDB is available for integration tests
try:
    import duckdb

    DUCKDB_AVAILABLE = True
except ImportError:
    DUCKDB_AVAILABLE = False


@pytest.mark.skipif(not DUCKDB_AVAILABLE, reason="DuckDB not installed")
class TestDuckDBIntegration:
    """Integration tests verifying Polars and DuckDB SQL produce identical results."""

    def test_exclude_transfers_polars_matches_duckdb(self):
        """Verify Polars and DuckDB SQL filters produce identical results."""
        # Create test data with all edge cases
        df = pl.DataFrame(
            {
                "is_transfer": [0, 1, None, 0, 1, None],
                "transfer_group_id": [None, "T1", None, None, "T2", None],
                "amount": [-100, -200, -50, -150, -250, -300],
            }
        )

        # Polars result
        polars_result = df.filter(exclude_transfers())

        # DuckDB SQL result
        conn = duckdb.connect()
        conn.register("test_table", df.to_arrow())
        sql = f"SELECT * FROM test_table WHERE {exclude_transfers_sql()}"
        duckdb_result = conn.execute(sql).pl()
        conn.close()

        # Results must match
        assert len(polars_result) == len(duckdb_result)
        assert sorted(polars_result["amount"].to_list()) == sorted(
            duckdb_result["amount"].to_list()
        )

    def test_only_transfers_polars_matches_duckdb(self):
        """Verify Polars and DuckDB SQL filters match for only_transfers."""
        df = pl.DataFrame(
            {
                "is_transfer": [0, 1, None, 0, 1],
                "transfer_group_id": [None, "T1", None, None, "T2"],
                "amount": [-100, -200, -50, -150, -250],
            }
        )

        # Polars result
        polars_result = df.filter(only_transfers())

        # DuckDB SQL result
        conn = duckdb.connect()
        conn.register("test_table", df.to_arrow())
        sql = f"SELECT * FROM test_table WHERE {only_transfers_sql()}"
        duckdb_result = conn.execute(sql).pl()
        conn.close()

        # Results must match
        assert len(polars_result) == len(duckdb_result)
        assert polars_result["amount"].to_list() == [-200, -250]
        assert duckdb_result["amount"].to_list() == [-200, -250]

    def test_mixed_types_consistency(self):
        """Verify consistency with realistic transaction data types."""
        df = pl.DataFrame(
            {
                "is_transfer": [0, 1, None, 0, None, 1, 0],
                "transfer_group_id": [None, "T1", None, None, None, "T2", None],
                "amount": [-1000.50, -2000.0, -500.25, 3000.0, -150.0, -750.0, -250.0],
                "type_norm": [
                    "expense",
                    "expense",
                    "expense",
                    "income",
                    "expense",
                    "expense",
                    "expense",
                ],
            }
        )

        # Polars: exclude transfers AND only expenses
        polars_result = df.filter(exclude_transfers() & (pl.col("type_norm") == "expense"))

        # DuckDB equivalent
        conn = duckdb.connect()
        conn.register("test_table", df.to_arrow())
        sql = f"""
            SELECT * FROM test_table
            WHERE {exclude_transfers_sql()} AND type_norm = 'expense'
        """
        duckdb_result = conn.execute(sql).pl()
        conn.close()

        # Both should return: rows with is_transfer in [0, NULL] AND type_norm = 'expense'
        assert len(polars_result) == len(duckdb_result)
        assert len(polars_result) == 4  # rows 0, 2, 4, 6
