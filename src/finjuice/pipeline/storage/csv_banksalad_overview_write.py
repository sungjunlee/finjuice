"""Write and append helpers for Banksalad overview CSV partitions.

Owns monthly partition writes and append-with-dedup for overview facts,
balance, cashflow, insurance, investment, and loan tables. Public overview
readers stay in :mod:`finjuice.pipeline.storage.csv_banksalad_overview`,
which re-exports these names so existing callers can keep importing from
that module.
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
    _write_partition,
)
from finjuice.pipeline.storage.csv_schema import (
    get_banksalad_balance_partition_path,
    get_banksalad_cashflow_partition_path,
    get_banksalad_insurance_partition_path,
    get_banksalad_investment_partition_path,
    get_banksalad_loan_partition_path,
    get_banksalad_overview_facts_partition_path,
)


def write_banksalad_overview_facts_month(
    base_dir: Path,
    df: pl.DataFrame,
    year: int,
    month: int,
    sort_by: tuple[str, ...] = ("snapshot_date", "block_id", "source_row", "source_col"),
) -> dict[str, Any]:
    """Write Banksalad overview facts to a monthly partition using atomic replace."""
    from finjuice.pipeline.storage.csv_banksalad_overview import _OVERVIEW_FACT_SPEC

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
    from finjuice.pipeline.storage.csv_banksalad_overview import _OVERVIEW_FACT_SPEC

    return _append_partitioned(
        spec=_OVERVIEW_FACT_SPEC,
        base_dir=base_dir,
        df=df,
        partition_column="snapshot_date",
        deduplicate=deduplicate,
    )


def write_banksalad_balance_month(
    base_dir: Path,
    df: pl.DataFrame,
    year: int,
    month: int,
    sort_by: tuple[str, ...] = ("snapshot_date", "side", "category", "item_name"),
) -> dict[str, Any]:
    """Write Banksalad balance projections to a monthly partition using atomic replace."""
    from finjuice.pipeline.storage.csv_banksalad_overview import _BALANCE_SPEC

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
    from finjuice.pipeline.storage.csv_banksalad_overview import _BALANCE_SPEC

    return _append_partitioned(
        spec=_BALANCE_SPEC,
        base_dir=base_dir,
        df=df,
        partition_column="snapshot_date",
        deduplicate=deduplicate,
    )


def write_banksalad_cashflow_month(
    base_dir: Path,
    df: pl.DataFrame,
    year: int,
    month: int,
    sort_by: tuple[str, ...] = ("period_month", "category"),
) -> dict[str, Any]:
    """Write Banksalad cashflow projections to a monthly partition using atomic replace."""
    from finjuice.pipeline.storage.csv_banksalad_overview import _CASHFLOW_SPEC

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
    from finjuice.pipeline.storage.csv_banksalad_overview import _CASHFLOW_SPEC

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


def write_banksalad_insurance_month(
    base_dir: Path,
    df: pl.DataFrame,
    year: int,
    month: int,
    sort_by: tuple[str, ...] = ("snapshot_date", "institution", "policy_name"),
) -> dict[str, Any]:
    """Write Banksalad insurance policies to a monthly partition."""
    from finjuice.pipeline.storage.csv_banksalad_overview import _INSURANCE_SPEC

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
    from finjuice.pipeline.storage.csv_banksalad_overview import _INSURANCE_SPEC

    return _append_partitioned(
        spec=_INSURANCE_SPEC,
        base_dir=base_dir,
        df=df,
        partition_column="snapshot_date",
        deduplicate=deduplicate,
    )


def write_banksalad_investment_month(
    base_dir: Path,
    df: pl.DataFrame,
    year: int,
    month: int,
    sort_by: tuple[str, ...] = ("snapshot_date", "institution", "product_name"),
) -> dict[str, Any]:
    """Write Banksalad investment positions to a monthly partition."""
    from finjuice.pipeline.storage.csv_banksalad_overview import _INVESTMENT_SPEC

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
    from finjuice.pipeline.storage.csv_banksalad_overview import _INVESTMENT_SPEC

    return _append_partitioned(
        spec=_INVESTMENT_SPEC,
        base_dir=base_dir,
        df=df,
        partition_column="snapshot_date",
        deduplicate=deduplicate,
    )


def write_banksalad_loan_month(
    base_dir: Path,
    df: pl.DataFrame,
    year: int,
    month: int,
    sort_by: tuple[str, ...] = ("snapshot_date", "institution", "product_name"),
) -> dict[str, Any]:
    """Write Banksalad loan positions to a monthly partition."""
    from finjuice.pipeline.storage.csv_banksalad_overview import _LOAN_SPEC

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
    from finjuice.pipeline.storage.csv_banksalad_overview import _LOAN_SPEC

    return _append_partitioned(
        spec=_LOAN_SPEC,
        base_dir=base_dir,
        df=df,
        partition_column="snapshot_date",
        deduplicate=deduplicate,
    )


__all__ = [
    "append_banksalad_balance",
    "append_banksalad_cashflow",
    "append_banksalad_insurance",
    "append_banksalad_investments",
    "append_banksalad_loans",
    "append_banksalad_overview_facts",
    "write_banksalad_balance_month",
    "write_banksalad_cashflow_month",
    "write_banksalad_insurance_month",
    "write_banksalad_investment_month",
    "write_banksalad_loan_month",
    "write_banksalad_overview_facts_month",
]
