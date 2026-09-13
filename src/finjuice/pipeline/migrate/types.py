"""Public types and constants for frozen-source preservation migration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

SCHEMA_VERSION = "finjuice.migration.v1"
PARSER_VERSION = "finjuice.migration.v1"
CAPTURE_KIND = "frozen_capture"
PLAN_KIND = "migration_plan"
MIGRATION_KIND = "preservation_baseline"
COMPLETION_MARKER = "FINJUICE_MIGRATION_COMPLETE"
CAPTURE_FILENAME = "capture-manifest.json"
PLAN_FILENAME = "migration-plan.json"
MIGRATION_MANIFEST_FILENAME = "migration-manifest.json"
ORIGIN_KIND = "legacy_current_state"
HIDDEN_CATEGORY_CODE = "hidden_category_sentinel_extracted.v1"

Disposition = Literal["migrated", "preserved_opaque", "quarantined", "intentionally_absent"]
ResultStatus = Literal["ok", "already_complete"]

INVENTORY_ROLES: tuple[str, ...] = (
    "transaction_partition",
    "overview_facts",
    "overview_balance",
    "overview_cashflow",
    "overview_insurance",
    "overview_investment",
    "overview_loan",
    "asset_snapshot",
    "source_workbook",
    "rules",
    "goals",
    "import_history",
    "audit_history",
    "overlay",
)

CSV_ROLES: frozenset[str] = frozenset(
    {
        "transaction_partition",
        "overview_facts",
        "overview_balance",
        "overview_cashflow",
        "overview_insurance",
        "overview_investment",
        "overview_loan",
        "asset_snapshot",
    }
)


@dataclass(frozen=True)
class CaptureEntry:
    """One inventoried frozen file or absent inventory role."""

    logical_role: str
    relative_path: str | None
    state: Literal["present", "intentionally_absent"]
    size: int | None = None
    sha256: str | None = None
    required: bool = False


@dataclass
class CaptureManifest:
    """Frozen input inventory used by plan/build/verify."""

    frozen_root: Path
    entries: list[CaptureEntry] = field(default_factory=list)
    extra_roots: dict[str, str] = field(default_factory=dict)
    canonical_digest: str = ""

    def present_files(self) -> list[CaptureEntry]:
        """Return present file entries."""
        return [entry for entry in self.entries if entry.state == "present"]

    def absent_roles(self) -> list[CaptureEntry]:
        """Return inventoried absences."""
        return [entry for entry in self.entries if entry.state == "intentionally_absent"]


@dataclass(frozen=True)
class PlannedInput:
    """One planned record or file-level input."""

    logical_role: str
    relative_path: str | None
    record_kind: str
    ordinal: int | None
    expected_disposition: Disposition
    sha256: str | None = None


@dataclass
class MigrationPlan:
    """Plan output: expected counts and dispositions for one capture."""

    capture_digest: str
    frozen_root: Path
    capture_path: Path | None
    inputs: list[PlannedInput] = field(default_factory=list)
    extra_roots: dict[str, str] = field(default_factory=dict)

    def counts_by_kind(self) -> dict[str, int]:
        """Return planned record counts by kind."""
        counts: dict[str, int] = {}
        for item in self.inputs:
            counts[item.record_kind] = counts.get(item.record_kind, 0) + 1
        return counts

    def disposition_counts(self) -> dict[str, int]:
        """Return planned disposition counts."""
        counts: dict[str, int] = {}
        for item in self.inputs:
            counts[item.expected_disposition] = counts.get(item.expected_disposition, 0) + 1
        return counts

    def to_public_dict(self) -> dict[str, Any]:
        """Return a privacy-safe plan summary."""
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": PLAN_KIND,
            "capture_digest": self.capture_digest,
            "input_count": len(self.inputs),
            "counts": self.counts_by_kind(),
            "expected_dispositions": self.disposition_counts(),
            "absent_count": sum(
                1 for item in self.inputs if item.expected_disposition == "intentionally_absent"
            ),
        }


@dataclass(frozen=True)
class MigrationResult:
    """Privacy-safe plan/build/verify result."""

    status: ResultStatus
    schema_version: str
    capture_digest: str
    candidate_digest: str | None
    input_count: int
    dispositions: dict[str, int]
    unexplained_loss_count: int
    issue_count: int
    origin_kind: str
    checks: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-serializable result envelope."""
        return {
            "status": self.status,
            "schema_version": self.schema_version,
            "capture_digest": self.capture_digest,
            "candidate_digest": self.candidate_digest,
            "input_count": self.input_count,
            "dispositions": dict(self.dispositions),
            "unexplained_loss_count": self.unexplained_loss_count,
            "issue_count": self.issue_count,
            "origin_kind": self.origin_kind,
            "checks": list(self.checks),
        }
