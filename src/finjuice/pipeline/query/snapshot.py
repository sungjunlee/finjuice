"""Revision-pinned SQLite snapshots for CLI and DuckDB query reads.

The generation locator (``FINJUICE_SQLITE_GENERATION``) only finds a published
repository. Dataset generation, revision, and row contents come from the
repository itself; the environment variable is not authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import polars as pl

from finjuice.pipeline.query.errors import QuerySourceError
from finjuice.pipeline.storage.authority import (
    ActivationEvidenceProvider,
    LegacyAuthority,
    resolve_storage_authority,
)
from finjuice.pipeline.storage.sqlite import RepositoryReader
from finjuice.pipeline.storage.sqlite.read_compat import (
    GENERATION_ENV_VAR,
    SqliteReadSourceError,
    distinct_month_count,
    filter_month_frame,
    frame_from_reader,
    latest_month_label,
    read_month_frame,
    read_transactions_frame,
)
from finjuice.pipeline.storage.sqlite.read_compat import (
    resolve_generation_database as _resolve_generation_locator,
)

CALCULATION_POLICY = "legacy_transaction_display.v1"


@dataclass(frozen=True)
class QuerySnapshot:
    """One committed repository revision projected into the CSV read contract."""

    database: Path
    dataset_generation: str
    dataset_revision: int
    schema_version: int
    calculation_policy: str
    as_of: str | None
    frame: pl.DataFrame


def resolve_generation_database() -> Path | None:
    """Return the configured generation database, or ``None`` in CSV mode.

    The env var is a locator only. Callers must read generation/revision from
    the published repository, not from the environment.

    Returns:
        Path to ``finjuice.sqlite3`` when a generation root is configured.

    Raises:
        QuerySourceError: The locator is set but no published database exists.
    """
    try:
        return _resolve_generation_locator()
    except SqliteReadSourceError as exc:
        raise QuerySourceError(str(exc)) from exc


def load_query_snapshot(database: Path) -> QuerySnapshot:
    """Load one revision-pinned transaction snapshot from a published repository.

    Args:
        database: Path to a published ``finjuice.sqlite3`` file.

    Returns:
        Snapshot whose frame matches the legacy CSV column contract.

    Raises:
        QuerySourceError: Repository identity is missing from the database.
    """
    with RepositoryReader(database) as reader:
        info = reader.info
        frame = frame_from_reader(reader)
    generation = info.dataset_generation
    revision = info.dataset_revision
    if generation is None or revision is None:
        raise QuerySourceError("Published repository is missing generation or revision.")
    return QuerySnapshot(
        database=database,
        dataset_generation=generation,
        dataset_revision=revision,
        schema_version=info.schema_version,
        calculation_policy=CALCULATION_POLICY,
        as_of=_as_of_date(frame),
        frame=frame,
    )


def configured_snapshot() -> QuerySnapshot | None:
    """Return the configured snapshot, or ``None`` when CSV mode is active."""
    database = resolve_generation_database()
    if database is None:
        return None
    return load_query_snapshot(database)


def configured_source_frame(
    data_dir: Path | None = None,
    evidence_provider: ActivationEvidenceProvider | None = None,
) -> pl.DataFrame | None:
    """Return the SQLite transaction frame for DuckDB ``source_frame``.

    Returns:
        Decoded CSV-contract frame, or ``None`` so callers keep using CSV.
    """
    if data_dir is not None:
        authority = resolve_storage_authority(data_dir, evidence_provider).authority
        if not isinstance(authority, LegacyAuthority):
            return None
    database = resolve_generation_database()
    if database is None:
        return None
    return read_transactions_frame(database)


def _as_of_date(frame: pl.DataFrame) -> str | None:
    """Return the latest transaction date string, or ``None`` if empty."""
    if frame.is_empty() or "date" not in frame.columns:
        return None
    value = frame.select(pl.col("date").max()).item()
    return None if value is None else str(value)


__all__ = [
    "CALCULATION_POLICY",
    "GENERATION_ENV_VAR",
    "QuerySnapshot",
    "configured_snapshot",
    "configured_source_frame",
    "distinct_month_count",
    "filter_month_frame",
    "latest_month_label",
    "load_query_snapshot",
    "read_month_frame",
    "read_transactions_frame",
    "resolve_generation_database",
]
