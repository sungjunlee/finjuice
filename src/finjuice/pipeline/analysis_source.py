"""Shared detached inputs for standalone analysis commands."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

import polars as pl

from finjuice.pipeline.checkup.repository_inputs import scoped_transactions
from finjuice.pipeline.storage.authority import ActivationEvidenceProvider
from finjuice.pipeline.storage.csv_schema import CSV_COLUMNS
from finjuice.pipeline.storage.csv_transactions_read_normalize import _decode_tag_columns

if TYPE_CHECKING:
    from finjuice.pipeline.storage.sqlite.analysis_reads import AnalysisReadSnapshot


class AnalysisReadError(ValueError):
    """Static failure to interpret authoritative analysis inputs."""


def read_analysis_source(
    data_dir: Path, provider: ActivationEvidenceProvider | None = None
) -> AnalysisReadSnapshot | None:
    """Detach one canonical revision, returning None only for legacy authority."""
    from finjuice.pipeline.storage.read_facade import read_analysis_snapshot

    try:
        return read_analysis_snapshot(data_dir, provider)
    except Exception:
        raise AnalysisReadError("Canonical analysis evidence could not be read.") from None


def analysis_frame(
    snapshot: AnalysisReadSnapshot, month: str | None = None, *, decode_tags: bool = True
) -> pl.DataFrame:
    """Project included scopes with the consumer's legacy tag representation."""
    if snapshot.unmaterialized_months and (
        month is None or month in snapshot.unmaterialized_months
    ):
        raise AnalysisReadError("Canonical transaction evidence is incomplete for this selection.")
    try:
        frame = scoped_transactions(snapshot.transactions, month)
        # Both standalone legacy readers use these CSV null literals. Project
        # them only for display/calculation; the detached canonical rows stay exact.
        frame = frame.with_columns(
            pl.when(pl.col(name).is_in(["", "NA", "NULL"]))
            .then(None)
            .otherwise(pl.col(name))
            .alias(name)
            for name in CSV_COLUMNS
            if frame.schema.get(name) == pl.String
        )
        return _decode_tag_columns(frame) if decode_tags else frame
    except Exception:
        raise AnalysisReadError("Canonical analysis rows could not be interpreted.") from None


def analysis_metadata(
    snapshot: AnalysisReadSnapshot, policy: str, month: str | None = None
) -> dict[str, Any]:
    """Identify a detached calculation without exposing financial source content."""
    return {
        "authority": "repository",
        "dataset_generation": snapshot.info.dataset_generation,
        "dataset_revision": snapshot.info.dataset_revision,
        "sqlite_schema_version": snapshot.info.schema_version,
        "calculation_policy": policy,
        "calculation_as_of": date.today().isoformat(),
        "calculation_month": month,
        "rules_selection_state": snapshot.rules.selection_state,
        "goals_selection_state": snapshot.goals.selection_state,
        "unknown_month_rows": sum(
            scope.included and scope.month is None for scope in snapshot.transactions.scopes
        ),
    }
