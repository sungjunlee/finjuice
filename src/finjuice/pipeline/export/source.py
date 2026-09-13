"""Exact repository authority and pinned display inputs for one export run."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from finjuice.pipeline.report_filters import apply_report_filters
from finjuice.pipeline.storage.authority import ActivationEvidenceProvider
from finjuice.pipeline.storage.csv_transactions_read_normalize import _decode_tag_columns
from finjuice.pipeline.storage.read_facade import (
    read_transaction_snapshot,
    snapshot_metadata,
    transaction_frame,
)
from finjuice.pipeline.storage.sqlite.transaction_reads import TransactionReadSnapshot
from finjuice.pipeline.tagging.models import ReportFilters
from finjuice.pipeline.tagging.rules_yaml_io import load_report_filters_bytes


class RepositoryExportError(RuntimeError):
    """Non-sensitive failure of repository export preparation or publication."""


@dataclass(frozen=True)
class ExportSourceOptions:
    """Stable selection and rendering options for a repository export."""

    format: str
    period: str | None
    filters_disabled: bool
    online: bool


@dataclass(frozen=True)
class RepositoryExportSource:
    """Detached full and report projections with their shared provenance."""

    full_frame: pl.DataFrame
    report_frame: pl.DataFrame
    filters_applied: int
    metadata: dict[str, Any]


def load_export_source(
    data_dir: Path,
    evidence_provider: ActivationEvidenceProvider | None,
    options: ExportSourceOptions,
) -> RepositoryExportSource | None:
    """Read once; only unactivated authority may use the legacy CSV path."""
    try:
        snapshot = read_transaction_snapshot(data_dir, evidence_provider)
        if snapshot is None:
            return None
        return _project_source(snapshot, options)
    except Exception:
        raise RepositoryExportError(
            "Repository export could not read validated source data."
        ) from None


def _project_source(
    snapshot: TransactionReadSnapshot, options: ExportSourceOptions
) -> RepositoryExportSource:
    filters = ReportFilters()
    if not options.filters_disabled:
        if snapshot.rules_content is not None and snapshot.rules_parsed_status != "parsed":
            raise ValueError("Canonical rules head is not parsed.")
        filters = load_report_filters_bytes(snapshot.rules_content)
    full = _decode_tag_columns(transaction_frame(_source_order(snapshot)))
    report = full
    if options.format in {"html", "md"} and options.period is not None:
        report = report.filter(pl.col("date").str.starts_with(options.period))
    report, count = apply_report_filters(report, filters)
    metadata = {
        **snapshot_metadata(snapshot),
        "calculation_policy": "legacy_export.v1",
        "calculation_as_of": _calculation_as_of(snapshot),
        "format": options.format,
        "period": options.period,
        "filters_disabled": options.filters_disabled,
        "online": options.online,
    }
    return RepositoryExportSource(full, report, count, metadata)


def _calculation_as_of(snapshot: TransactionReadSnapshot) -> str | None:
    dates = []
    for row in snapshot.rows:
        value = row.get("date")
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            continue
        try:
            dates.append(date.fromisoformat(value))
        except ValueError:
            continue
    return max(dates).isoformat() if dates else None


def _source_order(snapshot: TransactionReadSnapshot) -> TransactionReadSnapshot:
    """Restore proven CSV occurrence order without excluding other stored rows."""
    proven = {
        scope.transaction_id: (scope.month, scope.source_row)
        for scope in snapshot.scopes
        if scope.included and scope.month is not None and scope.source_row is not None
    }
    rows = tuple(
        sorted(
            snapshot.rows,
            key=lambda row: (
                row["transaction_id"] not in proven,
                *proven.get(row["transaction_id"], ("", 0)),
                row["transaction_id"],
            ),
        )
    )
    return replace(snapshot, rows=rows)
