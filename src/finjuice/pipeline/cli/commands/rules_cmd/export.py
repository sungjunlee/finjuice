"""List/export implementations for rules CLI commands."""

import logging
from pathlib import Path
from typing import Any, Optional

import typer
from rich.table import Table

from finjuice.pipeline.cli.output import ErrorCode, ExitCode, console, emit, emit_error, info
from finjuice.pipeline.cli.utils import get_config
from finjuice.pipeline.config import Config

logger = logging.getLogger(__name__)


def _render_rules_list(result: dict[str, Any]) -> None:
    """Render rules as a compact table."""
    rules = result.get("rules", [])
    if not rules:
        info("No rules found.")
        return

    table = Table(title="Rules")
    table.add_column("Name", style="cyan")
    table.add_column("Match")
    table.add_column("Category")
    table.add_column("Tags")
    table.add_column("Priority", justify="right")

    for rule in rules:
        tags = rule.get("tags", [])
        table.add_row(
            str(rule.get("name", "")),
            str(rule.get("match", "")),
            str(rule.get("category", "")),
            ", ".join(str(tag) for tag in tags) if isinstance(tags, list) else str(tags),
            str(rule.get("priority", "")),
        )

    console.print(table)


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


def export_rules_command(
    ctx: typer.Context,
    format_type: str = typer.Option(
        "yaml",
        "--format",
        "-f",
        help="Output format: yaml, banksalad, markdown",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Save output to file",
    ),
    stats: bool = typer.Option(
        True,
        "--stats/--no-stats",
        help="Include match statistics (default: True)",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """
    Export tagging rules as Banksalad category mapping guide.

    Converts your rules.yaml into a guide for configuring Banksalad's
    built-in category auto-classification feature.

    Examples:
        finjuice rules export                       # Show as YAML
        finjuice rules export --format banksalad    # Banksalad mapping guide
        finjuice rules export --format markdown -o guide.md  # Save as Markdown
    """
    import yaml

    from finjuice.pipeline.tagging.rules_yaml_io import load_rules
    from finjuice.pipeline.tagging.suggestions import (
        format_rules_as_banksalad_guide,
        format_rules_as_markdown,
    )

    # Get config from context
    config = get_config(ctx)

    try:
        if json_output:
            json_result = _compute_rules_export_json(config, json_output)
            emit(json_result, json_output, lambda _: None, command="rules export")
            return

        # Check if rules file exists
        if not config.rules_file.exists():
            typer.echo(f"❌ Rules file not found at {config.rules_file}", err=True)
            typer.echo("Create rules.yaml or run 'finjuice rules suggest --apply'.", err=True)
            raise typer.Exit(code=1)

        # Load rules
        rules = load_rules(config.rules_file)

        if not rules:
            typer.echo("📋 등록된 규칙이 없습니다.")
            typer.echo("💡 'finjuice rules suggest --apply'로 규칙을 추가하세요.")
            return

        typer.echo(f"📋 {len(rules)}개의 규칙을 내보냅니다.\n")

        # Format based on type
        if format_type == "banksalad":
            formatted_output = format_rules_as_banksalad_guide(rules, include_stats=stats)
        elif format_type == "markdown":
            formatted_output = format_rules_as_markdown(rules, include_stats=stats)
        elif format_type == "yaml":
            # Re-read raw YAML content
            formatted_output = config.rules_file.read_text(encoding="utf-8")
        else:
            typer.echo(f"❌ Unknown format: {format_type}", err=True)
            typer.echo("Supported formats: yaml, banksalad, markdown", err=True)
            raise typer.Exit(code=1)

        # Save or display
        if output:
            try:
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(formatted_output, encoding="utf-8")
                typer.echo(f"✅ {output}에 저장되었습니다.")
            except OSError as e:
                typer.echo(f"❌ 파일 저장 실패: {e}", err=True)
                raise typer.Exit(code=1)
        else:
            typer.echo(formatted_output)

    except typer.Exit:
        raise
    except (FileNotFoundError, PermissionError) as e:
        logger.error("Export rules failed (%s)", type(e).__name__)
        emit_error(
            f"File access error: {e}",
            error_code=ErrorCode.FILE_ACCESS_ERROR,
            json_output=json_output,
            command="rules export",
        )
    except ValueError as e:
        logger.error(f"Rules parsing error: {e}", exc_info=True)
        emit_error(
            f"Invalid rules.yaml format: {e}",
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            json_output=json_output,
            command="rules export",
        )
    except yaml.YAMLError as e:
        logger.error(f"YAML parsing error: {e}", exc_info=True)
        emit_error(
            f"Invalid rules.yaml format: {e}",
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            json_output=json_output,
            command="rules export",
        )
    except Exception as e:  # intended catch-all for CLI robustness
        logger.error(f"Unexpected error: {type(e).__name__}: {e}", exc_info=True)
        emit_error(
            f"Unexpected error: {e}",
            error_code=ErrorCode.UNEXPECTED_ERROR,
            json_output=json_output,
            command="rules export",
        )


def list_rules_command(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List tagging rules as structured JSON or a compact table."""
    config = get_config(ctx)
    result = _compute_rules_export_json(config, json_output)
    emit(result, json_output, _render_rules_list, command="rules list")
