"""JSON payload assembly helpers for ``finjuice networth``.

Owns as-of date parsing, aggregated position payload construction, the
custom JSON envelope, and the overview/breakdown command callbacks.
Typer parsers stay in :mod:`finjuice.pipeline.cli.commands.networth`,
which re-exports the names used by existing callers.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any, Literal

import typer

from finjuice.pipeline.cli.commands.assets_reads import load_portfolio_display
from finjuice.pipeline.cli.commands.networth_errors import _handle_networth_exception
from finjuice.pipeline.cli.commands.networth_guidance import _build_networth_guidance
from finjuice.pipeline.cli.commands.networth_rendering import (
    _render_breakdown,
    _render_overview,
)
from finjuice.pipeline.cli.output import _build_meta, info
from finjuice.pipeline.cli.utils import get_config
from finjuice.pipeline.networth import build_breakdown_rows, build_networth_position
from finjuice.pipeline.portfolio_networth import build_repository_networth

logger = logging.getLogger(__name__)


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
    display = load_portfolio_display(ctx, config.data_dir)
    metadata: dict[str, object] | None = None
    if display is None:
        position = build_networth_position(
            config.data_dir / "assets" / "snapshots",
            config.assets_file,
            as_of=as_of,
            balance_dir=config.data_dir / "banksalad" / "balance",
        )
    else:
        position, metadata = build_repository_networth(display, as_of=as_of)
    if metadata is not None and not json_output:
        info(
            f"Repository revision {metadata['dataset_revision']} "
            f"({metadata['dataset_generation']}); policy {metadata['calculation_policy']}; "
            f"as of {metadata['as_of'] or 'undated'}; "
            f"assets {metadata['assets_selection_state']} ({metadata['manual_config_policy']})"
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
        "_repository_metadata": metadata,
    }


def _run_overview_command(
    ctx: typer.Context,
    *,
    date_value: str | None,
    json_output: bool,
) -> None:
    """Run the default ``finjuice networth`` command body."""
    try:
        result = _build_networth_result(
            ctx,
            as_of=_parse_as_of(date_value),
            json_output=json_output,
            command="networth",
        )
        json_result = {key: value for key, value in result.items() if not key.startswith("_")}
        if json_output:
            _emit_networth_json(
                json_result,
                command="networth",
                as_of=result["as_of"],
                filters_applied=result["_filters_applied"],
                extras=result.get("_repository_metadata"),
            )
            return
        _render_overview(result)
    except typer.Exit:
        raise
    except Exception as exc:  # intended catch-all for CLI robustness
        logger.error("Failed to compute net worth (%s)", type(exc).__name__)
        _handle_networth_exception(exc, json_output=json_output, command="networth")


def _run_breakdown_command(
    ctx: typer.Context,
    *,
    by: Literal["category", "asset"],
    date_value: str | None,
    json_output: bool,
) -> None:
    """Run the ``finjuice networth breakdown`` command body."""
    try:
        result = _build_networth_result(
            ctx,
            as_of=_resolve_as_of(ctx, date_value),
            json_output=json_output,
            command="networth breakdown",
        )
        rows = build_breakdown_rows(result["_assets"], by=by)
        payload = {
            "as_of": result["as_of"],
            "breakdown": rows,
        }
        if json_output:
            _emit_networth_json(
                payload,
                command="networth breakdown",
                as_of=result["as_of"],
                filters_applied=result["_filters_applied"],
                extras=result.get("_repository_metadata"),
            )
            return
        _render_breakdown(result["as_of"], rows, by=by)
    except typer.Exit:
        raise
    except Exception as exc:  # intended catch-all for CLI robustness
        logger.error("Failed to compute net worth breakdown (%s)", type(exc).__name__)
        _handle_networth_exception(exc, json_output=json_output, command="networth breakdown")
