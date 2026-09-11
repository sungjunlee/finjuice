"""JSON payload helpers for ``finjuice rules export`` / ``rules list``.

Owns rule serialization and the JSON payload wrapper around the rules
export. The Typer commands stay in
:mod:`finjuice.pipeline.cli.commands.rules_cmd.export`, which re-exports
these helpers so existing callers can keep importing from that module.
"""

from __future__ import annotations

from typing import Any

from finjuice.pipeline.cli.output import ErrorCode, ExitCode, emit_error
from finjuice.pipeline.config import Config


def _serialize_rule_export(rule: Any) -> dict[str, Any]:
    """Convert a TagRule dataclass into a JSON-safe payload."""
    return {
        "name": rule.name,
        "match": rule.match,
        "fields": list(rule.fields),
        "tags": list(rule.tags),
        "category": rule.category,
        "priority": rule.priority,
    }


def _compute_rules_export_json(config: Config, json_output: bool) -> dict[str, Any]:
    """Compute JSON payload for `rules export`."""
    from finjuice.pipeline.tagging.rules_yaml_io import load_rules

    if not config.rules_file.exists():
        emit_error(
            f"Rules file not found at {config.rules_file}. "
            "Create rules.yaml or run 'finjuice rules suggest --apply'.",
            error_code=ErrorCode.RULES_FILE_NOT_FOUND,
            exit_code=ExitCode.USAGE_ERROR,
            suggestion="finjuice rules suggest --apply",
            json_output=json_output,
            command="rules export",
        )

    rules = load_rules(config.rules_file)
    return {
        "rule_count": len(rules),
        "rules": [_serialize_rule_export(rule) for rule in rules],
    }
