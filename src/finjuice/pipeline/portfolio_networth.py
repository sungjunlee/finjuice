"""Net worth calculated from one detached repository portfolio snapshot."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import polars as pl

from finjuice.pipeline.asset_config import AssetsConfig, load_assets_config_bytes
from finjuice.pipeline.networth import NetWorthPosition, build_networth_position_from_selections
from finjuice.pipeline.networth_helpers import BalanceSelection, SnapshotSelection
from finjuice.pipeline.portfolio_display import PortfolioDisplay, PortfolioDisplayError
from finjuice.pipeline.storage.sqlite.portfolio_reads import PortfolioConfigSnapshot


def _assets_config(selection: PortfolioConfigSnapshot) -> tuple[AssetsConfig, str]:
    if selection.selection_state == "absent" and not selection.revisions:
        return AssetsConfig(), "canonical_absence_empty.v1"
    head = selection.head
    if selection.selection_state != "selected" or head is None or head.parsed_status != "parsed":
        raise PortfolioDisplayError("Repository assets configuration requires a valid selection.")
    try:
        return load_assets_config_bytes(head.content), "selected_assets_config.v1"
    except Exception:
        raise PortfolioDisplayError(
            "Selected repository assets configuration is invalid."
        ) from None


def _select_partition(
    months: tuple[str, ...],
    partition: Callable[[str], pl.DataFrame | None],
    as_of: date | None,
) -> SnapshotSelection | None:
    month_limit = as_of.strftime("%Y-%m") if as_of else None
    for month in reversed(months):
        if month_limit is not None and month > month_limit:
            continue
        frame = partition(month)
        if frame is None or frame.is_empty():
            continue
        eligible = (
            frame if as_of is None else frame.filter(pl.col("snapshot_date") <= as_of.isoformat())
        )
        if eligible.is_empty():
            continue
        raw_date = eligible.select(pl.col("snapshot_date").max()).item()
        if raw_date is None:
            continue
        selected_date = date.fromisoformat(str(raw_date))
        return SnapshotSelection(
            month,
            selected_date,
            eligible.filter(pl.col("snapshot_date") == selected_date.isoformat()),
        )
    return None


def build_repository_networth(
    display: PortfolioDisplay, *, as_of: date | None = None
) -> tuple[NetWorthPosition, dict[str, object]]:
    """Apply legacy selection/calculation semantics without reading live files."""
    try:
        assets, policy = _assets_config(display.snapshot.assets)
        snapshot = _select_partition(display.snapshot_months, display.snapshot_partition, as_of)
        balance = _select_partition(display.balance_months, display.balance_partition, as_of)
        balance_selection = (
            BalanceSelection(balance.month, balance.snapshot_date, balance.frame)
            if balance is not None
            else None
        )
        position = build_networth_position_from_selections(
            snapshot, assets, as_of=as_of, balance_selection=balance_selection
        )
        metadata = {
            **display.metadata(),
            "manual_config_policy": policy,
            "assets_selection_state": display.snapshot.assets.selection_state,
            "as_of": position.as_of.isoformat() if position.as_of else None,
        }
        return position, metadata
    except PortfolioDisplayError:
        raise
    except Exception:
        raise PortfolioDisplayError("Repository net worth evidence cannot be calculated.") from None
