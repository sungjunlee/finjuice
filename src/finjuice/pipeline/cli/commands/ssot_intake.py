"""Submit preserved evidence, inspect decisions, and explicitly apply stored proposals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from finjuice.pipeline.cli.commands.ssot_accounts import _error, _facade
from finjuice.pipeline.cli.mutation_options import get_mutation_options, with_mutation_options
from finjuice.pipeline.cli.output import emit, info
from finjuice.pipeline.cli.utils import mutation_identity, mutation_metadata
from finjuice.pipeline.storage.mutation_facade import MutationIdentity
from finjuice.pipeline.storage.sqlite.backup_io import read_regular_bytes
from finjuice.pipeline.storage.sqlite.intake_submission import IntakeSubmission

intake_app = typer.Typer(
    help="Preserve original evidence and review explicitly supplied extraction and proposals.",
    no_args_is_help=True,
)


def _identity(ctx: typer.Context) -> MutationIdentity:
    options = get_mutation_options(ctx)
    if (
        options.expected_generation is None
        or options.expected_revision is None
        or options.idempotency_key is None
    ):
        raise ValueError("Explicit generation, revision and idempotency key are required.")
    return mutation_identity(
        options.idempotency_key, options.expected_generation, options.expected_revision
    )


def _render(payload: dict[str, Any]) -> None:
    if "decisions" in payload:
        info(f"증빙 제안: {len(payload['decisions'])}건; 리비전 {payload['dataset_revision']}")
        for decision in payload["decisions"]:
            info(
                f"{decision['proposal_id']}: {decision['status']}; "
                f"범위 {decision['application_scope']}; stale={decision['stale']}"
            )
            info(f"불확실성: {json.dumps(decision['uncertainties'], ensure_ascii=False)}")
            info(f"제안: {json.dumps(decision['proposal'], ensure_ascii=False)}")
            info(f"이전 제안: {json.dumps(decision.get('lineage'), ensure_ascii=False)}")
            successors = decision.get("successor_proposal_ids", [])
            info(f"후속 제안: {json.dumps(successors, ensure_ascii=False)}")
            _render_identity(decision)
    elif "parent_proposal_id" in payload:
        info(f"증빙 제안 수정: {payload['parent_proposal_id']} → {payload['proposal_id']}")
        info(f"이전 제안 상태: {payload['parent_status']}")
        _render_identity(payload)
    elif payload.get("status") == "rejected":
        info(f"증빙 제안 철회: {payload['proposal_id']}; 리비전 {payload['committed_revision']}")
    elif "application_key" in payload:
        info(f"증빙 제출: {payload['proposal_id']}; 리비전 {payload['committed_revision']}")
        _render_identity(payload)
    else:
        info(f"증빙 제안 적용: {payload['proposal_id']}; 리비전 {payload['committed_revision']}")
    if "replayed" in payload:
        info(f"기존 결과 재사용: {payload['replayed']}")


def _render_identity(payload: dict[str, Any]) -> None:
    info(f"확정 generation: {payload['expected_generation']}")
    info(f"확정 revision: {payload['expected_revision']}")
    info(f"확정 idempotency key: {payload['application_key']}")


@intake_app.command("submit")
@with_mutation_options
def intake_submit(
    ctx: typer.Context,
    source: Path = typer.Argument(..., help="Original description/image/workbook file"),
    metadata: Path = typer.Argument(..., help="Explicit extraction and proposal JSON document"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Preserve source bytes and supplied metadata; never infer OCR or account meaning."""
    name = "ssot intake submit"
    try:
        identity = _identity(ctx)
        body = json.loads(read_regular_bytes(metadata))
        required = {
            "source_kind",
            "media_type",
            "channel",
            "received_at",
            "extractor",
            "extraction",
            "proposal_scope",
            "proposal",
            "policy_version",
        }
        if (
            not isinstance(body, dict)
            or not required <= set(body)
            or set(body) - required - {"uncertainties"}
        ):
            raise ValueError(
                "Intake metadata requires explicit source, extraction and proposal fields."
            )
        uncertainties = body.pop("uncertainties", [])
        if not isinstance(uncertainties, list) or any(
            not isinstance(item, str) for item in uncertainties
        ):
            raise ValueError("Intake uncertainties must be a JSON array of strings.")
        assert identity.idempotency_key is not None
        assert identity.expected_generation is not None
        assert identity.expected_revision is not None
        submission = IntakeSubmission(
            **body,
            content=read_regular_bytes(source),
            actor="cli",
            idempotency_key=identity.idempotency_key,
            expected_generation=identity.expected_generation,
            expected_revision=identity.expected_revision,
            uncertainties=tuple(uncertainties),
        )
        receipt = _facade(ctx).submit_intake(submission)
        emit(
            {**receipt.result, **mutation_metadata(identity, receipt)},
            json_output,
            _render,
            command=name,
        )
    except Exception as exc:
        _error(exc, name, json_output)


@intake_app.command("list")
def intake_list(ctx: typer.Context, json_output: bool = typer.Option(False, "--json")) -> None:
    """Read one authority-bound snapshot including pending, stale and uncertain decisions."""
    name = "ssot intake list"
    try:
        emit(_facade(ctx).read_intake_decisions(), json_output, _render, command=name)
    except Exception as exc:
        _error(exc, name, json_output)


@intake_app.command("confirm")
@with_mutation_options
def intake_confirm(
    ctx: typer.Context,
    proposal_id: str = typer.Argument(...),
    confirmed_at: str = typer.Option(..., "--confirmed-at", help="Explicit confirmation timestamp"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Apply exactly the stored proposal with its explicit application identity."""
    name = "ssot intake confirm"
    try:
        identity = _identity(ctx)
        receipt = _facade(ctx).confirm_intake(
            proposal_id, identity=identity, confirmed_at=confirmed_at
        )
        emit(
            {**receipt.result, **mutation_metadata(identity, receipt)},
            json_output,
            _render,
            command=name,
        )
    except Exception as exc:
        _error(exc, name, json_output)


@intake_app.command("revise")
@with_mutation_options
def intake_revise(
    ctx: typer.Context,
    proposal_id: str = typer.Argument(...),
    request: Path = typer.Argument(
        ..., help="Parent digest, new proposal and explicit revision evidence"
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Atomically preserve a typed successor over verified source bytes; never erase its parent."""
    from finjuice.pipeline.storage.sqlite.intake_lifecycle import IntakeRevision

    name = "ssot intake revise"
    try:
        identity = _identity(ctx)
        body = json.loads(read_regular_bytes(request))
        uncertainties = body.pop("uncertainties")
        if not isinstance(uncertainties, list) or any(
            not isinstance(item, str) for item in uncertainties
        ):
            raise ValueError("Revision uncertainties must be an explicit JSON array of strings.")
        revision = IntakeRevision(
            parent_proposal_id=proposal_id, uncertainties=tuple(uncertainties), **body
        )
        receipt = _facade(ctx).revise_intake(revision, identity=identity)
        emit(
            {**receipt.result, **mutation_metadata(identity, receipt)},
            json_output,
            _render,
            command=name,
        )
    except Exception as exc:
        _error(exc, name, json_output)


@intake_app.command("withdraw")
@with_mutation_options
def intake_withdraw(
    ctx: typer.Context,
    proposal_id: str = typer.Argument(...),
    request: Path = typer.Argument(
        ..., help="Exact proposal digest, withdrawal evidence and timestamp"
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Reject an unapplied proposal; applied domain changes require a typed correction proposal."""
    from finjuice.pipeline.storage.sqlite.intake_lifecycle import IntakeWithdrawal

    name = "ssot intake withdraw"
    try:
        identity = _identity(ctx)
        body = json.loads(read_regular_bytes(request))
        withdrawal = IntakeWithdrawal(proposal_id=proposal_id, **body)
        receipt = _facade(ctx).withdraw_intake(withdrawal, identity=identity)
        emit(
            {**receipt.result, **mutation_metadata(identity, receipt)},
            json_output,
            _render,
            command=name,
        )
    except Exception as exc:
        _error(exc, name, json_output)
