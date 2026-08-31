"""Helpers for ``finjuice rules add`` / ``remove``.

Owns candidate upsert, dry-run DuckDB impact preview, and human
rendering. Typer commands and JSON compute stay in
:mod:`finjuice.pipeline.cli.commands.rules_cmd.mutations`.
"""

from __future__ import annotations

import logging
from typing import Any

from finjuice.pipeline.cli.output import ErrorCode, ExitCode, console, info, success, warning
from finjuice.pipeline.config import Config

from .shared import _emit_rules_error

logger = logging.getLogger(__name__)


def _upsert_candidate_rules(
    existing_rules: list[Any],
    candidate_rule: Any,
) -> tuple[str, list[Any]]:
    """Return the action and validation candidate set for an add/update mutation."""
    same_name_rules = [rule for rule in existing_rules if rule.name == candidate_rule.name]
    if len(same_name_rules) > 1:
        raise ValueError(
            f"Multiple rules named '{candidate_rule.name}' already exist. "
            "Resolve duplicates before updating this rule."
        )

    if same_name_rules:
        candidate_rules = [
            candidate_rule if rule.name == candidate_rule.name else rule for rule in existing_rules
        ]
        return "updated", candidate_rules

    return "added", [*existing_rules, candidate_rule]


def _compute_rule_impact_preview(
    config: Config,
    *,
    match_pattern: str,
    field_list: list[str],
    json_output: bool,
    command: str,
) -> dict[str, Any]:
    """Compute a dry-run impact preview using DuckDB ILIKE filters."""
    from finjuice.pipeline.analytics.duckdb_layer import DUCKDB_INSTALL_HINT, DuckDBAnalytics
    from finjuice.pipeline.sql_utils import quote_duckdb_identifier

    if not config.csv_base_dir.exists():
        if config.data_dir.exists():
            _emit_rules_error(
                f"No transaction data found at {config.csv_base_dir}. "
                "Run 'finjuice ingest' to import XLSX files.",
                error_code=ErrorCode.NO_DATA,
                exit_code=ExitCode.NO_DATA,
                suggestion="finjuice ingest",
                json_output=json_output,
                command=command,
            )
        _emit_rules_error(
            f"No transaction data found at {config.csv_base_dir}. "
            "Run 'finjuice init' to set up, then 'finjuice ingest'.",
            error_code=ErrorCode.DATA_DIR_NOT_INITIALIZED,
            exit_code=ExitCode.USAGE_ERROR,
            suggestion="finjuice init",
            json_output=json_output,
            command=command,
        )

    patterns = [pattern.strip() for pattern in match_pattern.split("|") if pattern.strip()]
    conditions: list[str] = []
    params: list[str] = []

    for field in field_list:
        field_identifier = quote_duckdb_identifier(field)
        for pattern in patterns:
            conditions.append(f"{field_identifier} ILIKE ?")
            params.append(f"%{pattern}%")

    match_condition = " OR ".join(conditions)

    try:
        with DuckDBAnalytics(config.data_dir) as analytics:
            sql = f"""
                SELECT
                    COUNT(*) FILTER (WHERE matches_rule) AS matched_transactions,
                    SUM(amount) FILTER (WHERE matches_rule) AS total_amount,
                    COUNT(*) AS total_transactions,
                    COUNT(*) FILTER (WHERE NOT is_untagged) AS tagged_transactions,
                    COUNT(*) FILTER (WHERE matches_rule AND is_untagged)
                        AS newly_tagged_transactions
                FROM (
                    SELECT
                        amount,
                        (tags_list IS NULL OR len(tags_list) = 0) AS is_untagged,
                        ({match_condition}) AS matches_rule
                    FROM transactions
                ) AS candidates
            """
            stats_df = analytics.conn.execute(sql, params).pl()
    except ImportError as exc:
        if str(exc) != DUCKDB_INSTALL_HINT:
            raise
        _emit_rules_error(
            str(exc),
            error_code=ErrorCode.SIMULATION_FAILED,
            exit_code=ExitCode.GENERAL_ERROR,
            suggestion="finjuice doctor",
            json_output=json_output,
            command=command,
        )
    except FileNotFoundError:
        _emit_rules_error(
            f"No transaction data found at {config.csv_base_dir}.",
            error_code=ErrorCode.NO_DATA,
            exit_code=ExitCode.NO_DATA,
            suggestion="finjuice ingest",
            json_output=json_output,
            command=command,
        )
    except (OSError, ValueError) as exc:
        logger.error("Dry-run preview failed (%s)", type(exc).__name__)
        _emit_rules_error(
            f"Dry-run impact preview failed: {exc}",
            error_code=ErrorCode.SIMULATION_FAILED,
            exit_code=ExitCode.GENERAL_ERROR,
            json_output=json_output,
            command=command,
        )

    matched_transactions = int(stats_df["matched_transactions"][0]) if len(stats_df) > 0 else 0
    total_amount = float(stats_df["total_amount"][0] or 0.0) if len(stats_df) > 0 else 0.0
    total_transactions = int(stats_df["total_transactions"][0] or 0) if len(stats_df) > 0 else 0
    tagged_transactions = int(stats_df["tagged_transactions"][0] or 0) if len(stats_df) > 0 else 0
    newly_tagged_transactions = (
        int(stats_df["newly_tagged_transactions"][0] or 0) if len(stats_df) > 0 else 0
    )
    coverage_after = (
        ((tagged_transactions + newly_tagged_transactions) / total_transactions) * 100
        if total_transactions > 0
        else 0.0
    )
    return {
        "patterns": patterns,
        "fields": list(field_list),
        "matched_transactions": matched_transactions,
        "total_amount": total_amount,
        "coverage_after": coverage_after,
    }


def _render_rule_mutation(result: dict[str, Any]) -> None:
    """Render human-readable output for rules add/remove commands."""
    if result["action"] == "removed":
        success(f"Removed rule '{result['rule_name']}'.")
        return

    action = result["action"]
    is_dry_run = bool(result.get("dry_run"))
    verb = {
        ("added", False): "Added",
        ("updated", False): "Updated",
        ("added", True): "Would add",
        ("updated", True): "Would update",
    }[(action, is_dry_run)]

    rule = result["rule"]
    info(f"{verb} rule '{rule['name']}'")
    console.print(f"Match: {rule['match']}")
    console.print(f"Fields: {', '.join(rule['fields'])}")
    console.print(f"Tags: {', '.join(rule['tags'])}")
    console.print(f"Priority: {rule['priority']}")
    if rule.get("category"):
        console.print(f"Category: {rule['category']}")

    if impact := result.get("impact"):
        console.print(
            f"Impact preview: {impact['matched_transactions']} matches, "
            f"{impact['total_amount']:,.0f} total amount"
        )

    validation = result["validation"]
    if validation["problems"]:
        warning(
            f"Validation reported {validation['errors']} errors and "
            f"{validation['warnings']} warnings."
        )
        for problem in validation["problems"]:
            console.print(f"- {problem['severity']}: {problem['message']}")
            if problem.get("suggestion"):
                console.print(f"  -> {problem['suggestion']}")
    else:
        success("Validation passed.")

    if is_dry_run:
        warning("Dry run: no changes made.")
