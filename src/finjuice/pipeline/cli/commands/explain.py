"""CLI command to explain why a transaction was classified a certain way.

Human rendering lives in :mod:`finjuice.pipeline.cli.commands.explain_rendering`
and is re-exported here so existing callers can keep importing from this
module.
"""

import logging
import re
from typing import Any, Optional, cast

import polars as pl
import typer

from finjuice.pipeline.analytics.duckdb_layer import DUCKDB_INSTALL_HINT, DuckDBAnalytics
from finjuice.pipeline.cli.commands.explain_rendering import render_explain
from finjuice.pipeline.cli.output import (
    ErrorCode,
    ExitCode,
    console,
    emit,
    emit_error,
    error,
    warning,
)
from finjuice.pipeline.cli.utils import get_config
from finjuice.pipeline.tagging.rules import apply_tagging_rules_v3, load_rules

logger = logging.getLogger(__name__)


def _search_transactions(
    config: Any,
    query: str,
    date: Optional[str],
) -> pl.DataFrame:
    """Search transactions matching query. Returns a Polars DataFrame."""
    with DuckDBAnalytics(config.data_dir) as analytics:
        where_parts = ["(merchant_raw ILIKE ? OR memo_raw ILIKE ?)"]
        params: list[str] = [f"%{query}%", f"%{query}%"]

        if date:
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
                raise ValueError("Invalid date format. Use YYYY-MM-DD.")
            where_parts.append("date = ?")
            params.append(date)

        where_sql = " AND ".join(where_parts)
        sql = f"""
            SELECT date, merchant_raw, memo_raw, amount,
                   major_raw, minor_raw, category_final
            FROM transactions
            WHERE {where_sql}
            ORDER BY date DESC
            LIMIT 10
        """
        result: pl.DataFrame = analytics.conn.execute(sql, params).pl()
        return result


def _select_transaction(df: pl.DataFrame, json_output: bool) -> dict[str, Any] | None:
    """Select a transaction from search results (auto-select first in JSON mode)."""
    # Single result or JSON mode: auto-select first match
    if len(df) == 1 or json_output:
        return cast(dict[str, Any], df.row(0, named=True))

    # Interactive mode: let user choose
    console.print(f"[cyan]Found {len(df)} transactions. Showing top 5:[/cyan]")
    for idx, row in enumerate(df.head(5).iter_rows(named=True), 1):
        console.print(
            f"{idx}. {row['date']} | {row['merchant_raw']} | {row['amount']} | {row['memo_raw']}"
        )

    try:
        selection = typer.prompt("Select transaction number (0 to cancel)", type=int)
    except typer.Abort:
        return None

    if selection == 0:
        return None
    if 1 <= selection <= len(df):
        return cast(dict[str, Any], df.row(selection - 1, named=True))
    error("Invalid selection")
    return None


def _build_explanation(
    target_row: dict[str, Any],
    rules: list,
) -> dict[str, Any]:
    """Build explanation result for a single transaction."""
    from finjuice.pipeline.tagging.matcher import _check_pattern_match

    result = apply_tagging_rules_v3(target_row, rules)
    effective_category = (
        result.category_rule
        or target_row.get("category_final")
        or target_row.get("minor_raw")
        or target_row.get("major_raw")
        or "미분류"
    )

    rule_trace = []
    for rule in rules:
        if not rule.enabled:
            continue
        patterns = [p.strip() for p in rule.match.split("|")]
        if _check_pattern_match(target_row, rule, patterns):
            rule_trace.append(
                {
                    "priority": rule.priority,
                    "rule_name": rule.name,
                    "matched_field": rule.match,
                    "tags_added": rule.tags,
                    "category_set": rule.category or None,
                }
            )

    return {
        "classification": {
            "matched_rules": result.matching_rules,
            "tags": result.tags,
            "category": effective_category,
            "category_rule": result.category_rule or None,
        },
        "rule_trace": rule_trace,
    }


def explain_command(
    ctx: typer.Context,
    query: str = typer.Argument(..., help="Search term to find transaction (e.g. merchant name)"),
    date: Optional[str] = typer.Option(None, "--date", "-d", help="Filter by date (YYYY-MM-DD)"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """
    Explain the classification of a transaction.

    Finds a transaction matching the query and shows which rules applied to it.
    If multiple transactions match, it lists them for selection.

    Examples:
        finjuice explain "스타벅스"
        finjuice explain "쿠팡" -d 2024-10-25
    """
    config = get_config(ctx)
    rules_path = config.rules_file

    # 1. Load rules
    try:
        rules = load_rules(rules_path)
    except (FileNotFoundError, ValueError) as e:
        emit_error(
            f"Failed to load rules: {e}",
            error_code=ErrorCode.FILE_NOT_FOUND,
            json_output=json_output,
            command="explain",
        )
    except OSError as e:
        logger.error("Unexpected error loading rules (%s)", type(e).__name__)
        emit_error(
            f"Unexpected error loading rules: {e}",
            error_code=ErrorCode.UNEXPECTED_ERROR,
            json_output=json_output,
            command="explain",
        )

    if not rules:
        no_rules_result: dict[str, Any] = {
            "query": query,
            "date_filter": date,
            "transaction": None,
            "classification": None,
            "rule_trace": [],
        }
        emit(
            no_rules_result,
            json_output,
            lambda r: warning("No rules found. Nothing to explain."),
            command="explain",
        )
        return

    # 2. Find transaction(s)
    try:
        df = _search_transactions(config, query, date)
    except ValueError as e:
        emit_error(
            str(e),
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            json_output=json_output,
            command="explain",
        )
    except ImportError as e:
        if str(e) != DUCKDB_INSTALL_HINT:
            raise
        emit_error(
            str(e),
            error_code=ErrorCode.QUERY_ERROR,
            suggestion="finjuice doctor",
            json_output=json_output,
            command="explain",
        )
    except (OSError, RuntimeError) as e:
        logger.error("Search failed (%s)", type(e).__name__)
        emit_error(
            f"Search failed: {e}",
            error_code=ErrorCode.QUERY_ERROR,
            json_output=json_output,
            command="explain",
        )

    if len(df) == 0:
        no_match_result: dict[str, Any] = {
            "query": query,
            "date_filter": date,
            "match_count": 0,
            "matches": [],
        }
        emit(
            no_match_result,
            json_output,
            lambda r: warning("No matching transactions found."),
            command="explain",
        )
        return

    # 3. Select transaction if multiple found
    target_row = None
    candidates = [
        {"index": idx, **row} for idx, row in enumerate(df.iter_rows(named=True), start=1)
    ]
    target_row = _select_transaction(df, json_output)

    if not target_row:
        return

    # 4. Run explanation logic
    explanation = _build_explanation(target_row, rules)

    result: dict[str, Any] = {
        "query": query,
        "date_filter": date,
        "match_count": len(df),
        "selected_index": 1,
        "candidates": candidates if len(df) > 1 else [],
        "transaction": target_row,
        "classification": explanation["classification"],
        "rule_trace": explanation["rule_trace"],
    }

    emit(result, json_output, render_explain, command="explain")


def register_explain_command(app: typer.Typer) -> None:
    """Register the explain command."""
    app.command(name="explain", rich_help_panel="Analysis")(explain_command)
