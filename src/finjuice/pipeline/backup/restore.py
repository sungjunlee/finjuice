"""Isolated restore, copy query, and mutation smoke for SQLite snapshots.

Restore never opens the source generation for writes. A verified copy can be
queried, manually corrected, queried again, and re-backed-up. The second
backup restores independently so copy mutation is proven without activating
the host dataset.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from finjuice.pipeline.backup.errors import BackupError
from finjuice.pipeline.backup.snapshot import SnapshotResult, create_sqlite_snapshot
from finjuice.pipeline.storage.sqlite import backup as sqlite_backup
from finjuice.pipeline.storage.sqlite.backup import RESTORE_CHECKS, RestoreResult
from finjuice.pipeline.storage.sqlite.errors import (
    BackupIncompleteError,
    BackupTransferError,
    BackupVerificationError,
    RepositoryPathError,
)
from finjuice.pipeline.storage.sqlite.ids import new_entity_id
from finjuice.pipeline.storage.sqlite.paths import GenerationPaths
from finjuice.pipeline.storage.sqlite.repository import RepositoryReader
from finjuice.pipeline.storage.sqlite.schema import validate_repository

_BUSY_TIMEOUT_MS: Final = 5_000
_CORRECTION_KIND: Final = "unknown"


@dataclass(frozen=True)
class RestoreReceipt:
    """Verified isolated restore of one complete snapshot."""

    backup_root: Path
    destination: Path
    database: Path
    source_generation: str
    dataset_revision: int
    manifest_digest: str
    verified: bool
    checks: tuple[str, ...]
    file_count: int
    byte_count: int

    def to_dict(self) -> dict[str, Any]:
        """Return a privacy-safe payload without filesystem paths."""
        return {
            "byte_count": self.byte_count,
            "checks": list(self.checks),
            "dataset_revision": self.dataset_revision,
            "file_count": self.file_count,
            "manifest_digest": self.manifest_digest,
            "source_generation": self.source_generation,
            "status": "restored" if self.verified else "incomplete_backup",
            "verified": self.verified,
        }


@dataclass(frozen=True)
class RestoredView:
    """Query surface over one inactive restored copy."""

    dataset_generation: str
    dataset_revision: int
    schema_version: int
    parties: tuple[dict[str, Any], ...]
    config_revisions: tuple[dict[str, Any], ...]
    source_artifacts: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class CorrectionReceipt:
    """One synthetic manual correction applied only to a restored copy."""

    party_id: str
    display_name: str
    dataset_revision: int


@dataclass(frozen=True)
class MutationSmokeResult:
    """Evidence that restore → query → correct → query → re-backup → restore works."""

    first_restore: RestoreReceipt
    before: RestoredView
    correction: CorrectionReceipt
    after: RestoredView
    rebackup: SnapshotResult
    second_restore: RestoreReceipt
    replayed: RestoredView


def restore_sqlite_snapshot(backup_root: Path, destination: Path) -> RestoreReceipt:
    """Copy one complete snapshot into a fresh inactive root and verify it.

    Args:
        backup_root: Directory holding a complete Online Backup snapshot.
        destination: Empty isolated restore root, separate from the source.

    Returns:
        A receipt whose ``verified`` flag is true only after integrity, foreign
        key, and payload hash checks pass.

    Raises:
        BackupError: If the backup is incomplete or the restored copy fails
            verification. The destination is not reported as restored.
    """
    try:
        inner = sqlite_backup.restore_backup(backup_root, destination)
    except BackupIncompleteError as exc:
        raise BackupError(
            "Backup is incomplete and cannot be restored.",
            code="INCOMPLETE_BACKUP",
        ) from exc
    except BackupVerificationError as exc:
        raise BackupError(
            "Restored copy failed integrity, foreign-key, or hash verification.",
            code="INCOMPLETE_BACKUP",
        ) from exc
    except BackupTransferError as exc:
        raise BackupError(
            "Restore transfer failed; the backup remains pending retry.",
            code="BACKUP_PENDING",
        ) from exc
    except RepositoryPathError as exc:
        raise BackupError(
            "Restore destination could not be prepared.",
            code="INVALID_ARGS",
        ) from exc
    return _receipt_from_inner(inner)


def query_restored_copy(destination: Path) -> RestoredView:
    """Read generation identity, config revisions, and parties from a restored copy."""
    database = GenerationPaths(Path(destination).expanduser().absolute()).database
    with RepositoryReader(database) as reader:
        return RestoredView(
            dataset_generation=str(reader.info.dataset_generation),
            dataset_revision=int(reader.info.dataset_revision or 0),
            schema_version=int(reader.info.schema_version),
            parties=tuple(reader.rows("parties")),
            config_revisions=tuple(reader.rows("config_revisions")),
            source_artifacts=tuple(reader.rows("source_artifacts")),
        )


def apply_copy_correction(
    destination: Path,
    *,
    display_name: str,
    party_id: str | None = None,
) -> CorrectionReceipt:
    """Insert one synthetic party on the restored copy and advance its revision.

    The source generation is never opened. This is copy-only mutation smoke,
    not host activation.
    """
    if not display_name:
        raise BackupError("Copy correction requires a synthetic display name.", code="INVALID_ARGS")
    database = GenerationPaths(Path(destination).expanduser().absolute()).database
    if not database.is_file():
        raise BackupError("Restored copy database is missing.", code="INCOMPLETE_BACKUP")
    entity_id = party_id or new_entity_id()
    connection = sqlite3.connect(database, timeout=_BUSY_TIMEOUT_MS / 1000)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            "INSERT INTO entities (entity_id, entity_kind) VALUES (?, 'party')",
            (entity_id,),
        )
        connection.execute(
            "INSERT INTO parties (entity_id, entity_kind, party_kind, display_name) "
            "VALUES (?, 'party', ?, ?)",
            (entity_id, _CORRECTION_KIND, display_name),
        )
        connection.execute(
            "UPDATE repository_meta SET dataset_revision = dataset_revision + 1 "
            "WHERE singleton = 1"
        )
        connection.commit()
        revision = int(
            connection.execute(
                "SELECT dataset_revision FROM repository_meta WHERE singleton = 1"
            ).fetchone()[0]
        )
    except sqlite3.Error as exc:
        connection.rollback()
        raise BackupError(
            "Copy correction could not be applied to the restored database.",
            code="VALIDATION_FAILED",
        ) from exc
    finally:
        connection.close()
    validate_repository(database)
    return CorrectionReceipt(
        party_id=entity_id,
        display_name=display_name,
        dataset_revision=revision,
    )


def restored_mutation_smoke(backup_root: Path, workspace: Path) -> MutationSmokeResult:
    """Restore, query, correct the copy, re-query, re-backup, and restore again."""
    root = Path(workspace).expanduser().absolute()
    first_dir = root / "restore-1"
    second_backup_dir = root / "backup-2"
    second_dir = root / "restore-2"
    first = restore_sqlite_snapshot(backup_root, first_dir)
    before = query_restored_copy(first_dir)
    correction = apply_copy_correction(first_dir, display_name="synthetic-copy-correction")
    after = query_restored_copy(first_dir)
    rebackup = create_sqlite_snapshot(first.database, second_backup_dir)
    if not rebackup.complete:
        raise BackupError(
            "Re-backup of the corrected copy did not complete.",
            code="INCOMPLETE_BACKUP",
        )
    second = restore_sqlite_snapshot(second_backup_dir, second_dir)
    replayed = query_restored_copy(second_dir)
    return MutationSmokeResult(
        first_restore=first,
        before=before,
        correction=correction,
        after=after,
        rebackup=rebackup,
        second_restore=second,
        replayed=replayed,
    )


def _receipt_from_inner(inner: RestoreResult) -> RestoreReceipt:
    """Adapt the inner restore receipt onto the pipeline snapshot restore surface."""
    if not inner.verified:
        raise BackupError(
            "Restored copy failed verification and is not usable.",
            code="INCOMPLETE_BACKUP",
        )
    return RestoreReceipt(
        backup_root=inner.backup_root,
        destination=inner.destination,
        database=inner.database,
        source_generation=inner.source_generation,
        dataset_revision=inner.dataset_revision,
        manifest_digest=inner.manifest_digest,
        verified=True,
        checks=tuple(inner.checks) or RESTORE_CHECKS,
        file_count=inner.file_count,
        byte_count=inner.byte_count,
    )


__all__ = [
    "CorrectionReceipt",
    "MutationSmokeResult",
    "RestoreReceipt",
    "RestoredView",
    "apply_copy_correction",
    "query_restored_copy",
    "restore_sqlite_snapshot",
    "restored_mutation_smoke",
]
