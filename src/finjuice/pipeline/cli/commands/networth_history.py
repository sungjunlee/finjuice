"""Monthly history-row helpers for ``finjuice networth``.

Owns snapshot-to-net-worth history points and the latest as-of date.
Typer commands stay in :mod:`finjuice.pipeline.cli.commands.networth`,
which re-exports the names used by existing callers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from finjuice.pipeline.asset_config import AssetsConfig
from finjuice.pipeline.networth import (
    list_history_snapshots,
    merge_asset_sources,
    snapshot_assets_from_selection,
)


def _history_as_of(rows: list[dict[str, Any]]) -> str | None:
    """Return the latest history point's as-of date."""
    return rows[-1]["as_of"] if rows else None


def _build_history_rows(
    snapshots_dir: Path,
    assets_config: AssetsConfig,
    *,
    months: int,
) -> list[dict[str, Any]]:
    """Build monthly net-worth history points from snapshots plus assets.yaml."""
    rows: list[dict[str, Any]] = []
    for snapshot in list_history_snapshots(snapshots_dir, months):
        assets = merge_asset_sources(
            snapshot_assets_from_selection(snapshot),
            assets_config.manual_assets,
        )
        total_assets = sum(asset.value for asset in assets)
        total_liabilities = sum(liability.principal for liability in assets_config.liabilities)
        rows.append(
            {
                "as_of": snapshot.snapshot_date.isoformat(),
                "net_worth": total_assets - total_liabilities,
            }
        )
    return rows
