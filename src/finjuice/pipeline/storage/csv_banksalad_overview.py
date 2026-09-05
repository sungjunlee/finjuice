"""Banksalad overview workbook CSV partition CRUD.

ADR-0013 stores source-fidelity overview facts separately from typed balance
and cashflow projections. These helpers intentionally mirror the transaction
and asset snapshot partition API while keeping the overview contracts isolated.

Table-driven partition I/O lives in
:mod:`finjuice.pipeline.storage.csv_banksalad_overview_helpers`.
Cashflow partition-source helpers live in
:mod:`finjuice.pipeline.storage.csv_banksalad_overview_cashflow` and are
re-exported here so existing callers can keep importing from this module.
Write/append helpers live in
:mod:`finjuice.pipeline.storage.csv_banksalad_overview_write` and are
re-exported here so existing callers can keep importing from this module.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from finjuice.pipeline.storage.csv_banksalad_overview_cashflow import (
    _cashflow_partition_source_expr,  # noqa: F401 — re-exported for existing overview imports
    _validate_cashflow_partition_source,  # noqa: F401 — re-exported for existing overview imports
)
from finjuice.pipeline.storage.csv_banksalad_overview_helpers import (
    _OverviewTableSpec,
    _read_month,
)
from finjuice.pipeline.storage.csv_banksalad_overview_write import (
    append_banksalad_balance,
    append_banksalad_cashflow,
    append_banksalad_insurance,
    append_banksalad_investments,
    append_banksalad_loans,
    append_banksalad_overview_facts,
    write_banksalad_balance_month,
    write_banksalad_cashflow_month,
    write_banksalad_insurance_month,
    write_banksalad_investment_month,
    write_banksalad_loan_month,
    write_banksalad_overview_facts_month,
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


def read_banksalad_insurance_month(
    base_dir: Path,
    year: int,
    month: int,
    columns: list[str] | None = None,
) -> pl.DataFrame:
    """Read Banksalad insurance policies for one month partition."""
    return _read_month(_INSURANCE_SPEC, base_dir, year, month, columns)


def read_banksalad_investment_month(
    base_dir: Path,
    year: int,
    month: int,
    columns: list[str] | None = None,
) -> pl.DataFrame:
    """Read Banksalad investment positions for one month partition."""
    return _read_month(_INVESTMENT_SPEC, base_dir, year, month, columns)


def read_banksalad_loan_month(
    base_dir: Path,
    year: int,
    month: int,
    columns: list[str] | None = None,
) -> pl.DataFrame:
    """Read Banksalad loan positions for one month partition."""
    return _read_month(_LOAN_SPEC, base_dir, year, month, columns)


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
