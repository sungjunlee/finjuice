"""Plan insert, quarantine, and evidence-only dispositions in memory."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from finjuice.pipeline.ingest.exact_assets import ExactMappedAssetRow
from finjuice.pipeline.ingest.exact_transactions import ExactMappedRow
from finjuice.pipeline.ingest.xlsx_evidence import SheetEvidence, WorkbookEvidence
from finjuice.pipeline.storage.sqlite.exact_import.cells import cell_has_content
from finjuice.pipeline.storage.sqlite.exact_import.mapping import (
    ExactWorkbookMappings,
    claimed_sheet_names,
)
from finjuice.pipeline.storage.sqlite.exact_import.models import (
    FamilyCounts,
    ImportCounts,
    ImportPlan,
    RowAction,
    RowDecision,
)
from finjuice.pipeline.storage.sqlite.exact_import.overlap import matching_transaction_ids

JSONValue = Any
_ABSENT_STATUS = {"no_asset_sheet", "no_overview_sheet", "no_transaction_sheet"}


def build_import_plan(
    evidence: WorkbookEvidence,
    mappings: ExactWorkbookMappings,
    existing_transactions: Sequence[Mapping[str, JSONValue]],
) -> ImportPlan:
    """Decide row dispositions without allocating IDs or writing SQL."""
    claimed = claimed_sheet_names(mappings)
    tx_decisions = _transaction_decisions(mappings, existing_transactions)
    asset_decisions = _asset_decisions(mappings)
    counts = _plan_counts(evidence, mappings, claimed, tx_decisions, asset_decisions)
    return ImportPlan(
        counts=counts,
        decisions=tx_decisions + asset_decisions,
        claimed_sheets=claimed,
        mapping_issue_codes=_mapping_issue_codes(mappings),
    )


def _plan_counts(
    evidence: WorkbookEvidence,
    mappings: ExactWorkbookMappings,
    claimed: Sequence[str],
    tx_decisions: Sequence[RowDecision],
    asset_decisions: Sequence[RowDecision],
) -> ImportCounts:
    counts = _counts(mappings, tx_decisions, asset_decisions)
    counts.mapper_status = {
        "assets": mappings.assets.status,
        "overview": mappings.overview.status,
        "transactions": mappings.transactions.status,
    }
    counts.unknown_sheets = _unknown_sheet_count(evidence, claimed)
    overview_sheet = _mapped_sheet(mappings.overview.status, mappings.overview.sheet_name)
    counts.uncovered_rows = _uncovered_row_count(
        evidence, claimed, tx_decisions, asset_decisions, overview_sheet
    )
    counts.overview.inserted = _overview_insert_count(mappings)
    counts.overview.unsupported = _overview_unsupported_count(mappings)
    return counts


def _transaction_decisions(
    mappings: ExactWorkbookMappings,
    existing: Sequence[Mapping[str, JSONValue]],
) -> tuple[RowDecision, ...]:
    rows: list[RowDecision] = []
    for row in mappings.transactions.rows:
        rows.append(_transaction_decision(row, existing))
    return tuple(rows)


def _transaction_decision(
    row: ExactMappedRow,
    existing: Sequence[Mapping[str, JSONValue]],
) -> RowDecision:
    if not row.supported:
        return RowDecision("transactions", "evidence", row.sheet_name, row.source_row)
    candidates = matching_transaction_ids(row, existing)
    if candidates:
        return RowDecision(
            "transactions",
            "quarantine",
            row.sheet_name,
            row.source_row,
            candidates,
        )
    return RowDecision("transactions", "insert", row.sheet_name, row.source_row)


def _asset_decisions(mappings: ExactWorkbookMappings) -> tuple[RowDecision, ...]:
    rows: list[RowDecision] = []
    for row in mappings.assets.rows:
        action: RowAction = "insert" if _asset_persistable(row) else "evidence"
        rows.append(RowDecision("assets", action, row.sheet_name, row.source_row))
    return tuple(rows)


def _asset_persistable(row: ExactMappedAssetRow) -> bool:
    if row.snapshot.parsed_date is None:
        return False
    if row.quantity is None and row.market_value is None:
        return False
    if row.source_account_id is None and row.source_account_name is None:
        return False
    return row.source_instrument_id is not None or row.source_instrument_name is not None


def _counts(
    mappings: ExactWorkbookMappings,
    tx_decisions: Sequence[RowDecision],
    asset_decisions: Sequence[RowDecision],
) -> ImportCounts:
    counts = ImportCounts()
    _apply_decisions(
        counts.transactions,
        tx_decisions,
        status=mappings.transactions.status,
        issues=mappings.transactions.issues,
    )
    _apply_decisions(
        counts.assets,
        asset_decisions,
        status=mappings.assets.status,
        issues=mappings.assets.issues,
    )
    return counts


def _apply_decisions(
    family: FamilyCounts,
    decisions: Sequence[RowDecision],
    *,
    status: str,
    issues: Sequence[object],
) -> None:
    for decision in decisions:
        if decision.action == "insert":
            family.inserted += 1
        elif decision.action == "quarantine":
            family.quarantined += 1
        else:
            family.unsupported += 1
    if decisions or _family_absent(status) or not issues:
        return
    family.unsupported += 1


def _overview_insert_count(mappings: ExactWorkbookMappings) -> int:
    snapshot = mappings.overview.snapshot.parsed_date
    if snapshot is None:
        return 0
    facts = len(mappings.overview.facts)
    projections = (
        sum(1 for item in mappings.overview.balances if item.supported)
        + sum(1 for item in mappings.overview.cashflows if item.supported)
        + sum(1 for item in mappings.overview.insurance if item.supported)
        + sum(1 for item in mappings.overview.investments if item.supported)
        + sum(1 for item in mappings.overview.loans if item.supported)
    )
    return facts + projections


def _overview_unsupported_count(mappings: ExactWorkbookMappings) -> int:
    if _family_absent(mappings.overview.status):
        return 0
    unsupported = 0
    if mappings.overview.status != "mapped":
        unsupported += 1
    if mappings.overview.snapshot.parsed_date is None and mappings.overview.facts:
        unsupported += len(mappings.overview.facts)
    unsupported += sum(1 for item in mappings.overview.balances if not item.supported)
    unsupported += sum(1 for item in mappings.overview.cashflows if not item.supported)
    unsupported += sum(1 for item in mappings.overview.insurance if not item.supported)
    unsupported += sum(1 for item in mappings.overview.investments if not item.supported)
    unsupported += sum(1 for item in mappings.overview.loans if not item.supported)
    return unsupported


def _unknown_sheet_count(evidence: WorkbookEvidence, claimed: Sequence[str]) -> int:
    claimed_set = set(claimed)
    return sum(1 for sheet in evidence.sheets if sheet.name not in claimed_set)


def _uncovered_row_count(
    evidence: WorkbookEvidence,
    claimed: Sequence[str],
    tx_decisions: Sequence[RowDecision],
    asset_decisions: Sequence[RowDecision],
    overview_sheet: str | None,
) -> int:
    covered = {(item.sheet_name, item.source_row) for item in (*tx_decisions, *asset_decisions)}
    covered.update(_overview_content_rows(evidence, overview_sheet))
    total = 0
    for sheet in evidence.sheets:
        total += _sheet_uncovered_rows(sheet, set(claimed), covered)
    return total


def _overview_content_rows(
    evidence: WorkbookEvidence,
    sheet_name: str | None,
) -> set[tuple[str, int]]:
    if sheet_name is None:
        return set()
    sheet = evidence.sheet(sheet_name)
    if sheet is None:
        return set()
    return {(sheet.name, cell.row) for cell in sheet.cells if cell_has_content(cell)}


def _mapped_sheet(status: str, sheet_name: str | None) -> str | None:
    if status != "mapped":
        return None
    return sheet_name


def _family_absent(status: object) -> bool:
    return status in _ABSENT_STATUS


def _sheet_uncovered_rows(
    sheet: SheetEvidence,
    claimed: set[str],
    covered: set[tuple[str, int]],
) -> int:
    rows = {cell.row for cell in sheet.cells if cell_has_content(cell)}
    if sheet.name not in claimed:
        return len(rows)
    return sum(1 for row in rows if (sheet.name, row) not in covered)


def _mapping_issue_codes(mappings: ExactWorkbookMappings) -> tuple[str, ...]:
    codes = [issue.code for issue in mappings.transactions.issues]
    codes.extend(issue.code for issue in mappings.assets.issues)
    codes.extend(issue.code for issue in mappings.overview.issues)
    return tuple(codes)
