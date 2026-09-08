"""Public and internal types for legacy full-tree backup."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

SCHEMA_VERSION = "finjuice.backup.v1"
COMPLETION_MARKER = "FINJUICE_BACKUP_COMPLETE"
MANIFEST_FILENAME = "backup-manifest.json"
PAYLOAD_DIRNAME = "payload"
DATA_ROOT_NAME = "data"
ROOTS_DIRNAME = "roots"
INACTIVE_GENERATION = "generation.json"

Presence = Literal["required", "optional"]
RootState = Literal["present", "intentionally_absent"]
EntryType = Literal["file", "directory"]
ConsistencyKind = Literal["stopped_writers", "named_snapshot"]


@dataclass(frozen=True)
class ConsistencyEvidence:
    """Operator-supplied capture consistency evidence."""

    kind: ConsistencyKind
    stopped_writers: tuple[str, ...] = ()
    snapshot_name: str | None = None


@dataclass(frozen=True)
class SourceRoot:
    """One inventoried backup root."""

    name: str
    presence: Presence
    path: Path | None = None
    role: str = "external"


@dataclass(frozen=True)
class StatIdentity:
    """lstat identity used to detect mid-capture mutation."""

    dev: int
    ino: int
    size: int
    mtime_ns: int
    mode: int
    entry_type: EntryType


@dataclass(frozen=True)
class InventoryEntry:
    """One portable inventory entry for a present root."""

    root: str
    path: str
    entry_type: EntryType
    size: int
    mode: str
    mtime_ns: int
    sha256: str | None
    identity: StatIdentity | None = None


@dataclass
class RootScan:
    """Scan result for one logical root."""

    spec: SourceRoot
    state: RootState
    entry_type: EntryType | None
    entries: list[InventoryEntry] = field(default_factory=list)


@dataclass
class Inventory:
    """Complete pre or post capture inventory."""

    roots: list[RootScan] = field(default_factory=list)
    entries: list[InventoryEntry] = field(default_factory=list)

    @property
    def file_count(self) -> int:
        return sum(1 for entry in self.entries if entry.entry_type == "file")

    @property
    def directory_count(self) -> int:
        return sum(1 for entry in self.entries if entry.entry_type == "directory")

    @property
    def byte_count(self) -> int:
        return sum(entry.size for entry in self.entries if entry.entry_type == "file")


@dataclass(frozen=True)
class CreateRequest:
    """Inputs for ``backup create``."""

    source: Path
    output: Path
    consistency: ConsistencyEvidence
    extra_roots: tuple[SourceRoot, ...] = ()
    parent_attempt_id: str | None = None


@dataclass(frozen=True)
class BackupResult:
    """Privacy-safe command result."""

    status: Literal["ok", "already_complete"]
    schema_version: str
    manifest_digest: str
    entry_count: int
    file_count: int
    directory_count: int
    byte_count: int
    root_count: int
    absent_optional_count: int
    finjuice_version: str
    data_schema_version: int | None
    data_schema_version_status: Literal["present", "missing", "invalid"]
    consistency_kind: str
    generation_status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "schema_version": self.schema_version,
            "manifest_digest": self.manifest_digest,
            "entry_count": self.entry_count,
            "file_count": self.file_count,
            "directory_count": self.directory_count,
            "byte_count": self.byte_count,
            "root_count": self.root_count,
            "absent_optional_count": self.absent_optional_count,
            "finjuice_version": self.finjuice_version,
            "data_schema_version": self.data_schema_version,
            "data_schema_version_status": self.data_schema_version_status,
            "consistency_kind": self.consistency_kind,
        }
        if self.generation_status is not None:
            payload["generation_status"] = self.generation_status
        return payload
