"""Monthly history from a single detached portfolio revision."""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl

from finjuice.pipeline.networth_helpers import (
    SnapshotSelection,
    merge_asset_sources,
    snapshot_assets_from_selection,
)
from finjuice.pipeline.portfolio_display import PortfolioDisplay, PortfolioDisplayError
from finjuice.pipeline.portfolio_networth import _assets_config


def build_repository_history(
    display: PortfolioDisplay, *, months: int
) -> tuple[list[dict[str, Any]], dict[str, object]]:
    """Preserve partition ordering and apply the same current manual config to all points."""
    try:
        assets, policy = _assets_config(display.snapshot.assets)
        rows: list[dict[str, Any]] = []
        for month in reversed(display.snapshot_months) if months > 0 else ():
            if len(rows) >= months:
                break
            frame = display.snapshot_partition(month)
            if frame is None or frame.is_empty():
                continue
            raw_date = frame.select(pl.col("snapshot_date").max()).item()
            if raw_date is None:
                continue
            selected_date = date.fromisoformat(str(raw_date))
            selection = SnapshotSelection(
                month,
                selected_date,
                frame.filter(pl.col("snapshot_date") == selected_date.isoformat()),
            )
            combined = merge_asset_sources(
                snapshot_assets_from_selection(selection), assets.manual_assets
            )
            rows.append(
                {
                    "as_of": selected_date.isoformat(),
                    "net_worth": sum(asset.value for asset in combined)
                    - sum(liability.principal for liability in assets.liabilities),
                }
            )
        rows.reverse()
        return rows, {
            **display.metadata(),
            "calculation_policy": "legacy_networth_history.v1",
            "manual_config_policy": policy,
            "assets_selection_state": display.snapshot.assets.selection_state,
            "as_of": rows[-1]["as_of"] if rows else None,
        }
    except PortfolioDisplayError:
        raise
    except Exception:
        raise PortfolioDisplayError("Repository net worth history cannot be calculated.") from None
