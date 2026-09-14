"""Import canonical local JSON statements and read their preserved evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from finjuice.pipeline.cli.commands.ssot_accounts import _error, _facade
from finjuice.pipeline.cli.commands.ssot_intake import _identity
from finjuice.pipeline.cli.mutation_options import with_mutation_options
from finjuice.pipeline.cli.output import emit, info
from finjuice.pipeline.cli.utils import mutation_metadata
from finjuice.pipeline.statements.canonical import StatementImport
from finjuice.pipeline.storage.sqlite.backup_io import read_regular_bytes


def _render(payload: dict[str, Any]) -> None:
    if "counts" in payload:
        counts = payload["counts"]
        info(
            f"명세서 {payload['source_identity']} ({payload['coverage']}) "
            f"레코드 {payload['record_count']}건"
        )
        info(
            f"  생성 {counts['created']} / 연결 {counts['linked']} / "
            f"재사용 {counts['reused']} / 보류 {counts['pending']}"
        )
        return
    info(f"보존된 명세서 증빙 {payload['record_count']}건")
    info(f"  결정 대기 외부 ID {len(payload['pending_external_ids'])}건")


@with_mutation_options
def import_json(
    ctx: typer.Context,
    document: Path = typer.Argument(..., help="Canonical JSON statement document"),
    original: Path = typer.Option(None, "--original", help="Upstream original bytes to preserve"),
    imported_at: str = typer.Option(..., "--imported-at", help="Timezone-aware import timestamp"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Preserve exact statement bytes and apply only explicitly decided economic records.

    The envelope must carry source_identity, schema_version, parser_version,
    original_hash, as_of, collected_at, coverage, currency and idempotency_key.
    A record becomes a transaction only with an explicit create decision over a
    confirmed account source binding; everything else stays pending evidence.
    """
    name = "ssot import-json"
    try:
        identity = _identity(ctx)
        command = StatementImport(
            content=read_regular_bytes(document),
            imported_at=imported_at,
            original=None if original is None else read_regular_bytes(original),
        )
        receipt = _facade(ctx).import_statement(command, identity=identity)
        emit(
            {**receipt.result, **mutation_metadata(identity, receipt)},
            json_output,
            _render,
            command=name,
        )
    except Exception as exc:
        _error(exc, name, json_output)


def statement_evidence(
    ctx: typer.Context,
    source_identity: str = typer.Option(None, "--source-identity"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Read every preserved statement record, its canonical mapping and pending state."""
    name = "ssot statement-evidence"
    try:
        emit(
            _facade(ctx).read_statement_evidence(source_identity=source_identity),
            json_output,
            _render,
            command=name,
        )
    except Exception as exc:
        _error(exc, name, json_output)


__all__ = ["import_json", "statement_evidence"]
