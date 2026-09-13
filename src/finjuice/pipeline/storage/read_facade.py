"""Authority-aware, revision-pinned read snapshots for application consumers."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import polars as pl

from finjuice.pipeline.storage.authority import (
    ActivationEvidenceProvider,
    LegacyAuthority,
    RepositoryAuthority,
    resolve_storage_authority,
    shared_write_lease,
)
from finjuice.pipeline.storage.csv_schema import CSV_COLUMNS, POLARS_SCHEMA
from finjuice.pipeline.storage.sqlite.errors import RepositoryIntegrityError
from finjuice.pipeline.storage.sqlite.repository import RepositoryReader
from finjuice.pipeline.storage.sqlite.status_reads import StatusReadSnapshot
from finjuice.pipeline.storage.sqlite.transaction_reads import TransactionReadSnapshot

_Snapshot = TypeVar("_Snapshot")

READ_POLICY = "legacy_transaction_display.v1"


def read_transaction_snapshot(
    data_dir: Path,
    evidence_provider: ActivationEvidenceProvider | None = None,
) -> TransactionReadSnapshot | None:
    """Read the active repository; return None only for an unactivated legacy root.

    The host supplies activation evidence independently of the pointer. Errors in
    activation or snapshot validation propagate; they never authorize CSV fallback.
    A shared lease prevents cutover while the selected generation is copied.
    """
    return _read_snapshot(data_dir, evidence_provider, RepositoryReader.transaction_snapshot)


def read_status_snapshot(
    data_dir: Path, evidence_provider: ActivationEvidenceProvider | None = None
) -> StatusReadSnapshot | None:
    """Read status from one revision, with the same fail-closed authority checks."""
    return _read_snapshot(data_dir, evidence_provider, RepositoryReader.status_snapshot)


def _read_snapshot(
    data_dir: Path,
    evidence_provider: ActivationEvidenceProvider | None,
    materialize: Callable[[RepositoryReader], _Snapshot],
) -> _Snapshot | None:
    dispatch = resolve_storage_authority(data_dir, evidence_provider)
    if isinstance(dispatch.authority, LegacyAuthority):
        return None
    with shared_write_lease(dispatch.paths):
        selected = resolve_storage_authority(data_dir, evidence_provider).authority
        if not isinstance(selected, RepositoryAuthority):
            raise RepositoryIntegrityError("Storage authority changed during read selection.")
        with RepositoryReader(selected.paths.database) as reader:
            if reader.info.dataset_generation != selected.activation.dataset_generation:
                raise RepositoryIntegrityError(
                    "Read snapshot generation does not match activation."
                )
            if (
                reader.info.dataset_revision is None
                or reader.info.dataset_revision < selected.activation.dataset_revision
            ):
                raise RepositoryIntegrityError("Read snapshot predates activation.")
            return materialize(reader)


def transaction_frame(snapshot: TransactionReadSnapshot) -> pl.DataFrame:
    """Project the legacy Polars display contract while retaining exact amount evidence.

    Float64 amount/confidence are compatibility display values, not canonical
    amounts. Exact strings and coefficient/scale remain separate columns.
    """
    schema = dict(POLARS_SCHEMA)
    schema.update(
        {
            "transaction_id": pl.String,
            "category_manual": pl.String,
            "amount_coefficient": pl.String,
            "amount_scale": pl.Int64,
            "amount_lexical": pl.String,
            "currency_unknown": pl.Boolean,
        }
    )
    columns = list(CSV_COLUMNS) + [name for name in schema if name not in CSV_COLUMNS]
    if not snapshot.rows:
        return pl.DataFrame(schema={name: schema[name] for name in columns})
    frame = pl.DataFrame(list(snapshot.rows), infer_schema_length=None)
    frame = frame.select(
        [
            pl.col(name).cast(schema[name], strict=True)
            if name in frame.columns
            else pl.lit(None, dtype=schema[name]).alias(name)
            for name in columns
        ]
    )
    for name in ("amount", "confidence"):
        if frame.select(pl.col(name).is_infinite().any()).item():
            raise ValueError("Exact value exceeds the finite legacy display range.")
    return frame


def snapshot_metadata(snapshot: TransactionReadSnapshot) -> dict[str, object]:
    """Identify the stable source and calculation contract of a derived result."""
    return {
        "authority": "repository",
        "dataset_generation": snapshot.info.dataset_generation,
        "dataset_revision": snapshot.info.dataset_revision,
        "sqlite_schema_version": snapshot.info.schema_version,
        "read_policy": READ_POLICY,
    }
