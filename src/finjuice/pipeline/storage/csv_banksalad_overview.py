"""Banksalad overview workbook CSV partition CRUD.

ADR-0013 stores source-fidelity overview facts separately from typed balance
and cashflow projections. These helpers intentionally mirror the transaction
and asset snapshot partition API while keeping the overview contracts isolated.

Table-driven partition I/O lives in
:mod:`finjuice.pipeline.storage.csv_banksalad_overview_helpers`.
Cashflow partition-source helpers live in
:mod:`finjuice.pipeline.storage.csv_banksalad_overview_cashflow` and are
re-exported here so existing callers can keep importing from this module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl

from finjuice.pipeline.storage.csv_banksalad_overview_cashflow import (
    _cashflow_partition_source_expr,
    _validate_cashflow_partition_source,
)
from finjuice.pipeline.storage.csv_banksalad_overview_helpers import (
    _append_partitioned,
    _empty_append_result,
    _ensure_columns,
    _OverviewTableSpec,
    _read_month,
    _write_partition,
)
from finjuice.pipeline.storage.csv_schema import (
    BANKSALAD_BALANCE_COLUMNS,
    BANKSALAD_BALANCE_POLARS_SCHEMA,
    BANKSALAD_CASHFLOW_COLUMNS,
    BANKSALAD_CASHFLOW_POLARS_SCHEMA,
    BANKSALAD_INSURANCE_COLUMNS,
    BANKSALAD_INSURANCE_POLARS_SCHEMA,
    BANKSALAD_INVESTMENT_COLUMNS,
    BANKSALAD_INVESTMENT_POLARS_SCHEMA,
    BANKSALAD_LOAN_COLUMNS,
    BANKSALAD_LOAN_POLARS_SCHEMA,
    BANKSALAD_OVERVIEW_FACT_COLUMNS,
    BANKSALAD_OVERVIEW_FACT_POLARS_SCHEMA,
    get_banksalad_balance_partition_path,
    get_banksalad_cashflow_partition_path,
    get_banksalad_insurance_partition_path,
    get_banksalad_investment_partition_path,
    get_banksalad_loan_partition_path,
    get_banksalad_overview_facts_partition_path,
)

BANKSALAD_OVERVIEW_FACT_DEDUP_KEY = [
    "snapshot_date",
    "block_id",
    "fact_kind",
    "row_label",
    "column_label",
    "source_row",
    "source_col",
]
BANKSALAD_BALANCE_DEDUP_KEY = ["snapshot_date", "side", "category", "item_name", "source_row"]
BANKSALAD_CASHFLOW_DEDUP_KEY = ["snapshot_date", "period_month", "category"]
BANKSALAD_INSURANCE_DEDUP_KEY = ["snapshot_date", "institution", "policy_name", "source_row"]
BANKSALAD_INVESTMENT_DEDUP_KEY = ["snapshot_date", "institution", "product_name", "source_row"]
BANKSALAD_LOAN_DEDUP_KEY = ["snapshot_date", "institution", "product_name", "source_row"]

_OVERVIEW_FACT_SPEC = _OverviewTableSpec(
    columns=BANKSALAD_OVERVIEW_FACT_COLUMNS,
    schema=BANKSALAD_OVERVIEW_FACT_POLARS_SCHEMA,
    path_builder=get_banksalad_overview_facts_partition_path,
    dedup_key=BANKSALAD_OVERVIEW_FACT_DEDUP_KEY,
    default_sort_by=("snapshot_date", "block_id", "source_row", "source_col"),
)
_BALANCE_SPEC = _OverviewTableSpec(
    columns=BANKSALAD_BALANCE_COLUMNS,
    schema=BANKSALAD_BALANCE_POLARS_SCHEMA,
    path_builder=get_banksalad_balance_partition_path,
    dedup_key=BANKSALAD_BALANCE_DEDUP_KEY,
    default_sort_by=("snapshot_date", "side", "category", "item_name"),
)
_CASHFLOW_SPEC = _OverviewTableSpec(
    columns=BANKSALAD_CASHFLOW_COLUMNS,
    schema=BANKSALAD_CASHFLOW_POLARS_SCHEMA,
    path_builder=get_banksalad_cashflow_partition_path,
    dedup_key=BANKSALAD_CASHFLOW_DEDUP_KEY,
    default_sort_by=("period_month", "category"),
)
_INSURANCE_SPEC = _OverviewTableSpec(
    columns=BANKSALAD_INSURANCE_COLUMNS,
    schema=BANKSALAD_INSURANCE_POLARS_SCHEMA,
    path_builder=get_banksalad_insurance_partition_path,
    dedup_key=BANKSALAD_INSURANCE_DEDUP_KEY,
    default_sort_by=("snapshot_date", "institution", "policy_name"),
)
_INVESTMENT_SPEC = _OverviewTableSpec(
    columns=BANKSALAD_INVESTMENT_COLUMNS,
    schema=BANKSALAD_INVESTMENT_POLARS_SCHEMA,
    path_builder=get_banksalad_investment_partition_path,
    dedup_key=BANKSALAD_INVESTMENT_DEDUP_KEY,
    default_sort_by=("snapshot_date", "institution", "product_name"),
)
_LOAN_SPEC = _OverviewTableSpec(
    columns=BANKSALAD_LOAN_COLUMNS,
    schema=BANKSALAD_LOAN_POLARS_SCHEMA,
    path_builder=get_banksalad_loan_partition_path,
    dedup_key=BANKSALAD_LOAN_DEDUP_KEY,
    default_sort_by=("snapshot_date", "institution", "product_name"),
)


def read_banksalad_overview_facts_month(
    base_dir: Path,
    year: int,
    month: int,
    columns: list[str] | None = None,
) -> pl.DataFrame:
    """Read Banksalad overview facts for one month partition."""
    return _read_month(
        spec=_OVERVIEW_FACT_SPEC,
        base_dir=base_dir,
        year=year,
        month=month,
        columns=columns,
    )


def write_banksalad_overview_facts_month(
    base_dir: Path,
    df: pl.DataFrame,
    year: int,
    month: int,
    sort_by: tuple[str, ...] = ("snapshot_date", "block_id", "source_row", "source_col"),
) -> dict[str, Any]:
    """Write Banksalad overview facts to a monthly partition using atomic replace."""
    return _write_partition(
        spec=_OVERVIEW_FACT_SPEC,
        partition_path=get_banksalad_overview_facts_partition_path(base_dir, year, month),
        df=df,
        sort_by=sort_by,
    )


def append_banksalad_overview_facts(
    base_dir: Path, df: pl.DataFrame, deduplicate: bool = True
) -> dict[str, Any]:
    """Append Banksalad overview facts partitioned by ``snapshot_date``."""
    return _append_partitioned(
        spec=_OVERVIEW_FACT_SPEC,
        base_dir=base_dir,
        df=df,
        partition_column="snapshot_date",
        deduplicate=deduplicate,
    )


def read_banksalad_balance_month(
    base_dir: Path,
    year: int,
    month: int,
    columns: list[str] | None = None,
) -> pl.DataFrame:
    """Read Banksalad balance projections for one month partition."""
    return _read_month(
        spec=_BALANCE_SPEC,
        base_dir=base_dir,
        year=year,
        month=month,
        columns=columns,
    )


def write_banksalad_balance_month(
    base_dir: Path,
    df: pl.DataFrame,
    year: int,
    month: int,
    sort_by: tuple[str, ...] = ("snapshot_date", "side", "category", "item_name"),
) -> dict[str, Any]:
    """Write Banksalad balance projections to a monthly partition using atomic replace."""
    return _write_partition(
        spec=_BALANCE_SPEC,
        partition_path=get_banksalad_balance_partition_path(base_dir, year, month),
        df=df,
        sort_by=sort_by,
    )


def append_banksalad_balance(
    base_dir: Path, df: pl.DataFrame, deduplicate: bool = True
) -> dict[str, Any]:
    """Append Banksalad balance projections partitioned by ``snapshot_date``."""
    return _append_partitioned(
        spec=_BALANCE_SPEC,
        base_dir=base_dir,
        df=df,
        partition_column="snapshot_date",
        deduplicate=deduplicate,
    )


def read_banksalad_cashflow_month(
    base_dir: Path,
    year: int,
    month: int,
    columns: list[str] | None = None,
) -> pl.DataFrame:
    """Read Banksalad cashflow projections for one month partition."""
    return _read_month(
        spec=_CASHFLOW_SPEC,
        base_dir=base_dir,
        year=year,
        month=month,
        columns=columns,
    )


def write_banksalad_cashflow_month(
    base_dir: Path,
    df: pl.DataFrame,
    year: int,
    month: int,
    sort_by: tuple[str, ...] = ("period_month", "category"),
) -> dict[str, Any]:
    """Write Banksalad cashflow projections to a monthly partition using atomic replace."""
    return _write_partition(
        spec=_CASHFLOW_SPEC,
        partition_path=get_banksalad_cashflow_partition_path(base_dir, year, month),
        df=df,
        sort_by=sort_by,
    )


def append_banksalad_cashflow(
    base_dir: Path, df: pl.DataFrame, deduplicate: bool = True
) -> dict[str, Any]:
    """Append Banksalad cashflow projections.

    Rows are partitioned by ``period_month`` when populated, otherwise by the
    ``snapshot_date`` month. The stored schema always keeps both columns.
    """
    if df.height == 0:
        return _empty_append_result()

    if "period_month" not in df.columns and "snapshot_date" not in df.columns:
        raise ValueError("DataFrame must have 'period_month' or 'snapshot_date' for partitioning")

    df = _ensure_columns(df=df, spec=_CASHFLOW_SPEC)
    df = df.with_columns(_cashflow_partition_source_expr().alias("_partition_source"))
    _validate_cashflow_partition_source(df)

    return _append_partitioned(
        spec=_CASHFLOW_SPEC,
        base_dir=base_dir,
        df=df,
        partition_column="_partition_source",
        deduplicate=deduplicate,
    )


def read_banksalad_insurance_month(
    base_dir: Path,
    year: int,
    month: int,
    columns: list[str] | None = None,
) -> pl.DataFrame:
    """Read Banksalad insurance policies for one month partition."""
    return _read_month(_INSURANCE_SPEC, base_dir, year, month, columns)


def write_banksalad_insurance_month(
    base_dir: Path,
    df: pl.DataFrame,
    year: int,
    month: int,
    sort_by: tuple[str, ...] = ("snapshot_date", "institution", "policy_name"),
) -> dict[str, Any]:
    """Write Banksalad insurance policies to a monthly partition."""
    return _write_partition(
        spec=_INSURANCE_SPEC,
        partition_path=get_banksalad_insurance_partition_path(base_dir, year, month),
        df=df,
        sort_by=sort_by,
    )


def append_banksalad_insurance(
    base_dir: Path, df: pl.DataFrame, deduplicate: bool = True
) -> dict[str, Any]:
    """Append Banksalad insurance policies partitioned by ``snapshot_date``."""
    return _append_partitioned(
        spec=_INSURANCE_SPEC,
        base_dir=base_dir,
        df=df,
        partition_column="snapshot_date",
        deduplicate=deduplicate,
    )


def read_banksalad_investment_month(
    base_dir: Path,
    year: int,
    month: int,
    columns: list[str] | None = None,
) -> pl.DataFrame:
    """Read Banksalad investment positions for one month partition."""
    return _read_month(_INVESTMENT_SPEC, base_dir, year, month, columns)


def write_banksalad_investment_month(
    base_dir: Path,
    df: pl.DataFrame,
    year: int,
    month: int,
    sort_by: tuple[str, ...] = ("snapshot_date", "institution", "product_name"),
) -> dict[str, Any]:
    """Write Banksalad investment positions to a monthly partition."""
    return _write_partition(
        spec=_INVESTMENT_SPEC,
        partition_path=get_banksalad_investment_partition_path(base_dir, year, month),
        df=df,
        sort_by=sort_by,
    )


def append_banksalad_investments(
    base_dir: Path, df: pl.DataFrame, deduplicate: bool = True
) -> dict[str, Any]:
    """Append Banksalad investment positions partitioned by ``snapshot_date``."""
    return _append_partitioned(
        spec=_INVESTMENT_SPEC,
        base_dir=base_dir,
        df=df,
        partition_column="snapshot_date",
        deduplicate=deduplicate,
    )


def read_banksalad_loan_month(
    base_dir: Path,
    year: int,
    month: int,
    columns: list[str] | None = None,
) -> pl.DataFrame:
    """Read Banksalad loan positions for one month partition."""
    return _read_month(_LOAN_SPEC, base_dir, year, month, columns)


def write_banksalad_loan_month(
    base_dir: Path,
    df: pl.DataFrame,
    year: int,
    month: int,
    sort_by: tuple[str, ...] = ("snapshot_date", "institution", "product_name"),
) -> dict[str, Any]:
    """Write Banksalad loan positions to a monthly partition."""
    return _write_partition(
        spec=_LOAN_SPEC,
        partition_path=get_banksalad_loan_partition_path(base_dir, year, month),
        df=df,
        sort_by=sort_by,
    )


def append_banksalad_loans(
    base_dir: Path, df: pl.DataFrame, deduplicate: bool = True
) -> dict[str, Any]:
    """Append Banksalad loan positions partitioned by ``snapshot_date``."""
    return _append_partitioned(
        spec=_LOAN_SPEC,
        base_dir=base_dir,
        df=df,
        partition_column="snapshot_date",
        deduplicate=deduplicate,
    )


__all__ = [
    "BANKSALAD_BALANCE_DEDUP_KEY",
    "BANKSALAD_CASHFLOW_DEDUP_KEY",
    "BANKSALAD_INSURANCE_DEDUP_KEY",
    "BANKSALAD_INVESTMENT_DEDUP_KEY",
    "BANKSALAD_LOAN_DEDUP_KEY",
    "BANKSALAD_OVERVIEW_FACT_DEDUP_KEY",
    "append_banksalad_balance",
    "append_banksalad_cashflow",
    "append_banksalad_insurance",
    "append_banksalad_investments",
    "append_banksalad_loans",
    "append_banksalad_overview_facts",
    "read_banksalad_balance_month",
    "read_banksalad_cashflow_month",
    "read_banksalad_insurance_month",
    "read_banksalad_investment_month",
    "read_banksalad_loan_month",
    "read_banksalad_overview_facts_month",
    "write_banksalad_balance_month",
    "write_banksalad_cashflow_month",
    "write_banksalad_insurance_month",
    "write_banksalad_investment_month",
    "write_banksalad_loan_month",
    "write_banksalad_overview_facts_month",
]
