"""Detached, complete source-backed history from one repository revision."""

from __future__ import annotations

import sqlite3
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from finjuice.pipeline.storage.sqlite.errors import RepositoryIntegrityError
from finjuice.pipeline.storage.sqlite.paths import GenerationPaths
from finjuice.pipeline.storage.sqlite.schema import RepositoryInfo


@dataclass(frozen=True)
class LegacyHistoryRecord:
    """One original CSV record, preserving aliases separately from evidence IDs."""

    occurrence_id: str
    artifact_id: str
    provenance_id: str
    source_row: int
    fields: dict[str, str | None]
    raw_payload: dict[str, Any]


@dataclass(frozen=True)
class NativeImportHistoryRecord:
    """A verified native completion without inferred legacy archive or row counts."""

    occurrence_id: str
    artifact_id: str
    provenance_id: str
    original_filename: str | None
    imported_at: str | None
    counts: dict[str, Any]
    legacy_file_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class HistoryReadSnapshot:
    """Caller-owned history records pinned to the reader's dataset revision."""

    info: RepositoryInfo
    legacy_records: tuple[LegacyHistoryRecord, ...]
    native_records: tuple[NativeImportHistoryRecord, ...]


def history_snapshot(
    connection: sqlite3.Connection, paths: GenerationPaths, info: RepositoryInfo
) -> HistoryReadSnapshot:
    """Read complete history evidence without interpreting transaction projections."""
    from finjuice.pipeline.storage.sqlite.history_native import native_history_records
    from finjuice.pipeline.storage.sqlite.history_rows import legacy_history_records
    from finjuice.pipeline.storage.sqlite.history_sources import verified_history_sources

    try:
        sources = verified_history_sources(connection, paths)
        legacy = tuple(
            record for source in sources for record in legacy_history_records(connection, source)
        )
        native = native_history_records(connection, paths)
        return deepcopy(HistoryReadSnapshot(info, legacy, native))
    except Exception:
        raise RepositoryIntegrityError(
            "Canonical history evidence is incomplete or invalid."
        ) from None
