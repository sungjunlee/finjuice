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

from finjuice.pipeline.storage.authority import legacy_write_lease
from finjuice.pipeline.storage.csv_banksalad_overview_cashflow import (
    _cashflow_partition_source_expr,
    _validate_cashflow_partition_source,
)
from finjuice.pipeline.storage.csv_banksalad_overview_helpers import (
    _append_partitioned,
    _empty_append_result,
    _ensure_columns,
    _OverviewTableSpec,
    _write_partition,
)
from finjuice.pipeline.storage.sqlite.objects import _assert_no_symlink_ancestors


def write_banksalad_overview_facts_month(
    df: pl.DataFrame,
    year: int,
    month: int,
    sort_by: tuple[str, ...] = ("snapshot_date", "block_id", "source_row", "source_col"),
    *,
    authority_data_dir: Path,
) -> dict[str, Any]:
    """Write Banksalad overview facts to a monthly partition using atomic replace."""
    from finjuice.pipeline.storage.csv_banksalad_overview import _OVERVIEW_FACT_SPEC

    return _leased_write_partition(
        (_OVERVIEW_FACT_SPEC, "overview_facts"), df, (year, month), sort_by, authority_data_dir
    )


def append_banksalad_overview_facts(
    df: pl.DataFrame,
    deduplicate: bool = True,
    *,
    authority_data_dir: Path,
) -> dict[str, Any]:
    """Append Banksalad overview facts partitioned by ``snapshot_date``."""
    from finjuice.pipeline.storage.csv_banksalad_overview import _OVERVIEW_FACT_SPEC

    return _leased_append_table(
        (_OVERVIEW_FACT_SPEC, "overview_facts"),
        df,
        "snapshot_date",
        deduplicate,
        authority_data_dir,
    )


def write_banksalad_balance_month(
    df: pl.DataFrame,
    year: int,
    month: int,
    sort_by: tuple[str, ...] = ("snapshot_date", "side", "category", "item_name"),
    *,
    authority_data_dir: Path,
) -> dict[str, Any]:
    """Write Banksalad balance projections to a monthly partition using atomic replace."""
    from finjuice.pipeline.storage.csv_banksalad_overview import _BALANCE_SPEC

    return _leased_write_partition(
        (_BALANCE_SPEC, "balance"), df, (year, month), sort_by, authority_data_dir
    )


def append_banksalad_balance(
    df: pl.DataFrame,
    deduplicate: bool = True,
    *,
    authority_data_dir: Path,
) -> dict[str, Any]:
    """Append Banksalad balance projections partitioned by ``snapshot_date``."""
    from finjuice.pipeline.storage.csv_banksalad_overview import _BALANCE_SPEC

    return _leased_append_table(
        (_BALANCE_SPEC, "balance"), df, "snapshot_date", deduplicate, authority_data_dir
    )


def write_banksalad_cashflow_month(
    df: pl.DataFrame,
    year: int,
    month: int,
    sort_by: tuple[str, ...] = ("period_month", "category"),
    *,
    authority_data_dir: Path,
) -> dict[str, Any]:
    """Write Banksalad cashflow projections to a monthly partition using atomic replace."""
    from finjuice.pipeline.storage.csv_banksalad_overview import _CASHFLOW_SPEC

    return _leased_write_partition(
        (_CASHFLOW_SPEC, "cashflow"), df, (year, month), sort_by, authority_data_dir
    )


def append_banksalad_cashflow(
    df: pl.DataFrame,
    deduplicate: bool = True,
    *,
    authority_data_dir: Path,
) -> dict[str, Any]:
    """Append Banksalad cashflow projections.

    Rows are partitioned by ``period_month`` when populated, otherwise by the
    ``snapshot_date`` month. The stored schema always keeps both columns.
    """
    from finjuice.pipeline.storage.csv_banksalad_overview import _CASHFLOW_SPEC

    base_dir, authority_data_dir = _authority_overview_root(authority_data_dir, "cashflow")
    with legacy_write_lease(authority_data_dir):
        return _append_cashflow_unleased(_CASHFLOW_SPEC, base_dir, df, deduplicate)


def write_banksalad_insurance_month(
    df: pl.DataFrame,
    year: int,
    month: int,
    sort_by: tuple[str, ...] = ("snapshot_date", "institution", "policy_name"),
    *,
    authority_data_dir: Path,
) -> dict[str, Any]:
    """Write Banksalad insurance policies to a monthly partition."""
    from finjuice.pipeline.storage.csv_banksalad_overview import _INSURANCE_SPEC

    return _leased_write_partition(
        (_INSURANCE_SPEC, "insurance"), df, (year, month), sort_by, authority_data_dir
    )


def append_banksalad_insurance(
    df: pl.DataFrame,
    deduplicate: bool = True,
    *,
    authority_data_dir: Path,
) -> dict[str, Any]:
    """Append Banksalad insurance policies partitioned by ``snapshot_date``."""
    from finjuice.pipeline.storage.csv_banksalad_overview import _INSURANCE_SPEC

    return _leased_append_table(
        (_INSURANCE_SPEC, "insurance"), df, "snapshot_date", deduplicate, authority_data_dir
    )


def write_banksalad_investment_month(
    df: pl.DataFrame,
    year: int,
    month: int,
    sort_by: tuple[str, ...] = ("snapshot_date", "institution", "product_name"),
    *,
    authority_data_dir: Path,
) -> dict[str, Any]:
    """Write Banksalad investment positions to a monthly partition."""
    from finjuice.pipeline.storage.csv_banksalad_overview import _INVESTMENT_SPEC

    return _leased_write_partition(
        (_INVESTMENT_SPEC, "investments"), df, (year, month), sort_by, authority_data_dir
    )


def append_banksalad_investments(
    df: pl.DataFrame,
    deduplicate: bool = True,
    *,
    authority_data_dir: Path,
) -> dict[str, Any]:
    """Append Banksalad investment positions partitioned by ``snapshot_date``."""
    from finjuice.pipeline.storage.csv_banksalad_overview import _INVESTMENT_SPEC

    return _leased_append_table(
        (_INVESTMENT_SPEC, "investments"), df, "snapshot_date", deduplicate, authority_data_dir
    )


def write_banksalad_loan_month(
    df: pl.DataFrame,
    year: int,
    month: int,
    sort_by: tuple[str, ...] = ("snapshot_date", "institution", "product_name"),
    *,
    authority_data_dir: Path,
) -> dict[str, Any]:
    """Write Banksalad loan positions to a monthly partition."""
    from finjuice.pipeline.storage.csv_banksalad_overview import _LOAN_SPEC

    return _leased_write_partition(
        (_LOAN_SPEC, "loans"), df, (year, month), sort_by, authority_data_dir
    )


def append_banksalad_loans(
    df: pl.DataFrame,
    deduplicate: bool = True,
    *,
    authority_data_dir: Path,
) -> dict[str, Any]:
    """Append Banksalad loan positions partitioned by ``snapshot_date``."""
    from finjuice.pipeline.storage.csv_banksalad_overview import _LOAN_SPEC

    return _leased_append_table(
        (_LOAN_SPEC, "loans"), df, "snapshot_date", deduplicate, authority_data_dir
    )


def _leased_write_partition(
    spec_table: tuple[_OverviewTableSpec, str],
    df: pl.DataFrame,
    year_month: tuple[int, int],
    sort_by: tuple[str, ...],
    authority_data_dir: Path,
) -> dict[str, Any]:
    spec, table = spec_table
    base_dir, authority_data_dir = _authority_overview_root(authority_data_dir, table)
    year, month = year_month
    with legacy_write_lease(authority_data_dir):
        return _write_partition(
            spec=spec,
            partition_path=spec.path_builder(base_dir, year, month),
            df=df,
            sort_by=sort_by,
        )


def _leased_append_table(
    spec_table: tuple[_OverviewTableSpec, str],
    df: pl.DataFrame,
    partition_column: str,
    deduplicate: bool,
    authority_data_dir: Path,
) -> dict[str, Any]:
    spec, table = spec_table
    base_dir, authority_data_dir = _authority_overview_root(authority_data_dir, table)
    with legacy_write_lease(authority_data_dir):
        return _append_partitioned(
            spec=spec,
            base_dir=base_dir,
            df=df,
            partition_column=partition_column,
            deduplicate=deduplicate,
        )


def _append_cashflow_unleased(
    spec: _OverviewTableSpec,
    base_dir: Path,
    df: pl.DataFrame,
    deduplicate: bool,
) -> dict[str, Any]:
    if df.height == 0:
        return _empty_append_result()
    if "period_month" not in df.columns and "snapshot_date" not in df.columns:
        raise ValueError("DataFrame must have 'period_month' or 'snapshot_date' for partitioning")
    df = _ensure_columns(df=df, spec=spec)
    df = df.with_columns(_cashflow_partition_source_expr().alias("_partition_source"))
    _validate_cashflow_partition_source(df)
    return _append_partitioned(
        spec=spec,
        base_dir=base_dir,
        df=df,
        partition_column="_partition_source",
        deduplicate=deduplicate,
    )


def _authority_overview_root(authority_data_dir: Path, table: str) -> tuple[Path, Path]:
    """Return the only overview table root allowed beneath an explicit data authority."""
    normalized_data_dir = authority_data_dir.expanduser().absolute()
    table_root = normalized_data_dir / "banksalad" / table
    _assert_no_symlink_ancestors(table_root, allow_missing=True)
    return table_root, normalized_data_dir


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
