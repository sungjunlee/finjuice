"""Source-backed asset meaning and exact declared-scope reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from finjuice.pipeline.cli.commands.ssot_accounts import _error, _facade
from finjuice.pipeline.cli.mutation_options import get_mutation_options, with_mutation_options
from finjuice.pipeline.cli.output import emit, info
from finjuice.pipeline.cli.utils import mutation_identity, mutation_metadata
from finjuice.pipeline.storage.sqlite.asset_meanings import AssetMeaningDecision
from finjuice.pipeline.storage.sqlite.asset_reports import AssetRelationDecision, AssetReportQuery
from finjuice.pipeline.storage.sqlite.backup_io import read_regular_bytes

assets_app = typer.Typer(
    help="Confirm source-backed asset meanings and report exact scoped ownership.",
    no_args_is_help=True,
)


def _render(payload: dict[str, Any]) -> None:
    if "completeness" in payload:
        info(f"명시 범위 자산 보고: {payload['completeness']}")
        info(f"검토 항목: {len(payload['issues'])}건; 평가금액은 현금흐름이 아닙니다.")
    elif "assertion_id" in payload:
        info(f"자산 결정 기록: {payload['assertion_id']}")
    else:
        info(f"자산 원본 후보: {len(payload['sources'])}건")
    info(json.dumps(payload, ensure_ascii=False))


@assets_app.command("list")
def asset_list(ctx: typer.Context, json_output: bool = typer.Option(False, "--json")) -> None:
    """List original source identities, pending meanings and immutable decision history."""
    try:
        emit(_facade(ctx).read_canonical_assets(), json_output, _render, command="ssot assets list")
    except Exception as exc:
        _error(exc, "ssot assets list", json_output)


def _decide(
    ctx: typer.Context, path: Path, previous: str | None, relation: bool, json_output: bool
) -> None:
    verb = "correct" if previous else "confirm"
    name = f"ssot assets {'relation-' if relation else ''}{verb}"
    try:
        body = json.loads(read_regular_bytes(path))
        options = get_mutation_options(ctx)
        if (
            options.expected_generation is None
            or options.expected_revision is None
            or options.idempotency_key is None
        ):
            raise ValueError("Explicit generation, revision and idempotency key are required.")
        identity = mutation_identity(
            options.idempotency_key, options.expected_generation, options.expected_revision
        )
        facade = _facade(ctx)
        if relation:
            relation_command = AssetRelationDecision(**body, supersedes_assertion_id=previous)
            receipt = facade.confirm_asset_relation(relation_command, identity=identity)
        else:
            meaning = AssetMeaningDecision(**body, supersedes_assertion_id=previous)
            receipt = facade.confirm_asset_meaning(meaning, identity=identity)
        emit(
            {**receipt.result, **mutation_metadata(identity, receipt)},
            json_output,
            _render,
            command=name,
        )
    except Exception as exc:
        _error(exc, name, json_output)


@assets_app.command("confirm")
@with_mutation_options
def asset_confirm(
    ctx: typer.Context, request: Path, json_output: bool = typer.Option(False, "--json")
) -> None:
    """Record explicit meaning/scope/date/evidence for one existing source value."""
    _decide(ctx, request, None, False, json_output)


@assets_app.command("correct")
@with_mutation_options
def asset_correct(
    ctx: typer.Context,
    assertion_id: str,
    request: Path,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Append a source meaning correction; retain its earlier assertion and raw source."""
    _decide(ctx, request, assertion_id, False, json_output)


@assets_app.command("relation-confirm")
@with_mutation_options
def relation_confirm(
    ctx: typer.Context, request: Path, json_output: bool = typer.Option(False, "--json")
) -> None:
    """Explicitly include/overlap two existing source entities with review evidence."""
    _decide(ctx, request, None, True, json_output)


@assets_app.command("relation-correct")
@with_mutation_options
def relation_correct(
    ctx: typer.Context,
    assertion_id: str,
    request: Path,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Correct an inclusion/overlap decision without deleting its previous evidence."""
    _decide(ctx, request, assertion_id, True, json_output)


@assets_app.command("report")
def asset_report(  # noqa: PLR0913 - explicit CLI query flags
    ctx: typer.Context,
    as_of: str = typer.Option(..., "--as-of"),
    currency: str = typer.Option(..., "--currency"),
    party: list[str] = typer.Option(..., "--party"),
    source: list[str] = typer.Option([], "--source"),
    stale_days: int = typer.Option(30, "--stale-days", min=0),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Report exact owned values in an explicit party/source scope; surface unknowns."""
    try:
        query = AssetReportQuery(as_of, currency, tuple(party), tuple(source), stale_days)
        emit(
            _facade(ctx).read_canonical_assets(query),
            json_output,
            _render,
            command="ssot assets report",
        )
    except Exception as exc:
        _error(exc, "ssot assets report", json_output)
