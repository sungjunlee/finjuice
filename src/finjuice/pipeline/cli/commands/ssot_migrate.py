"""Preservation migration commands for inactive SQLite candidates."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Optional

import typer

from finjuice.pipeline.backup import BackupError
from finjuice.pipeline.cli import output
from finjuice.pipeline.cli.output import ErrorCode, ExitCode, emit, emit_error
from finjuice.pipeline.config import Config
from finjuice.pipeline.migration import (
    MigrationError,
    MigrationResult,
    build_migration,
    plan_migration,
    verify_migration,
)

ssot_app = typer.Typer(help="Manage inactive SQLite migration candidates.", no_args_is_help=True)
migrate_app = typer.Typer(
    help="Plan, build, and verify preservation migrations.", no_args_is_help=True
)
ssot_app.add_typer(migrate_app, name="migrate")

_PUBLIC_ENUMS = {
    "status": {"ok", "already_complete"},
    "phase": {"migration_plan", "migration_verify", "migration_build"},
    "generation_status": {"inactive"},
    "origin_kind": {"legacy_current_state"},
}
_PUBLIC_CHECKS = {
    "database_integrity",
    "foreign_keys",
    "object_hashes",
    "capture_reconstruction",
    "source_semantic_parity",
}
_LIMITATIONS = [
    "Activation, consumer parity, runtime restore, and operator approval remain unverified.",
    "Adapter replay checks consistency; independent semantic review remains required.",
]


def _public_summary(result: MigrationResult) -> dict[str, Any]:
    """Select only validated summary fields; detailed plan evidence stays private."""
    data = result.to_dict()
    summary: dict[str, Any] = {}
    for name, allowed in _PUBLIC_ENUMS.items():
        value = data.get(name)
        if isinstance(value, str) and value in allowed:
            summary[name] = value
    for name in ("input_count", "dataset_revision"):
        value = data.get(name)
        if type(value) is int and value >= 0:
            summary[name] = value
    for name, pattern in (
        ("manifest_digest", r"sha256:[0-9a-f]{64}"),
        ("attempt_id", r"[0-9a-f]{32}"),
    ):
        value = data.get(name)
        if isinstance(value, str) and re.fullmatch(pattern, value):
            summary[name] = value
    checks = data.get("checks")
    if isinstance(checks, dict):
        summary["checks"] = {
            name: value
            for name, value in checks.items()
            if name in _PUBLIC_CHECKS
            and isinstance(value, str)
            and value in {"passed", "failed", "not_run"}
        }
    summary["cutover_ready"] = False
    summary["limitations"] = _LIMITATIONS
    return summary


def _render(result: dict[str, Any]) -> None:
    output.success(f"Migration {result.get('status', 'completed')}")
    if "input_count" in result:
        output.info(f"  inputs: {result['input_count']}")
    if "manifest_digest" in result:
        output.info(f"  digest: {result['manifest_digest']}")
    output.info("  cutover: not ready; activation and operational checks remain pending")


def _run(operation: Callable[[], MigrationResult], *, command: str, json_output: bool) -> None:
    try:
        result = _public_summary(operation())
    except (MigrationError, BackupError, ValueError):
        emit_error(
            "Migration validation failed. Check frozen evidence and isolated target requirements.",
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            json_output=json_output,
            command=command,
        )
    except Exception:  # intended catch-all: underlying errors may contain private paths or rows
        emit_error(
            "Migration could not complete. Inspect private evidence before retrying.",
            error_code=ErrorCode.UNEXPECTED_ERROR,
            exit_code=ExitCode.GENERAL_ERROR,
            json_output=json_output,
            command=command,
        )
    emit(result, json_output, _render, command=command)


def _active_data_dir(ctx: typer.Context) -> Path:
    try:
        if isinstance(ctx.obj, dict) and "active_data_dir" in ctx.obj:
            active = ctx.obj["active_data_dir"]
            if active is None:
                raise MigrationError("Active data directory could not be resolved safely.")
            return Path(active)
        return Config.from_env().data_dir
    except (TypeError, ValueError, OSError) as exc:
        raise MigrationError("Active data directory could not be resolved safely.") from exc


@migrate_app.command("plan")
def migrate_plan(
    manifest: Path = typer.Option(..., "--manifest", help="Verified frozen capture manifest."),
    output: Optional[Path] = typer.Option(
        None, "--output", help="New private plan file. Omit for a read-only summary."
    ),
    json_output: bool = typer.Option(False, "--json", help="Output a privacy-safe JSON summary."),
) -> None:
    """Inspect a verified capture and optionally write an immutable preservation plan."""
    _run(
        lambda: plan_migration(manifest, output=output),
        command="ssot migrate plan",
        json_output=json_output,
    )


@migrate_app.command("build")
def migrate_build(
    ctx: typer.Context,
    plan: Path = typer.Option(..., "--plan", help="Private preservation plan file."),
    staging: Path = typer.Option(
        ..., "--staging", help="New or empty inactive candidate directory."
    ),
    parent_attempt_id: Optional[str] = typer.Option(
        None, "--parent-attempt-id", help="Prior failed attempt ID for a linked fresh attempt."
    ),
    json_output: bool = typer.Option(False, "--json", help="Output a privacy-safe JSON summary."),
) -> None:
    """Build a preservation candidate without activating it."""
    _run(
        lambda: build_migration(
            plan,
            staging,
            active_data_dir=_active_data_dir(ctx),
            parent_attempt_id=parent_attempt_id,
        ),
        command="ssot migrate build",
        json_output=json_output,
    )


@migrate_app.command("verify")
def migrate_verify(
    candidate: Path = typer.Option(..., "--candidate", help="Candidate migration manifest."),
    json_output: bool = typer.Option(False, "--json", help="Output a privacy-safe JSON summary."),
) -> None:
    """Verify preservation evidence and integrity of an inactive candidate."""
    _run(
        lambda: verify_migration(candidate),
        command="ssot migrate verify",
        json_output=json_output,
    )
