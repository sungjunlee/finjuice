"""Freeze immutable canonical month closes, reopen explicitly and read close history."""

from __future__ import annotations

from typing import Any

import typer

from finjuice.pipeline.cli.commands.ssot_accounts import _error, _facade
from finjuice.pipeline.cli.commands.ssot_intake import _identity
from finjuice.pipeline.cli.mutation_options import with_mutation_options
from finjuice.pipeline.cli.output import emit, info
from finjuice.pipeline.cli.utils import mutation_metadata
from finjuice.pipeline.close.canonical import ASSET_SCOPES, CloseCommand, ReopenCommand

close_app = typer.Typer(
    help="Record immutable month close revisions and explicit reopen lineage.",
    no_args_is_help=True,
)


def _render_close(payload: dict[str, Any]) -> None:
    close = payload["close"]
    info(
        f"{close['period']} 마감 리비전 {close['close_revision']} "
        f"({close['completeness']}, 데이터셋 리비전 {close['dataset_revision']})"
    )
    for currency, totals in close["totals"]["transactions"].items():
        info(f"  {currency}: 수입 {totals['income']} 지출 {totals['expense']} 순액 {totals['net']}")
    for name, count in close["unresolved"].items():
        info(f"  미해결 {name}: {count}건")
    for change in payload["diff"]:
        info(f"  차이: {change.get('field')} ({change.get('reason')})")


def _render_history(payload: dict[str, Any]) -> None:
    for period, state in payload["periods"].items():
        info(
            f"{period}: {state['state']} 리비전 {state['close_revision']} ({state['completeness']})"
        )
    for revision in payload["revisions"]:
        digest = str(revision["report_digest"])[:12]
        info(f"  {revision['period']} r{revision['close_revision']} {digest}")


def _render(payload: dict[str, Any]) -> None:
    if "close" in payload:
        _render_close(payload)
    elif "revisions" in payload:
        _render_history(payload)
    else:
        info(f"마감 {payload['period']} 리비전 {payload['close_revision']} 재개방")


@close_app.command("run")
@with_mutation_options
def run(
    ctx: typer.Context,
    period: str = typer.Option(..., "--period", help="Closed month as YYYY-MM"),
    source_as_of: str = typer.Option(..., "--source-as-of", help="Timezone-aware source as-of"),
    calculation_policy: str = typer.Option(..., "--calculation-policy"),
    closed_at: str = typer.Option(..., "--closed-at", help="Timezone-aware close timestamp"),
    reason: str = typer.Option(..., "--reason"),
    asset_scope: str = typer.Option(ASSET_SCOPES[0], "--asset-scope"),
    party_id: list[str] = typer.Option([], "--party-id"),
    source_id: list[str] = typer.Option([], "--source-id"),
    valuation_currency: str | None = typer.Option(None, "--valuation-currency"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Freeze exact per-currency totals; a still-closed month must be reopened first."""
    name = "ssot close run"
    try:
        identity = _identity(ctx)
        command = CloseCommand(
            period=period,
            source_as_of=source_as_of,
            calculation_policy=calculation_policy,
            closed_at=closed_at,
            reason=reason,
            asset_scope=asset_scope,
            party_ids=tuple(party_id),
            source_ids=tuple(source_id),
            valuation_currency=valuation_currency,
        )
        receipt = _facade(ctx).close_period(command, identity=identity)
        emit(
            {**receipt.result, **mutation_metadata(identity, receipt)},
            json_output,
            _render,
            command=name,
        )
    except Exception as exc:
        _error(exc, name, json_output)


@close_app.command("reopen")
@with_mutation_options
def reopen(
    ctx: typer.Context,
    period: str = typer.Option(..., "--period"),
    reason: str = typer.Option(..., "--reason"),
    reopened_at: str = typer.Option(..., "--reopened-at"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Reopen the newest close revision without undoing later recorded transactions."""
    name = "ssot close reopen"
    try:
        identity = _identity(ctx)
        command = ReopenCommand(period=period, reason=reason, reopened_at=reopened_at)
        receipt = _facade(ctx).reopen_period(command, identity=identity)
        emit(
            {**receipt.result, **mutation_metadata(identity, receipt)},
            json_output,
            _render,
            command=name,
        )
    except Exception as exc:
        _error(exc, name, json_output)


@close_app.command("history")
def history(
    ctx: typer.Context,
    period: str = typer.Option(None, "--period"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Regenerate stored close reports from frozen facts and read their history."""
    name = "ssot close history"
    try:
        emit(_facade(ctx).read_close_history(period=period), json_output, _render, command=name)
    except Exception as exc:
        _error(exc, name, json_output)


__all__ = ["close_app"]
