"""Shared financial snapshot helpers for CLI surfaces.

Monthly stats, structural-savings, and top-category compute helpers live in
:mod:`finjuice.pipeline.insights_helpers` and are re-exported here so existing
callers can keep importing from this module.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

import polars as pl
import yaml

try:
    import duckdb
except ImportError:
    duckdb = None  # type: ignore[assignment]

from finjuice.pipeline.analytics.duckdb_layer import DUCKDB_INSTALL_HINT, DuckDBAnalytics
from finjuice.pipeline.config import Config
from finjuice.pipeline.insights_helpers import (
    MonthlyStats,  # noqa: F401 — re-exported for existing insights imports
    RecurringSavingsSummary,  # noqa: F401 — re-exported for existing insights imports
    SnapshotCategory,
    StructuralSavingsSource,
    TransactionStructuralSavingsSummary,  # noqa: F401 — re-exported for existing insights imports
    _build_category_expr,  # noqa: F401 — re-exported for existing insights imports
    _calculate_monthly_stats,
    _calculate_top_categories,
    _calculate_transaction_structural_savings,
    _category_label,  # noqa: F401 — re-exported for existing insights imports
    _coerce_float,  # noqa: F401 — re-exported for existing insights imports
    _exclude_transfer_rows,
    _load_recurring_savings_summary,
    _matching_structural_tags,  # noqa: F401 — re-exported for existing insights imports
    _month_from_row,  # noqa: F401 — re-exported for existing insights imports
    _month_from_value,  # noqa: F401 — re-exported for existing insights imports
    _normalize_tag,  # noqa: F401 — re-exported for existing insights imports
    _observed_months,  # noqa: F401 — re-exported for existing insights imports
    _parse_tag_value,  # noqa: F401 — re-exported for existing insights imports
    _summarize_recurring_savings,  # noqa: F401 — re-exported for existing insights imports
)
from finjuice.pipeline.storage.report_filter_exprs import build_report_filter_polars_expr
from finjuice.pipeline.tagging.models import ReportFilters
from finjuice.pipeline.tagging.rules_yaml_io import load_report_filters

logger = logging.getLogger(__name__)

DEFAULT_STRUCTURAL_SAVINGS_TAG_ALIASES = ("정기저축", "IRP", "연금", "투자입금")

_REPORT_FILTER_CANDIDATES = (
    ("report_filters.yaml",),
    ("report_filters.yml",),
    ("metadata", "report_filters.yaml"),
    ("metadata", "report_filters.yml"),
)


@dataclass(frozen=True)
class StatusSnapshot:
    """Shared detailed status snapshot used by CLI consumers."""

    data_range: Optional[str]
    monthly_avg_income: Optional[int]
    monthly_avg_expense: Optional[int]
    savings_rate_3mo: Optional[float]
    residual_savings_rate_3mo: Optional[float]
    monthly_avg_consumption_expense: Optional[int]
    consumption_savings_rate_3mo: Optional[float]
    structural_savings_monthly_avg: int
    structural_savings_transaction_monthly_avg: int
    recurring_savings_monthly_amount: int
    structural_savings_sources: list[StructuralSavingsSource]
    top_categories: Optional[list[SnapshotCategory]]
    active_filters: int
    active_goals: list[str]

    def to_dict(self) -> dict[str, Any]:
        """Serialize snapshot for JSON/YAML emission."""
        return asdict(self)


@dataclass(frozen=True)
class StatusSnapshotResult:
    """Snapshot payload plus optional warning for degraded analytics."""

    snapshot: StatusSnapshot
    warning: Optional[str] = None


def collect_status_snapshot(
    config: Config,
    *,
    top_n: int = 5,
    report_filters: ReportFilters | None = None,
    active_filter_count: int | None = None,
) -> StatusSnapshotResult:
    """Collect a reusable financial snapshot for journal/status surfaces."""
    partition_files = list(_iter_partition_files(config.csv_base_dir))
    date_start, date_end = _compute_date_range(partition_files)
    recurring_summary = _load_recurring_savings_summary(config.goals_file)
    configured_filters = (
        report_filters if report_filters is not None else _load_configured_report_filters(config)
    )
    resolved_active_filter_count = (
        _count_active_filters(config.data_dir)
        if active_filter_count is None
        else active_filter_count
    )
    base_snapshot = StatusSnapshot(
        data_range=_format_date_range(date_start, date_end),
        monthly_avg_income=None,
        monthly_avg_expense=None,
        savings_rate_3mo=None,
        residual_savings_rate_3mo=None,
        monthly_avg_consumption_expense=None,
        consumption_savings_rate_3mo=None,
        structural_savings_monthly_avg=recurring_summary["monthly_amount"],
        structural_savings_transaction_monthly_avg=0,
        recurring_savings_monthly_amount=recurring_summary["monthly_amount"],
        structural_savings_sources=list(recurring_summary["sources"]),
        top_categories=None,
        active_filters=resolved_active_filter_count,
        active_goals=[],
    )

    if not partition_files:
        return StatusSnapshotResult(snapshot=base_snapshot)

    duckdb_logger = logging.getLogger("finjuice.pipeline.analytics.duckdb_layer")
    previous_duckdb_level = duckdb_logger.level
    duckdb_logger.setLevel(logging.WARNING)
    try:
        with DuckDBAnalytics(config.data_dir) as analytics:
            df = analytics.conn.execute("SELECT * FROM transactions").pl()
    except ImportError as exc:
        if str(exc) != DUCKDB_INSTALL_HINT:
            logger.warning("Status snapshot analytics unavailable: %s", exc)
        return StatusSnapshotResult(
            snapshot=base_snapshot,
            warning=(
                "Detailed analytics unavailable; run `finjuice doctor` for the "
                "DuckDB install command."
            ),
        )
    except FileNotFoundError:
        return StatusSnapshotResult(snapshot=base_snapshot)
    except (duckdb.Error, pl.exceptions.ComputeError) as exc:
        logger.warning("Status snapshot analytics failed: %s", exc)
        return StatusSnapshotResult(
            snapshot=base_snapshot,
            warning="Detailed analytics unavailable; check transaction data and analytics setup.",
        )
    finally:
        duckdb_logger.setLevel(previous_duckdb_level)

    if df.is_empty():
        return StatusSnapshotResult(snapshot=base_snapshot)

    # Honor report_filters so `status --detailed` and journal snapshots agree
    # with the main status counts (FLT-01 / #443 merge).
    filter_expr = build_report_filter_polars_expr(configured_filters)
    if filter_expr is not None:
        df = df.filter(~filter_expr)
        if df.is_empty():
            return StatusSnapshotResult(snapshot=base_snapshot)

    non_transfer_df = _exclude_transfer_rows(df)
    if non_transfer_df.is_empty():
        snapshot = StatusSnapshot(
            data_range=base_snapshot.data_range,
            monthly_avg_income=0,
            monthly_avg_expense=0,
            savings_rate_3mo=None,
            residual_savings_rate_3mo=None,
            monthly_avg_consumption_expense=0,
            consumption_savings_rate_3mo=None,
            structural_savings_monthly_avg=recurring_summary["monthly_amount"],
            structural_savings_transaction_monthly_avg=0,
            recurring_savings_monthly_amount=recurring_summary["monthly_amount"],
            structural_savings_sources=list(recurring_summary["sources"]),
            top_categories=[],
            active_filters=base_snapshot.active_filters,
            active_goals=base_snapshot.active_goals,
        )
        return StatusSnapshotResult(snapshot=snapshot)

    tag_aliases = set(DEFAULT_STRUCTURAL_SAVINGS_TAG_ALIASES) | recurring_summary["tag_aliases"]
    transaction_structural = _calculate_transaction_structural_savings(
        non_transfer_df,
        tag_aliases=tag_aliases,
    )
    monthly_stats = _calculate_monthly_stats(
        non_transfer_df,
        structural_monthly_amounts=transaction_structural["monthly_amounts"],
    )
    structural_transaction_avg = monthly_stats["structural_savings_transaction_monthly_avg"]
    recurring_monthly = recurring_summary["monthly_amount"]
    snapshot = StatusSnapshot(
        data_range=base_snapshot.data_range,
        monthly_avg_income=monthly_stats["monthly_avg_income"],
        monthly_avg_expense=monthly_stats["monthly_avg_expense"],
        savings_rate_3mo=monthly_stats["savings_rate_3mo"],
        residual_savings_rate_3mo=monthly_stats["residual_savings_rate_3mo"],
        monthly_avg_consumption_expense=monthly_stats["monthly_avg_consumption_expense"],
        consumption_savings_rate_3mo=monthly_stats["consumption_savings_rate_3mo"],
        structural_savings_monthly_avg=structural_transaction_avg + recurring_monthly,
        structural_savings_transaction_monthly_avg=structural_transaction_avg,
        recurring_savings_monthly_amount=recurring_monthly,
        structural_savings_sources=[
            *recurring_summary["sources"],
            *transaction_structural["sources"],
        ],
        top_categories=_calculate_top_categories(non_transfer_df, top_n=top_n),
        active_filters=base_snapshot.active_filters,
        active_goals=base_snapshot.active_goals,
    )
    return StatusSnapshotResult(snapshot=snapshot)


def _iter_partition_files(csv_base_dir: Path) -> list[Path]:
    """Return sorted CSV partitions under transactions/."""
    if not csv_base_dir.exists():
        return []
    return sorted(path for path in csv_base_dir.rglob("*.csv") if path.is_file())


def _load_configured_report_filters(config: Config) -> ReportFilters:
    """Best-effort loader for status snapshot consumers outside the CLI layer."""
    try:
        return load_report_filters(config.rules_file)
    except (OSError, ValueError) as exc:
        logger.warning("Skipping report_filters in snapshot due to load error: %s", exc)
        return ReportFilters()


def _compute_date_range(partition_files: list[Path]) -> tuple[Optional[str], Optional[str]]:
    """Scan partition files for min/max date strings."""
    min_date: Optional[str] = None
    max_date: Optional[str] = None

    for partition_path in partition_files:
        try:
            date_df = pl.read_csv(
                partition_path,
                columns=["date"],
                schema_overrides={"date": pl.Utf8},
                null_values=["", "NA", "NULL"],
            )
        except (OSError, pl.exceptions.ComputeError) as exc:
            logger.warning("Could not read dates from %s: %s", partition_path, exc)
            continue

        if date_df.is_empty():
            continue

        partition_min = date_df.select(pl.col("date").min()).item()
        partition_max = date_df.select(pl.col("date").max()).item()

        if partition_min and (min_date is None or partition_min < min_date):
            min_date = partition_min
        if partition_max and (max_date is None or partition_max > max_date):
            max_date = partition_max

    return min_date, max_date


def _format_date_range(date_start: Optional[str], date_end: Optional[str]) -> Optional[str]:
    """Format the snapshot data range label."""
    if not date_start or not date_end:
        return None
    return f"{date_start} ~ {date_end}"


def _count_active_filters(data_dir: Path) -> int:
    """Best-effort count of active report filters if the file exists."""
    rules_path = data_dir / "rules.yaml"
    if rules_path.exists():
        try:
            filters = load_report_filters(rules_path)
        except (OSError, ValueError) as exc:
            logger.warning("Could not parse report filters from %s: %s", rules_path, exc)
        else:
            if not filters.is_empty():
                return filters.total_rules

    payload = _load_report_filters(data_dir)
    if payload is None:
        return 0

    if isinstance(payload, list):
        return sum(1 for item in payload if _filter_enabled(item))

    if isinstance(payload, dict):
        if isinstance(payload.get("filters"), list):
            return sum(1 for item in payload["filters"] if _filter_enabled(item))
        if isinstance(payload.get("report_filters"), list):
            return sum(1 for item in payload["report_filters"] if _filter_enabled(item))
        return sum(1 for value in payload.values() if _filter_enabled(value))

    return 0


def _load_report_filters(data_dir: Path) -> Any | None:
    """Load report filters from common on-disk locations."""
    for parts in _REPORT_FILTER_CANDIDATES:
        candidate = data_dir.joinpath(*parts)
        if not candidate.exists():
            continue
        try:
            return yaml.safe_load(candidate.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            logger.warning("Could not parse report filters file %s: %s", candidate, exc)
            return None
    return None


def _filter_enabled(payload: Any) -> bool:
    """Return True when a filter payload looks active."""
    if payload is None:
        return False
    if isinstance(payload, bool):
        return payload
    if isinstance(payload, dict):
        enabled = payload.get("enabled")
        return enabled is not False
    return True
