"""Repository selection for the legacy month-scoped show interface."""

from __future__ import annotations

from dataclasses import replace

import polars as pl
import typer

from finjuice.pipeline.cli.report_filters import no_filter_requested
from finjuice.pipeline.storage.csv_transactions_read_normalize import _decode_tag_columns
from finjuice.pipeline.storage.read_facade import transaction_frame
from finjuice.pipeline.storage.sqlite.errors import RepositoryIntegrityError
from finjuice.pipeline.storage.sqlite.transaction_reads import TransactionReadSnapshot
from finjuice.pipeline.tagging.rules import ReportFilters
from finjuice.pipeline.tagging.rules_yaml_io import load_report_filters_bytes


def repository_show_rows(
    snapshot: TransactionReadSnapshot, month: str | None, *, search_all: bool
) -> tuple[pl.DataFrame | None, str | None, int]:
    """Select by preserved partition scope before applying any display filters."""
    scopes = {scope.transaction_id: scope for scope in snapshot.scopes}
    if set(scopes) != {row["transaction_id"] for row in snapshot.rows}:
        raise RepositoryIntegrityError("Transaction snapshot is missing partition scope evidence.")
    months = snapshot.partition_months
    selected_month = month
    if selected_month is None and not search_all and months:
        selected_month = months[-1]
    if selected_month is not None and selected_month not in months:
        return None, selected_month, len(months)
    if selected_month is None and not search_all:
        return None, None, len(months)
    original_order = sorted(
        snapshot.scopes,
        key=lambda scope: (
            scope.source_row is None,
            scope.month or "",
            scope.source_row or 0,
            scope.transaction_id,
        ),
    )
    row_by_id = {row["transaction_id"]: row for row in snapshot.rows}
    rows = tuple(
        row_by_id[scope.transaction_id]
        for scope in original_order
        if scope.included and (selected_month is None or scope.month == selected_month)
    )
    if not rows and not months:
        return None, selected_month, 0
    frame = transaction_frame(replace(snapshot, rows=rows))
    if selected_month is None:
        # The legacy all-partition reader sorts before show applies its final
        # descending sort; matching this also preserves equal-time pagination.
        frame = frame.sort("datetime")
    return _decode_tag_columns(frame), selected_month, len(months)


def repository_show_filters(ctx: typer.Context, snapshot: TransactionReadSnapshot) -> ReportFilters:
    """Read canonical report filters from the already selected row revision."""
    if no_filter_requested(ctx):
        return ReportFilters()
    if snapshot.rules_content is not None and snapshot.rules_parsed_status != "parsed":
        raise ValueError("Canonical rules head is not parsed; report filters cannot be applied.")
    return load_report_filters_bytes(snapshot.rules_content)
