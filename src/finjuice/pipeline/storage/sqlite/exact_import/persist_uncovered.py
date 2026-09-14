"""Preserve nonempty source rows and cells not claimed by typed families."""

from __future__ import annotations

from collections.abc import Sequence

from finjuice.pipeline.ingest.xlsx_evidence import CellEvidence, SheetEvidence, WorkbookEvidence
from finjuice.pipeline.storage.sqlite.exact_import.cells import cell_has_content
from finjuice.pipeline.storage.sqlite.exact_import.evidence import (
    IssueView,
    PersistSession,
    SourcePlace,
    add_issues,
    add_row_provenance,
)
from finjuice.pipeline.storage.sqlite.exact_import.models import RowDecision


def persist_uncovered(
    session: PersistSession,
    evidence: WorkbookEvidence,
    claimed_sheets: Sequence[str],
    decisions: Sequence[RowDecision],
    *,
    overview_sheet: str | None,
) -> int:
    """Write remaining nonempty rows and return how many were preserved."""
    covered = {(item.sheet_name, item.source_row) for item in decisions}
    covered.update(_sheet_content_rows(evidence, overview_sheet))
    preserved = 0
    claimed = set(claimed_sheets)
    for sheet in evidence.sheets:
        preserved += _persist_sheet(session, sheet, claimed, covered)
    return preserved


def _sheet_content_rows(
    evidence: WorkbookEvidence,
    sheet_name: str | None,
) -> set[tuple[str, int]]:
    """Treat mapped overview rows as covered because facts already store cells."""
    if sheet_name is None:
        return set()
    sheet = evidence.sheet(sheet_name)
    if sheet is None:
        return set()
    return {(sheet.name, cell.row) for cell in sheet.cells if cell_has_content(cell)}


def _persist_sheet(
    session: PersistSession,
    sheet: SheetEvidence,
    claimed: set[str],
    covered: set[tuple[str, int]],
) -> int:
    grouped = _rows(sheet)
    unknown_sheet = sheet.name not in claimed
    preserved = 0
    for row_number, cells in grouped.items():
        if not unknown_sheet and (sheet.name, row_number) in covered:
            continue
        _persist_row(session, sheet.name, row_number, cells, unknown_sheet)
        preserved += 1
    return preserved


def _persist_row(
    session: PersistSession,
    sheet_name: str,
    source_row: int,
    cells: Sequence[CellEvidence],
    unknown_sheet: bool,
) -> None:
    family = "unknown_sheet" if unknown_sheet else "uncovered_row"
    place = SourcePlace(family, sheet_name, source_row)
    provenance_id = add_row_provenance(
        session,
        place,
        cells,
        {"unknown_sheet": unknown_sheet},
    )
    if unknown_sheet:
        add_issues(
            session,
            provenance_id,
            (
                IssueView(
                    "UNKNOWN_SHEET",
                    None,
                    source_row,
                    None,
                    "Worksheet was not a mapped family.",
                ),
            ),
            sheet_name=sheet_name,
        )


def _rows(sheet: SheetEvidence) -> dict[int, tuple[CellEvidence, ...]]:
    grouped: dict[int, list[CellEvidence]] = {}
    for cell in sheet.cells:
        if not cell_has_content(cell):
            continue
        grouped.setdefault(cell.row, []).append(cell)
    return {row: tuple(cells) for row, cells in grouped.items()}
