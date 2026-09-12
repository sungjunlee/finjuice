"""Aggregated net worth CLI commands.

JSON payload assembly helpers live in
:mod:`finjuice.pipeline.cli.commands.networth_payload` and are re-exported
here so existing callers can keep importing from this module. Forecast
scenario serialization helpers live in
:mod:`finjuice.pipeline.cli.commands.networth_forecast`. Monthly history-row
helpers live in :mod:`finjuice.pipeline.cli.commands.networth_history`. JSON
health/action guidance helpers live in
:mod:`finjuice.pipeline.cli.commands.networth_guidance`. Validation and
runtime error envelopes live in
:mod:`finjuice.pipeline.cli.commands.networth_errors`. assets.yaml
init/validate helpers live in
:mod:`finjuice.pipeline.cli.commands.networth_helpers`.

Typer parsers stay here. Overview/breakdown, history, and forecast
callback bodies live beside the payload, history, and forecast modules.
"""

from __future__ import annotations

from typing import Literal

import typer

from finjuice.pipeline.cli.commands.networth_errors import (
    _handle_networth_exception,  # noqa: F401 — re-exported for existing networth imports
    _raise_goals_validation_error,  # noqa: F401 — re-exported for existing networth imports
    _validation_issue_to_problem,  # noqa: F401 — re-exported for existing networth imports
)
from finjuice.pipeline.cli.commands.networth_forecast import (
    _build_all_scenario_forecasts,  # noqa: F401 — re-exported for existing networth imports
    _forecast_start_as_of,  # noqa: F401 — re-exported for existing networth imports
    _run_forecast_command,
    _serialize_forecast_scenario,  # noqa: F401 — re-exported for existing networth imports
)
from finjuice.pipeline.cli.commands.networth_guidance import (
    _build_networth_guidance,  # noqa: F401 — re-exported for existing networth imports
    _build_networth_signals,  # noqa: F401 — re-exported for existing networth imports
    _build_source_flags,  # noqa: F401 — re-exported for existing networth imports
    _resolve_snapshot_status,  # noqa: F401 — re-exported for existing networth imports
)
from finjuice.pipeline.cli.commands.networth_helpers import (
    _assets_init_payload,  # noqa: F401 — re-exported for existing networth imports
    _build_validate_payload,  # noqa: F401 — re-exported for existing networth imports
    _emit_assets_file_json,  # noqa: F401 — re-exported for existing networth imports
    _run_init_command,
    _run_validate_command,
    _write_starter_assets_yaml,  # noqa: F401 — re-exported for existing networth imports
)
from finjuice.pipeline.cli.commands.networth_history import (
    _build_history_rows,  # noqa: F401 — re-exported for existing networth imports
    _history_as_of,  # noqa: F401 — re-exported for existing networth imports
    _run_history_command,
)
from finjuice.pipeline.cli.commands.networth_payload import (
    _build_networth_result,  # noqa: F401 — re-exported for existing networth imports
    _emit_networth_json,  # noqa: F401 — re-exported for existing networth imports
    _parse_as_of,  # noqa: F401 — re-exported for existing networth imports
    _resolve_as_of,  # noqa: F401 — re-exported for existing networth imports
    _run_breakdown_command,
    _run_overview_command,
)

networth_app = typer.Typer(
    name="networth",
    help=(
        "View aggregated net worth from asset snapshots plus assets.yaml. "
        "Use `finjuice assets` for raw snapshot rows."
    ),
    invoke_without_command=True,
    no_args_is_help=False,
)


@networth_app.callback(invoke_without_command=True)
def networth_callback(
    ctx: typer.Context,
    date_value: str | None = typer.Option(None, "--date", help="Snapshot date (YYYY-MM-DD)"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show aggregated net worth from snapshots + assets.yaml."""
    if ctx.invoked_subcommand is not None:
        return
    _run_overview_command(ctx, date_value=date_value, json_output=json_output)


@networth_app.command()
def breakdown(
    ctx: typer.Context,
    by: Literal["category", "asset"] = typer.Option(
        ...,
        "--by",
        help="Break down by category or asset",
    ),
    date_value: str | None = typer.Option(None, "--date", help="Snapshot date (YYYY-MM-DD)"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show aggregated asset breakdown by category or asset."""
    _run_breakdown_command(ctx, by=by, date_value=date_value, json_output=json_output)


@networth_app.command()
def history(
    ctx: typer.Context,
    months: int = typer.Option(6, "--months", min=1, help="Max monthly points to return"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show monthly net worth history from available snapshots."""
    _run_history_command(ctx, months=months, json_output=json_output)


@networth_app.command()
def forecast(
    ctx: typer.Context,
    years: int = typer.Option(5, "--years", min=1, max=100, help="Forecast horizon in years"),
    scenario: Literal["conservative", "neutral", "optimistic", "all"] = typer.Option(
        "neutral",
        "--scenario",
        help="Scenario: conservative, neutral, optimistic, all",
    ),
    from_value: str | None = typer.Option(None, "--from", help="Forecast start date (YYYY-MM-DD)"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Project net worth under deterministic scenario assumptions."""
    _run_forecast_command(
        ctx,
        years=years,
        scenario=scenario,
        from_value=from_value,
        json_output=json_output,
    )


@networth_app.command("init")
def init_command(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Create a starter assets.yaml from the built-in template."""
    _run_init_command(ctx, json_output=json_output)


@networth_app.command("validate")
def validate_command(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Validate assets.yaml and report line-numbered errors."""
    _run_validate_command(ctx, json_output=json_output)
