"""Add/remove implementations for rules CLI commands."""

import logging
from typing import Any, Optional

import typer

from finjuice.pipeline.cli.output import ErrorCode, ExitCode, console, emit, info, success, warning
from finjuice.pipeline.cli.utils import get_config
from finjuice.pipeline.config import Config
from finjuice.pipeline.constants import DEFAULT_RULE_PRIORITY

from .shared import (
    _append_rule_mutation_audit_event,
    _build_rule_dict_from_cli,
    _emit_rules_error,
    _serialize_rule_payload,
    _serialize_validation_summary,
)

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


def _compute_add_rule(
    config: Config,
    *,
    name: str,
    match_pattern: str,
    tags: str,
    category: Optional[str],
    priority: int,
    fields: str,
    dry_run: bool,
    json_output: bool,
) -> dict[str, Any]:
    """Compute the result payload for `finjuice rules add`."""
    from finjuice.pipeline.tagging.models import TagRule
    from finjuice.pipeline.tagging.rules_yaml_io import load_rules
    from finjuice.pipeline.tagging.validator import validate_rules

    command = "rules add"

    try:
        validated_dict = _build_rule_dict_from_cli(
            name=name,
            match_pattern=match_pattern,
            tags=tags,
            category=category,
            priority=priority,
            fields=fields,
        )
    except ValueError as exc:
        _emit_rules_error(
            str(exc),
            error_code=ErrorCode.INVALID_ARGS,
            exit_code=ExitCode.USAGE_ERROR,
            suggestion="finjuice rules add --help",
            json_output=json_output,
            command=command,
        )

    try:
        existing_rules = load_rules(config.rules_file)
    except ValueError as exc:
        _emit_rules_error(
            f"Failed to load rules: {exc}",
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            suggestion="finjuice rules validate",
            json_output=json_output,
            command=command,
        )

    candidate_rule = TagRule(**validated_dict)

    try:
        action, candidate_rules = _upsert_candidate_rules(existing_rules, candidate_rule)
    except ValueError as exc:
        _emit_rules_error(
            str(exc),
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            suggestion="finjuice rules validate",
            json_output=json_output,
            command=command,
        )

    validation_result = validate_rules(candidate_rules)
    if validation_result.has_errors:
        _emit_rules_error(
            "Rule set validation failed. Resolve duplicate rule names and retry.",
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            suggestion="finjuice rules validate",
            json_output=json_output,
            command=command,
        )

    result: dict[str, Any] = {
        "action": action,
        "rule": _serialize_rule_payload(candidate_rule),
        "validation": _serialize_validation_summary(validation_result),
    }

    if dry_run:
        result["dry_run"] = True
        result["dry_run_action"] = action
        result["preview_action"] = "would_update" if action == "updated" else "would_add"
        result["rules_file_modified"] = False
        impact_preview = _compute_rule_impact_preview(
            config,
            match_pattern=validated_dict["match"],
            field_list=list(validated_dict["fields"]),
            json_output=json_output,
            command=command,
        )
        result["impact"] = {
            "patterns": impact_preview["patterns"],
            "fields": impact_preview["fields"],
            "matched_transactions": impact_preview["matched_transactions"],
            "total_amount": impact_preview["total_amount"],
        }
        if action == "updated":
            # Omit coverage_after for updates because the preview cannot
            # model rows that would STOP matching after the old rule is
            # replaced.  Reporting a potentially misleading number is worse
            # than omitting it.
            result["impact"]["note"] = (
                "coverage_after omitted for updates: preview shows new pattern "
                "matches only and cannot subtract rows lost from the old pattern."
            )
        else:
            result["coverage_after"] = float(impact_preview["coverage_after"])
        return result

    from finjuice.pipeline.tagging.rules_yaml_io import add_rule_roundtrip, update_rule_roundtrip

    try:
        if action == "updated":
            update_rule_roundtrip(validated_dict, config.rules_file)
        else:
            add_rule_roundtrip(validated_dict, config.rules_file)
    except KeyError as exc:
        _emit_rules_error(
            str(exc),
            error_code=ErrorCode.RULE_NOT_FOUND,
            exit_code=ExitCode.USAGE_ERROR,
            suggestion="finjuice rules validate",
            json_output=json_output,
            command=command,
        )
    except ValueError as exc:
        _emit_rules_error(
            str(exc),
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            suggestion="finjuice rules validate",
            json_output=json_output,
            command=command,
        )
    except OSError as exc:
        _emit_rules_error(
            f"Failed to write rules file: {exc}",
            error_code=ErrorCode.FILE_ACCESS_ERROR,
            exit_code=ExitCode.GENERAL_ERROR,
            json_output=json_output,
            command=command,
        )

    _append_rule_mutation_audit_event(
        config,
        command=command,
        action=action,
        rule_name=candidate_rule.name,
        change_summary=f"rule {action}",
    )
    return result


def add_rule_command(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="Rule name (letters, numbers, underscores)"),
    match_pattern: str = typer.Option(..., "--match", help="Pipe-separated regex patterns"),
    tags: str = typer.Option(..., "--tags", help="Comma-separated tags"),
    category: Optional[str] = typer.Option(None, "--category", help="Optional category"),
    priority: int = typer.Option(
        DEFAULT_RULE_PRIORITY,
        "--priority",
        help="Rule priority (0-100, higher runs first)",
    ),
    fields: str = typer.Option(
        "merchant_raw",
        "--fields",
        help="Comma-separated transaction fields to match",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview impact without writing"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Add or update a tagging rule programmatically."""
    config = get_config(ctx)
    result = _compute_add_rule(
        config,
        name=name,
        match_pattern=match_pattern,
        tags=tags,
        category=category,
        priority=priority,
        fields=fields,
        dry_run=dry_run,
        json_output=json_output,
    )
    emit(result, json_output, _render_rule_mutation, command="rules add")


def _compute_remove_rule(
    config: Config,
    *,
    name: str,
    json_output: bool,
) -> dict[str, Any]:
    """Compute the result payload for `finjuice rules remove`."""
    from finjuice.pipeline.tagging.rules_yaml_io import load_rules, remove_rule_roundtrip

    command = "rules remove"

    try:
        existing_rules = load_rules(config.rules_file)
    except ValueError as exc:
        _emit_rules_error(
            f"Failed to load rules: {exc}",
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            suggestion="finjuice rules validate",
            json_output=json_output,
            command=command,
        )

    matching_rules = [rule for rule in existing_rules if rule.name == name]
    if not matching_rules:
        _emit_rules_error(
            f"Rule not found: {name}",
            error_code=ErrorCode.RULE_NOT_FOUND,
            exit_code=ExitCode.USAGE_ERROR,
            suggestion="finjuice rules validate",
            json_output=json_output,
            command=command,
        )
    if len(matching_rules) > 1:
        _emit_rules_error(
            f"Multiple rules named '{name}' found. Resolve duplicates before removing.",
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            suggestion="finjuice rules validate",
            json_output=json_output,
            command=command,
        )

    try:
        remove_rule_roundtrip(name, config.rules_file)
    except KeyError:
        _emit_rules_error(
            f"Rule not found: {name}",
            error_code=ErrorCode.RULE_NOT_FOUND,
            exit_code=ExitCode.USAGE_ERROR,
            suggestion="finjuice rules validate",
            json_output=json_output,
            command=command,
        )
    except ValueError as exc:
        _emit_rules_error(
            str(exc),
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            suggestion="finjuice rules validate",
            json_output=json_output,
            command=command,
        )
    except OSError as exc:
        _emit_rules_error(
            f"Failed to write rules file: {exc}",
            error_code=ErrorCode.FILE_ACCESS_ERROR,
            exit_code=ExitCode.GENERAL_ERROR,
            json_output=json_output,
            command=command,
        )

    _append_rule_mutation_audit_event(
        config,
        command=command,
        action="removed",
        rule_name=name,
        change_summary="rule removed",
    )
    return {"action": "removed", "rule_name": name}


def remove_rule_command(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="Rule name to remove"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Remove a tagging rule by name."""
    config = get_config(ctx)
    result = _compute_remove_rule(config, name=name, json_output=json_output)
    emit(result, json_output, _render_rule_mutation, command="rules remove")
