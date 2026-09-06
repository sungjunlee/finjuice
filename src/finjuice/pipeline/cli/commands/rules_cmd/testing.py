"""Dry-run testing implementation for rules CLI commands.

Human-readable Rich rendering lives in
:mod:`finjuice.pipeline.cli.commands.rules_cmd.testing_rendering`.
Rule-test matching and match-result compute live in
:mod:`finjuice.pipeline.cli.commands.rules_cmd.testing_match`.
Those helpers are re-exported here so existing callers can keep
importing from this module.
"""

import difflib
import re
from typing import Any

import typer

from finjuice.pipeline.cli.output import ErrorCode, ExitCode, emit
from finjuice.pipeline.cli.utils import get_config
from finjuice.pipeline.config import Config

from .shared import _emit_rules_error
from .testing_match import (
    _RULE_EVAL_FIELDS,
    _build_rules_test_cross_tags,  # noqa: F401 — re-exported for existing testing imports
    _build_rules_test_monthly_distribution,  # noqa: F401 — re-exported for existing testing imports
    _collect_rules_test_matches,
    _normalize_rules_test_tags,  # noqa: F401 — re-exported for existing testing imports
    _record_rules_test_match,  # noqa: F401 — re-exported for existing testing imports
    _rule_matches_row,  # noqa: F401 — re-exported for existing testing imports
    _serialize_rules_test_sample,  # noqa: F401 — re-exported for existing testing imports
)
from .testing_rendering import (
    _format_rules_test_amount,  # noqa: F401 — re-exported for existing testing imports
    _format_rules_test_header,  # noqa: F401 — re-exported for existing testing imports
    _format_rules_test_tags,  # noqa: F401 — re-exported for existing testing imports
    _render_rules_test,
    _render_rules_test_counter_table,  # noqa: F401 — re-exported for existing testing imports
    _render_rules_test_sample,  # noqa: F401 — re-exported for existing testing imports
)


def _format_rules_test_suggestion(rule_name: str, all_rules: list[Any]) -> str | None:
    """Build a did-you-mean hint for an unknown rule name."""
    matches = difflib.get_close_matches(
        rule_name,
        [rule.name for rule in all_rules],
        n=3,
        cutoff=0.6,
    )
    return f"Did you mean: {', '.join(matches)}" if matches else None


def _emit_rules_test_month_error(month: str, *, json_output: bool) -> None:
    """Emit the canonical INVALID_ARGS error for malformed --month."""
    _emit_rules_error(
        f"Invalid month format: {month}. Use YYYY-MM.",
        error_code=ErrorCode.INVALID_ARGS,
        exit_code=ExitCode.USAGE_ERROR,
        suggestion="finjuice rules test --help",
        json_output=json_output,
        command="rules test",
    )


def _parse_rules_test_month(month: str | None, *, json_output: bool) -> tuple[int, int] | None:
    """Validate and parse a YYYY-MM month filter."""
    if month is None:
        return None
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        _emit_rules_test_month_error(month, json_output=json_output)
    year, month_text = month.split("-")
    month_number = int(month_text)
    if not 1 <= month_number <= 12:
        _emit_rules_test_month_error(month, json_output=json_output)
    return int(year), month_number


def _emit_missing_rules_file(config: Config, *, json_output: bool) -> None:
    """Emit the RULES_FILE_NOT_FOUND envelope used by `rules test`."""
    _emit_rules_error(
        f"Rules file not found at {config.rules_file}. "
        "Create rules.yaml or run 'finjuice rules suggest --apply'.",
        error_code=ErrorCode.RULES_FILE_NOT_FOUND,
        exit_code=ExitCode.USAGE_ERROR,
        suggestion="finjuice rules suggest --apply",
        json_output=json_output,
        command="rules test",
    )


def _emit_rules_load_failure(exc: Exception, *, json_output: bool) -> None:
    """Emit the VALIDATION_FAILED envelope for a corrupt rules.yaml."""
    _emit_rules_error(
        f"Failed to load rules: {exc}",
        error_code=ErrorCode.VALIDATION_FAILED,
        exit_code=ExitCode.VALIDATION_ERROR,
        suggestion="finjuice rules validate",
        json_output=json_output,
        command="rules test",
    )


def _load_all_rules_or_error(config: Config, *, json_output: bool) -> list[Any]:
    """Load all rules from config.rules_file or emit a structured error."""
    from finjuice.pipeline.tagging.rules_yaml_io import load_rules

    if not config.rules_file.exists():
        _emit_missing_rules_file(config, json_output=json_output)
    try:
        return load_rules(config.rules_file)
    except ValueError as exc:
        _emit_rules_load_failure(exc, json_output=json_output)
        raise  # unreachable; keeps type-checker happy


def _emit_rule_not_found(rule_name: str, all_rules: list[Any], *, json_output: bool) -> None:
    """Emit the RULE_NOT_FOUND envelope with a did-you-mean hint."""
    _emit_rules_error(
        f"Rule not found: {rule_name}",
        error_code=ErrorCode.RULE_NOT_FOUND,
        exit_code=ExitCode.USAGE_ERROR,
        suggestion=_format_rules_test_suggestion(rule_name, all_rules),
        json_output=json_output,
        command="rules test",
    )


def _emit_duplicate_rule(rule_name: str, *, json_output: bool) -> None:
    """Emit the VALIDATION_FAILED envelope for duplicate rule names."""
    _emit_rules_error(
        f"Multiple rules named '{rule_name}' found. Resolve duplicates before testing.",
        error_code=ErrorCode.VALIDATION_FAILED,
        exit_code=ExitCode.VALIDATION_ERROR,
        suggestion="finjuice rules validate",
        json_output=json_output,
        command="rules test",
    )


def _load_rules_test_rule(
    config: Config,
    *,
    rule_name: str,
    json_output: bool,
) -> Any:
    """Load a single rule by exact name."""
    all_rules = _load_all_rules_or_error(config, json_output=json_output)
    matches = [rule for rule in all_rules if rule.name == rule_name]
    if not matches:
        _emit_rule_not_found(rule_name, all_rules, json_output=json_output)
    if len(matches) > 1:
        _emit_duplicate_rule(rule_name, json_output=json_output)
    return matches[0]


def _rules_test_columns(rule: Any) -> list[str]:
    """Return the minimal column set needed for rule testing."""
    _ = rule  # rule-referenced fields outside _RULE_EVAL_FIELDS are ignored by the real pipeline
    columns = [
        "date",
        "time",
        "category_final",
        "tags_rule",
        "tags_final",
        "datetime",
        *_RULE_EVAL_FIELDS,
    ]
    return list(dict.fromkeys(columns))


def _read_rules_test_partitions(
    config: Config, *, columns: list[str], month: str | None, json_output: bool
) -> Any:
    """Read partitions for rule testing, honoring an optional YYYY-MM scope."""
    from finjuice.pipeline.storage.csv_transactions import get_all_transactions, read_month

    period = _parse_rules_test_month(month, json_output=json_output)
    if period:
        return read_month(config.csv_base_dir, period[0], period[1], columns=columns)
    return get_all_transactions(config.csv_base_dir, columns=columns)


def _emit_rules_test_no_data(month: str | None, *, json_output: bool) -> None:
    """Emit the NO_DATA envelope for an empty partition scope."""
    target = f" for {month}" if month else ""
    _emit_rules_error(
        f"No transaction data found{target}.",
        error_code=ErrorCode.NO_DATA,
        exit_code=ExitCode.NO_DATA,
        suggestion="finjuice ingest",
        json_output=json_output,
        command="rules test",
    )


def _load_rules_test_df(
    config: Config,
    *,
    rule: Any,
    month: str | None,
    json_output: bool,
) -> Any:
    """Load the requested transaction scope for rule testing."""
    columns = _rules_test_columns(rule)
    df = _read_rules_test_partitions(config, columns=columns, month=month, json_output=json_output)
    if getattr(df, "height", 0) == 0:
        _emit_rules_test_no_data(month, json_output=json_output)
    return df.sort("datetime") if "datetime" in df.columns else df


def _compute_rules_test(
    config: Config,
    *,
    rule_name: str,
    limit: int,
    month: str | None,
    json_output: bool,
) -> dict[str, Any]:
    """Compute `finjuice rules test` output.

    JSON schema:
    {
      "rule_name": "llm_service",
      "scope": {"month": "2024-10" | null, "total_rows_scanned": 12345},
      "match_count": 44,
      "sample": [{"date": "2024-10-03", "time": "14:22", "...": "..."}],
      "monthly_distribution": {"2024-09": 10, "2024-10": 18},
      "cross_tags_top": [{"tag": "디지털구독", "count": 42}]
    }
    """
    rule = _load_rules_test_rule(config, rule_name=rule_name, json_output=json_output)
    df = _load_rules_test_df(config, rule=rule, month=month, json_output=json_output)
    result = _collect_rules_test_matches(df, rule=rule, limit=limit)
    return {
        "rule_name": rule.name,
        "scope": {"month": month, "total_rows_scanned": int(df.height)},
        **result,
    }


def test_rule_command(
    ctx: typer.Context,
    rule_name: str = typer.Argument(..., metavar="RULE_NAME", help="Exact rule name to test"),
    limit: int = typer.Option(5, "--limit", min=0, help="Sample row count (default: 5)"),
    month: str | None = typer.Option(None, "--month", help="Restrict to one partition (YYYY-MM)"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Dry-run a single rule against existing transactions without writing changes."""
    config = get_config(ctx)
    result = _compute_rules_test(
        config,
        rule_name=rule_name,
        limit=limit,
        month=month,
        json_output=json_output,
    )
    emit(result, json_output, _render_rules_test, command="rules test")
