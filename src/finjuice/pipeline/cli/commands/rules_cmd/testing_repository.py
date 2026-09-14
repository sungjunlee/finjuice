"""Pinned canonical execution of the existing single-rule dry run."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import typer

from finjuice.pipeline.analysis_source import (
    analysis_frame,
    analysis_metadata,
    read_analysis_source,
)
from finjuice.pipeline.cli.output import ErrorCode, ExitCode
from finjuice.pipeline.cli.utils import get_activation_evidence_provider, get_config
from finjuice.pipeline.tagging.rules_yaml_io import load_rules_bytes

from .shared import _emit_rules_error
from .testing_match import _collect_rules_test_matches


@dataclass(frozen=True)
class RepositoryRuleTestOptions:
    """Existing CLI choices for a pinned rule test."""

    rule_name: str
    limit: int
    month: str | None
    json_output: bool


def compute_repository_rules_test(
    ctx: typer.Context, options: RepositoryRuleTestOptions
) -> dict[str, Any] | None:
    """Run stored canonical rules without report filters or live-file fallback."""
    from .testing import (
        _emit_duplicate_rule,
        _emit_rule_not_found,
        _emit_rules_test_no_data,
        _parse_rules_test_month,
    )

    try:
        snapshot = read_analysis_source(
            get_config(ctx).data_dir, get_activation_evidence_provider(ctx)
        )
        if snapshot is None:
            return None
        selection = snapshot.rules
        head = selection.head
        if (
            selection.selection_state != "selected"
            or head is None
            or head.parsed_status != "parsed"
        ):
            raise ValueError("Canonical rules are not selected and parsed.")
        rules = load_rules_bytes(head.content)
        matches = [rule for rule in rules if rule.name == options.rule_name]
        if not matches:
            _emit_rule_not_found(options.rule_name, rules, json_output=options.json_output)
        if len(matches) > 1:
            _emit_duplicate_rule(options.rule_name, json_output=options.json_output)
        rule = matches[0]
        for condition in rule.conditions:
            if condition.op == "regex":
                re.compile(condition.value)
        _parse_rules_test_month(options.month, json_output=options.json_output)
        frame = analysis_frame(snapshot, options.month)
        if frame.is_empty():
            _emit_rules_test_no_data(options.month, json_output=options.json_output)
        frame = frame.sort("datetime")
        result = _collect_rules_test_matches(frame, rule=rule, limit=options.limit)
        metadata = analysis_metadata(snapshot, "canonical_rules_test.v1", month=options.month)
        metadata["rules_revision_id"] = head.revision_id
        return {
            "rule_name": rule.name,
            "scope": {"month": options.month, "total_rows_scanned": frame.height},
            **result,
            "_repository_meta": metadata,
        }
    except typer.Exit:
        raise
    except Exception:
        _emit_rules_error(
            "Canonical rules test could not be evaluated.",
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            suggestion="finjuice rules validate",
            json_output=options.json_output,
            command="rules test",
        )
        raise AssertionError("Unreachable") from None
