"""
Validate tagging rules command.

Checks rules.yaml for conflicts, duplicates, and potential issues.
"""

import logging
from typing import Any

import typer

from finjuice.pipeline.cli import output
from finjuice.pipeline.cli.output import ErrorCode, ExitCode, emit, emit_error
from finjuice.pipeline.config import Config
from finjuice.pipeline.tagging.models import RuleValidationError
from finjuice.pipeline.tagging.rules_yaml_io import (
    load_report_filters,
    load_rules,
    load_rules_collecting,
)
from finjuice.pipeline.tagging.validator import ValidationIssue, validate_rules

logger = logging.getLogger(__name__)


def _severity_style(severity: str) -> str:
    """Get Rich style for severity level."""
    if severity == "error":
        return "bold red"
    elif severity == "warning":
        return "yellow"
    return "dim"


def _severity_icon(severity: str) -> str:
    """Get icon for severity level."""
    if severity == "error":
        return "❌"
    elif severity == "warning":
        return "⚠️"
    return "ℹ️"


def _print_issue(issue: ValidationIssue, index: int) -> None:
    """Print a single validation issue."""
    icon = _severity_icon(issue.severity)
    style = _severity_style(issue.severity)

    output.console.print(f"\n{index}. [{style}]{icon} {issue.issue_type}[/{style}]")
    output.console.print(f"   {issue.message}")

    if issue.rules_involved:
        rules_str = ", ".join(issue.rules_involved)
        output.console.print(f"   [dim]Rules: {rules_str}[/dim]")

    if issue.suggestion:
        output.console.print(f"   [cyan]→ {issue.suggestion}[/cyan]")


def _issue_to_problem(issue: ValidationIssue) -> dict[str, Any]:
    """Convert a validation issue to a JSON-safe problem entry."""
    rule_name = issue.rule_name
    if rule_name is None and len(issue.rules_involved) == 1:
        rule_name = issue.rules_involved[0]

    return {
        "severity": issue.severity,
        "type": issue.issue_type,
        "message": issue.message,
        "rules": list(issue.rules_involved),
        "suggestion": issue.suggestion,
        "rule_index": issue.rule_index,
        "rule_name": rule_name,
    }


def _collected_error_to_issue(rule_error: RuleValidationError) -> ValidationIssue:
    """Convert a collected rule-load failure into a normal validation issue."""
    return ValidationIssue(
        severity="error",
        issue_type="invalid_rule",
        message=rule_error.message,
        rules_involved=[rule_error.rule_name],
        suggestion=rule_error.suggestion,
        rule_index=rule_error.rule_index,
        rule_name=rule_error.rule_name,
    )


def _compute_validate_rules(config: Config, json_output: bool, strict: bool) -> dict[str, Any]:
    """Compute rule-validation output for JSON or text rendering."""
    rules_path = config.rules_file

    if not rules_path.exists():
        emit_error(
            f"Rules file not found: {rules_path}",
            error_code=ErrorCode.RULES_FILE_NOT_FOUND,
            exit_code=ExitCode.USAGE_ERROR,
            json_output=json_output,
            command="rules validate",
        )

    try:
        load_report_filters(rules_path)
        if strict:
            rules = load_rules(rules_path)
            collected_issues: list[ValidationIssue] = []
        else:
            load_result = load_rules_collecting(rules_path)
            rules = load_result.rules
            collected_issues = [
                _collected_error_to_issue(rule_error) for rule_error in load_result.errors
            ]
    except (FileNotFoundError, ValueError) as e:
        emit_error(
            f"Failed to load rules: {e}",
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            json_output=json_output,
            command="rules validate",
        )

    total_rules = len(rules) + len(collected_issues)
    if total_rules == 0:
        return {
            "status": "valid",
            "total_rules": 0,
            "errors": 0,
            "warnings": 0,
            "passed": 0,
            "problems": [],
            "_issues": [],
            "_has_errors": False,
            "_empty": True,
        }

    result = validate_rules(rules)
    issues = [*collected_issues, *result.issues]
    problems = [_issue_to_problem(issue) for issue in issues]
    error_items = [p for p in problems if p["severity"] == "error"]
    warning_items = [p for p in problems if p["severity"] == "warning"]

    return {
        "status": "valid" if not issues else "issues",
        "total_rules": total_rules,
        "errors": len(error_items),
        "warnings": len(warning_items),
        "passed": result.passed,
        "problems": problems,
        "_issues": issues,
        "_has_errors": bool(error_items),
        "_empty": False,
    }


def _render_validate_rules(result: dict[str, Any]) -> None:
    """Render human-readable validation output."""
    if result["_empty"]:
        output.warning("No rules found in rules.yaml")
        return

    output.info(f"🔍 규칙 검증 중... ({result['total_rules']}개 규칙)")
    output.newline()

    errors = [issue for issue in result["_issues"] if issue.severity == "error"]
    warnings = [issue for issue in result["_issues"] if issue.severity == "warning"]
    info_issues = [issue for issue in result["_issues"] if issue.severity == "info"]

    if errors:
        output.console.print(f"[bold red]❌ 오류 {len(errors)}건[/bold red]")
        output.hr()
        for i, issue in enumerate(errors, 1):
            _print_issue(issue, i)

    if warnings:
        if errors:
            output.newline()
        output.console.print(f"[bold yellow]⚠️  경고 {len(warnings)}건[/bold yellow]")
        output.hr()
        for i, issue in enumerate(warnings, 1):
            _print_issue(issue, i)

    if info_issues:
        if errors or warnings:
            output.newline()
        output.console.print(f"[dim]ℹ️  정보 {len(info_issues)}건[/dim]")
        for i, issue in enumerate(info_issues, 1):
            _print_issue(issue, i)

    output.newline()
    if not result["_issues"]:
        output.success("모든 규칙 검증 통과!")
    else:
        output.success(f"통과 {result['passed']}건")

    output.hr()
    rows = [
        ("총 규칙", f"{result['total_rules']}개"),
        ("오류", f"{result['errors']}건"),
        ("경고", f"{result['warnings']}건"),
        ("통과", f"{result['passed']}건"),
    ]
    output.table_summary("검증 요약", rows, columns=("항목", "결과"))
    output.newline()


def validate_rules_command(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Fail fast on the first malformed rule instead of collecting all rule-load errors",
    ),
) -> None:
    """
    Validate tagging rules for conflicts and issues.

    Checks for:
    - Duplicate rule names
    - Pattern overlaps (rules that match same transactions)
    - Priority inversions (broad patterns blocking specific ones)
    - Invalid regex patterns

    Examples:
        finjuice rules validate
    """
    config: Config = ctx.obj["config"]
    result = _compute_validate_rules(config, json_output, strict)
    json_result = {k: v for k, v in result.items() if not k.startswith("_")}
    emit(
        json_result,
        json_output,
        lambda _: _render_validate_rules(result),
        command="rules validate",
    )

    if result["_has_errors"]:
        raise typer.Exit(1)
