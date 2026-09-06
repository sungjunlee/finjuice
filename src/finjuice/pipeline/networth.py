"""Shared asset snapshot + net worth aggregation helpers.

Asset/liability conversion, source merging, and name-normalization helpers
live in :mod:`finjuice.pipeline.networth_helpers`. Snapshot and Banksalad
balance partition discovery, loading, and as-of selection live in
:mod:`finjuice.pipeline.networth_cluster`. Both are re-exported here so
existing callers can keep importing from this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from finjuice.pipeline.asset_config import (
    Liability,
    load_assets_config,
)
from finjuice.pipeline.networth_cluster import (
    discover_balance_months,  # noqa: F401 — re-exported for existing networth imports
    discover_snapshot_months,  # noqa: F401 — re-exported for existing networth imports
    list_history_snapshots,  # noqa: F401 — re-exported for existing networth imports
    load_balance_partition,  # noqa: F401 — re-exported for existing networth imports
    load_latest_balance_partition,  # noqa: F401 — re-exported for existing networth imports
    load_latest_snapshot_partition,  # noqa: F401 — re-exported for existing networth imports
    load_snapshot_partition,  # noqa: F401 — re-exported for existing networth imports
    select_balance_as_of,
    select_snapshot_as_of,
)
from finjuice.pipeline.networth_helpers import (
    AggregatedAsset,
    BalanceSelection,  # noqa: F401 — re-exported for existing networth imports
    SnapshotSelection,  # noqa: F401 — re-exported for existing networth imports
    _balance_side_frame,  # noqa: F401 — re-exported for existing networth imports
    _normalize_overview_asset_category,  # noqa: F401 — re-exported for existing networth imports
    balance_assets_from_selection,
    balance_liabilities_from_selection,
    merge_asset_sources,
    merge_liability_sources,
    normalize_asset_name,  # noqa: F401 — re-exported for existing networth imports
    snapshot_assets_from_selection,
)


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
