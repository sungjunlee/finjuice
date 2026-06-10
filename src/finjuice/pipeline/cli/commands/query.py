"""
CLI command for executing SQL queries on transaction data.
"""

import logging
from typing import Optional

import typer
from rich.table import Table

from finjuice.pipeline.analytics.duckdb_layer import (
    DUCKDB_INSTALL_HINT,
    DuckDBAnalytics,
    validate_readonly_sql,
)
from finjuice.pipeline.analytics.query_builder import build_report_filter_duckdb_where
from finjuice.pipeline.cli import output as cli_output
from finjuice.pipeline.cli.output import ErrorCode, ExitCode, console
from finjuice.pipeline.cli.report_filters import (
    count_matched_report_filters,
    load_cli_report_filters,
)
from finjuice.pipeline.cli.utils import get_config

logger = logging.getLogger(__name__)


def _strip_trailing_sql_terminator(sql: str) -> str:
    """Remove a single optional trailing semicolon before wrapping a SELECT."""
    return sql.strip().removesuffix(";").strip()


def query_command(
    ctx: typer.Context,
    sql: str = typer.Argument(..., help="SQL query to execute (SELECT only)"),
    output: Optional[str] = typer.Option(
        None, "--output", "-o", help="Output format: table, csv, json, markdown"
    ),
    json_output: bool = typer.Option(False, "--json", help="Alias for --output json"),
    limit: int = typer.Option(
        cli_output.DEFAULT_PAGINATION_LIMIT,
        "--limit",
        help="Maximum rows to return (max 10000)",
    ),
    cursor: str = typer.Option("0", "--cursor", help="Opaque pagination cursor"),
    max_bytes: int = typer.Option(
        cli_output.DEFAULT_MAX_BYTES,
        "--max-bytes",
        help="Maximum serialized JSON response size before truncating rows",
    ),
) -> None:
    """
    Execute a SQL query on your transaction data.

    The query is executed against a 'transactions' view created from your CSV partitions.
    Only SELECT and WITH statements are allowed for safety.
    Report filters are applied by default by prepending a CTE that rebinds the
    conventional `transactions` view to filtered rows; use the root `--no-filter`
    flag when you need the unfiltered audit view for this invocation.
    Privacy profiles are intentionally not exposed here because arbitrary SQL
    can rename, compute, or combine sensitive row fields outside a stable
    redaction contract.

    Examples:
        finjuice query "SELECT * FROM transactions LIMIT 5"
        finjuice query "SELECT month, SUM(amount) FROM transactions GROUP BY month"
        finjuice query "SELECT * FROM transactions WHERE amount < -100000" -o markdown
    """
    config = get_config(ctx)
    if json_output:
        if output is None:
            output = "json"
        elif output != "json":
            cli_output.emit_error(
                "Cannot use --json with a conflicting --output value. Use --output json or --json.",
                error_code=ErrorCode.INVALID_ARGS,
                exit_code=ExitCode.USAGE_ERROR,
                json_output=True,
                command="query",
            )

    structured_output = output == "json"
    limit, cursor_offset, max_bytes = cli_output.validate_pagination_args(
        limit,
        cursor,
        max_bytes,
        json_output=structured_output,
        command="query",
    )
    report_filters = load_cli_report_filters(
        ctx,
        config,
        command="query",
        json_output=structured_output,
    )
    filters_applied = 0

    try:
        validate_readonly_sql(sql)
    except ValueError as e:
        cli_output.emit_error(
            str(e),
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            json_output=structured_output,
            command="query",
        )

    # Initialize analytics layer
    try:
        with DuckDBAnalytics(config.data_dir, require_transactions=False) as analytics:
            # View 'transactions' is automatically registered in __init__
            # (See src/finjuice/pipeline/analytics/duckdb_layer.py)

            # Enforce security via strict SQL validation (no semicolons, restricted keywords)
            # rather than DB-level read-only mode, which can interfere with view creation.

            execution_sql = _strip_trailing_sql_terminator(sql)

            # Build CTE-prefixed query to preserve DuckDB alias resolution in GROUP BY
            # (CTE body is parsed as top-level statement; subquery wrapping breaks aliases)
            cte_prefix = "WITH "
            if not report_filters.is_empty():
                source_df = analytics.query_readonly(
                    "SELECT date, merchant_raw, category_final FROM transactions_source"
                ).pl()
                filters_applied = count_matched_report_filters(source_df, report_filters)
                filter_where = build_report_filter_duckdb_where(report_filters)
                if filter_where is not None:
                    cte_prefix = (
                        "WITH\n"
                        "transactions AS (\n"
                        "    SELECT *\n"
                        "    FROM transactions_source\n"
                        f"    WHERE NOT ({filter_where})\n"
                        "),\n"
                    )

            # User SQL is wrapped only after validate_readonly_sql rejects unsafe forms.
            wrapped_prefix = f"{cte_prefix}_finjuice_query AS (\n{execution_sql}\n)\n"  # nosec B608

            total_estimate = int(
                analytics.query_readonly(
                    f"{wrapped_prefix}SELECT COUNT(*) AS total_count FROM _finjuice_query"
                ).fetchone()[0]
            )
            if limit == 0:
                result_df = analytics.query_readonly(
                    f"{wrapped_prefix}SELECT * FROM _finjuice_query LIMIT 0"
                ).pl()
            else:
                result_df = analytics.query_readonly(
                    f"{wrapped_prefix}"
                    f"SELECT * FROM _finjuice_query "  # nosec B608
                    f"LIMIT {limit} OFFSET {cursor_offset}"  # nosec B608
                ).pl()
            pagination = cli_output.build_offset_pagination(
                limit=limit,
                cursor_offset=cursor_offset,
                total_estimate=total_estimate,
                fetched_count=len(result_df),
            )

            if output == "csv":
                typer.echo(result_df.write_csv())
            elif output == "json":
                payload = cli_output.truncate_rows_to_max_bytes(
                    {
                        "rows": result_df.to_dicts(),
                        "row_count": len(result_df),
                    },
                    pagination=pagination,
                    max_bytes=max_bytes,
                    command="query",
                    meta_extras={"filters_applied": filters_applied},
                )
                cli_output.emit(
                    payload,
                    True,
                    lambda _: None,
                    command="query",
                    meta_extras={"filters_applied": filters_applied},
                )
            elif output == "markdown":
                typer.echo(cli_output.render_markdown_dataframe(result_df))
            else:
                # Default: Rich Table
                table = Table(title="Query Result")
                for col in result_df.columns:
                    table.add_column(col)

                for row in result_df.rows():
                    table.add_row(*[str(x) for x in row])

                console.print(table)
                cli_output.render_pagination_footer(len(result_df), pagination)

    except ImportError as e:
        if str(e) != DUCKDB_INSTALL_HINT:
            raise
        cli_output.emit_error(
            str(e),
            error_code=ErrorCode.QUERY_ERROR,
            suggestion="finjuice doctor",
            json_output=structured_output,
            command="query",
        )
    except Exception as e:  # intended catch-all for CLI robustness
        logger.error(f"Query execution failed: {e}", exc_info=True)
        cli_output.emit_error(
            f"Query execution failed: {e}",
            error_code=ErrorCode.QUERY_ERROR,
            json_output=structured_output,
            command="query",
        )


def register_query_command(app: typer.Typer) -> None:
    """Register the query command."""
    app.command(name="query", rich_help_panel="Analysis")(query_command)
