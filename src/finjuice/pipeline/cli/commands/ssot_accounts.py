"""Explicit account source confirmation/correction and canonical account reads."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from finjuice.pipeline.cli.mutation_options import get_mutation_options, with_mutation_options
from finjuice.pipeline.cli.output import ErrorCode, ExitCode, emit, emit_error, info
from finjuice.pipeline.cli.utils import get_mutation_facade, mutation_identity, mutation_metadata
from finjuice.pipeline.config import Config
from finjuice.pipeline.storage.mutation_facade import StorageMutationFacade
from finjuice.pipeline.storage.sqlite.account_bindings import AccountBindingConfirmation
from finjuice.pipeline.storage.sqlite.backup_io import read_regular_bytes

account_app = typer.Typer(
    help="Inspect canonical accounts and explicitly bind source identities.", no_args_is_help=True
)


def _facade(ctx: typer.Context) -> StorageMutationFacade:
    config = ctx.obj.get("config")
    if config is None:
        config = Config(data_dir=ctx.obj["active_data_dir"])
    return get_mutation_facade(ctx, config)


def _render(payload: dict[str, Any]) -> None:
    info(f"리비전: {payload.get('dataset_revision', payload.get('committed_revision'))}")
    if "binding_id" in payload:
        info(f"계좌 연결 확정: {payload['binding_id']}")
    for account in payload.get("accounts", []):
        info(
            f"계좌 {account['account_id']}: {account['display_name']} "
            f"({account['ownership_state']})"
        )
    for binding in payload.get("bindings", []):
        info(
            f"연결 {binding['binding_id']} → {binding['account_id']}, "
            f"교정 대상: {binding['supersedes_binding_id']}"
        )
    for item in payload.get("candidates", []):
        info(
            f"{item['source_namespace']} / {item['external_key']}: "
            f"{item['status']} → {item['account_id']}"
        )
    if "as_of" in payload:
        info(json.dumps(payload, ensure_ascii=False))


def _error(exc: Exception, command: str, json_output: bool) -> None:
    emit_error(
        str(exc),
        error_code=ErrorCode.VALIDATION_FAILED,
        exit_code=ExitCode.VALIDATION_ERROR,
        json_output=json_output,
        command=command,
    )


@account_app.command("list")
def account_list(ctx: typer.Context, json_output: bool = typer.Option(False, "--json")) -> None:
    """List accounts, exact source candidates and immutable confirmation history."""
    try:
        emit(
            _facade(ctx).read_account_bindings(), json_output, _render, command="ssot account list"
        )
    except Exception as exc:
        _error(exc, "ssot account list", json_output)


def _confirm(ctx: typer.Context, request: Path, previous: str | None, json_output: bool) -> None:
    command_name = "ssot account correct" if previous else "ssot account confirm"
    try:
        payload = json.loads(read_regular_bytes(request))
        if not isinstance(payload, dict) or set(payload) != {
            "source_namespace",
            "external_key",
            "account_id",
            "evidence",
        }:
            raise ValueError(
                "Binding request requires source_namespace, external_key, account_id and evidence."
            )
        decision = AccountBindingConfirmation(**payload, supersedes_binding_id=previous)
        options = get_mutation_options(ctx)
        if (
            options.expected_generation is None
            or options.expected_revision is None
            or options.idempotency_key is None
        ):
            raise ValueError(
                "Confirmation requires explicit generation, revision and idempotency key."
            )
        identity = mutation_identity(
            options.idempotency_key, options.expected_generation, options.expected_revision
        )
        receipt = _facade(ctx).confirm_account_binding(decision, identity=identity)
        emit(
            {**receipt.result, **mutation_metadata(identity, receipt)},
            json_output,
            _render,
            command=command_name,
        )
    except Exception as exc:
        _error(exc, command_name, json_output)


@account_app.command("confirm")
@with_mutation_options
def account_confirm(
    ctx: typer.Context,
    request: Path = typer.Argument(...),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Confirm an exact source binding from an explicit JSON request file."""
    _confirm(ctx, request, None, json_output)


@account_app.command("correct")
@with_mutation_options
def account_correct(
    ctx: typer.Context,
    binding_id: str = typer.Argument(...),
    request: Path = typer.Argument(...),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Append a correction of the named current binding; retain the original evidence."""
    _confirm(ctx, request, binding_id, json_output)


@account_app.command("ownership")
def account_ownership(
    ctx: typer.Context,
    account_id: str = typer.Argument(...),
    as_of: str = typer.Option(..., "--as-of"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Read exact confirmed ownership as of a date without household aggregation."""
    try:
        emit(
            _facade(ctx).read_account_ownership(account_id, as_of=as_of),
            json_output,
            _render,
            command="ssot account ownership",
        )
    except Exception as exc:
        _error(exc, "ssot account ownership", json_output)


@account_app.command("preview")
def account_preview(
    ctx: typer.Context,
    request: Path = typer.Argument(...),
    corrects: str | None = typer.Option(None, "--corrects"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Preview binding impact; pass its generation/revision to confirm or correct."""
    try:
        payload = json.loads(read_regular_bytes(request))
        command = AccountBindingConfirmation(**payload, supersedes_binding_id=corrects)
        preview = _facade(ctx).preview_account_binding(command)
        emit(dict(preview.result), json_output, _render_decision, command="ssot account preview")
    except Exception as exc:
        _error(exc, "ssot account preview", json_output)


def _render_decision(payload: dict[str, Any]) -> None:
    if "observed_scope" in payload:
        info(f"계좌 연결 미리보기: 관측 근거 {len(payload['observed_scope'])}건")
        info("기존 거래·자산은 변경하지 않습니다. 새 import에만 적용됩니다.")
        info(f"확인에 사용할 generation: {payload['expected_generation']}")
        info(f"확인에 사용할 revision: {payload['expected_revision']}")
    else:
        info(f"소유권 확정: {payload['assertion_id']}")
        info(f"교정 대상: {payload['supersedes_assertion_id']}")
    info(json.dumps(payload, ensure_ascii=False))


def _ownership_decision(
    ctx: typer.Context, request: Path, previous: str | None, json_output: bool
) -> None:
    from finjuice.pipeline.storage.sqlite.account_decisions import (
        OwnershipDecision,
        OwnershipShareDecision,
    )

    name = "ssot account ownership-correct" if previous else "ssot account ownership-confirm"
    try:
        payload = json.loads(read_regular_bytes(request))
        shares = tuple(OwnershipShareDecision(**share) for share in payload.pop("shares"))
        command = OwnershipDecision(**payload, shares=shares, supersedes_assertion_id=previous)
        options = get_mutation_options(ctx)
        if (
            options.expected_generation is None
            or options.expected_revision is None
            or options.idempotency_key is None
        ):
            raise ValueError(
                "Confirmation requires explicit generation, revision and idempotency key."
            )
        identity = mutation_identity(
            options.idempotency_key, options.expected_generation, options.expected_revision
        )
        receipt = _facade(ctx).confirm_ownership(command, identity=identity)
        emit(
            {**receipt.result, **mutation_metadata(identity, receipt)},
            json_output,
            _render_decision,
            command=name,
        )
    except Exception as exc:
        _error(exc, name, json_output)


@account_app.command("ownership-confirm")
@with_mutation_options
def ownership_confirm(
    ctx: typer.Context,
    request: Path = typer.Argument(...),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Confirm exact party shares, effective dates and explicit evidence from JSON."""
    _ownership_decision(ctx, request, None, json_output)


@account_app.command("ownership-correct")
@with_mutation_options
def ownership_correct(
    ctx: typer.Context,
    assertion_id: str = typer.Argument(...),
    request: Path = typer.Argument(...),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Correct ownership by appending a confirmed successor; retain prior evidence."""
    _ownership_decision(ctx, request, assertion_id, json_output)
