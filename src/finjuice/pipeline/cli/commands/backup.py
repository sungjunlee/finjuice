"""CLI commands for complete legacy backup create/verify/restore."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import typer

from finjuice.pipeline.backup import (
    BackupError,
    ConsistencyEvidence,
    CreateRequest,
    SourceRoot,
    create_backup,
    restore_backup,
    verify_backup,
)
from finjuice.pipeline.backup.paths import parse_named_root, validate_root_name
from finjuice.pipeline.backup.types import Presence
from finjuice.pipeline.cli import output
from finjuice.pipeline.cli.output import ErrorCode, ExitCode, emit, emit_error
from finjuice.pipeline.config import Config

backup_app = typer.Typer(
    name="backup",
    help="Create, verify, and restore a complete legacy data-tree backup.",
    no_args_is_help=True,
)


def _error_code(code: str) -> ErrorCode:
    try:
        return ErrorCode(code)
    except ValueError:
        return ErrorCode.VALIDATION_FAILED


def _fail(exc: BackupError, *, command: str, json_output: bool) -> None:
    emit_error(
        exc.message,
        error_code=_error_code(exc.code),
        exit_code=ExitCode.VALIDATION_ERROR
        if exc.code in {"VALIDATION_FAILED", "INVALID_ARGS", "FILE_NOT_FOUND"}
        else ExitCode.GENERAL_ERROR,
        suggestion=exc.suggestion,
        json_output=json_output,
        command=command,
    )


def _unexpected(exc: Exception, *, command: str, json_output: bool) -> None:
    emit_error(
        f"Unexpected backup error: {type(exc).__name__}",
        error_code=ErrorCode.UNEXPECTED_ERROR,
        exit_code=ExitCode.GENERAL_ERROR,
        json_output=json_output,
        command=command,
    )


def _render(result: dict[str, Any]) -> None:
    output.success(f"Backup {result['status']}")
    output.info(f"  entries: {result['entry_count']}")
    output.info(f"  files: {result['file_count']}")
    output.info(f"  directories: {result['directory_count']}")
    output.info(f"  bytes: {result['byte_count']}")
    output.info(f"  digest: {result['manifest_digest']}")
    if result.get("generation_status"):
        output.info(f"  generation: {result['generation_status']}")


def _consistency(
    consistency: str,
    stopped_writer: list[str] | None,
    snapshot_name: str | None,
) -> ConsistencyEvidence:
    kind = consistency.replace("-", "_")
    writers = tuple(item for item in (stopped_writer or []) if item)
    return ConsistencyEvidence(
        kind=kind,  # type: ignore[arg-type]
        stopped_writers=writers,
        snapshot_name=snapshot_name,
    )


def _extra_roots(
    source_root: list[str] | None,
    optional_root: list[str] | None,
) -> tuple[SourceRoot, ...]:
    optional = {validate_root_name(name) for name in (optional_root or [])}
    present: dict[str, SourceRoot] = {}
    for raw in source_root or []:
        name, path_text = parse_named_root(raw)
        if name in present:
            raise BackupError("Duplicate source-root name.", code="INVALID_ARGS")
        presence: Presence = "optional" if name in optional else "required"
        path = Path(path_text) if path_text else None
        present[name] = SourceRoot(name=name, presence=presence, path=path)
    roots = list(present.values())
    for name in optional:
        if name not in present:
            roots.append(SourceRoot(name=name, presence="optional", path=None))
    return tuple(roots)


def _active_data_dir(ctx: typer.Context) -> Path:
    if isinstance(ctx.obj, dict) and "active_data_dir" in ctx.obj:
        active = ctx.obj["active_data_dir"]
        if active is None:
            raise BackupError(
                "Active data directory could not be resolved safely.",
                code="VALIDATION_FAILED",
            )
        return Path(active)
    try:
        return Config.from_env().data_dir
    except (TypeError, ValueError, OSError) as exc:
        raise BackupError(
            "Active data directory could not be resolved safely.",
            code="VALIDATION_FAILED",
        ) from exc


@backup_app.command("create")
def backup_create(  # noqa: PLR0913 - Typer command signature mirrors public CLI flags.
    ctx: typer.Context,
    source: Path = typer.Option(..., "--source", help="Legacy data directory to capture."),
    output: Path = typer.Option(..., "--output", help="New backup directory to publish."),
    source_root: Optional[list[str]] = typer.Option(
        None,
        "--source-root",
        help="Additional inventoried root as NAME=PATH. Repeatable.",
    ),
    optional_root: Optional[list[str]] = typer.Option(
        None,
        "--optional-root",
        help="Mark a named root optional. Absent optional roots are recorded.",
    ),
    consistency: str = typer.Option(
        ...,
        "--consistency",
        help="stopped-writers or named-snapshot. Not a host-wide writer proof.",
    ),
    stopped_writer: Optional[list[str]] = typer.Option(
        None,
        "--stopped-writer",
        help="Operator-confirmed stopped writer name. Repeatable.",
    ),
    snapshot_name: Optional[str] = typer.Option(
        None,
        "--snapshot-name",
        help="Named quiesced snapshot taken after writers were stopped.",
    ),
    parent_attempt_id: Optional[str] = typer.Option(
        None, "--parent-attempt-id", help="Prior capture attempt ID, as 32 lowercase hex digits."
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Capture an inventoried data tree on Linux or macOS into a new backup directory."""
    command = "backup create"
    try:
        result = create_backup(
            CreateRequest(
                source=source,
                output=output,
                consistency=_consistency(consistency, stopped_writer, snapshot_name),
                extra_roots=_extra_roots(source_root, optional_root),
                parent_attempt_id=parent_attempt_id,
            )
        )
    except BackupError as exc:
        _fail(exc, command=command, json_output=json_output)
        return
    except Exception as exc:  # intended catch-all for CLI robustness
        _unexpected(exc, command=command, json_output=json_output)
        return
    emit(result.to_dict(), json_output, _render, command=command)


@backup_app.command("verify")
def backup_verify(
    backup_manifest: Path = typer.Argument(..., help="Backup manifest or backup directory."),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Verify a published backup manifest, marker, and payload."""
    command = "backup verify"
    try:
        result = verify_backup(backup_manifest)
    except BackupError as exc:
        _fail(exc, command=command, json_output=json_output)
        return
    except Exception as exc:  # intended catch-all for CLI robustness
        _unexpected(exc, command=command, json_output=json_output)
        return
    emit(result.to_dict(), json_output, _render, command=command)


@backup_app.command("restore")
def backup_restore(  # noqa: PLR0913 - Typer command signature mirrors public CLI flags.
    ctx: typer.Context,
    backup_manifest: Path = typer.Argument(..., help="Backup manifest or backup directory."),
    target: Path = typer.Option(..., "--target", help="Empty or new isolated restore directory."),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Restore a verified backup on Linux or macOS into an inactive isolated directory."""
    command = "backup restore"
    try:
        result = restore_backup(
            backup_manifest,
            target,
            active_data_dir=_active_data_dir(ctx),
        )
    except BackupError as exc:
        _fail(exc, command=command, json_output=json_output)
        return
    except Exception as exc:  # intended catch-all for CLI robustness
        _unexpected(exc, command=command, json_output=json_output)
        return
    emit(result.to_dict(), json_output, _render, command=command)
