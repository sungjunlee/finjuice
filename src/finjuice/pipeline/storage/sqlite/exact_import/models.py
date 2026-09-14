"""DTOs for exact XLSX import intent, planning, and receipts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from finjuice.pipeline.storage.sqlite.exact_import.capture import ExactWorkbookCapture
from finjuice.pipeline.storage.sqlite.exact_import.constants import (
    IMPORT_POLICY_VERSION,
    PARSER_POLICY_VERSION,
)

JSONValue = Any
FamilyName = Literal["transactions", "assets", "overview", "unknown"]
RowAction = Literal["insert", "quarantine", "evidence"]


@dataclass(frozen=True)
class ExactImportIntent:
    """Explicit interpretation options; never a transient collection clock."""

    transaction_sheet: str | None = None
    asset_sheet: str | None = None
    overview_sheet: str | None = None
    snapshot_date: str | None = None
    collected_at: str | None = None

    def payload(self) -> dict[str, JSONValue]:
        """Return the stable user-intent fields stored on the request and manifest."""
        return {
            "asset_sheet": self.asset_sheet,
            "collected_at": self.collected_at,
            "overview_sheet": self.overview_sheet,
            "snapshot_date": self.snapshot_date,
            "transaction_sheet": self.transaction_sheet,
        }


@dataclass(frozen=True)
class ExactImportCommand:
    """One file-level import request bound to captured bytes and intent."""

    capture: ExactWorkbookCapture
    intent: ExactImportIntent = ExactImportIntent()
    preview: bool = False

    def payload(self) -> dict[str, JSONValue]:
        """Return the MutationService payload without a transient execution clock."""
        return {
            "artifact_digest": self.capture.artifact_id,
            "byte_length": self.capture.byte_length,
            "filename": self.capture.filename,
            "import_policy_version": IMPORT_POLICY_VERSION,
            "intent": self.intent.payload(),
            "parser_policy_version": PARSER_POLICY_VERSION,
        }


@dataclass(frozen=True)
class RowDecision:
    """One source row disposition inside a planned import."""

    family: FamilyName
    action: RowAction
    sheet_name: str
    source_row: int
    candidate_ids: tuple[str, ...] = ()


@dataclass
class FamilyCounts:
    """Integer counts for one mapped family."""

    inserted: int = 0
    reused: int = 0
    quarantined: int = 0
    unsupported: int = 0

    def as_dict(self) -> dict[str, int]:
        """Return JSON-safe integer counts."""
        return {
            "inserted": self.inserted,
            "quarantined": self.quarantined,
            "reused": self.reused,
            "unsupported": self.unsupported,
        }


@dataclass
class ImportCounts:
    """Domain counts shared by preview and committed receipts."""

    transactions: FamilyCounts = field(default_factory=FamilyCounts)
    assets: FamilyCounts = field(default_factory=FamilyCounts)
    overview: FamilyCounts = field(default_factory=FamilyCounts)
    unknown_sheets: int = 0
    uncovered_rows: int = 0
    mapper_status: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, JSONValue]:
        """Return nested integer/string counts without floats or IDs."""
        return {
            "assets": self.assets.as_dict(),
            "mapper_status": dict(self.mapper_status),
            "overview": self.overview.as_dict(),
            "transactions": self.transactions.as_dict(),
            "uncovered_rows": self.uncovered_rows,
            "unknown_sheets": self.unknown_sheets,
        }


@dataclass
class ImportPlan:
    """In-memory disposition for one captured workbook."""

    counts: ImportCounts
    decisions: tuple[RowDecision, ...]
    claimed_sheets: tuple[str, ...]
    mapping_issue_codes: tuple[str, ...]
