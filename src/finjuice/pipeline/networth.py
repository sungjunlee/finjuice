"""Shared asset snapshot + net worth aggregation helpers.

Asset/liability conversion, source merging, and name-normalization helpers
live in :mod:`finjuice.pipeline.networth_helpers` and are re-exported here so
existing callers can keep importing from this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from finjuice.pipeline.asset_config import (
    Liability,
    load_assets_config,
)
from finjuice.pipeline.networth_helpers import (
    AggregatedAsset,
    BalanceSelection,
    SnapshotSelection,
    _balance_side_frame,  # noqa: F401 — re-exported for existing networth imports
    _normalize_overview_asset_category,  # noqa: F401 — re-exported for existing networth imports
    balance_assets_from_selection,
    balance_liabilities_from_selection,
    merge_asset_sources,
    merge_liability_sources,
    normalize_asset_name,  # noqa: F401 — re-exported for existing networth imports
    snapshot_assets_from_selection,
)
from finjuice.pipeline.storage.csv_banksalad_overview import read_banksalad_balance_month
from finjuice.pipeline.storage.csv_schema import ASSET_SNAPSHOT_POLARS_SCHEMA


@dataclass(frozen=True)
class NetWorthPosition:
    """Aggregated net worth state for one effective date."""

    as_of: date | None
    assets: list[AggregatedAsset]
    liabilities: list[Liability]
    total_assets: float
    total_liabilities: float
    net_worth: float
    primary_source: str = "manual"


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


def build_networth_position(
    snapshots_dir: Path,
    assets_file: Path,
    *,
    as_of: date | None = None,
    balance_dir: Path | None = None,
) -> NetWorthPosition:
    """Return the aggregated net worth state for one effective date."""
    balance_selection = (
        select_balance_as_of(balance_dir, as_of) if balance_dir is not None else None
    )
    snapshot_selection = select_snapshot_as_of(snapshots_dir, as_of)
    assets_config = load_assets_config(assets_file, allow_missing_file=True)

    source_assets = (
        balance_assets_from_selection(balance_selection)
        if balance_selection is not None
        else snapshot_assets_from_selection(snapshot_selection)
    )
    assets = merge_asset_sources(
        source_assets,
        assets_config.manual_assets,
    )
    overview_liabilities = balance_liabilities_from_selection(balance_selection)
    liabilities = merge_liability_sources(overview_liabilities, assets_config.liabilities)
    total_assets = sum(asset.value for asset in assets)
    total_liabilities = sum(liability.principal for liability in liabilities)
    resolved_as_of = (
        as_of
        if as_of is not None
        else balance_selection.snapshot_date
        if balance_selection is not None
        else snapshot_selection.snapshot_date
        if snapshot_selection is not None
        else None
    )

    primary_source = (
        "overview"
        if balance_selection is not None
        else "snapshot"
        if snapshot_selection is not None
        else "manual"
    )

    return NetWorthPosition(
        as_of=resolved_as_of,
        assets=assets,
        liabilities=liabilities,
        total_assets=total_assets,
        total_liabilities=total_liabilities,
        net_worth=total_assets - total_liabilities,
        primary_source=primary_source,
    )


def build_breakdown_rows(
    assets: list[AggregatedAsset],
    *,
    by: str,
) -> list[dict[str, Any]]:
    """Build category- or asset-level breakdown rows."""
    total_assets = sum(asset.value for asset in assets)
    if by == "asset":
        rows = [
            {
                "asset_name": asset.name,
                "value": asset.value,
                "share_pct": _share_pct(asset.value, total_assets),
            }
            for asset in assets
        ]
        return rows

    grouped: dict[str, float] = {}
    for asset in assets:
        grouped[asset.category] = grouped.get(asset.category, 0.0) + asset.value

    return [
        {
            "category": category,
            "value": value,
            "share_pct": _share_pct(value, total_assets),
        }
        for category, value in sorted(grouped.items(), key=lambda item: (-item[1], item[0]))
    ]


def _share_pct(value: float, total: float) -> float:
    """Return a percentage share for one asset bucket."""
    if total <= 0:
        return 0.0
    return round((value / total) * 100.0, 2)
