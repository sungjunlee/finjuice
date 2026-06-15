"""Tests for Banksalad overview workbook CSV partition storage."""

from pathlib import Path

import polars as pl
import pytest
import yaml

from finjuice.pipeline.storage.csv_partition import (
    BANKSALAD_BALANCE_DEDUP_KEY,
    BANKSALAD_BALANCE_POLARS_SCHEMA,
    BANKSALAD_CASHFLOW_DEDUP_KEY,
    BANKSALAD_CASHFLOW_POLARS_SCHEMA,
    BANKSALAD_OVERVIEW_FACT_COLUMNS,
    BANKSALAD_OVERVIEW_FACT_DEDUP_KEY,
    BANKSALAD_OVERVIEW_FACT_POLARS_SCHEMA,
    append_banksalad_balance,
    append_banksalad_cashflow,
    append_banksalad_overview_facts,
    get_banksalad_balance_partition_path,
    get_banksalad_cashflow_partition_path,
    get_banksalad_overview_facts_partition_path,
    read_banksalad_balance_month,
    read_banksalad_cashflow_month,
    read_banksalad_overview_facts_month,
)


def _overview_facts_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "fact_id": ["fact_b", "fact_a", "fact_c"],
            "snapshot_date": ["2026-06-15", "2026-06-15", "2026-07-01"],
            "sheet_name": ["overview", "overview", "overview"],
            "block_id": ["cashflow", "balance", "balance"],
            "block_title": ["Synthetic Cashflow", "Synthetic Balance", "Synthetic Balance"],
            "fact_kind": ["table_value", "table_value", "table_value"],
            "row_label": ["net", "asset_total", "asset_total"],
            "column_label": ["2026-06", "current", "current"],
            "value_numeric": [100.0, 200.0, 300.0],
            "value_text": [None, None, None],
            "value_type": ["number", "number", "number"],
            "file_id": ["260615_1", "260615_1", "260701_1"],
            "source_row": [8, 4, 4],
            "source_col": [3, 2, 2],
        }
    )


def _balance_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "snapshot_date": ["2026-06-15", "2026-06-15", "2026-07-01"],
            "side": ["liability", "asset", "asset"],
            "category": ["loan", "deposit", "deposit"],
            "item_name": ["item_b", "item_a", "item_a"],
            "amount": [50.0, 200.0, 210.0],
            "currency": ["KRW", "KRW", "KRW"],
            "source_fact_id": ["fact_b", "fact_a", "fact_c"],
            "file_id": ["260615_1", "260615_1", "260701_1"],
            "source_row": [6, 5, 5],
        }
    )


def _cashflow_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "snapshot_date": ["2026-06-15", "2026-06-15", "2026-06-15"],
            "period_month": ["2026-07", "2026-06", None],
            "category": ["expense", "income", "net"],
            "amount": [-80.0, 120.0, 40.0],
            "source_fact_id": ["fact_expense", "fact_income", "fact_net"],
            "file_id": ["260615_1", "260615_1", "260615_1"],
        }
    )


def test_banksalad_empty_reads_return_typed_dataframes(tmp_path: Path) -> None:
    base_dir = tmp_path / "banksalad"

    facts = read_banksalad_overview_facts_month(base_dir / "overview_facts", 2026, 6)
    balance = read_banksalad_balance_month(base_dir / "balance", 2026, 6)
    cashflow = read_banksalad_cashflow_month(base_dir / "cashflow", 2026, 6)

    assert facts.height == 0
    assert facts.schema == BANKSALAD_OVERVIEW_FACT_POLARS_SCHEMA
    assert balance.height == 0
    assert balance.schema == BANKSALAD_BALANCE_POLARS_SCHEMA
    assert cashflow.height == 0
    assert cashflow.schema == BANKSALAD_CASHFLOW_POLARS_SCHEMA


def test_banksalad_dedup_keys_match_schema_yaml() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    schema_paths = [
        repo_root / "templates" / "schema.yaml",
        repo_root / "src" / "finjuice" / "templates" / "schema.yaml",
    ]

    for schema_path in schema_paths:
        schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
        workbook_schemas = schema["banksalad_workbook_schemas"]

        assert (
            workbook_schemas["overview_facts_v0"]["key_policy"]["dedup_key"]
            == BANKSALAD_OVERVIEW_FACT_DEDUP_KEY
        )
        assert (
            workbook_schemas["balance_projection_v0"]["key_policy"]["dedup_key"]
            == BANKSALAD_BALANCE_DEDUP_KEY
        )
        assert (
            workbook_schemas["cashflow_projection_v0"]["key_policy"]["dedup_key"]
            == BANKSALAD_CASHFLOW_DEDUP_KEY
        )


def test_banksalad_overview_facts_append_dedups_and_sorts_partitions(tmp_path: Path) -> None:
    base_dir = tmp_path / "banksalad" / "overview_facts"
    batch = pl.concat([_overview_facts_df(), _overview_facts_df().slice(0, 1)])

    result1 = append_banksalad_overview_facts(base_dir, batch)
    result2 = append_banksalad_overview_facts(base_dir, _overview_facts_df())
    june = read_banksalad_overview_facts_month(base_dir, 2026, 6)
    july = read_banksalad_overview_facts_month(base_dir, 2026, 7)

    assert result1 == {
        "total_rows": 4,
        "partitions_updated": 2,
        "rows_inserted": 3,
        "rows_skipped": 1,
    }
    assert result2 == {
        "total_rows": 3,
        "partitions_updated": 0,
        "rows_inserted": 0,
        "rows_skipped": 3,
    }
    assert get_banksalad_overview_facts_partition_path(base_dir, 2026, 6).exists()
    assert get_banksalad_overview_facts_partition_path(base_dir, 2026, 7).exists()
    assert june.columns == BANKSALAD_OVERVIEW_FACT_COLUMNS
    assert list(june.select(["block_id", "source_row"]).iter_rows()) == [
        ("balance", 4),
        ("cashflow", 8),
    ]
    assert july.height == 1


def test_banksalad_balance_append_partitions_and_dedups(tmp_path: Path) -> None:
    base_dir = tmp_path / "banksalad" / "balance"
    batch = pl.concat([_balance_df(), _balance_df().slice(1, 1)])

    result = append_banksalad_balance(base_dir, batch)
    repeat = append_banksalad_balance(base_dir, _balance_df())
    june = read_banksalad_balance_month(base_dir, 2026, 6)

    assert result["rows_inserted"] == 3
    assert result["rows_skipped"] == 1
    assert result["partitions_updated"] == 2
    assert repeat["rows_inserted"] == 0
    assert repeat["rows_skipped"] == 3
    assert get_banksalad_balance_partition_path(base_dir, 2026, 6).exists()
    assert get_banksalad_balance_partition_path(base_dir, 2026, 7).exists()
    assert list(june.select(["side", "category", "item_name"]).iter_rows()) == [
        ("asset", "deposit", "item_a"),
        ("liability", "loan", "item_b"),
    ]


def test_banksalad_cashflow_uses_period_month_when_available(tmp_path: Path) -> None:
    base_dir = tmp_path / "banksalad" / "cashflow"

    result = append_banksalad_cashflow(base_dir, _cashflow_df())
    repeat = append_banksalad_cashflow(base_dir, _cashflow_df())
    june = read_banksalad_cashflow_month(base_dir, 2026, 6)
    july = read_banksalad_cashflow_month(base_dir, 2026, 7)

    assert result == {
        "total_rows": 3,
        "partitions_updated": 2,
        "rows_inserted": 3,
        "rows_skipped": 0,
    }
    assert repeat == {
        "total_rows": 3,
        "partitions_updated": 0,
        "rows_inserted": 0,
        "rows_skipped": 3,
    }
    assert get_banksalad_cashflow_partition_path(base_dir, 2026, 6).exists()
    assert get_banksalad_cashflow_partition_path(base_dir, 2026, 7).exists()
    assert list(june.select(["period_month", "category"]).iter_rows()) == [
        ("2026-06", "income"),
        (None, "net"),
    ]
    assert list(july.select(["period_month", "category"]).iter_rows()) == [("2026-07", "expense")]


def test_banksalad_cashflow_requires_valid_partition_source(tmp_path: Path) -> None:
    base_dir = tmp_path / "banksalad" / "cashflow"
    invalid_rows = pl.DataFrame(
        {
            "snapshot_date": [None, None],
            "period_month": [None, "2026/06"],
            "category": ["net", "income"],
            "amount": [40.0, 120.0],
        }
    )

    with pytest.raises(ValueError, match="Cashflow partition source must be populated as YYYY-MM"):
        append_banksalad_cashflow(base_dir, invalid_rows)

    assert not base_dir.exists()


def test_banksalad_append_empty_batches_are_noops(tmp_path: Path) -> None:
    base_dir = tmp_path / "banksalad"

    assert append_banksalad_overview_facts(base_dir / "overview_facts", pl.DataFrame()) == {
        "total_rows": 0,
        "partitions_updated": 0,
        "rows_inserted": 0,
        "rows_skipped": 0,
    }
    assert append_banksalad_balance(base_dir / "balance", pl.DataFrame()) == {
        "total_rows": 0,
        "partitions_updated": 0,
        "rows_inserted": 0,
        "rows_skipped": 0,
    }
    assert append_banksalad_cashflow(base_dir / "cashflow", pl.DataFrame()) == {
        "total_rows": 0,
        "partitions_updated": 0,
        "rows_inserted": 0,
        "rows_skipped": 0,
    }
    assert not base_dir.exists()
