"""JSON payload assembly helpers for ``finjuice networth``.

Owns as-of date parsing, aggregated position payload construction, and
the custom JSON envelope. Typer commands stay in
:mod:`finjuice.pipeline.cli.commands.networth`, which re-exports the
names used by existing callers.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import typer

from finjuice.pipeline.cli.commands.networth_guidance import _build_networth_guidance
from finjuice.pipeline.cli.output import _build_meta
from finjuice.pipeline.cli.utils import get_config
from finjuice.pipeline.networth import build_networth_position


def _parse_as_of(raw_value: str | None) -> date | None:
    """Parse an ISO date option."""
    if raw_value is None:
        return None
    return date.fromisoformat(raw_value)


def _resolve_as_of(ctx: typer.Context, date_value: str | None) -> date | None:
    """Resolve the effective as-of date for networth subcommands."""
    if date_value is not None:
        return _parse_as_of(date_value)

    parent_ctx = ctx.parent
    if parent_ctx is None:
        return None

    parent_date_value = parent_ctx.params.get("date_value")
    if parent_date_value is None:
        return None

    return _parse_as_of(str(parent_date_value))


def _emit_networth_json(
    payload: dict[str, Any],
    *,
    command: str,
    as_of: str | None,
    filters_applied: int,
    extras: dict[str, Any] | None = None,
) -> None:
    """Emit JSON with the custom networth envelope."""
    meta_extras = {
        "filters_applied": filters_applied,
        "as_of": as_of,
    }
    if extras:
        meta_extras.update(extras)
    meta = _build_meta(command, extras=meta_extras)
    typer.echo(json.dumps({"_meta": meta, **payload}, ensure_ascii=False, indent=2))


def _build_networth_result(
    ctx: typer.Context,
    *,
    as_of: date | None,
    json_output: bool,
    command: str,
) -> dict[str, Any]:
    """Build the aggregated net worth payload."""
    config = get_config(ctx)
    position = build_networth_position(
        config.data_dir / "assets" / "snapshots",
        config.assets_file,
        as_of=as_of,
        balance_dir=config.data_dir / "banksalad" / "balance",
    )
    resolved_as_of = position.as_of.isoformat() if position.as_of is not None else None

    return {
        "as_of": resolved_as_of,
        "total_assets": position.total_assets,
        "total_liabilities": position.total_liabilities,
        "net_worth": position.net_worth,
        **_build_networth_guidance(
            assets=position.assets,
            liabilities=position.liabilities,
            net_worth=position.net_worth,
            primary_source=position.primary_source,
        ),
        "_assets": position.assets,
        "_liabilities": position.liabilities,
        "_filters_applied": 0,
    }
