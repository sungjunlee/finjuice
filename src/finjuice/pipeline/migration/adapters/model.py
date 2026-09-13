"""Deterministic, read-only analysis and repository emission primitives."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from finjuice.pipeline.migration.policy import LEGACY_POLICY
from finjuice.pipeline.storage.sqlite.ids import migration_entity_id
from finjuice.pipeline.storage.sqlite.records import (
    EntityKind,
    LegacyIdentifierRecord,
    MigrationIdentityRecord,
    PreservationIssueRecord,
    ProvenanceRecord,
)
from finjuice.pipeline.storage.sqlite.repository import RepositoryBuilder

PARSER = "legacy_preservation.v1"


@dataclass(frozen=True)
class FileContext:
    """Frozen capture identity and original, unnormalized logical locator."""

    capture_digest: str
    root_name: str
    relative_path: str
    source_schema_version: str | None = None
    config_head_timestamp: str | None = None
    migration_policy: str = LEGACY_POLICY
    fact_index: tuple[tuple[str, str, str], ...] = ()


@dataclass(frozen=True)
class FileAnalysis:
    """Immutable privacy-safe counts produced identically by analysis and build."""

    record_counts: tuple[tuple[str, int], ...]
    disposition_counts: tuple[tuple[str, int], ...]
    issue_counts: tuple[tuple[str, int], ...]

    def to_dict(self) -> dict[str, dict[str, int]]:
        return {
            "record_counts": dict(self.record_counts),
            "disposition_counts": dict(self.disposition_counts),
            "issue_counts": dict(self.issue_counts),
        }


class Emitter:
    """Emit the same deterministic records with or without a repository writer."""

    def __init__(self, context: FileContext, builder: RepositoryBuilder | None) -> None:
        self.context = context
        self.builder = builder
        self.records: Counter[str] = Counter()
        self.dispositions: Counter[str] = Counter()
        self.issues: Counter[str] = Counter()
        self.row: int | None = None
        self.occurrence = self.identifier("source_occurrence")

    def locator(self, **extra: Any) -> dict[str, Any]:
        return {
            "root": self.context.root_name,
            "path": self.context.relative_path,
            "row": self.row,
            **extra,
        }

    def identifier(self, kind: str, **extra: Any) -> str:
        return migration_entity_id(self.context.capture_digest, kind, self.locator(**extra))

    def call(self, method: str, *args: Any, **kwargs: Any) -> None:
        if self.builder is not None:
            getattr(self.builder, method)(*args, **kwargs)

    def entity(self, kind: EntityKind, record: Any, **extra: Any) -> str:
        identifier = self.identifier(kind, **extra)
        self.call(f"add_{kind}", record)
        self.call(
            "add_migration_identity",
            MigrationIdentityRecord(
                identifier, self.context.capture_digest, kind, self.locator(**extra)
            ),
        )
        self.records[kind] += 1
        self.legacy(identifier, "old_path", self.context.relative_path, **extra)
        return identifier

    def legacy(self, entity: str, kind: str, value: str, **extra: Any) -> None:
        stored_kind = (
            kind
            if kind in {"row_hash", "file_id", "source_row", "old_path", "account_text", "fact_id"}
            else "other"
        )
        stored_value = value if stored_kind == kind else f"{kind}:{value}"
        self.call(
            "add_legacy_identifier",
            LegacyIdentifierRecord(
                entity,
                stored_kind,
                stored_value,
                self.context.capture_digest,
                self.identifier("provenance"),
                self.identifier("legacy_identifier", entity=entity, identifier_kind=kind, **extra),
            ),
        )

    def provenance(self, payload: dict[str, Any]) -> str:
        identifier = self.identifier("provenance")
        self.call(
            "add_provenance",
            ProvenanceRecord(
                identifier,
                self.occurrence,
                self.locator(),
                self.locator(),
                PARSER,
                self.context.source_schema_version,
            ),
        )
        self.call(
            "add_legacy_payload", identifier, payload, payload_id=self.identifier("legacy_payload")
        )
        self.records["provenance"] += 1
        return identifier

    def issue(self, kind: str, field: str | None = None, value: str | None = None) -> None:
        self.call(
            "add_preservation_issue",
            PreservationIssueRecord(
                self.identifier("provenance"),
                kind,
                {"preserved_in": "legacy_payload"},
                field,
                value,
                self.identifier("preservation_issue", issue=kind, field=field),
            ),
        )
        self.issues[kind] += 1

    def disposition(self, value: str, reason: str) -> None:
        self.call("add_migration_disposition", self.identifier("provenance"), value, reason)
        self.dispositions[value] += 1

    def finish(self) -> FileAnalysis:
        return FileAnalysis(
            tuple(sorted(self.records.items())),
            tuple(sorted(self.dispositions.items())),
            tuple(sorted(self.issues.items())),
        )
