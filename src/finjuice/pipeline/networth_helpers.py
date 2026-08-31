"""Aggregation compute helpers for net worth positions.

Owns converting snapshot/overview slices into asset and liability rows,
merging overlapping sources, and name-normalization used for dedup.
Public ``build_networth_position`` stays in :mod:`finjuice.pipeline.networth`,
which re-exports the public names used by existing callers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import polars as pl

from finjuice.pipeline.asset_config import (
    ASSET_CATEGORIES,
    Liability,
    ManualAsset,
)


@dataclass(frozen=True)
class AggregatedAsset:
    """One asset included in an aggregated net worth view."""

    name: str
    category: str
    value: float
    source: str


@dataclass(frozen=True)
class SnapshotSelection:
    """Selected snapshot slice for one effective date."""

    month: str
    snapshot_date: date
    frame: pl.DataFrame


@dataclass(frozen=True)
class BalanceSelection:
    """Selected Banksalad overview balance slice for one effective date."""

    month: str
    snapshot_date: date
    frame: pl.DataFrame


def snapshot_assets_from_selection(selection: SnapshotSelection | None) -> list[AggregatedAsset]:
    """Convert one snapshot slice into aggregated per-asset rows."""
    if selection is None or selection.frame.is_empty():
        return []

    grouped = (
        selection.frame.group_by("instrument_id")
        .agg(pl.col("market_value").sum().alias("value"))
        .sort("value", descending=True)
    )
    return [
        AggregatedAsset(
            name=str(row["instrument_id"]),
            category="financial",
            value=float(row["value"] or 0.0),
            source="snapshot",
        )
        for row in grouped.to_dicts()
    ]


def balance_assets_from_selection(selection: BalanceSelection | None) -> list[AggregatedAsset]:
    """Convert one overview balance slice into asset rows."""
    if selection is None or selection.frame.is_empty():
        return []

    assets_df = _balance_side_frame(selection.frame, "asset")
    return [
        AggregatedAsset(
            name=str(row["item_name"]),
            category=_normalize_overview_asset_category(str(row["category"] or "")),
            value=float(row["amount"] or 0.0),
            source="overview",
        )
        for row in assets_df.to_dicts()
    ]


def balance_liabilities_from_selection(selection: BalanceSelection | None) -> list[Liability]:
    """Convert one overview balance slice into liability rows."""
    if selection is None or selection.frame.is_empty():
        return []

    liabilities_df = _balance_side_frame(selection.frame, "liability")
    return [
        Liability(
            name=str(row["item_name"]),
            principal=float(row["amount"] or 0.0),
            type=str(row["category"]) if row["category"] is not None else None,
        )
        for row in liabilities_df.to_dicts()
    ]


def merge_asset_sources(
    snapshot_assets: list[AggregatedAsset],
    manual_assets: list[ManualAsset],
) -> list[AggregatedAsset]:
    """Merge snapshot and manual assets with manual precedence on name match."""
    merged: dict[str, AggregatedAsset] = {
        normalize_asset_name(asset.name): asset for asset in snapshot_assets
    }

    for asset in manual_assets:
        merged[normalize_asset_name(asset.name)] = AggregatedAsset(
            name=asset.name,
            category=asset.category,
            value=asset.value,
            source="manual",
        )

    return sorted(merged.values(), key=lambda asset: (-asset.value, asset.name))


def merge_liability_sources(
    overview_liabilities: list[Liability],
    manual_liabilities: list[Liability],
) -> list[Liability]:
    """Merge overview and manual liabilities with manual precedence on name match."""
    merged: dict[str, Liability] = {
        normalize_asset_name(liability.name): liability for liability in overview_liabilities
    }

    for liability in manual_liabilities:
        merged[normalize_asset_name(liability.name)] = liability

    return sorted(merged.values(), key=lambda liability: (-liability.principal, liability.name))


def normalize_asset_name(name: str) -> str:
    """Normalize an asset name for exact dedup matching."""
    return name.strip().casefold()


def _balance_side_frame(frame: pl.DataFrame, side: str) -> pl.DataFrame:
    return (
        frame.filter(pl.col("side") == side)
        .group_by(["category", "item_name", "currency"])
        .agg(pl.col("amount").sum().alias("amount"))
        .sort("amount", descending=True)
    )


def _normalize_overview_asset_category(category: str) -> str:
    normalized = category.strip().casefold()
    return normalized if normalized in ASSET_CATEGORIES else "other"
