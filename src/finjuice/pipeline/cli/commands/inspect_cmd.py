"""Privacy-safe workbook inspection commands.

Workbook structure inspection lives in
:mod:`finjuice.pipeline.cli.commands.inspect_helpers` and is re-exported
here so existing callers can keep importing from this module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from zipfile import BadZipFile

import typer
from openpyxl.utils.exceptions import InvalidFileException
from rich.table import Table

from finjuice.pipeline.cli import output
from finjuice.pipeline.cli.commands.inspect_helpers import (
    _collect_allowlisted_anchors,  # noqa: F401 — re-exported for existing inspect imports
    _detect_blocks,  # noqa: F401 — re-exported for existing inspect imports
    _detect_roles,  # noqa: F401 — re-exported for existing inspect imports
    _inspect_worksheet,  # noqa: F401 — re-exported for existing inspect imports
    inspect_xlsx_structure,
)
from finjuice.pipeline.cli.output import ErrorCode, ExitCode

inspect_app = typer.Typer(
    help="Privacy-safe source file inspection.",
    add_completion=False,
)


def _render_xlsx_inspection(result: dict[str, Any]) -> None:
    table = Table(title=f"XLSX structure: {result['file']['name']}")
    table.add_column("Sheet")
    table.add_column("Rows", justify="right")
    table.add_column("Columns", justify="right")
    table.add_column("Roles")
    table.add_column("Blocks")

    for worksheet in result["worksheets"]:
        table.add_row(
            worksheet["name"],
            str(worksheet["row_count"]),
            str(worksheet["column_count"]),
            ", ".join(worksheet["detected_roles"]) or "-",
            ", ".join(worksheet["detected_blocks"]) or "-",
        )
    output.console.print(table)


@inspect_app.command("xlsx")
def inspect_xlsx_command(
    file_path: Path = typer.Argument(..., help="XLSX workbook to inspect"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Inspect workbook structure without exposing raw financial cell values."""
    command = "inspect xlsx"
    if not file_path.exists():
        output.emit_error(
            f"File not found: {file_path.name}",
            error_code=ErrorCode.FILE_NOT_FOUND,
            exit_code=ExitCode.VALIDATION_ERROR,
            json_output=json_output,
            command=command,
        )
    if not file_path.is_file():
        output.emit_error(
            f"Not a file: {file_path.name}",
            error_code=ErrorCode.INVALID_ARGS,
            exit_code=ExitCode.VALIDATION_ERROR,
            json_output=json_output,
            command=command,
        )
    if file_path.suffix.lower() not in {".xlsx", ".xlsm"}:
        output.emit_error(
            "Only .xlsx and .xlsm workbooks are supported.",
            error_code=ErrorCode.INVALID_ARGS,
            exit_code=ExitCode.VALIDATION_ERROR,
            json_output=json_output,
            command=command,
        )

    try:
        result = inspect_xlsx_structure(file_path)
    except (BadZipFile, InvalidFileException, OSError, ValueError) as exc:
        output.emit_error(
            f"Failed to inspect workbook: {type(exc).__name__}",
            error_code=ErrorCode.INSPECTION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            json_output=json_output,
            command=command,
        )

    output.emit(result, json_output, _render_xlsx_inspection, command=command)
