"""finjuice CLI: ``history`` command for displaying import history.

Extracted from ``cli/commands/init.py`` as part of Batch 3a of Epic #707.
"""

import json
import logging
from typing import Any

import polars as pl
import typer
from rich.table import Table

from finjuice.pipeline.cli import output
from finjuice.pipeline.cli.output import _build_meta, console
from finjuice.pipeline.cli.utils import get_config

logger = logging.getLogger(__name__)


def _render_history(result: dict[str, Any]) -> None:
    """Render human-readable import history."""
    entries = result.get("entries", [])
    if not entries:
        output.info("📝 No import history found.")
        output.info("   Run 'finjuice ingest' to import XLSX files.")
        return

    table = Table(title="Import History")
    table.add_column("File ID", style="cyan")
    table.add_column("Filename", style="yellow")
    table.add_column("Rows", justify="right", style="green")
    table.add_column("Archived", style="blue")
    table.add_column("Imported At", style="magenta")

    for row in entries:
        filename = row["original_filename"]
        if len(filename) > 40:
            filename = filename[:37] + "..."

        archived_val = str(row.get("archived", "")).lower()
        archived = "Yes" if archived_val in ("yes", "true", "1") else "No"

        table.add_row(
            row["file_id"],
            filename,
            str(row.get("source_rows", 0)),
            archived,
            row["imported_at"][:16] if row["imported_at"] else "N/A",
        )

    console.print(table)

    total_files = result.get("total_files", 0)
    total_rows = result.get("total_rows", 0)
    archived_count = result.get("archived_count", 0)
    output.info(f"\n📊 Summary: {total_files} files, {total_rows:,} rows imported")
    output.info(f"📦 Archived: {archived_count} files")


def history_command(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Display import history log.

    Shows all imported files with:
    - File ID (YYMMDD_N format)
    - Original filename
    - Number of rows imported
    - Archive status
    - Import timestamp

    Examples:
        finjuice history
    """
    config = get_config(ctx)
    entries = _load_history_entries(config)

    # History uses list schema for backward compatibility (not dict)
    emit_history(entries, json_output)


def _load_history_entries(config: Any) -> list[dict[str, Any]]:
    """Load import history entries from CSV."""
    history_file = config.metadata_dir / "import_history.csv"
    if not history_file.exists():
        return []
    try:
        df = pl.read_csv(history_file)
        return df.to_dicts() if len(df) > 0 else []
    except (OSError, pl.exceptions.ComputeError) as e:
        logger.error("Failed to read import history (%s)", type(e).__name__)
        return []


def _render_history_full(entries: list[dict[str, Any]]) -> None:
    """Render history entries as a Rich table with summary."""
    if not entries:
        _render_history({"entries": []})
        return

    df = pl.DataFrame(entries)
    total_files = len(df)
    total_rows = df["source_rows"].sum() if "source_rows" in df.columns else 0
    archived_count = (
        df["archived"].str.to_lowercase().is_in(["yes", "true", "1"]).sum()
        if "archived" in df.columns
        else 0
    )
    _render_history(
        {
            "entries": entries,
            "total_files": total_files,
            "total_rows": total_rows,
            "archived_count": archived_count,
        }
    )


def emit_history(entries: list[dict[str, Any]], json_output: bool) -> None:
    """Emit history as structured JSON or a Rich table."""
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "_meta": _build_meta("history"),
                    "records": entries,
                    "count": len(entries),
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
        return

    _render_history_full(entries)
