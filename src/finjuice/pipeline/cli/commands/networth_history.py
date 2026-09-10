"""Monthly history-row helpers for ``finjuice networth``.

Owns snapshot-to-net-worth history points, the latest as-of date, and
the history command callback. Typer parsers stay in
:mod:`finjuice.pipeline.cli.commands.networth`, which re-exports the
names used by existing callers.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import typer

from finjuice.pipeline.asset_config import AssetsConfig, load_assets_config
from finjuice.pipeline.cli.commands.networth_errors import _handle_networth_exception
from finjuice.pipeline.cli.commands.networth_payload import _emit_networth_json
from finjuice.pipeline.cli.commands.networth_rendering import _render_history
from finjuice.pipeline.cli.utils import get_config
from finjuice.pipeline.networth import (
    list_history_snapshots,
    merge_asset_sources,
    snapshot_assets_from_selection,
)

logger = logging.getLogger(__name__)


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


def _run_history_command(
    ctx: typer.Context,
    *,
    months: int,
    json_output: bool,
) -> None:
    """Run the ``finjuice networth history`` command body."""
    command = "networth history"
    try:
        config = get_config(ctx)
        assets_config = load_assets_config(config.assets_file, allow_missing_file=True)
        rows = _build_history_rows(
            config.data_dir / "assets" / "snapshots",
            assets_config,
            months=months,
        )
        as_of = _history_as_of(rows)
        payload = {"history": rows}
        if json_output:
            _emit_networth_json(
                payload,
                command=command,
                as_of=as_of,
                filters_applied=0,
            )
            return
        _render_history(rows)
    except typer.Exit:
        raise
    except Exception as exc:  # intended catch-all for CLI robustness
        logger.error("Failed to compute net worth history: %s", exc, exc_info=True)
        _handle_networth_exception(exc, json_output=json_output, command=command)
