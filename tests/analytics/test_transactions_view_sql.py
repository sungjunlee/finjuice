"""Identity and behavior coverage for the transactions-view SQL helper split."""

from __future__ import annotations

import importlib


def test_duckdb_layer_reexports_transactions_view_sql_helpers() -> None:
    """View SQL builders stay importable from duckdb_layer after the split."""
    layer = importlib.import_module("finjuice.pipeline.analytics.duckdb_layer")
    helpers = importlib.import_module("finjuice.pipeline.analytics.transactions_view_sql")

    assert layer.build_transfer_normalization_exprs is helpers.build_transfer_normalization_exprs
    assert (
        layer.build_transactions_source_projection is helpers.build_transactions_source_projection
    )
    assert layer.build_transactions_source_sql is helpers.build_transactions_source_sql
    assert callable(layer.DuckDBAnalytics)


def test_transfer_exprs_fall_back_for_missing_columns() -> None:
    """Missing transfer columns must yield neutral default expressions."""
    helpers = importlib.import_module("finjuice.pipeline.analytics.transactions_view_sql")

    is_transfer_expr, transfer_group_expr, candidate_default_expr = (
        helpers.build_transfer_normalization_exprs(["date", "amount"])
    )

    assert is_transfer_expr == "CAST(0 AS BIGINT)"
    assert transfer_group_expr == "CAST(NULL AS VARCHAR)"
    assert candidate_default_expr == "COALESCE(CAST(0 AS BIGINT), 0)"


def test_transfer_exprs_use_try_cast_when_columns_present() -> None:
    """Detected transfer columns must use TRY_CAST-based normalization."""
    helpers = importlib.import_module("finjuice.pipeline.analytics.transactions_view_sql")

    is_transfer_expr, transfer_group_expr, candidate_default_expr = (
        helpers.build_transfer_normalization_exprs(
            ["is_transfer", "transfer_group_id", "is_transfer_candidate"]
        )
    )

    assert is_transfer_expr == 'TRY_CAST("is_transfer" AS BIGINT)'
    assert transfer_group_expr == 'CAST("transfer_group_id" AS VARCHAR)'
    assert candidate_default_expr == 'COALESCE(TRY_CAST("is_transfer" AS BIGINT), 0)'


def test_projection_appends_defaults_for_missing_transfer_columns() -> None:
    """The projection passes columns through and appends transfer defaults."""
    helpers = importlib.import_module("finjuice.pipeline.analytics.transactions_view_sql")

    projection = helpers.build_transactions_source_projection(["date", "amount"])

    assert projection == [
        '"date"',
        '"amount"',
        'CAST(NULL AS VARCHAR) AS "transfer_group_id"',
        'COALESCE(CAST(0 AS BIGINT), 0) AS "is_transfer_candidate"',
    ]


def test_projection_normalizes_existing_transfer_columns() -> None:
    """Existing transfer columns must be cast instead of defaulting."""
    helpers = importlib.import_module("finjuice.pipeline.analytics.transactions_view_sql")

    projection = helpers.build_transactions_source_projection(
        ["is_transfer", "transfer_group_id", "is_transfer_candidate"]
    )

    assert projection == [
        '"is_transfer"',
        'CAST("transfer_group_id" AS VARCHAR) AS "transfer_group_id"',
        'COALESCE(TRY_CAST("is_transfer_candidate" AS BIGINT), '
        'COALESCE(TRY_CAST("is_transfer" AS BIGINT), 0)) AS "is_transfer_candidate"',
    ]


def test_source_sql_projects_normalization_and_tags_list() -> None:
    """The source view DDL must keep the documented normalization shape."""
    helpers = importlib.import_module("finjuice.pipeline.analytics.transactions_view_sql")

    sql = helpers.build_transactions_source_sql(["date", "tags_final"])

    assert sql.startswith("CREATE OR REPLACE VIEW transactions_source AS")
    assert '"date",' in sql
    assert "    ) AS is_transfer_bool," in sql
    assert 'from_json("tags_final", \'["VARCHAR"]\') AS tags_list' in sql
    assert sql.endswith("FROM transactions_raw")
