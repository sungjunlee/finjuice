"""CLI commands for SQLite generation backup create/restore/status."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import typer

from finjuice.pipeline.cli import output
from finjuice.pipeline.cli.output import ErrorCode, ExitCode, emit, emit_error
from finjuice.pipeline.config import get_default_data_dir
from finjuice.pipeline.config_file import load_config
from finjuice.pipeline.storage.sqlite.backup import (
    backup_status,
    create_backup,
)
from finjuice.pipeline.storage.sqlite.errors import (
    BackupIncompleteError,
    BackupVerificationError,
    RepositoryBackupError,
    RepositoryPathError,
)
from finjuice.pipeline.storage.sqlite.inactive_restore import restore_workspace

ssot_backup_app = typer.Typer(
    name="backup",
    help=(
        "Create snapshots, capture a local recovery graph, retain a managed store, "
        "and restore inactive workspaces."
    ),
    no_args_is_help=True,
)


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
        "The SQLite backup operation could not be verified or completed.",
        error_code=ErrorCode.VALIDATION_FAILED if validation else ErrorCode.GENERAL_ERROR,
        exit_code=ExitCode.VALIDATION_ERROR if validation else ExitCode.GENERAL_ERROR,
        json_output=json_output,
        command=command,
    )


def _unexpected(exc: Exception, *, command: str, json_output: bool) -> None:
    emit_error(
        "The SQLite backup operation could not be completed.",
        error_code=ErrorCode.UNEXPECTED_ERROR,
        exit_code=ExitCode.GENERAL_ERROR,
        json_output=json_output,
        command=command,
    )


def _render_create(result: dict[str, Any]) -> None:
    output.success("Local SQLite snapshot backup complete")
    output.info(f"  generation: {result['source_generation']}")
    output.info(f"  revision: {result['dataset_revision']}")
    output.info(f"  files: {result['file_count']}")
    output.info(f"  bytes: {result['byte_count']}")
    output.info(f"  digest: {result['manifest_digest']}")
    if result.get("warnings"):
        output.warning(f"  warnings: {', '.join(result['warnings'])}")


def _render_restore(result: dict[str, Any]) -> None:
    output.success("Inactive SQLite workspace restored")
    output.info(f"  generation: {result['dataset_generation']}")
    output.info(f"  revision: {result['initial_dataset_revision']}")
    output.info(f"  restore ID: {result['restore_id']}")
    output.info(f"  descriptor digest: {result['descriptor_digest']}")
    output.info("Keep this complete JSON receipt independently for inactive session admission.")
    output.console.print_json(data=result)
    output.info("This local restore does not activate or promote the workspace.")


def _render_status(result: dict[str, Any]) -> None:
    if result["complete"]:
        output.success("SQLite backup complete")
    else:
        output.warning("SQLite backup incomplete")
    output.info(f"  reason: {result['reason']}")
    if result.get("manifest_digest"):
        output.info(f"  digest: {result['manifest_digest']}")


def _active_data_dir(ctx: typer.Context) -> Path:
    # Config.from_env intentionally tolerates invalid user configuration elsewhere.
    # Restore must not interpret that fallback as evidence of an isolated target.
    config = load_config()
    explicit = ctx.find_root().params.get("data_dir") or os.getenv("FINJUICE_DATA_DIR")
    if explicit is not None:
        return Path(explicit).expanduser().resolve()
    return config.get_data_path() if config is not None else get_default_data_dir()


def _reject_active_restore(target: Path, active: Path) -> None:
    if ".." in target.parts:
        raise RepositoryPathError("Restore destination must not contain parent traversal.")
    resolved_target = target.expanduser().resolve()
    resolved_active = active.expanduser().resolve()
    if (
        resolved_target == resolved_active
        or resolved_target.is_relative_to(resolved_active)
        or resolved_active.is_relative_to(resolved_target)
    ):
        raise RepositoryPathError("Restore destination must be an isolated inactive directory.")


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
    target: Path = typer.Option(
        ..., "--target", help="Fresh isolated workspace directory; parent must exist."
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Restore a verified SQLite backup into an inactive isolated directory."""
    command = "ssot backup restore"
    try:
        _reject_active_restore(target, _active_data_dir(ctx))
        result = restore_workspace(backup, target)
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
    """Report whether one SQLite backup directory is an intact local snapshot."""
    command = "ssot backup status"
    try:
        result = backup_status(backup)
    except Exception as exc:  # intended catch-all for CLI robustness
        _unexpected(exc, command=command, json_output=json_output)
        return
    emit(result.to_dict(), json_output, _render_status, command=command)


def _register_recovery_bundle_commands() -> None:
    import importlib

    importlib.import_module("finjuice.pipeline.cli.commands.sqlite_recovery_bundle")
    importlib.import_module("finjuice.pipeline.cli.commands.sqlite_recovery_store")
    importlib.import_module("finjuice.pipeline.cli.commands.sqlite_backup_deliver")


_register_recovery_bundle_commands()
