"""Status facts from one detached repository revision, without CSV diagnostics."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Any

import polars as pl

from finjuice.pipeline.cli.output import ErrorCode, ExitCode
from finjuice.pipeline.storage.csv_transactions_read_normalize import _decode_tag_columns
from finjuice.pipeline.storage.read_facade import (
    read_status_snapshot,
    snapshot_metadata,
    transaction_frame,
)
from finjuice.pipeline.storage.report_filter_exprs import (
    build_report_filter_polars_expr,
    matched_report_filter_rule_indexes,
)
from finjuice.pipeline.storage.sqlite.status_reads import ConfigHeadSnapshot, StatusReadSnapshot
from finjuice.pipeline.tagging.models import ReportFilters
from finjuice.pipeline.tagging.rules_yaml_io import load_report_filters_bytes

from .compute import StatusCommandError, StatusFacts, StatusOptions
from .compute_helpers import _add_untagged_merchants, _count_tagging_rows, _top_untagged_merchants


def collect_repository_status_facts(options: StatusOptions) -> StatusFacts | None:
    """Select authority once; errors never authorize legacy fallback."""
    try:
        snapshot = read_status_snapshot(options.config.data_dir, options.evidence_provider)
        if snapshot is None:
            return None
        return _collect(snapshot, options)
    except StatusCommandError:
        raise
    except Exception:
        raise StatusCommandError(
            "Repository status could not read validated source data.",
            error_code=ErrorCode.INSPECTION_FAILED,
            exit_code=ExitCode.GENERAL_ERROR,
            suggestion=None,
        ) from None


def _filters(snapshot: StatusReadSnapshot, options: StatusOptions) -> ReportFilters:
    if options.no_filter:
        return ReportFilters()
    head = snapshot.rules
    try:
        if head is not None and head.parsed_status != "parsed":
            raise ValueError("Canonical rules are not parsed.")
        # Caller-supplied/live filters cannot override the selected canonical revision.
        return load_report_filters_bytes(head.content if head else None)
    except ValueError:
        raise StatusCommandError(
            "Canonical rules cannot supply report filters.",
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            suggestion="finjuice --no-filter status --json",
        ) from None


def _head(head: ConfigHeadSnapshot | None) -> dict[str, Any]:
    return {
        "revision_id": head.revision_id if head else None,
        "parsed_status": head.parsed_status if head else "missing",
        "updated_at": head.updated_at if head else None,
    }


def _frame(snapshot: StatusReadSnapshot) -> pl.DataFrame:
    transactions = snapshot.transactions
    by_id = {row["transaction_id"]: row for row in transactions.rows}
    scopes = sorted(
        transactions.scopes,
        key=lambda s: (
            not s.included,
            s.month or "",
            s.source_row is None,
            s.source_row or 0,
            s.transaction_id,
        ),
    )
    if {scope.transaction_id for scope in scopes} != set(by_id):
        raise ValueError("Missing status scope evidence.")
    ordered = replace(transactions, rows=tuple(by_id[scope.transaction_id] for scope in scopes))
    return _decode_tag_columns(transaction_frame(ordered))


def _metadata(snapshot: StatusReadSnapshot, frame: pl.DataFrame) -> dict[str, Any]:
    dates: list[str] = []
    for value in frame["date"].drop_nulls().unique().to_list():
        try:
            if len(value) == 10 and date.fromisoformat(value).isoformat() == value:
                dates.append(value)
        except ValueError:
            continue
    return {
        **snapshot_metadata(snapshot.transactions),
        "calculation_policy": "legacy_status.v1",
        "calculation_as_of": max(dates, default=None),
    }


def _repository(snapshot: StatusReadSnapshot, full: pl.DataFrame) -> dict[str, Any]:
    occurrences = snapshot.source_occurrences
    last_import = _last_import(snapshot)
    scopes = snapshot.transactions.scopes
    return {
        "metadata": _metadata(snapshot, full),
        "schema_version": snapshot.info.schema_version,
        "rules_head": _head(snapshot.rules),
        "goals_head": _head(snapshot.goals),
        "source_counts": {
            "total_rows": full.height,
            "primary_scope_rows": sum(s.included for s in scopes),
            "out_of_scope_rows": sum(not s.included for s in scopes),
            "unknown_month_rows": sum(s.month is None for s in scopes),
        },
        "last_import": last_import,
        "legacy_import_history_count": len(snapshot.legacy_import_history),
        "source_occurrence_counts": {
            origin: sum(item.origin == origin for item in occurrences)
            for origin in ("native_import", "migration_capture", "other")
        },
    }


def _last_import(snapshot: StatusReadSnapshot) -> dict[str, Any]:
    # Native completed imports occurred after the captured baseline. Do not compare
    # their UTC clock to timezone-unknown preserved strings to infer chronology.
    native = [item for item in snapshot.source_occurrences if item.origin == "native_import"]
    latest = max(
        native, key=lambda item: (item.imported_at or "", item.occurrence_id), default=None
    )
    if latest is not None:
        return {
            "imported_at": latest.imported_at,
            "file_id": latest.legacy_file_ids[0] if len(latest.legacy_file_ids) == 1 else None,
            "occurrence_id": latest.occurrence_id,
            "origin": latest.origin,
            "selection_policy": "native_then_legacy_lexical.v1",
        }
    history = snapshot.legacy_import_history
    last = None
    if history:
        # Match the old status Polars sort, including null and source-row tie order.
        rows = sorted(history, key=lambda item: (item.source_row, item.provenance_id))
        selected = pl.DataFrame(
            {"imported_at": [item.imported_at or None for item in rows], "index": range(len(rows))}
        ).sort("imported_at", descending=True)
        last = rows[selected["index"][0]]
    return {
        "imported_at": (last.imported_at or None) if last else None,
        "file_id": (last.legacy_file_id or None) if last else None,
        "occurrence_id": None,
        "origin": "legacy_import_history" if last else None,
        "provenance_id": last.provenance_id if last else None,
        "selection_policy": "native_then_legacy_lexical.v1",
    }


def _collect(snapshot: StatusReadSnapshot, options: StatusOptions) -> StatusFacts:
    filters = _filters(snapshot, options)
    full = _frame(snapshot)
    matched = len(matched_report_filter_rule_indexes(full, filters))
    expression = build_report_filter_polars_expr(filters)
    frame = full.filter(~expression) if expression is not None else full
    counts = _count_tagging_rows(frame)
    merchants: dict[str, int] = {}
    _add_untagged_merchants(merchants, counts.pop("untagged"))
    top_merchants, merchant_count = _top_untagged_merchants(merchants, top_n=options.top_n)
    total = frame.height
    tagged = total - counts["untagged_count"]
    suggestable = total - counts["transfer_excluded_count"]
    suggestable_tagged = suggestable - counts["suggestable_untagged_count"]
    repository = _repository(snapshot, full)
    detailed, warning = _detailed(snapshot, options, full, filters)
    return StatusFacts(
        data_dir=options.config.data_dir,
        data_dir_resolved=str(options.config.data_dir.resolve()),
        data_dir_source=options.data_dir_source,
        total_rows=total,
        min_date=frame["date"].min(),
        max_date=frame["date"].max(),
        partition_count=len(snapshot.transactions.partition_months),
        schema_summary=None,
        last_import_date=repository["last_import"]["imported_at"],
        last_import_file=repository["last_import"]["file_id"],
        rules_path=options.config.rules_file,
        rules_exists=snapshot.rules is not None,
        rules_modified=snapshot.rules.updated_at if snapshot.rules else None,
        tagged_count=tagged,
        tagging_rate=round(tagged / total * 100, 2) if total else 0.0,
        suggestable_transaction_count=suggestable,
        suggestable_tagged_count=suggestable_tagged,
        suggestable_tagging_rate=round(suggestable_tagged / suggestable * 100, 2)
        if suggestable
        else 0.0,
        untagged_merchants=top_merchants,
        untagged_merchants_total=merchant_count,
        filters_applied=matched,
        detailed_requested=options.detailed,
        top_n=options.top_n,
        detailed_stats=detailed,
        detailed_stats_warning=warning,
        repository=repository,
        **counts,
    )


def _detailed(
    snapshot: StatusReadSnapshot,
    options: StatusOptions,
    frame: pl.DataFrame,
    filters: ReportFilters,
) -> tuple[dict[str, Any] | None, str | None]:
    if not options.detailed:
        return None, None
    from finjuice.pipeline.insights import (
        RepositoryStatusSnapshotOptions,
        collect_repository_status_snapshot,
    )

    result = collect_repository_status_snapshot(
        frame,
        RepositoryStatusSnapshotOptions(
            goals_content=snapshot.goals.content if snapshot.goals else None,
            goals_parsed_status=snapshot.goals.parsed_status if snapshot.goals else None,
            report_filters=filters,
            top_n=options.top_n,
            active_filter_count=filters.total_rules,
        ),
    )
    return result.snapshot.to_dict(), result.warning
