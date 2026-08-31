"""Review command for transactions needing manual attention.

Filter predicates live in :mod:`finjuice.pipeline.cli.commands.review_filters`
and are re-exported here so existing callers can keep importing from this
module. Human rendering lives in
:mod:`finjuice.pipeline.cli.commands.review_rendering`. JSON row projection
lives in :mod:`finjuice.pipeline.cli.commands.review_serialize`.
"""

import logging
from pathlib import Path
from typing import Any, Optional

import polars as pl
import typer

from finjuice.pipeline.cli import output as cli_output
from finjuice.pipeline.cli.commands.export_helpers import validate_period
from finjuice.pipeline.cli.commands.review_filters import (
    _count_matches,
    _default_review_expr,
    _is_list_dtype,  # noqa: F401 — re-exported for existing review imports
    _rule_matched_expr,
    _tags_present_expr,  # noqa: F401 — re-exported for existing review imports
    _untagged_expr,
)
from finjuice.pipeline.cli.commands.review_rendering import (
    _format_amount,  # noqa: F401 — re-exported for existing review imports
    _format_confidence,  # noqa: F401 — re-exported for existing review imports
    _render_review,
)
from finjuice.pipeline.cli.commands.review_serialize import (
    _compact_review_result,
    _serialize_transaction,
)
from finjuice.pipeline.cli.output import ErrorCode, ExitCode, emit, emit_error
from finjuice.pipeline.cli.privacy import (
    PrivacyProfile,
    apply_privacy_profile,
    privacy_meta,
)
from finjuice.pipeline.cli.utils import get_config
from finjuice.pipeline.tagging.rules_yaml_io import summarize_rule_notes

logger = logging.getLogger(__name__)


def _load_latest_month(csv_base_dir: Path) -> tuple[Optional[pl.DataFrame], Optional[str]]:
    """Load the most recent transaction month from CSV partitions."""
    from finjuice.pipeline.storage.csv_transactions import read_month

    partitions = sorted(csv_base_dir.glob("*/*/transactions.csv"))
    if not partitions:
        return None, None

    latest = partitions[-1]
    year = int(latest.parts[-3])
    month = int(latest.parts[-2])
    month_label = f"{year:04d}-{month:02d}"

    return read_month(csv_base_dir, year, month), month_label


def _load_all_history(csv_base_dir: Path) -> Optional[pl.DataFrame]:
    """Load every transaction partition for all-history review mode."""
    from finjuice.pipeline.storage.csv_transactions import get_all_transactions

    partitions = sorted(csv_base_dir.glob("*/*/transactions.csv"))
    if not partitions:
        return None

    return get_all_transactions(csv_base_dir)


def _build_review_next_steps(
    *,
    month_label: str | None,
    all_history: bool,
    untagged: bool,
    low_confidence: float | None,
    untagged_count: int,
    limit: int,
    next_cursor: str | None,
    matched_count: int,
) -> list[dict[str, str]]:
    """Return additive next-step cues for agent consumers."""
    if matched_count == 0:
        return []

    steps: list[dict[str, str]] = []
    active_filters: list[str] = []
    if untagged:
        active_filters.append("--untagged")
    if all_history:
        active_filters.append("--all-history")
    elif month_label:
        active_filters.extend(["--month", month_label])
    if low_confidence is not None:
        active_filters.extend(["--low-confidence", str(low_confidence)])
    current_filter_suffix = f" {' '.join(active_filters)}" if active_filters else ""

    if untagged_count > 0 and not untagged:
        untagged_filter_suffix = " --untagged"
        if active_filters:
            untagged_filter_suffix += f" {' '.join(active_filters)}"
        steps.append(
            {
                "signal": "untagged_transactions",
                "message": "Focus on empty-tag rows first.",
                "command": f"finjuice review --json{untagged_filter_suffix}",
            }
        )

    if next_cursor is not None:
        steps.append(
            {
                "signal": "truncated_queue",
                "message": "Fetch the next page of the review queue.",
                "command": (
                    f"finjuice review --json{current_filter_suffix} "
                    f"--limit {limit} --cursor {next_cursor}"
                ),
            }
        )

    return steps


def _load_review_rule_notes(rules_file: Path) -> list[dict[str, Any]]:
    """Best-effort rule notes for review JSON output."""
    try:
        return summarize_rule_notes(rules_file, limit=5)
    except (OSError, ValueError):
        return []


def _sort_review_rows(df: pl.DataFrame) -> pl.DataFrame:
    """Sort review rows newest-first with a stable row_hash tie-breaker."""
    sort_columns = [column for column in ("datetime", "date", "row_hash") if column in df.columns]
    if not sort_columns:
        return df
    descending = [column != "row_hash" for column in sort_columns]
    return df.sort(sort_columns, descending=descending)


def _sync_review_page_counts(payload: dict[str, Any]) -> None:
    """Keep count fields aligned after JSON byte truncation."""
    returned_count = len(payload.get("transactions", []))
    payload["total_count"] = returned_count
    payload.pop("row_count", None)

    signals = payload.get("signals")
    if isinstance(signals, dict):
        signals["returned_count"] = returned_count
        pagination = payload.get("pagination")
        if isinstance(pagination, dict):
            signals["truncated"] = bool(pagination.get("has_more", False))


def review_command(
    ctx: typer.Context,
    untagged: bool = typer.Option(
        False, "--untagged", help="Show only untagged transactions (tags_final=[])"
    ),
    low_confidence: Optional[float] = typer.Option(
        None,
        "--low-confidence",
        help="Filter by confidence below threshold (e.g., 0.7)",
    ),
    month: Optional[str] = typer.Option(None, "--month", help="Filter by month (YYYY-MM)"),
    all_history: bool = typer.Option(
        False,
        "--all-history",
        help="Review matching transactions across all available monthly partitions",
    ),
    limit: int = typer.Option(50, "--limit", "-n", help="Number of transactions to show"),
    cursor: str = typer.Option("0", "--cursor", help="Opaque pagination cursor"),
    max_bytes: int = typer.Option(
        cli_output.DEFAULT_MAX_BYTES,
        "--max-bytes",
        help="Maximum serialized JSON response size before truncating transactions",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    privacy: PrivacyProfile = typer.Option(
        PrivacyProfile.RAW,
        "--privacy",
        help="Privacy profile for JSON output: raw, redacted, or compact",
    ),
) -> None:
    """Show transactions that need manual review."""
    from finjuice.pipeline.storage.csv_transactions import read_month

    command_name = "review"
    config = get_config(ctx)
    validate_period(month, json_output, command=command_name, privacy=privacy)

    if all_history and month is not None:
        emit_error(
            "Use either --month or --all-history, not both.",
            error_code=ErrorCode.INVALID_ARGS,
            exit_code=ExitCode.USAGE_ERROR,
            json_output=json_output,
            command=command_name,
            privacy=privacy,
        )

    if low_confidence is not None and not 0.0 <= low_confidence <= 1.0:
        emit_error(
            f"Invalid low-confidence threshold: {low_confidence}",
            error_code=ErrorCode.INVALID_ARGS,
            exit_code=ExitCode.USAGE_ERROR,
            json_output=json_output,
            command=command_name,
            privacy=privacy,
        )

    limit, cursor_offset, max_bytes = cli_output.validate_pagination_args(
        limit,
        cursor,
        max_bytes,
        json_output=json_output,
        command=command_name,
    )

    try:
        df: Optional[pl.DataFrame]
        month_label: Optional[str] = month

        if all_history:
            df = _load_all_history(config.csv_base_dir)
            month_label = None
            if df is None:
                emit_error(
                    "No transaction data found",
                    error_code=ErrorCode.NO_DATA,
                    exit_code=ExitCode.NO_DATA,
                    json_output=json_output,
                    command=command_name,
                    privacy=privacy,
                )
        elif month:
            year_str, mon_str = month.split("-")
            csv_path = config.csv_base_dir / year_str / mon_str / "transactions.csv"
            if not csv_path.exists():
                emit_error(
                    f"No data for {month}",
                    error_code=ErrorCode.NO_DATA,
                    exit_code=ExitCode.NO_DATA,
                    json_output=json_output,
                    command=command_name,
                    privacy=privacy,
                )
            df = read_month(config.csv_base_dir, int(year_str), int(mon_str))
        else:
            df, month_label = _load_latest_month(config.csv_base_dir)
            if df is None:
                emit_error(
                    "No transaction data found",
                    error_code=ErrorCode.NO_DATA,
                    exit_code=ExitCode.NO_DATA,
                    json_output=json_output,
                    command=command_name,
                    privacy=privacy,
                )

        assert df is not None, "df should not be None after data load"

        if month_label is None:
            month_label = month

        tags_dtype = df.schema.get("tags_final")

        if month is not None:
            df = df.filter(pl.col("date").str.starts_with(month))

        if untagged or low_confidence is not None:
            if untagged:
                df = df.filter(_untagged_expr(tags_dtype))
            if low_confidence is not None:
                df = df.filter(
                    pl.col("confidence").is_null() | (pl.col("confidence") < low_confidence)
                )
        else:
            df = df.filter(_default_review_expr(tags_dtype))

        matched_count = len(df)
        low_confidence_count = 0
        if low_confidence is not None and "confidence" in df.columns:
            low_confidence_count = _count_matches(
                df,
                pl.col("confidence").is_null() | (pl.col("confidence") < low_confidence),
            )
        needs_review_count = (
            _count_matches(df, pl.col("needs_review") == 1) if "needs_review" in df.columns else 0
        )
        untagged_count = _count_matches(df, _untagged_expr(tags_dtype))
        unclassified_count = (
            _count_matches(df, pl.col("category_final") == "미분류")
            if "category_final" in df.columns
            else 0
        )
        rule_matched_count = _count_matches(df, _rule_matched_expr(df))

        df = _sort_review_rows(df)
        df = df.slice(cursor_offset, limit)

        transactions = [
            _serialize_transaction(row, low_confidence_threshold=low_confidence)
            for row in df.to_dicts()
        ]
        returned_count = len(transactions)
        pagination = cli_output.build_offset_pagination(
            limit=limit,
            cursor_offset=cursor_offset,
            total_estimate=matched_count,
            fetched_count=returned_count,
        )
        pagination_dict = pagination.to_dict()
        truncated = pagination.has_more
        health_reasons = ["review_queue"] if matched_count > 0 else []
        result = {
            "transactions": transactions,
            "total_count": returned_count,
            "filters": {
                "untagged": untagged,
                "low_confidence": low_confidence,
                "month": month_label,
                "all_history": all_history,
                "limit": limit,
                "cursor": str(cursor_offset),
            },
            "month": month_label,
            "health": {
                "status": "warning" if health_reasons else "ok",
                "reasons": health_reasons,
            },
            "actionable": matched_count > 0,
            "signals": {
                "matched_count": matched_count,
                "returned_count": returned_count,
                "truncated": truncated,
                "needs_review_count": needs_review_count,
                "needs_review_flag_count": needs_review_count,
                "untagged_count": untagged_count,
                "unclassified_count": unclassified_count,
                "uncategorized_count": unclassified_count,
                "rule_matched_count": rule_matched_count,
                "low_confidence_count": low_confidence_count,
                "low_confidence_threshold": low_confidence,
            },
            "rule_notes": _load_review_rule_notes(config.rules_file) if matched_count > 0 else [],
            "next_steps": _build_review_next_steps(
                month_label=month_label,
                all_history=all_history,
                untagged=untagged,
                low_confidence=low_confidence,
                untagged_count=untagged_count,
                limit=limit,
                next_cursor=pagination.next_cursor,
                matched_count=matched_count,
            ),
            "pagination": pagination_dict,
        }

        if json_output:
            output_result = apply_privacy_profile(result, privacy, compact=_compact_review_result)
            output_result = cli_output.truncate_rows_to_max_bytes(
                output_result,
                pagination=pagination,
                max_bytes=max_bytes,
                command=command_name,
                meta_extras=privacy_meta(privacy),
                rows_key="transactions",
            )
            _sync_review_page_counts(output_result)
            pagination_payload = output_result.get("pagination")
            if isinstance(pagination_payload, dict):
                output_result["next_steps"] = _build_review_next_steps(
                    month_label=month_label,
                    all_history=all_history,
                    untagged=untagged,
                    low_confidence=low_confidence,
                    untagged_count=untagged_count,
                    limit=limit,
                    next_cursor=pagination_payload.get("next_cursor"),
                    matched_count=matched_count,
                )
        else:
            output_result = result
        emit(
            output_result,
            json_output,
            _render_review,
            command="review",
            meta_extras=privacy_meta(privacy),
        )

    except typer.Exit:
        raise
    except Exception as exc:  # intended catch-all for CLI robustness
        logger.error(f"Failed to review transactions: {exc}", exc_info=True)
        emit_error(
            f"Failed to review transactions: {exc}",
            error_code=ErrorCode.GENERAL_ERROR,
            json_output=json_output,
            command=command_name,
            privacy=privacy,
        )
