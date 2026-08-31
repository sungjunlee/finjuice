"""Partition path helpers for CSV storage contracts.

Owns year/month partition file path construction for transactions, asset
snapshots, and Banksalad overview tables. Schema column lists and Polars
dtypes stay in :mod:`finjuice.pipeline.storage.csv_schema`.
"""

from __future__ import annotations

from pathlib import Path


def get_partition_path(base_dir: Path, year: int, month: int) -> Path:
    """Return CSV partition file path for the given transaction year/month.

    Example:
        >>> get_partition_path(Path('data/transactions'), 2024, 10)
        PosixPath('data/transactions/2024/10/transactions.csv')
    """
    return base_dir / str(year) / f"{month:02d}" / "transactions.csv"


def get_asset_snapshot_partition_path(base_dir: Path, year: int, month: int) -> Path:
    """Return CSV partition file path for the given asset snapshot year/month."""
    return base_dir / str(year) / f"{month:02d}" / "snapshots.csv"


def get_banksalad_overview_facts_partition_path(base_dir: Path, year: int, month: int) -> Path:
    """Return Banksalad overview facts partition path for the given snapshot year/month."""
    return base_dir / str(year) / f"{month:02d}" / "facts.csv"


def get_banksalad_balance_partition_path(base_dir: Path, year: int, month: int) -> Path:
    """Return Banksalad balance projection partition path for the given snapshot year/month."""
    return base_dir / str(year) / f"{month:02d}" / "balance.csv"


def get_banksalad_cashflow_partition_path(base_dir: Path, year: int, month: int) -> Path:
    """Return Banksalad cashflow projection partition path for the given period year/month."""
    return base_dir / str(year) / f"{month:02d}" / "cashflow.csv"


def get_banksalad_insurance_partition_path(base_dir: Path, year: int, month: int) -> Path:
    """Return Banksalad insurance partition path for the given snapshot year/month."""
    return base_dir / str(year) / f"{month:02d}" / "insurance.csv"


def get_banksalad_investment_partition_path(base_dir: Path, year: int, month: int) -> Path:
    """Return Banksalad investment partition path for the given snapshot year/month."""
    return base_dir / str(year) / f"{month:02d}" / "investments.csv"


def get_banksalad_loan_partition_path(base_dir: Path, year: int, month: int) -> Path:
    """Return Banksalad loan partition path for the given snapshot year/month."""
    return base_dir / str(year) / f"{month:02d}" / "loans.csv"
