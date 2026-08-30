"""Add/remove implementations for rules CLI commands.

Candidate upsert, dry-run impact preview, and human rendering live in
:mod:`finjuice.pipeline.cli.commands.rules_cmd.mutations_helpers`.
"""

from typing import Any, Optional

import typer

from finjuice.pipeline.cli.output import ErrorCode, ExitCode, emit
from finjuice.pipeline.cli.utils import get_config
from finjuice.pipeline.config import Config
from finjuice.pipeline.constants import DEFAULT_RULE_PRIORITY

from .mutations_helpers import (
    _compute_rule_impact_preview,
    _render_rule_mutation,
    _upsert_candidate_rules,
)
from .shared import (
    _append_rule_mutation_audit_event,
    _build_rule_dict_from_cli,
    _emit_rules_error,
    _serialize_rule_payload,
    _serialize_validation_summary,
)


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
