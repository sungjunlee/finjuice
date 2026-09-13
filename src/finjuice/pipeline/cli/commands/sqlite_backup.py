"""CLI commands for SQLite generation backup create/restore/status."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from finjuice.pipeline.cli import output
from finjuice.pipeline.cli.output import ErrorCode, ExitCode, emit, emit_error
from finjuice.pipeline.config import Config
from finjuice.pipeline.storage.sqlite.backup import (
    backup_status,
    create_backup,
    restore_backup,
)
from finjuice.pipeline.storage.sqlite.errors import (
    BackupIncompleteError,
    BackupVerificationError,
    RepositoryBackupError,
    RepositoryPathError,
)

ssot_app = typer.Typer(
    name="ssot",
    help="SQLite authoritative-storage operators that do not replace legacy backup.",
    no_args_is_help=True,
)
ssot_backup_app = typer.Typer(
    name="backup",
    help="Create, restore, and inspect a SQLite generation backup.",
    no_args_is_help=True,
)
ssot_app.add_typer(ssot_backup_app, name="backup")


def _fail(
    exc: RepositoryBackupError | RepositoryPathError,
    *,
    command: str,
    json_output: bool,
) -> None:
    validation = isinstance(
        exc,
        (BackupIncompleteError, BackupVerificationError, RepositoryPathError),
    )
    emit_error(
        str(exc),
        error_code=ErrorCode.VALIDATION_FAILED if validation else ErrorCode.GENERAL_ERROR,
        exit_code=ExitCode.VALIDATION_ERROR if validation else ExitCode.GENERAL_ERROR,
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


def _render_create(result: dict[str, Any]) -> None:
    output.success("SQLite backup complete")
    output.info(f"  generation: {result['source_generation']}")
    output.info(f"  revision: {result['dataset_revision']}")
    output.info(f"  files: {result['file_count']}")
    output.info(f"  bytes: {result['byte_count']}")
    output.info(f"  digest: {result['manifest_digest']}")
    if result.get("warnings"):
        output.warning(f"  warnings: {', '.join(result['warnings'])}")


def _render_restore(result: dict[str, Any]) -> None:
    output.success("SQLite backup restored")
    output.info(f"  generation: {result['source_generation']}")
    output.info(f"  revision: {result['dataset_revision']}")
    output.info(f"  status: {result['generation_status']}")
    output.info(f"  digest: {result['manifest_digest']}")


def _render_status(result: dict[str, Any]) -> None:
    if result["complete"]:
        output.success("SQLite backup complete")
    else:
        output.warning("SQLite backup incomplete")
    output.info(f"  reason: {result['reason']}")
    if result.get("manifest_digest"):
        output.info(f"  digest: {result['manifest_digest']}")


def _active_data_dir(ctx: typer.Context) -> Path | None:
    if isinstance(ctx.obj, dict) and "active_data_dir" in ctx.obj:
        active = ctx.obj["active_data_dir"]
        return None if active is None else Path(active)
    try:
        return Config.from_env().data_dir
    except (TypeError, ValueError, OSError):
        return None


def _reject_active_restore(target: Path, active: Path | None) -> None:
    if active is None or not active.exists():
        return
    resolved_target = target.expanduser().absolute()
    resolved_active = active.expanduser().absolute()
    if (
        resolved_target == resolved_active
        or resolved_target.is_relative_to(resolved_active)
        or resolved_active.is_relative_to(resolved_target)
    ):
        raise RepositoryPathError(
            "Restore destination must be an isolated inactive directory.",
        )


@ssot_backup_app.command("create")
def sqlite_backup_create(
    source: Path = typer.Option(..., "--source", help="Published generation root or database."),
    output_dir: Path = typer.Option(..., "--output", help="Backup directory to publish."),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Capture one SQLite generation snapshot and its referenced artifacts."""
    command = "ssot backup create"
    try:
        result = create_backup(source, output_dir)
    except (RepositoryBackupError, RepositoryPathError) as exc:
        _fail(exc, command=command, json_output=json_output)
        return
    except Exception as exc:  # intended catch-all for CLI robustness
        _unexpected(exc, command=command, json_output=json_output)
        return
    emit(result.to_dict(), json_output, _render_create, command=command)


@ssot_backup_app.command("restore")
def sqlite_backup_restore(
    ctx: typer.Context,
    backup: Path = typer.Argument(..., help="Backup directory or current attempt."),
    target: Path = typer.Option(..., "--target", help="Empty or new isolated restore directory."),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Restore a verified SQLite backup into an inactive isolated directory."""
    command = "ssot backup restore"
    try:
        _reject_active_restore(target, _active_data_dir(ctx))
        result = restore_backup(backup, target)
    except (RepositoryBackupError, RepositoryPathError) as exc:
        _fail(exc, command=command, json_output=json_output)
        return
    except Exception as exc:  # intended catch-all for CLI robustness
        _unexpected(exc, command=command, json_output=json_output)
        return
    emit(result.to_dict(), json_output, _render_restore, command=command)


@ssot_backup_app.command("status")
def sqlite_backup_status(
    backup: Path = typer.Argument(..., help="Backup directory to inspect."),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Report whether one SQLite backup directory is complete and trusted."""
    command = "ssot backup status"
    try:
        result = backup_status(backup)
    except Exception as exc:  # intended catch-all for CLI robustness
        _unexpected(exc, command=command, json_output=json_output)
        return
    emit(result.to_dict(), json_output, _render_status, command=command)
