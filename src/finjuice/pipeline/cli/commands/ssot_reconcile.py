"""Canonical purchase/order settlement evidence and explicit N:M decisions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from finjuice.pipeline.cli.commands.ssot_accounts import _error, _facade
from finjuice.pipeline.cli.commands.ssot_intake import _identity
from finjuice.pipeline.cli.mutation_options import with_mutation_options
from finjuice.pipeline.cli.output import emit, info
from finjuice.pipeline.cli.utils import mutation_metadata
from finjuice.pipeline.reconcile.canonical import (
    AllocationConfirmation,
    AllocationWithdrawal,
    EvidenceSubmission,
    PurchaseEvidence,
)
from finjuice.pipeline.storage.sqlite.backup_io import read_regular_bytes

reconcile_app = typer.Typer(
    help="Preserve purchase evidence and review exact N:M ledger settlements.", no_args_is_help=True
)


def _render(payload: dict[str, Any]) -> None:
    info("구매 증빙은 별도 현금 지출로 합산하지 않습니다.")
    if "candidates" in payload:
        info(
            f"대사 후보 {len(payload['candidates'])}건; "
            f"확정/철회 이력 {len(payload['allocations'])}건"
        )
    info(json.dumps(payload, ensure_ascii=False))


def _document(path: Path) -> dict[str, Any]:
    body = json.loads(read_regular_bytes(path))
    if not isinstance(body, dict):
        raise ValueError("Reconciliation request must be a JSON object.")
    return body


@reconcile_app.command("submit")
@with_mutation_options
def submit(
    ctx: typer.Context,
    source: Path,
    metadata: Path,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Preserve original bytes and explicit purchase/order/line-item/payment evidence.

    Metadata: source_namespace, received_at, items. Each item explicitly names
    external_key, evidence_kind, occurred_on, amount (decimal string), currency,
    settlement_unit, detail, optional parent_external_key and transaction_id.
    Positive evidence is a purchase; negative evidence is a refund.
    """
    name = "ssot reconcile submit"
    try:
        identity = _identity(ctx)
        body = _document(metadata)
        items = tuple(PurchaseEvidence(**item) for item in body.pop("items"))
        command = EvidenceSubmission(**body, content=read_regular_bytes(source), items=items)
        receipt = _facade(ctx).import_reconcile_evidence(command, identity=identity)
        emit(
            {**receipt.result, **mutation_metadata(identity, receipt)},
            json_output,
            _render,
            command=name,
        )
    except Exception as exc:
        _error(exc, name, json_output)


@reconcile_app.command("candidates")
def candidates(
    ctx: typer.Context,
    window_days: int = typer.Option(14, "--window-days", min=0),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Explain exact candidates, residuals and immutable decisions; never apply guesses."""
    name = "ssot reconcile candidates"
    try:
        emit(
            _facade(ctx).read_reconcile_evidence(window_days=window_days),
            json_output,
            _render,
            command=name,
        )
    except Exception as exc:
        _error(exc, name, json_output)


@reconcile_app.command("confirm")
@with_mutation_options
def confirm(
    ctx: typer.Context, request: Path, json_output: bool = typer.Option(False, "--json")
) -> None:
    """Confirm evidence_ids/payment_ids and reviewed expected_residual/currency with reason/time."""
    name = "ssot reconcile confirm"
    try:
        identity = _identity(ctx)
        body = _document(request)
        body["evidence_ids"] = tuple(body["evidence_ids"])
        body["payment_ids"] = tuple(body["payment_ids"])
        receipt = _facade(ctx).confirm_reconcile(AllocationConfirmation(**body), identity=identity)
        emit(
            {**receipt.result, **mutation_metadata(identity, receipt)},
            json_output,
            _render,
            command=name,
        )
    except Exception as exc:
        _error(exc, name, json_output)


@reconcile_app.command("withdraw")
@with_mutation_options
def withdraw(
    ctx: typer.Context, request: Path, json_output: bool = typer.Option(False, "--json")
) -> None:
    """Append allocation_id/reason/withdrawn_at; regrouping requires a new explicit confirmation."""
    name = "ssot reconcile withdraw"
    try:
        identity = _identity(ctx)
        receipt = _facade(ctx).withdraw_reconcile(
            AllocationWithdrawal(**_document(request)), identity=identity
        )
        emit(
            {**receipt.result, **mutation_metadata(identity, receipt)},
            json_output,
            _render,
            command=name,
        )
    except Exception as exc:
        _error(exc, name, json_output)
