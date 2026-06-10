"""Shared helpers for rules CLI commands."""

import re
from typing import Any, Optional

from finjuice.pipeline.cli.audit_log import append_financial_mutation_event
from finjuice.pipeline.cli.output import emit_error
from finjuice.pipeline.config import Config
from finjuice.pipeline.constants import MAX_RULE_PRIORITY, MIN_RULE_PRIORITY
from finjuice.pipeline.storage.csv_partition import CSV_COLUMNS

RULE_NAME_PATTERN = re.compile(r"^\w+$", re.UNICODE)
TRANSFER_EXCLUSION_DESCRIPTION = (
    "Only rows where is_transfer == 1 and transfer_group_id is present are excluded; "
    "unconfirmed transfer candidates remain suggestable."
)


def _append_rule_mutation_audit_event(
    config: Config,
    *,
    command: str,
    action: str,
    rule_name: str,
    change_summary: str,
) -> None:
    """Append a privacy-safe audit event for a successful rule mutation."""
    append_financial_mutation_event(
        config.data_dir,
        {
            "command": command,
            "action": action,
            "rule_name": rule_name,
            "fields_changed": ["rule"],
            "change_summary": change_summary,
        },
    )


def _serialize_rule_payload(rule: Any) -> dict[str, Any]:
    """Convert a TagRule-like object into a JSON-safe payload."""
    return {
        "name": rule.name,
        "match": rule.match,
        "fields": list(rule.fields),
        "tags": list(rule.tags),
        "priority": rule.priority,
        "enabled": bool(rule.enabled),
        "category": rule.category,
        "created_by": rule.created_by,
        "created_at": rule.created_at,
        "confidence": float(rule.confidence),
        "notes": rule.notes,
    }


def _validation_issue_to_problem(issue: Any) -> dict[str, Any]:
    """Convert a validation issue into a JSON-safe payload."""
    return {
        "severity": issue.severity,
        "type": issue.issue_type,
        "message": issue.message,
        "rules": list(issue.rules_involved),
        "suggestion": issue.suggestion,
    }


def _serialize_validation_summary(result: Any) -> dict[str, Any]:
    """Build a JSON-safe validation summary."""
    return {
        "status": "valid" if not result.issues else "issues",
        "total_rules": result.total_rules,
        "errors": len(result.errors),
        "warnings": len(result.warnings),
        "passed": result.passed,
        "problems": [_validation_issue_to_problem(issue) for issue in result.issues],
    }


def _stats_int(stats: dict[str, Any], key: str, fallback: int = 0) -> int:
    """Read an integer coverage stat with fallback for older test doubles."""
    return int(stats.get(key, fallback) or 0)


def _stats_float(stats: dict[str, Any], key: str, fallback: float = 0.0) -> float:
    """Read a float coverage stat with fallback for older test doubles."""
    return float(stats.get(key, fallback) or 0.0)


def _augment_suggestion_stats(stats: dict[str, Any]) -> dict[str, Any]:
    """Add explicit transfer-exclusion fields while keeping legacy stat keys."""
    total_count = _stats_int(stats, "total_count")
    untagged_count = _stats_int(stats, "untagged_count")
    suggestable_total_count = _stats_int(stats, "suggestable_total_count", total_count)
    suggestable_untagged_count = _stats_int(
        stats,
        "suggestable_untagged_count",
        untagged_count,
    )
    transfer_excluded_count = _stats_int(
        stats,
        "transfer_excluded_count",
        max(total_count - suggestable_total_count, 0),
    )
    transfer_excluded_untagged_count = _stats_int(
        stats,
        "transfer_excluded_untagged_count",
        max(untagged_count - suggestable_untagged_count, 0),
    )
    coverage_before = _stats_float(stats, "coverage_before_pct")
    suggestable_coverage_before = _stats_float(
        stats,
        "suggestable_coverage_before_pct",
        coverage_before,
    )

    return {
        **stats,
        "total_count": total_count,
        "untagged_count": untagged_count,
        "suggestable_total_count": suggestable_total_count,
        "suggestable_untagged_count": suggestable_untagged_count,
        "transfer_excluded_count": transfer_excluded_count,
        "transfer_excluded_untagged_count": transfer_excluded_untagged_count,
        "coverage_before_pct": round(float(coverage_before), 2),
        "suggestable_coverage_before_pct": round(float(suggestable_coverage_before), 2),
    }


def _suggest_transfer_exclusions(stats: dict[str, Any]) -> dict[str, Any]:
    """Return the transfer-exclusion explanation for `rules suggest` JSON."""
    return {
        "excluded_count": _stats_int(stats, "transfer_excluded_count"),
        "excluded_untagged_count": _stats_int(stats, "transfer_excluded_untagged_count"),
        "definition": TRANSFER_EXCLUSION_DESCRIPTION,
    }


def _rules_suggest_count_payload(stats: dict[str, Any]) -> dict[str, Any]:
    """Return the shared additive count payload for `rules suggest`."""
    return {
        "untagged_count": _stats_int(stats, "untagged_count"),
        "suggestable_untagged_count": _stats_int(stats, "suggestable_untagged_count"),
        "total_count": _stats_int(stats, "total_count"),
        "suggestable_total_count": _stats_int(stats, "suggestable_total_count"),
        "transfer_exclusions": _suggest_transfer_exclusions(stats),
        "coverage_before_pct": round(_stats_float(stats, "coverage_before_pct"), 2),
        "suggestable_coverage_before_pct": round(
            _stats_float(stats, "suggestable_coverage_before_pct"),
            2,
        ),
    }


def _emit_rules_error(
    message: str,
    *,
    json_output: bool,
    command: str,
    error_code: str,
    exit_code: int,
    suggestion: str | None = None,
) -> None:
    """Emit a structured rules command error and exit."""
    rendered_message = message
    if suggestion and not json_output and suggestion.startswith("Did you mean:"):
        rendered_message = f"{message}\n{suggestion}"
    emit_error(
        rendered_message,
        error_code=error_code,
        exit_code=exit_code,
        suggestion=suggestion,
        json_output=json_output,
        command=command,
    )


def _parse_csv_values(raw_value: str, *, label: str) -> list[str]:
    """Parse a comma-separated CLI option into a list of non-empty values."""
    values = [item.strip() for item in raw_value.split(",") if item.strip()]
    if not values:
        raise ValueError(f"At least one {label} value is required.")
    return values


def _validate_rule_name(name: str) -> None:
    """Validate the allowed rule name format."""
    if not RULE_NAME_PATTERN.fullmatch(name):
        raise ValueError("Rule name must contain only letters, numbers, and underscores.")


def _validate_regex_patterns(match_pattern: str) -> str:
    """Validate each pipe-separated pattern as a regex. Returns normalized pattern."""
    raw_segments = [segment.strip() for segment in match_pattern.split("|")]
    if any(segment == "" for segment in raw_segments):
        raise ValueError(
            "Match pattern contains empty alternation (e.g. 'foo|' or 'foo||bar'). "
            "Remove trailing or double pipes."
        )
    patterns = [s for s in raw_segments if s]
    if not patterns:
        raise ValueError("Match pattern must contain at least one non-empty pattern.")

    for pattern in patterns:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"Invalid regex pattern '{pattern}': {exc}") from exc

    return "|".join(patterns)


def _build_rule_dict_from_cli(
    *,
    name: str,
    match_pattern: str,
    tags: str,
    category: Optional[str],
    priority: int,
    fields: str,
) -> dict[str, Any]:
    """Parse and validate CLI arguments into a rule dictionary."""
    from finjuice.pipeline.tagging.validator import _validate_rule

    _validate_rule_name(name)
    normalized_match = _validate_regex_patterns(match_pattern)

    tag_list = _parse_csv_values(tags, label="tag")
    field_list = _parse_csv_values(fields, label="field")

    allowed_fields = set(CSV_COLUMNS)
    invalid_fields = [field for field in field_list if field not in allowed_fields]
    if invalid_fields:
        allowed_str = ", ".join(sorted(allowed_fields))
        raise ValueError(
            f"Invalid field(s): {', '.join(invalid_fields)}. Must be one of: {allowed_str}"
        )

    if not MIN_RULE_PRIORITY <= priority <= MAX_RULE_PRIORITY:
        raise ValueError(
            f"Priority must be {MIN_RULE_PRIORITY}-{MAX_RULE_PRIORITY}, got {priority}"
        )

    rule_dict: dict[str, Any] = {
        "name": name,
        "match": normalized_match,
        "fields": field_list,
        "tags": tag_list,
        "priority": priority,
    }
    normalized_category = (category or "").strip()
    if normalized_category:
        rule_dict["category"] = normalized_category

    return _validate_rule(rule_dict, 0)
