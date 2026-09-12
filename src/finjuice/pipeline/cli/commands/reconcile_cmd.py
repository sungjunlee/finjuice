"""CLI for evidence vs ledger reconciliation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from finjuice.pipeline.cli import output
from finjuice.pipeline.cli.output import ErrorCode, emit, emit_error
from finjuice.pipeline.cli.utils import get_config
from finjuice.pipeline.reconcile import DEFAULT_WINDOW_DAYS, reconcile
from finjuice.pipeline.reconcile.json_io import evidence_from_payload, report_to_payload
from finjuice.pipeline.reconcile.payments import payments_from_ledger


def _render_reconcile(result: dict[str, Any]) -> None:
    """Render a privacy-safe reconcile summary."""
    output.success("[OK] Reconcile complete:")
    output.info(f"  Evidence: {result['evidence_count']}")
    output.info(f"  Payments: {result['payment_count']}")
    output.info(f"  Matched: {result['matched']}")
    output.info(f"  Partial: {result['partial']}")
    output.info(f"  Unmatched: {result['unmatched']}")


def reconcile_command(
    ctx: typer.Context,
    evidence: Path = typer.Option(
        ...,
        "--evidence",
        help="JSON file of purchase/order/receipt evidence (not the ledger SSOT)",
        exists=True,
        readable=True,
    ),
    window_days: int = typer.Option(
        DEFAULT_WINDOW_DAYS,
        "--window-days",
        help="Max day gap between evidence and ledger payment",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Match evidence to ledger payments without writing transactions.

    Missing Banksalad months leave evidence unmatched. Email/order exports are
    evidence only and are never treated as the ledger SSOT.
    """
    config = get_config(ctx)
    try:
        payload = json.loads(evidence.read_text(encoding="utf-8"))
        items = evidence_from_payload(payload)
        payments = payments_from_ledger(config.csv_base_dir)
        report = reconcile(items, payments, window_days=window_days)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        emit_error(
            f"Reconcile failed: {error}",
            error_code=ErrorCode.VALIDATION_FAILED,
            json_output=json_output,
            command="reconcile",
        )
    emit(report_to_payload(report), json_output, _render_reconcile, command="reconcile")
