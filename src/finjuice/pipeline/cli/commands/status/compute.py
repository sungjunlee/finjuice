"""Data collection for the ``finjuice status`` command."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl

from finjuice.pipeline.cli.output import ErrorCode, ExitCode
from finjuice.pipeline.config import Config
from finjuice.pipeline.filters import exclude_transfers, only_transfers
from finjuice.pipeline.insights import collect_status_snapshot
from finjuice.pipeline.storage.csv_schema import POLARS_SCHEMA
from finjuice.pipeline.storage.report_filter_exprs import (
    build_report_filter_polars_expr,
    matched_report_filter_rule_indexes,
)
from finjuice.pipeline.storage.schema_registry import (
    PartitionSchemaSummary,
    summarize_partition_schema_versions,
)
from finjuice.pipeline.tagging.models import ReportFilters
from finjuice.pipeline.tagging.rules_yaml_io import load_report_filters

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StatusOptions:
    """Typed options crossing from the Typer wrapper into the status use case."""

    config: Config
    data_dir_source: str
    detailed: bool
    top_n: int
    no_filter: bool
    report_filters: ReportFilters | None


@dataclass(frozen=True)
class StatusFacts:
    """Facts collected for status diagnosis and rendering."""

    data_dir: Path
    data_dir_resolved: str
    data_dir_source: str
    total_rows: int
    min_date: Any | None
    max_date: Any | None
    partition_count: int
    schema_summary: PartitionSchemaSummary
    last_import_date: Any | None
    last_import_file: Any | None
    rules_path: Path
    rules_exists: bool
    rules_modified: str | None
    tagged_count: int
    untagged_count: int
    tagging_rate: float
    suggestable_transaction_count: int
    suggestable_tagged_count: int
    suggestable_untagged_count: int
    suggestable_tagging_rate: float
    transfer_candidate_count: int
    transfer_excluded_count: int
    transfer_excluded_untagged_count: int
    unconfirmed_transfer_candidate_count: int
    untagged_merchants: list[dict[str, Any]]
    untagged_merchants_total: int
    filters_applied: int
    detailed_requested: bool
    top_n: int
    detailed_stats: dict[str, Any] | None = None
    detailed_stats_warning: str | None = None


@dataclass(frozen=True)
class _TransactionMetrics:
    """Aggregated transaction metrics across CSV partitions."""

    total_rows: int
    min_date: Any | None
    max_date: Any | None
    untagged_count: int
    suggestable_untagged_count: int
    transfer_candidate_count: int
    transfer_excluded_count: int
    transfer_excluded_untagged_count: int
    unconfirmed_transfer_candidate_count: int
    untagged_merchants: list[dict[str, Any]]
    untagged_merchants_total: int
    filters_applied: int


class StatusCommandError(Exception):
    """Status use-case failure that the CLI wrapper renders consistently."""

    def __init__(
        self,
        message: str,
        *,
        error_code: ErrorCode,
        exit_code: ExitCode,
        suggestion: str | None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.exit_code = exit_code
        self.suggestion = suggestion


def collect_status_facts(options: StatusOptions) -> StatusFacts:
    """Collect status facts without deciding severity or rendering output."""
    data_dir = options.config.data_dir
    partitions = _transaction_partitions_or_raise(data_dir)
    schema_summary = summarize_partition_schema_versions(
        partitions,
        metadata_dir=data_dir / "metadata",
    )
    report_filters = _load_status_report_filters(options)
    report_filter_expr = build_report_filter_polars_expr(report_filters)
    metrics = _collect_transaction_metrics(
        partitions,
        report_filters,
        report_filter_expr,
        top_n=options.top_n,
    )
    last_import_date, last_import_file = _read_last_import(data_dir)
    rules_path = options.config.rules_file
    rules_exists = rules_path.exists()
    rules_modified = (
        datetime.fromtimestamp(rules_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        if rules_exists
        else None
    )

    tagged_count = metrics.total_rows - metrics.untagged_count if metrics.total_rows > 0 else 0
    tagging_rate = (
        round((tagged_count / metrics.total_rows) * 100, 2) if metrics.total_rows > 0 else 0.0
    )
    suggestable_transaction_count = metrics.total_rows - metrics.transfer_excluded_count
    suggestable_tagged_count = suggestable_transaction_count - metrics.suggestable_untagged_count
    suggestable_tagging_rate = (
        round((suggestable_tagged_count / suggestable_transaction_count) * 100, 2)
        if suggestable_transaction_count > 0
        else 0.0
    )
    detailed_stats: dict[str, Any] | None = None
    detailed_stats_warning = None
    if options.detailed:
        snapshot_result = collect_status_snapshot(
            options.config,
            top_n=options.top_n,
            report_filters=report_filters,
            active_filter_count=0 if options.no_filter else None,
        )
        detailed_stats = snapshot_result.snapshot.to_dict()
        detailed_stats_warning = snapshot_result.warning

    return StatusFacts(
        data_dir=data_dir,
        data_dir_resolved=str(data_dir.resolve()),
        data_dir_source=options.data_dir_source,
        total_rows=metrics.total_rows,
        min_date=metrics.min_date,
        max_date=metrics.max_date,
        partition_count=len(partitions),
        schema_summary=schema_summary,
        last_import_date=last_import_date,
        last_import_file=last_import_file,
        rules_path=rules_path,
        rules_exists=rules_exists,
        rules_modified=rules_modified,
        tagged_count=tagged_count,
        untagged_count=metrics.untagged_count,
        tagging_rate=tagging_rate,
        suggestable_transaction_count=suggestable_transaction_count,
        suggestable_tagged_count=suggestable_tagged_count,
        suggestable_untagged_count=metrics.suggestable_untagged_count,
        suggestable_tagging_rate=suggestable_tagging_rate,
        transfer_candidate_count=metrics.transfer_candidate_count,
        transfer_excluded_count=metrics.transfer_excluded_count,
        transfer_excluded_untagged_count=metrics.transfer_excluded_untagged_count,
        unconfirmed_transfer_candidate_count=metrics.unconfirmed_transfer_candidate_count,
        untagged_merchants=metrics.untagged_merchants,
        untagged_merchants_total=metrics.untagged_merchants_total,
        filters_applied=metrics.filters_applied,
        detailed_requested=options.detailed,
        top_n=options.top_n,
        detailed_stats=detailed_stats,
        detailed_stats_warning=detailed_stats_warning,
    )


def _transaction_partitions_or_raise(data_dir: Path) -> list[Path]:
    """Return validated transaction partitions or raise a status error."""
    transactions_dir = data_dir / "transactions"
    if not transactions_dir.exists():
        if data_dir.exists():
            raise StatusCommandError(
                "No transactions directory. Run 'finjuice ingest' first.",
                error_code=ErrorCode.NO_DATA,
                exit_code=ExitCode.NO_DATA,
                suggestion="finjuice ingest",
            )
        raise StatusCommandError(
            "Data directory not initialized. Run 'finjuice init' first.",
            error_code=ErrorCode.DATA_DIR_NOT_INITIALIZED,
            exit_code=ExitCode.USAGE_ERROR,
            suggestion="finjuice init",
        )

    partitions = list(transactions_dir.rglob("*.csv"))
    if not partitions:
        raise StatusCommandError(
            "No CSV partitions found. Run 'finjuice ingest' first.",
            error_code=ErrorCode.NO_DATA,
            exit_code=ExitCode.NO_DATA,
            suggestion="finjuice ingest",
        )
    return _validated_partitions(transactions_dir, partitions)


def _validated_partitions(transactions_dir: Path, partitions: list[Path]) -> list[Path]:
    """Return partitions that resolve inside the transactions directory."""
    transactions_dir_resolved = transactions_dir.resolve()
    valid_partitions = []
    for partition_path in partitions:
        try:
            if partition_path.resolve().is_relative_to(transactions_dir_resolved):
                valid_partitions.append(partition_path)
            else:
                logger.warning("Skipping partition outside transactions dir: %s", partition_path)
        except (ValueError, OSError) as exc:
            logger.warning("Could not validate path %s: %s", partition_path, exc)
    return valid_partitions


def _collect_transaction_metrics(
    partitions: list[Path],
    report_filters: ReportFilters,
    report_filter_expr: pl.Expr | None,
    *,
    top_n: int,
) -> _TransactionMetrics:
    """Aggregate row, date, tagging, and filter metrics across partitions."""
    total_rows = 0
    min_date = None
    max_date = None
    untagged_count = 0
    suggestable_untagged_count = 0
    transfer_candidate_count = 0
    transfer_excluded_count = 0
    transfer_excluded_untagged_count = 0
    unconfirmed_transfer_candidate_count = 0
    untagged_merchants: dict[str, int] = {}
    matched_filter_indexes: set[int] = set()

    for partition_path in partitions:
        try:
            df = _read_status_partition(partition_path)
            matched_filter_indexes.update(matched_report_filter_rule_indexes(df, report_filters))
            if report_filter_expr is not None:
                df = df.filter(~report_filter_expr)

            total_rows += len(df)
            if len(df) == 0:
                continue

            min_date, max_date = _expand_date_range(df, min_date, max_date)
            row_metrics = _count_tagging_rows(df)
            untagged_count += row_metrics["untagged_count"]
            suggestable_untagged_count += row_metrics["suggestable_untagged_count"]
            transfer_candidate_count += row_metrics["transfer_candidate_count"]
            transfer_excluded_count += row_metrics["transfer_excluded_count"]
            transfer_excluded_untagged_count += row_metrics["transfer_excluded_untagged_count"]
            unconfirmed_transfer_candidate_count += row_metrics[
                "unconfirmed_transfer_candidate_count"
            ]
            _add_untagged_merchants(untagged_merchants, row_metrics["untagged"])
        except (OSError, pl.exceptions.ComputeError) as exc:
            logger.warning("Could not read %s: %s", partition_path, exc)

    untagged_merchant_list, untagged_merchants_total = _top_untagged_merchants(
        untagged_merchants,
        top_n=top_n,
    )
    return _TransactionMetrics(
        total_rows=total_rows,
        min_date=min_date,
        max_date=max_date,
        untagged_count=untagged_count,
        suggestable_untagged_count=suggestable_untagged_count,
        transfer_candidate_count=transfer_candidate_count,
        transfer_excluded_count=transfer_excluded_count,
        transfer_excluded_untagged_count=transfer_excluded_untagged_count,
        unconfirmed_transfer_candidate_count=unconfirmed_transfer_candidate_count,
        untagged_merchants=untagged_merchant_list,
        untagged_merchants_total=untagged_merchants_total,
        filters_applied=len(matched_filter_indexes),
    )


def _read_status_partition(partition_path: Path) -> pl.DataFrame:
    """Read one status partition with the canonical Polars schema overrides."""
    df = pl.read_csv(
        partition_path,
        schema_overrides=POLARS_SCHEMA,
        null_values=["", "NA", "NULL"],
    )
    return _normalize_status_partition_schema(df)


def _normalize_status_partition_schema(df: pl.DataFrame) -> pl.DataFrame:
    """Backfill read-time v3 category columns for compatible v2 partitions."""
    if "is_transfer_candidate" not in df.columns:
        if "is_transfer" in df.columns:
            df = df.with_columns(
                pl.col("is_transfer")
                .cast(pl.Int64, strict=False)
                .fill_null(0)
                .alias("is_transfer_candidate")
            )
        else:
            df = df.with_columns(pl.lit(0).cast(pl.Int64).alias("is_transfer_candidate"))

    if "category_rule" not in df.columns:
        df = df.with_columns(pl.lit(None).cast(pl.Utf8).alias("category_rule"))
    else:
        df = df.with_columns(_blank_to_null("category_rule").alias("category_rule"))

    fallback_candidates: list[pl.Expr] = [_blank_to_null("category_rule")]
    fallback_candidates.append(
        _blank_to_null("minor_raw") if "minor_raw" in df.columns else pl.lit(None).cast(pl.Utf8)
    )
    fallback_candidates.append(
        _blank_to_null("major_raw") if "major_raw" in df.columns else pl.lit(None).cast(pl.Utf8)
    )
    fallback_candidates.append(pl.lit("미분류").cast(pl.Utf8))
    fallback_expr = pl.coalesce(fallback_candidates)

    if "category_final" not in df.columns:
        return df.with_columns(fallback_expr.alias("category_final"))

    return df.with_columns(
        pl.when(_blank_to_null("category_final").is_not_null())
        .then(pl.col("category_final").cast(pl.Utf8, strict=False))
        .otherwise(fallback_expr)
        .alias("category_final")
    )


def _blank_to_null(column_name: str) -> pl.Expr:
    """Return a string expression that treats blank values as null."""
    return pl.col(column_name).cast(pl.Utf8, strict=False).str.strip_chars().replace("", None)


def _expand_date_range(
    df: pl.DataFrame,
    min_date: Any | None,
    max_date: Any | None,
) -> tuple[Any | None, Any | None]:
    """Return the expanded min/max date range for one non-empty partition."""
    partition_min = df.select(pl.col("date").min()).item()
    partition_max = df.select(pl.col("date").max()).item()

    next_min = partition_min if min_date is None or partition_min < min_date else min_date
    next_max = partition_max if max_date is None or partition_max > max_date else max_date
    return next_min, next_max


def _count_tagging_rows(df: pl.DataFrame) -> dict[str, Any]:
    """Return tagging counters for one filtered partition."""
    tags_col = df.schema.get("tags_final")
    untagged = df.filter(_tags_empty_expr(tags_col))
    non_transfer = df.filter(_exclude_transfers_expr(df))
    suggestable_untagged = non_transfer.filter(_tags_empty_expr(tags_col))
    transfer_count = _count_transfer_rows(df)
    transfer_candidate_count = _count_transfer_candidate_rows(df)
    return {
        "untagged": untagged,
        "untagged_count": len(untagged),
        "suggestable_untagged_count": len(suggestable_untagged),
        "transfer_candidate_count": transfer_candidate_count,
        "transfer_excluded_count": transfer_count,
        "transfer_excluded_untagged_count": max(len(untagged) - len(suggestable_untagged), 0),
        "unconfirmed_transfer_candidate_count": max(
            transfer_candidate_count - transfer_count,
            0,
        ),
    }


def _add_untagged_merchants(
    merchant_counts: dict[str, int],
    untagged: pl.DataFrame,
) -> None:
    """Accumulate top-untagged merchant counts without logging row details."""
    if len(untagged) == 0 or "merchant_raw" not in untagged.columns:
        return
    for merchant in untagged["merchant_raw"].to_list():
        if merchant:
            merchant_counts[merchant] = merchant_counts.get(merchant, 0) + 1


def _top_untagged_merchants(
    merchant_counts: dict[str, int],
    *,
    top_n: int,
) -> tuple[list[dict[str, Any]], int]:
    """Return sorted untagged merchant payload and total unique count."""
    all_untagged_sorted = sorted(merchant_counts.items(), key=lambda item: item[1], reverse=True)
    return (
        [{"merchant": name, "count": count} for name, count in all_untagged_sorted[:top_n]],
        len(all_untagged_sorted),
    )


def _load_status_report_filters(options: StatusOptions) -> ReportFilters:
    """Load status report filters after no-data validation has completed."""
    if options.report_filters is not None:
        return options.report_filters
    if options.no_filter:
        return ReportFilters()

    try:
        return load_report_filters(options.config.rules_file)
    except ValueError as exc:
        raise StatusCommandError(
            f"Failed to load report filters: {exc}",
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            suggestion=None,
        ) from exc


def _read_last_import(data_dir: Path) -> tuple[Any | None, Any | None]:
    """Return latest import timestamp and file id from import history."""
    import_history_path = data_dir / "metadata" / "import_history.csv"
    if not import_history_path.exists():
        return None, None

    try:
        import_df = pl.read_csv(import_history_path)
        if len(import_df) == 0:
            return None, None
        last_row = import_df.sort("imported_at", descending=True).head(1)
        return last_row.select("imported_at").item(), last_row.select("file_id").item()
    except (OSError, pl.exceptions.ComputeError) as exc:
        logger.warning("Could not read import history: %s", exc)
        return None, None


def _tags_empty_expr(dtype: pl.DataType | None) -> pl.Expr:
    """Return an expression matching empty or null final tags."""
    if dtype == pl.List(pl.Utf8) or (dtype is not None and str(dtype).startswith("List")):
        return (pl.col("tags_final").list.len() == 0) | pl.col("tags_final").is_null()

    return pl.col("tags_final").str.strip_chars().is_in(["[]", ""]) | pl.col("tags_final").is_null()


def _exclude_transfers_expr(df: pl.DataFrame) -> pl.Expr:
    """Return the transfer-exclusion expression, tolerating older schema partitions."""
    if "is_transfer" not in df.columns:
        return pl.lit(True)
    if "transfer_group_id" not in df.columns:
        return pl.col("is_transfer").fill_null(0) == 0
    return exclude_transfers()


def _count_transfer_rows(df: pl.DataFrame) -> int:
    """Return confirmed transfer row count, tolerating older schema partitions."""
    if "is_transfer" not in df.columns or df.is_empty():
        return 0
    if "transfer_group_id" not in df.columns:
        return len(df.filter(pl.col("is_transfer") == 1))
    return len(df.filter(only_transfers()))


def _count_transfer_candidate_rows(df: pl.DataFrame) -> int:
    """Return transfer-like candidate row count, tolerating older schema partitions."""
    if df.is_empty():
        return 0
    if "is_transfer_candidate" in df.columns:
        return len(df.filter(pl.col("is_transfer_candidate").fill_null(0) == 1))
    if "is_transfer" in df.columns:
        return len(df.filter(pl.col("is_transfer").fill_null(0) == 1))
    return 0
