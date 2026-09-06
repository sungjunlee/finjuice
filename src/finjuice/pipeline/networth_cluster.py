"""Snapshot and Banksalad balance partition selection helpers.

Owns discovering available months, loading CSV partitions, and selecting
the latest slice on or before an as-of date. Public
``build_networth_position`` stays in :mod:`finjuice.pipeline.networth`,
which re-exports these names so existing callers can keep importing from
that module.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

from finjuice.pipeline.networth_helpers import BalanceSelection, SnapshotSelection
from finjuice.pipeline.storage.csv_banksalad_overview import read_banksalad_balance_month
from finjuice.pipeline.storage.csv_schema import ASSET_SNAPSHOT_POLARS_SCHEMA


def discover_snapshot_months(snapshots_dir: Path) -> list[str]:
    """Return sorted list of available snapshot months (YYYY-MM)."""
    months: list[str] = []
    if not snapshots_dir.exists():
        return months

    for year_dir in sorted(snapshots_dir.iterdir()):
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue
        for month_dir in sorted(year_dir.iterdir()):
            if not month_dir.is_dir() or not month_dir.name.isdigit():
                continue
            if (month_dir / "snapshots.csv").exists():
                months.append(f"{year_dir.name}-{month_dir.name}")
    return months


def discover_balance_months(balance_dir: Path) -> list[str]:
    """Return sorted list of available Banksalad balance months (YYYY-MM)."""
    months: list[str] = []
    if not balance_dir.exists():
        return months

    for year_dir in sorted(balance_dir.iterdir()):
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue
        for month_dir in sorted(year_dir.iterdir()):
            if not month_dir.is_dir() or not month_dir.name.isdigit():
                continue
            if (month_dir / "balance.csv").exists():
                months.append(f"{year_dir.name}-{month_dir.name}")
    return months


def load_snapshot_partition(snapshots_dir: Path, month: str) -> pl.DataFrame | None:
    """Load one snapshot partition by YYYY-MM."""
    year, mon = month.split("-", 1)
    csv_file = snapshots_dir / year / mon / "snapshots.csv"
    if not csv_file.exists():
        return None

    return pl.read_csv(
        csv_file,
        schema_overrides=ASSET_SNAPSHOT_POLARS_SCHEMA,
        null_values=["", "NA", "NULL"],
    )


def load_latest_snapshot_partition(snapshots_dir: Path) -> tuple[pl.DataFrame | None, str | None]:
    """Load the latest snapshot partition and return (df, YYYY-MM)."""
    months = discover_snapshot_months(snapshots_dir)
    if not months:
        return None, None

    latest = months[-1]
    return load_snapshot_partition(snapshots_dir, latest), latest


def load_balance_partition(balance_dir: Path, month: str) -> pl.DataFrame | None:
    """Load one Banksalad balance partition by YYYY-MM."""
    year, mon = month.split("-", 1)
    return read_banksalad_balance_month(balance_dir, int(year), int(mon))


def load_latest_balance_partition(balance_dir: Path) -> tuple[pl.DataFrame | None, str | None]:
    """Load the latest Banksalad balance partition and return (df, YYYY-MM)."""
    months = discover_balance_months(balance_dir)
    if not months:
        return None, None

    latest = months[-1]
    return load_balance_partition(balance_dir, latest), latest


def select_snapshot_as_of(
    snapshots_dir: Path,
    as_of: date | None = None,
) -> SnapshotSelection | None:
    """Return the latest snapshot slice on or before *as_of*."""
    months = discover_snapshot_months(snapshots_dir)
    if not months:
        return None

    month_limit = as_of.strftime("%Y-%m") if as_of is not None else None
    candidate_months = [month for month in months if month_limit is None or month <= month_limit]

    for month in reversed(candidate_months):
        df = load_snapshot_partition(snapshots_dir, month)
        if df is None or df.is_empty():
            continue

        eligible = df
        if as_of is not None:
            eligible = eligible.filter(pl.col("snapshot_date") <= as_of.isoformat())

        if eligible.is_empty():
            continue

        selected_date_raw = eligible.select(pl.col("snapshot_date").max()).to_series()[0]
        if selected_date_raw is None:
            continue

        selected_date = date.fromisoformat(str(selected_date_raw))
        selected_frame = eligible.filter(pl.col("snapshot_date") == selected_date.isoformat())
        return SnapshotSelection(month=month, snapshot_date=selected_date, frame=selected_frame)

    return None


def select_balance_as_of(
    balance_dir: Path,
    as_of: date | None = None,
) -> BalanceSelection | None:
    """Return the latest Banksalad overview balance slice on or before *as_of*."""
    months = discover_balance_months(balance_dir)
    if not months:
        return None

    month_limit = as_of.strftime("%Y-%m") if as_of is not None else None
    candidate_months = [month for month in months if month_limit is None or month <= month_limit]

    for month in reversed(candidate_months):
        df = load_balance_partition(balance_dir, month)
        if df is None or df.is_empty():
            continue

        eligible = df
        if as_of is not None:
            eligible = eligible.filter(pl.col("snapshot_date") <= as_of.isoformat())

        if eligible.is_empty():
            continue

        selected_date_raw = eligible.select(pl.col("snapshot_date").max()).to_series()[0]
        if selected_date_raw is None:
            continue

        selected_date = date.fromisoformat(str(selected_date_raw))
        selected_frame = eligible.filter(pl.col("snapshot_date") == selected_date.isoformat())
        return BalanceSelection(month=month, snapshot_date=selected_date, frame=selected_frame)

    return None


def list_history_snapshots(snapshots_dir: Path, months: int) -> list[SnapshotSelection]:
    """Return up to *months* monthly snapshot points, oldest-to-newest."""
    if months <= 0:
        return []

    selections: list[SnapshotSelection] = []
    for month in reversed(discover_snapshot_months(snapshots_dir)):
        if len(selections) >= months:
            break

        df = load_snapshot_partition(snapshots_dir, month)
        if df is None or df.is_empty():
            continue

        selected_date_raw = df.select(pl.col("snapshot_date").max()).to_series()[0]
        if selected_date_raw is None:
            continue

        selected_date = date.fromisoformat(str(selected_date_raw))
        selected_frame = df.filter(pl.col("snapshot_date") == selected_date.isoformat())
        selections.append(
            SnapshotSelection(month=month, snapshot_date=selected_date, frame=selected_frame)
        )

    return list(reversed(selections))
