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

_MAX_LISTED_CANDIDATES = 5
_MAX_SEARCH_CANDIDATES = 10


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
            SELECT row_hash, date, merchant_raw, memo_raw, amount,
                   major_raw, minor_raw, category_final
            FROM transactions
            WHERE {where_sql}
            ORDER BY date DESC
            LIMIT {_MAX_SEARCH_CANDIDATES}
        """
        result: pl.DataFrame = analytics.conn.execute(sql, params).pl()
        return result


def _row_at(df: pl.DataFrame, index_1based: int) -> dict[str, Any]:
    """Return the 1-based listed candidate as a named row dict."""
    return cast(dict[str, Any], df.row(index_1based - 1, named=True))


def _validate_pick(pick: int, match_count: int) -> None:
    """Raise ValueError when ``--pick`` is outside the listed candidate range."""
    listed = min(match_count, _MAX_LISTED_CANDIDATES)
    if pick < 1 or pick > listed:
        raise ValueError(
            f"Invalid --pick {pick}: choose a number from 1 to {listed} "
            f"({match_count} matches found, top {listed} listed)."
        )


def _prompt_transaction_choice(df: pl.DataFrame) -> tuple[dict[str, Any], int] | None:
    """Prompt for a listed candidate. Returns None when the user cancels."""
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
    listed = min(len(df), _MAX_LISTED_CANDIDATES)
    if 1 <= selection <= listed:
        return _row_at(df, selection), selection
    error(f"Invalid selection: choose a number from 1 to {listed}")
    return None


def _select_transaction(
    df: pl.DataFrame,
    json_output: bool,
    pick: int | None = None,
) -> tuple[dict[str, Any], int] | None:
    """Select a listed candidate.

    ``--pick N`` selects the nth match. JSON mode without ``--pick`` auto-selects
    the first match and still returns the candidate list. Interactive prompt is
    the default when several rows match and neither flag is given.
    """
    match_count = len(df)
    if pick is not None:
        _validate_pick(pick, match_count)
        return _row_at(df, pick), pick

    if match_count == 1 or json_output:
        return _row_at(df, 1), 1

    return _prompt_transaction_choice(df)


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


def _load_explain_rules(rules_path: Any, json_output: bool) -> list:
    """Load tagging rules or emit a CLI error."""
    try:
        return load_rules(rules_path)
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


def _search_explain_matches(
    config: Any,
    query: str,
    date: Optional[str],
    json_output: bool,
) -> pl.DataFrame:
    """Search matching transactions or emit a CLI error."""
    try:
        return _search_transactions(config, query, date)
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


def _selected_row_or_error(
    df: pl.DataFrame,
    json_output: bool,
    pick: int | None,
) -> tuple[dict[str, Any], int] | None:
    """Select a listed candidate or emit a validation error for ``--pick``."""
    try:
        return _select_transaction(df, json_output, pick)
    except ValueError as e:
        emit_error(
            str(e),
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            json_output=json_output,
            command="explain",
        )


def explain_command(
    ctx: typer.Context,
    query: str = typer.Argument(..., help="Search term to find transaction (e.g. merchant name)"),
    date: Optional[str] = typer.Option(None, "--date", "-d", help="Filter by date (YYYY-MM-DD)"),
    pick: Optional[int] = typer.Option(
        None,
        "--pick",
        help="Select the nth listed match (1-based) without prompting",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """
    Explain the classification of a transaction.

    Finds a transaction matching the query and shows which rules applied to it.
    If multiple transactions match, it lists them for selection. Use ``--pick``
    to choose a listed candidate without a prompt; ``--json`` includes the
    candidate list with ``row_hash`` values.

    Examples:
        finjuice explain "스타벅스"
        finjuice explain "스타벅스" --pick 2
        finjuice explain "스타벅스" --json
        finjuice explain "쿠팡" -d 2024-10-25
    """
    config = get_config(ctx)
    from finjuice.pipeline.cli.commands.explain_reads import ExplainRequest, repository_explain

    if repository_explain(ctx, config, ExplainRequest(query, date, pick, json_output)):
        return

    # 1. Load rules
    rules = _load_explain_rules(config.rules_file, json_output)
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
    df = _search_explain_matches(config, query, date, json_output)
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
    # Candidates are capped to the listed top rows so --pick indexes and the
    # interactive prompt operate on the same list.
    candidates = [
        {"index": idx, **row}
        for idx, row in enumerate(df.head(_MAX_LISTED_CANDIDATES).iter_rows(named=True), start=1)
    ]
    selected = _selected_row_or_error(df, json_output, pick)
    if not selected:
        return
    target_row, selected_index = selected

    # 4. Run explanation logic
    explanation = _build_explanation(target_row, rules)

    result: dict[str, Any] = {
        "query": query,
        "date_filter": date,
        "match_count": len(df),
        "selected_index": selected_index,
        "candidates": candidates if len(df) > 1 else [],
        "transaction": target_row,
        "classification": explanation["classification"],
        "rule_trace": explanation["rule_trace"],
    }

    emit(result, json_output, render_explain, command="explain")


def register_explain_command(app: typer.Typer) -> None:
    """Register the explain command."""
    app.command(name="explain", rich_help_panel="Analysis")(explain_command)
