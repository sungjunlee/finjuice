"""Privacy-safe workbook inspection commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from zipfile import BadZipFile

import typer
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from rich.table import Table

from finjuice.pipeline.cli import output
from finjuice.pipeline.cli.output import ErrorCode, ExitCode
from finjuice.pipeline.ingest.schemas import (
    is_asset_sheet_name,
    normalize_sheet_name,
)

inspect_app = typer.Typer(
    help="Privacy-safe source file inspection.",
    add_completion=False,
)

_OVERVIEW_SHEET = normalize_sheet_name("뱅샐현황")
_ANCHOR_LABELS = {
    normalize_sheet_name("기준일"): "snapshot_date",
    normalize_sheet_name("자산"): "asset_anchor",
    normalize_sheet_name("부채"): "liability_anchor",
    normalize_sheet_name("현금흐름현황"): "cashflow_anchor",
    normalize_sheet_name("현금흐름"): "cashflow_anchor",
    normalize_sheet_name("월별현금흐름"): "cashflow_anchor",
    normalize_sheet_name("수입지출현황"): "cashflow_anchor",
    normalize_sheet_name("날짜"): "date_header",
    normalize_sheet_name("시간"): "time_header",
    normalize_sheet_name("타입"): "type_header",
    normalize_sheet_name("금액"): "amount_header",
    normalize_sheet_name("결제수단"): "account_header",
    normalize_sheet_name("분류"): "category_header",
    normalize_sheet_name("항목"): "item_header",
}


def inspect_xlsx_structure(file_path: Path) -> dict[str, Any]:
    """Return privacy-safe structure metadata for one XLSX workbook."""
    workbook = load_workbook(file_path, read_only=True, data_only=True)
    try:
        worksheets = [
            _inspect_worksheet(sheet, index) for index, sheet in enumerate(workbook.worksheets)
        ]
    finally:
        workbook.close()

    detected_roles = sorted(
        {role for worksheet in worksheets for role in worksheet["detected_roles"]}
    )
    return {
        "file": {
            "name": file_path.name,
            "extension": file_path.suffix.lower(),
        },
        "summary": {
            "worksheet_count": len(worksheets),
            "detected_roles": detected_roles,
        },
        "worksheets": worksheets,
    }


def _inspect_worksheet(sheet: Any, index: int) -> dict[str, Any]:
    anchors = _collect_allowlisted_anchors(sheet)
    anchor_names = {anchor["anchor"] for anchor in anchors}
    roles = _detect_roles(str(sheet.title), anchor_names)
    blocks = _detect_blocks(anchor_names, roles)

    return {
        "index": index,
        "name": str(sheet.title),
        "row_count": int(sheet.max_row or 0),
        "column_count": int(sheet.max_column or 0),
        "detected_roles": roles,
        "detected_blocks": blocks,
        "allowlisted_anchors": anchors,
    }


def _collect_allowlisted_anchors(sheet: Any) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int]] = set()

    for row in sheet.iter_rows():
        for cell in row:
            normalized = normalize_sheet_name(str(cell.value)) if cell.value is not None else ""
            anchor = _ANCHOR_LABELS.get(normalized)
            if anchor is None:
                continue

            key = (anchor, int(cell.row), int(cell.column))
            if key in seen:
                continue
            seen.add(key)
            anchors.append(
                {
                    "anchor": anchor,
                    "row": int(cell.row),
                    "column": int(cell.column),
                }
            )

    return anchors


def _detect_roles(sheet_name: str, anchor_names: set[str]) -> list[str]:
    roles: list[str] = []
    if _is_transaction_sheet(anchor_names):
        roles.append("transaction_detail")
    if is_asset_sheet_name(sheet_name):
        roles.append("asset_snapshot")
    if normalize_sheet_name(sheet_name) == _OVERVIEW_SHEET or _is_overview_sheet(anchor_names):
        roles.append("banksalad_overview")
    return roles


def _is_transaction_sheet(anchor_names: set[str]) -> bool:
    required_anchor_names = {
        "date_header",
        "time_header",
        "type_header",
        "amount_header",
        "account_header",
    }
    return required_anchor_names <= anchor_names


def _is_overview_sheet(anchor_names: set[str]) -> bool:
    return (
        {"asset_anchor", "liability_anchor"} <= anchor_names
        or "cashflow_anchor" in anchor_names
        or "snapshot_date" in anchor_names
    )


def _detect_blocks(anchor_names: set[str], roles: list[str]) -> list[str]:
    blocks: list[str] = []
    if "transaction_detail" in roles:
        blocks.append("transaction_table")
    if "asset_snapshot" in roles:
        blocks.append("asset_snapshot_table")
    if {"asset_anchor", "liability_anchor"} <= anchor_names:
        blocks.append("balance_status")
    if "cashflow_anchor" in anchor_names:
        blocks.append("cashflow_monthly")
    return blocks


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
