"""Run the pure exact mappers against captured workbook evidence."""

from __future__ import annotations

from dataclasses import dataclass

from finjuice.pipeline.ingest.exact_assets import ExactAssetMapping, map_exact_assets
from finjuice.pipeline.ingest.exact_overview import ExactOverviewMapping, map_exact_overview
from finjuice.pipeline.ingest.exact_transactions import (
    ExactTransactionMapping,
    map_exact_transactions,
)
from finjuice.pipeline.storage.sqlite.exact_import.models import ExactImportCommand


@dataclass(frozen=True)
class ExactWorkbookMappings:
    """One workbook mapped by the three exact family mappers."""

    transactions: ExactTransactionMapping
    assets: ExactAssetMapping
    overview: ExactOverviewMapping


def map_captured_workbook(command: ExactImportCommand) -> ExactWorkbookMappings:
    """Map captured evidence without rereading the source path."""
    evidence = command.capture.evidence
    intent = command.intent
    return ExactWorkbookMappings(
        transactions=map_exact_transactions(evidence, sheet_name=intent.transaction_sheet),
        assets=map_exact_assets(
            evidence,
            sheet_name=intent.asset_sheet,
            snapshot_date=intent.snapshot_date,
            collected_at=intent.collected_at,
        ),
        overview=map_exact_overview(
            evidence,
            sheet_name=intent.overview_sheet,
            snapshot_date=intent.snapshot_date,
            source_filename=command.capture.filename,
            collected_at=intent.collected_at,
        ),
    )


def claimed_sheet_names(mappings: ExactWorkbookMappings) -> tuple[str, ...]:
    """Return worksheet names selected by a successful family mapping."""
    names: list[str] = []
    for mapping in (mappings.transactions, mappings.assets, mappings.overview):
        if mapping.status == "mapped" and mapping.sheet_name is not None:
            names.append(mapping.sheet_name)
    return tuple(dict.fromkeys(names))
