"""Read-only verification of a repository export receipt against current data."""

from pathlib import Path
from typing import Any

import typer

from finjuice.pipeline.cli import output
from finjuice.pipeline.cli.output import ErrorCode, emit, emit_error
from finjuice.pipeline.cli.utils import get_activation_evidence_provider, get_config
from finjuice.pipeline.export.artifacts import inspect_repository_export
from finjuice.pipeline.storage.read_facade import read_transaction_snapshot, snapshot_metadata


def export_verify_command(
    ctx: typer.Context,
    manifest_path: Path = typer.Argument(..., help="Manifest inside this dataset's export runs"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> dict[str, Any]:
    """Check export revision freshness and modified or missing artifacts without writing."""
    config = get_config(ctx)
    try:
        snapshot = read_transaction_snapshot(config.data_dir, get_activation_evidence_provider(ctx))
        if snapshot is None:
            raise ValueError("Repository authority is required.")
        result = inspect_repository_export(
            manifest_path, config.data_dir / "exports", snapshot_metadata(snapshot)
        )
    except Exception:
        emit_error(
            "Could not verify the export manifest against validated repository data.",
            error_code=ErrorCode.EXPORT_FAILED,
            json_output=json_output,
            command="export-verify",
        )
        raise AssertionError("emit_error must exit")
    result["command"] = "export-verify"
    emit(result, json_output, _render_verification, command="export-verify")
    return result


def _render_verification(result: dict[str, Any]) -> None:
    freshness = "stale" if result["stale"] else "current"
    output.info(f"Export data: {freshness}; artifact integrity: {result['integrity']}")
    for entry in result["files"]:
        if entry["status"] != "intact":
            output.warning(f"  {entry['path']}: {entry['status']}")
