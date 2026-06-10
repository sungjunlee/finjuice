"""Template SQL execution layer."""

from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from finjuice.pipeline.cli import output as cli_output
from finjuice.pipeline.sql_utils import quote_duckdb_identifier

from .options import TemplateRunOptions
from .param_coercion import (
    _parse_month_start,
    _parse_param_kv,
    _quote_sql_literal,
    _resolve_param_values,
    _resolve_template_context,
)
from .registry import TemplateUnknownError, _load_registry, _load_sql
from .result import TemplateRunAuditState, TemplateRunResult

logger = logging.getLogger(__name__)

TOKEN_PATTERN = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")
TemplateDomain = Literal["asset", "transaction"]
PivotAgg = Literal["sum", "avg", "count", "max", "min"]
PivotValue = Literal["amount", "count"]

PIVOT_TEMPLATE_NAME = "pivot"
PIVOT_OTHER_BUCKET = "_other_"
PIVOT_ROW_AXIS_EXPRESSIONS: dict[str, str] = {
    "month": "COALESCE(strftime(date, '%Y-%m'), '_unknown_')",
    "year": "COALESCE(strftime(date, '%Y'), '_unknown_')",
    "quarter": (
        "COALESCE("
        "strftime(date, '%Y') || '-Q' || CAST(date_part('quarter', date) AS VARCHAR), "
        "'_unknown_'"
        ")"
    ),
    "account": "COALESCE(account, '_unknown_')",
    "type_norm": "COALESCE(type_norm, '_unknown_')",
    "is_transfer": "CASE WHEN COALESCE(is_transfer_bool, FALSE) THEN 'true' ELSE 'false' END",
}
PIVOT_COL_AXIS_EXPRESSIONS: dict[str, str] = {
    "category_final": "COALESCE(category_final, '_unknown_')",
    "major_raw": "COALESCE(major_raw, '_unknown_')",
    "minor_raw": "COALESCE(minor_raw, '_unknown_')",
    "merchant_raw": "COALESCE(merchant_raw, '_unknown_')",
    "type_norm": "COALESCE(type_norm, '_unknown_')",
}


@dataclass(frozen=True)
class TemplateExecutionDependencies:
    """Patchable dependencies used by the template run use case."""

    duckdb_analytics: Callable[..., Any]
    validate_readonly_sql: Callable[[str], str]
    load_cli_report_filters: Callable[..., Any]
    count_matched_report_filters: Callable[[Any, Any], int]


@dataclass(frozen=True)
class TemplateRunEvent:
    """Audit event data for one template run."""

    data_dir: Path
    template_name: str
    success: bool
    output_format: str
    user_params: dict[str, str]
    duration: float
    json_output: bool = False
    row_count: int | None = None
    error_type: str | None = None


def _quote_sql_identifier(value: str) -> str:
    """Return a double-quoted SQL identifier."""
    return quote_duckdb_identifier(value)


def _next_month_start(month_literal: str) -> date:
    """Return the first day of the month after the given YYYY-MM literal."""
    month_start = _parse_month_start(month_literal, param_name="months")
    if month_start.month == 12:
        return date(month_start.year + 1, 1, 1)
    return date(month_start.year, month_start.month + 1, 1)


def _build_pivot_months_where(months: str | None) -> str:
    """Build an inclusive month-range predicate for DuckDB DATE rows."""
    if months is None:
        return "TRUE"

    start_month, end_month = months.split(":", 1)
    next_month = _next_month_start(end_month)
    return (
        f"date >= DATE {_quote_sql_literal(f'{start_month}-01')} "
        f"AND date < DATE {_quote_sql_literal(next_month.isoformat())}"
    )


def _normalize_pivot_agg(value: PivotValue, agg: PivotAgg) -> PivotAgg:
    """Resolve `value=count` into the only meaningful aggregate."""
    if value == "count":
        if agg in {"sum", "count"}:
            return "count"
        raise ValueError(
            "Invalid pivot parameters: value=count only supports agg=count "
            "(the default agg=sum is treated as count)."
        )
    return agg


def _build_pivot_base_rows_sql(
    *,
    row: str,
    col: str,
    value: PivotValue,
    months: str | None,
) -> str:
    """Build the normalized base-row SELECT for pivot aggregation."""
    row_expr = PIVOT_ROW_AXIS_EXPRESSIONS[row]
    metric_expr = "1" if value == "count" else "ABS(amount)"
    where_clauses = [_build_pivot_months_where(months)]

    if col == "tags_final":
        where_clauses.append("tags_final IS NOT NULL")
        where_sql = " AND ".join(where_clauses)
        return (
            "SELECT\n"
            f"    {row_expr} AS row_key,\n"
            "    COALESCE(tag, '_unknown_') AS col_key,\n"
            f"    {metric_expr} AS metric_value\n"
            "FROM transactions\n"
            "CROSS JOIN UNNEST(from_json(tags_final, '[\"VARCHAR\"]')) AS tag_list(tag)\n"
            f"WHERE {where_sql}"
        )

    col_expr = PIVOT_COL_AXIS_EXPRESSIONS[col]
    where_sql = " AND ".join(where_clauses)
    return (
        "SELECT\n"
        f"    {row_expr} AS row_key,\n"
        f"    {col_expr} AS col_key,\n"
        f"    {metric_expr} AS metric_value\n"
        "FROM transactions\n"
        f"WHERE {where_sql}"
    )


def _build_pivot_rank_expr(*, value: PivotValue, agg: PivotAgg) -> str:
    """Return the metric used for top-N column discovery."""
    if value == "count" or agg == "count":
        return "COUNT(*)"
    return "SUM(metric_value)"


def _discover_pivot_columns(
    analytics: Any,
    *,
    row: str,
    col: str,
    value: PivotValue,
    agg: PivotAgg,
    months: str | None,
    top_n_cols: int,
) -> tuple[list[str], bool]:
    """Discover deterministic pivot columns and whether `_other_` is needed."""
    base_rows_sql = _build_pivot_base_rows_sql(row=row, col=col, value=value, months=months)
    rank_expr = _build_pivot_rank_expr(value=value, agg=agg)
    discovery_sql = f"""
        WITH base_rows AS (
        {base_rows_sql}
        )
        SELECT col_key
        FROM (
            SELECT
                col_key,
                {rank_expr} AS rank_value
            FROM base_rows
            GROUP BY col_key
        ) ranked_columns
        ORDER BY rank_value DESC, col_key ASC
    """
    discovered_result = analytics.query_readonly(discovery_sql).fetchall()
    discovered = [str(row_value[0]) for row_value in discovered_result]
    return discovered[:top_n_cols], len(discovered) > top_n_cols


def _build_pivot_bucket_case(columns: list[str], include_other_bucket: bool) -> str:
    """Build the column bucketing CASE expression."""
    if not include_other_bucket:
        return "col_key"

    in_list = ", ".join(_quote_sql_literal(column) for column in columns)
    return (
        "CASE\n"
        f"        WHEN col_key IN ({in_list}) THEN col_key\n"
        f"        ELSE {_quote_sql_literal(PIVOT_OTHER_BUCKET)}\n"
        "    END"
    )


def _build_pivot_column_projection(column: str, agg: PivotAgg) -> str:
    """Build one static pivot projection column."""
    column_literal = _quote_sql_literal(column)
    column_alias = _quote_sql_identifier(column)

    if agg == "sum":
        inner = f"SUM(CASE WHEN column_bucket = {column_literal} THEN metric_value END)"
    elif agg == "avg":
        inner = f"AVG(CASE WHEN column_bucket = {column_literal} THEN metric_value END)"
    elif agg == "count":
        inner = f"COUNT(CASE WHEN column_bucket = {column_literal} THEN 1 END)"
    elif agg == "max":
        inner = f"MAX(CASE WHEN column_bucket = {column_literal} THEN metric_value END)"
    else:
        inner = f"MIN(CASE WHEN column_bucket = {column_literal} THEN metric_value END)"

    return f"    COALESCE({inner}, 0) AS {column_alias}"


def _run_pivot_template(
    analytics: Any,
    sql_template: str,
    resolved_params: dict[str, Any],
) -> tuple[Any, list[str]]:
    """Execute the dynamic pivot template and return result rows plus discovered columns."""
    row_axis = str(resolved_params["row"])
    col_axis = str(resolved_params["col"])
    value = str(resolved_params["value"])
    raw_agg = str(resolved_params["agg"])
    months = resolved_params.get("months")
    top_n_cols = int(resolved_params["top_n_cols"])

    agg = _normalize_pivot_agg(value=value, agg=raw_agg)  # type: ignore[arg-type]
    columns, include_other_bucket = _discover_pivot_columns(
        analytics,
        row=row_axis,
        col=col_axis,
        value=value,  # type: ignore[arg-type]
        agg=agg,
        months=months,
        top_n_cols=top_n_cols,
    )
    pivot_columns = columns + ([PIVOT_OTHER_BUCKET] if include_other_bucket else [])

    rendered_sql = _render_sql(
        sql_template,
        {
            "base_rows_sql": _build_pivot_base_rows_sql(
                row=row_axis,
                col=col_axis,
                value=value,  # type: ignore[arg-type]
                months=months,
            ),
            "bucket_case_sql": _build_pivot_bucket_case(columns, include_other_bucket),
            "row_alias": _quote_sql_identifier(row_axis),
            "pivot_columns_sql": (
                ",\n"
                + ",\n".join(
                    _build_pivot_column_projection(column, agg) for column in pivot_columns
                )
                if pivot_columns
                else ""
            ),
        },
    )
    return analytics.query_readonly(rendered_sql).pl(), pivot_columns


def _render_sql(sql_template: str, resolved_params: dict[str, str]) -> str:
    """Render SQL template by replacing {{param}} tokens."""

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in resolved_params:
            raise ValueError(f"Template is missing value for parameter token '{{{{{key}}}}}'")
        return resolved_params[key]

    return TOKEN_PATTERN.sub(replace, sql_template)


def _build_param_fingerprint(user_params: dict[str, str]) -> str:
    """Build a stable hash fingerprint for template parameters."""
    if not user_params:
        return "none"
    normalized = "|".join(f"{key}={user_params[key]}" for key in sorted(user_params))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _resolve_template_domain(template_name: str) -> TemplateDomain:
    """Resolve template domain from name for audit compatibility."""
    return "asset" if template_name.startswith("asset_") else "transaction"


def write_template_run_event(
    event_data: TemplateRunEvent,
    *,
    append_event: Callable[[Path, dict[str, Any]], None],
    warn: Callable[[str], None],
) -> None:
    """Record template run result for metrics extraction."""
    event: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": "template_run",
        "command": f"finjuice template run {event_data.template_name}",
        "template_name": event_data.template_name,
        "template_domain": _resolve_template_domain(event_data.template_name),
        "success": event_data.success,
        "duration": round(event_data.duration, 3),
        "output_format": event_data.output_format,
        "param_keys": sorted(event_data.user_params.keys()),
        "param_fingerprint": _build_param_fingerprint(event_data.user_params),
    }
    if event_data.row_count is not None:
        event["row_count"] = event_data.row_count
    if event_data.error_type:
        event["error_type"] = event_data.error_type

    try:
        append_event(event_data.data_dir, event)
    except OSError as e:
        logger.warning(f"Failed to write template audit event: {e}")
        if not event_data.json_output:
            warn("Audit logging failed; this template run was not recorded.")
    except (TypeError, ValueError):
        logger.exception("Failed to serialize template audit event payload")
        if not event_data.json_output:
            warn("Audit logging failed due to invalid payload; run was not recorded.")


def execute_template_run(
    options: TemplateRunOptions,
    *,
    dependencies: TemplateExecutionDependencies,
    audit_state: TemplateRunAuditState,
) -> TemplateRunResult:
    """Execute a SQL template and return a typed rendering result."""
    templates = _load_registry()
    if options.name not in templates:
        raise TemplateUnknownError(options.name)

    template_spec = templates[options.name]
    sql_file = str(template_spec.get("sql_file", ""))
    sql_template = _load_sql(sql_file)

    user_params = _parse_param_kv(options.params)
    audit_state.user_params = user_params
    template_meta_extras: dict[str, Any] = {}
    pivot_columns: list[str] | None = None

    if options.name != PIVOT_TEMPLATE_NAME:
        resolved_params, template_meta_extras = _resolve_template_context(
            options.name, template_spec, user_params
        )
        sql = _render_sql(sql_template, resolved_params)
        dependencies.validate_readonly_sql(sql)

    report_filters = dependencies.load_cli_report_filters(
        options.ctx,
        options.config,
        command="template run",
        json_output=options.machine_output,
    )

    with dependencies.duckdb_analytics(
        options.config.data_dir, report_filters=report_filters
    ) as analytics:
        filters_applied = 0
        if not report_filters.is_empty():
            source_df = analytics.query_readonly(
                "SELECT date, merchant_raw, category_final FROM transactions_source"
            ).pl()
            filters_applied = dependencies.count_matched_report_filters(source_df, report_filters)

        if options.name == PIVOT_TEMPLATE_NAME:
            pivot_values = _resolve_param_values(options.name, template_spec, user_params)
            result_df, pivot_columns = _run_pivot_template(
                analytics,
                sql_template,
                pivot_values,
            )
        else:
            result_df = analytics.query_readonly(sql).pl()

    total_row_count = len(result_df)
    paged_df = result_df.slice(options.cursor_offset, options.limit)
    row_count = len(paged_df)
    pagination = cli_output.build_offset_pagination(
        limit=options.limit,
        cursor_offset=options.cursor_offset,
        total_estimate=total_row_count,
        fetched_count=row_count,
    )

    return TemplateRunResult(
        template_name=options.name,
        result_df=paged_df,
        row_count=row_count,
        total_row_count=total_row_count,
        pagination=pagination,
        output_format=options.output_format,
        file=options.file,
        machine_output=options.machine_output,
        filters_applied=filters_applied,
        template_meta_extras=template_meta_extras,
        pivot_columns=pivot_columns,
        user_params=user_params,
        max_bytes=options.max_bytes,
        duration=time.perf_counter() - audit_state.started_at,
    )
