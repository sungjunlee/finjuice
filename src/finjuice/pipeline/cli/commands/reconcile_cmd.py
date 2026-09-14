"""CLI for evidence vs ledger reconciliation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import typer

from finjuice.pipeline.cli import output
from finjuice.pipeline.cli.output import ErrorCode, emit, emit_error
from finjuice.pipeline.cli.utils import get_activation_evidence_provider, get_config
from finjuice.pipeline.reconcile import DEFAULT_WINDOW_DAYS, reconcile
from finjuice.pipeline.reconcile.exact_calculation import calculation_limits, reconcile_exact
from finjuice.pipeline.reconcile.json_io import evidence_from_payload, report_to_payload
from finjuice.pipeline.reconcile.payments import payments_from_ledger
from finjuice.pipeline.reconcile.repository import read_repository_payments


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
    evidence only and are never treated as the ledger SSOT. Canonical payment IDs
    are transaction UUIDs. Unknown canonical dates or currencies fail explicitly.
    """
    config = get_config(ctx)
    metadata: dict[str, Any] | None = None
    try:
        source = read_repository_payments(config.data_dir, get_activation_evidence_provider(ctx))
        evidence_bytes = evidence.read_bytes()
        payload = json.loads(evidence_bytes.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Evidence document must be an object.")
        items = evidence_from_payload(payload)
        if source is None:
            payments = payments_from_ledger(config.csv_base_dir)
            report = reconcile(items, payments, window_days=window_days)
        else:
            report = reconcile_exact(items, source.payments, window_days=window_days)
            metadata = {
                **source.metadata,
                "calculation_limits": calculation_limits(),
                "window_days": window_days,
                "evidence_input": {
                    "basis": "external_file",
                    "sha256": hashlib.sha256(evidence_bytes).hexdigest(),
                },
            }
    except Exception:
        emit_error(
            "Reconcile could not be computed from valid evidence and authoritative payments.",
            error_code=ErrorCode.VALIDATION_FAILED,
            json_output=json_output,
            command="reconcile",
        )
        raise AssertionError("emit_error must exit") from None
    if metadata and not json_output:
        output.info(f"Repository revision: {metadata['dataset_revision']} (payment IDs: UUID)")
    emit(
        report_to_payload(report),
        json_output,
        _render_reconcile,
        command="reconcile",
        meta_extras=metadata,
    )
