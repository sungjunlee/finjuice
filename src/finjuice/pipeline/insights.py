"""Shared financial snapshot helpers for CLI surfaces."""

from __future__ import annotations

import ast
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional, TypedDict

import polars as pl
import yaml

try:
    import duckdb
except ImportError:
    duckdb = None  # type: ignore[assignment]

from finjuice.pipeline.analytics.duckdb_layer import DUCKDB_INSTALL_HINT, DuckDBAnalytics
from finjuice.pipeline.config import Config
from finjuice.pipeline.filters import exclude_transfers_for
from finjuice.pipeline.goals import (
    GoalsDocument,
    load_goals_file,
    monthly_amount_for_recurring_savings,
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
class SnapshotCategory:
    """Single category rollup for journal/status snapshots."""

    name: str
    amount: int


class StructuralSavingsSource(TypedDict, total=False):
    """Sanitized structural savings source row for status snapshots."""

    source: str
    label: str
    amount: int
    monthly_amount: int
    frequency: str
    tags: list[str]
    category: str
    transaction_count: int
    months: list[str]
    configured_source: str


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


class MonthlyStats(TypedDict):
    """Typed monthly aggregation payload."""

    monthly_avg_income: Optional[int]
    monthly_avg_expense: Optional[int]
    savings_rate_3mo: Optional[float]
    residual_savings_rate_3mo: Optional[float]
    monthly_avg_consumption_expense: Optional[int]
    consumption_savings_rate_3mo: Optional[float]
    structural_savings_transaction_monthly_avg: int


class RecurringSavingsSummary(TypedDict):
    """Recurring savings declared in goals.yaml."""

    monthly_amount: int
    sources: list[StructuralSavingsSource]
    tag_aliases: set[str]


class TransactionStructuralSavingsSummary(TypedDict):
    """Structural savings inferred from transaction tags."""

    monthly_amounts: dict[str, int]
    sources: list[StructuralSavingsSource]


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


def _exclude_transfer_rows(df: pl.DataFrame) -> pl.DataFrame:
    """Apply the shared transfer exclusion rule when possible."""
    return df.filter(exclude_transfers_for(df))


def _calculate_monthly_stats(
    df: pl.DataFrame,
    *,
    structural_monthly_amounts: dict[str, int] | None = None,
) -> MonthlyStats:
    """Compute monthly averages and a recent savings rate."""
    structural_by_month = structural_monthly_amounts or {}
    if df.is_empty() or "date" not in df.columns or "amount" not in df.columns:
        return {
            "monthly_avg_income": None,
            "monthly_avg_expense": None,
            "savings_rate_3mo": None,
            "residual_savings_rate_3mo": None,
            "monthly_avg_consumption_expense": None,
            "consumption_savings_rate_3mo": None,
            "structural_savings_transaction_monthly_avg": 0,
        }

    monthly = (
        df.with_columns(pl.col("date").cast(pl.Utf8).str.slice(0, 7).alias("month"))
        .filter(pl.col("month").is_not_null())
        .group_by("month")
        .agg(
            [
                pl.when(pl.col("amount") > 0)
                .then(pl.col("amount"))
                .otherwise(0.0)
                .sum()
                .alias("income"),
                pl.when(pl.col("amount") < 0)
                .then(pl.col("amount").abs())
                .otherwise(0.0)
                .sum()
                .alias("expense"),
            ]
        )
        .sort("month")
    )

    if monthly.is_empty():
        return {
            "monthly_avg_income": None,
            "monthly_avg_expense": None,
            "savings_rate_3mo": None,
            "residual_savings_rate_3mo": None,
            "monthly_avg_consumption_expense": None,
            "consumption_savings_rate_3mo": None,
            "structural_savings_transaction_monthly_avg": 0,
        }

    avg_income = monthly.select(pl.col("income").mean()).item()
    avg_expense = monthly.select(pl.col("expense").mean()).item()
    monthly_rows = list(monthly.iter_rows(named=True))
    month_count = len(monthly_rows)
    consumption_expense_total = 0.0
    structural_total = 0.0
    for row in monthly_rows:
        month = str(row["month"])
        expense = float(row["expense"] or 0.0)
        structural_amount = min(float(structural_by_month.get(month, 0)), expense)
        structural_total += structural_amount
        consumption_expense_total += max(expense - structural_amount, 0.0)

    recent = monthly.sort("month", descending=True).head(3)
    recent_income = float(recent.select(pl.col("income").sum()).item() or 0.0)
    recent_expense = float(recent.select(pl.col("expense").sum()).item() or 0.0)
    recent_months = [str(month) for month in recent.get_column("month").to_list()]
    recent_structural = sum(structural_by_month.get(month, 0) for month in recent_months)
    recent_consumption_expense = max(recent_expense - recent_structural, 0.0)
    savings_rate = (
        round((recent_income - recent_expense) / recent_income, 2) if recent_income > 0 else None
    )
    consumption_savings_rate = (
        round((recent_income - recent_consumption_expense) / recent_income, 2)
        if recent_income > 0
        else None
    )

    return {
        "monthly_avg_income": int(round(float(avg_income or 0.0))),
        "monthly_avg_expense": int(round(float(avg_expense or 0.0))),
        "savings_rate_3mo": savings_rate,
        "residual_savings_rate_3mo": savings_rate,
        "monthly_avg_consumption_expense": int(
            round(consumption_expense_total / month_count if month_count else 0.0)
        ),
        "consumption_savings_rate_3mo": consumption_savings_rate,
        "structural_savings_transaction_monthly_avg": int(
            round(structural_total / month_count if month_count else 0.0)
        ),
    }


def _load_recurring_savings_summary(goals_file: Path) -> RecurringSavingsSummary:
    """Load confirmed recurring savings entries from a valid goals.yaml."""
    result = load_goals_file(goals_file)
    if result.document is None or result.problems:
        return {"monthly_amount": 0, "sources": [], "tag_aliases": set()}
    return _summarize_recurring_savings(result.document)


def _summarize_recurring_savings(document: GoalsDocument) -> RecurringSavingsSummary:
    """Convert recurring_savings goals into source rows and tag aliases."""
    entries = document.recurring_savings or []
    sources: list[StructuralSavingsSource] = []
    tag_aliases: set[str] = set()
    monthly_total = 0

    for goal in entries:
        monthly_amount = monthly_amount_for_recurring_savings(goal)
        monthly_total += monthly_amount
        tags = list(goal.tags or [])
        tag_aliases.update(tags)
        row: StructuralSavingsSource = {
            "source": "goals.yaml",
            "label": goal.label,
            "monthly_amount": monthly_amount,
            "amount": goal.amount,
            "frequency": goal.frequency,
            "tags": tags,
        }
        if goal.source and goal.source != "goals.yaml":
            row["configured_source"] = goal.source
        sources.append(row)

    return {"monthly_amount": monthly_total, "sources": sources, "tag_aliases": tag_aliases}


def _calculate_transaction_structural_savings(
    df: pl.DataFrame,
    *,
    tag_aliases: set[str],
) -> TransactionStructuralSavingsSummary:
    """Infer structural savings from expense rows tagged with known savings aliases."""
    if df.is_empty() or "amount" not in df.columns or "date" not in df.columns:
        return {"monthly_amounts": {}, "sources": []}

    alias_map = {_normalize_tag(alias): alias for alias in tag_aliases if alias.strip()}
    groups: dict[tuple[str | None, tuple[str, ...]], dict[str, Any]] = {}
    monthly_amounts: dict[str, int] = {}

    for row in df.iter_rows(named=True):
        amount = _coerce_float(row.get("amount"))
        if amount is None or amount >= 0:
            continue
        month = _month_from_row(row)
        if month is None:
            continue
        matching_tags = _matching_structural_tags(row.get("tags_final"), alias_map)
        if not matching_tags:
            continue

        absolute_amount = int(round(abs(amount)))
        monthly_amounts[month] = monthly_amounts.get(month, 0) + absolute_amount
        category = _category_label(row)
        key = (category, tuple(matching_tags))
        group = groups.setdefault(
            key,
            {
                "amount": 0,
                "transaction_count": 0,
                "months": set(),
                "category": category,
                "tags": matching_tags,
            },
        )
        group["amount"] += absolute_amount
        group["transaction_count"] += 1
        group["months"].add(month)

    source_rows: list[StructuralSavingsSource] = []
    observed_month_count = len(_observed_months(df))
    for group in sorted(groups.values(), key=lambda item: (item["category"] or "", item["tags"])):
        monthly_amount = (
            int(round(group["amount"] / observed_month_count)) if observed_month_count else 0
        )
        source: StructuralSavingsSource = {
            "source": "transactions",
            "label": ", ".join(group["tags"]),
            "amount": int(group["amount"]),
            "monthly_amount": monthly_amount,
            "transaction_count": int(group["transaction_count"]),
            "tags": list(group["tags"]),
            "months": sorted(group["months"]),
        }
        if group["category"]:
            source["category"] = str(group["category"])
        source_rows.append(source)

    return {"monthly_amounts": monthly_amounts, "sources": source_rows}


def _observed_months(df: pl.DataFrame) -> set[str]:
    """Return months represented by rows with usable dates."""
    if "date" not in df.columns:
        return set()
    return {
        month
        for value in df.get_column("date").to_list()
        if (month := _month_from_value(value)) is not None
    }


def _month_from_row(row: dict[str, Any]) -> str | None:
    """Extract YYYY-MM from a transaction row."""
    return _month_from_value(row.get("date"))


def _month_from_value(value: Any) -> str | None:
    """Extract YYYY-MM from a date-like value."""
    if value is None:
        return None
    raw = str(value)
    if len(raw) < 7:
        return None
    return raw[:7]


def _matching_structural_tags(value: Any, alias_map: dict[str, str]) -> list[str]:
    """Return unique structural savings tags matched by aliases."""
    matched: dict[str, str] = {}
    for tag in _parse_tag_value(value):
        normalized = _normalize_tag(tag)
        if normalized in alias_map:
            matched[normalized] = alias_map[normalized]
    return sorted(matched.values(), key=lambda tag: tag.casefold())


def _parse_tag_value(value: Any) -> list[str]:
    """Parse tag arrays stored as lists, JSON strings, or Python-list strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if not isinstance(value, str):
        return []

    stripped = value.strip()
    if not stripped or stripped in {"[]", "null", "None"}:
        return []
    for parser in (json.loads, ast.literal_eval):
        try:
            parsed = parser(stripped)
        except (ValueError, SyntaxError):
            continue
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    return [stripped]


def _normalize_tag(tag: str) -> str:
    """Normalize a tag or alias for matching."""
    return tag.strip().casefold()


def _coerce_float(value: Any) -> float | None:
    """Best-effort numeric coercion for mixed transaction schemas."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _category_label(row: dict[str, Any]) -> str | None:
    """Return a sanitized category label without merchant or account details."""
    for column_name in ("category_final", "category_rule", "minor_raw", "major_raw"):
        value = row.get(column_name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _calculate_top_categories(df: pl.DataFrame, *, top_n: int) -> list[SnapshotCategory]:
    """Compute top expense categories with schema-compatible fallback order."""
    if df.is_empty() or "amount" not in df.columns:
        return []

    expense_df = df.filter(pl.col("amount") < 0)
    if expense_df.is_empty():
        return []

    category_expr = _build_category_expr(expense_df)
    categories_df = (
        expense_df.with_columns(category_expr.alias("snapshot_category"))
        .group_by("snapshot_category")
        .agg(pl.col("amount").sum().abs().alias("total_amount"))
        .sort("total_amount", descending=True)
        .head(top_n)
    )

    return [
        SnapshotCategory(name=str(row[0]), amount=int(round(float(row[1]))))
        for row in categories_df.iter_rows()
    ]


def _build_category_expr(df: pl.DataFrame) -> pl.Expr:
    """Build a fallback category expression for mixed schema versions."""
    exprs: list[pl.Expr] = []
    for column_name in ("category_final", "category_rule", "minor_raw", "major_raw"):
        if column_name in df.columns:
            exprs.append(pl.col(column_name).cast(pl.Utf8))
    if not exprs:
        return pl.lit("미분류")
    return pl.coalesce([*exprs, pl.lit("미분류")])
