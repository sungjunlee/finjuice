"""Rendering and JSON payload assembly for template commands."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from rich.table import Table

from finjuice.pipeline.cli import output as cli_output
from finjuice.pipeline.cli.output import _build_meta, console, emit

from .result import TemplateListResult, TemplateRunResult, TemplateShowResult


def _print_table(result_df: Any, title: str = "Template Result") -> None:
    """Render a Polars DataFrame with Rich table output."""
    table = Table(title=title)
    for col in result_df.columns:
        table.add_column(col)

    for row in result_df.rows():
        table.add_row(*[str(value) for value in row])

    console.print(table)


def _write_text_output(content: str, file_path: Path | None, *, json_output: bool = False) -> None:
    """Write output text to file or stdout."""
    if file_path:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        if not json_output:
            cli_output.success(f"Saved to {file_path}")
    else:
        print(content)


def _write_json_output(payload: dict[str, Any], file_path: Path | None) -> None:
    """Write a JSON payload to file or stdout."""
    _write_text_output(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        file_path,
        json_output=True,
    )


def _normalize_json_value(value: Any) -> Any:
    """Convert non-native scalar values into JSON-friendly primitives."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, list):
        return [_normalize_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_json_value(item) for key, item in value.items()}
    return value


def _build_template_list_result(templates: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Build structured template registry output."""
    result: list[dict[str, Any]] = []
    for name, spec in templates.items():
        params = spec.get("params", {}) or {}
        result.append(
            {
                "name": name,
                "description": str(spec.get("description", "")),
                "params": params if isinstance(params, dict) else {},
            }
        )
    return {"templates": result}


def _build_template_show_result(result: TemplateShowResult) -> dict[str, Any]:
    """Build structured template metadata output."""
    return {
        "name": result.name,
        "description": result.description,
        "parameters": result.parameters,
        "sql": result.sql,
    }


def _render_template_list(result: dict[str, Any]) -> None:
    """Render template registry as a Rich table."""
    table = Table(title="Query Templates")
    table.add_column("Name", style="cyan")
    table.add_column("Description")
    table.add_column("Params", style="dim")

    for template_info in result.get("templates", []):
        params = template_info.get("params", {})
        param_names = ", ".join(params.keys()) if isinstance(params, dict) and params else "-"
        table.add_row(
            str(template_info.get("name", "")),
            str(template_info.get("description", "")),
            param_names,
        )

    console.print(table)
    console.print("\nUsage: [green]finjuice template show <name>[/green]")


def _render_template_show(result: dict[str, Any]) -> None:
    """Render template metadata and SQL definition."""
    console.print(f"\n[bold]{result.get('name', '')}[/bold]")
    console.print(f"[dim]{result.get('description', '')}[/dim]\n")

    params = result.get("parameters", {})
    if isinstance(params, dict) and params:
        param_table = Table(title="Parameters")
        param_table.add_column("Name", style="cyan")
        param_table.add_column("Type")
        param_table.add_column("Required")
        param_table.add_column("Default")

        for param_name, param_spec in params.items():
            param_spec_dict = param_spec if isinstance(param_spec, dict) else {}
            param_type = str(param_spec_dict.get("type", "str"))
            required = "yes" if bool(param_spec_dict.get("required", False)) else "no"
            default = str(param_spec_dict.get("default", "-"))
            param_table.add_row(param_name, param_type, required, default)

        console.print(param_table)
        console.print()

    console.print("[bold]SQL[/bold]")
    console.print(f"```sql\n{str(result.get('sql', '')).strip()}\n```")


def emit_template_list(result: TemplateListResult, *, json_output: bool) -> None:
    """Emit the template list result."""
    emit(
        _build_template_list_result(result.templates),
        json_output,
        _render_template_list,
        command="template list",
    )


def emit_template_show(result: TemplateShowResult, *, json_output: bool) -> None:
    """Emit the template show result."""
    emit(
        _build_template_show_result(result),
        json_output,
        _render_template_show,
        command="template show",
    )


def render_template_run_result(result: TemplateRunResult) -> int:
    """Render a completed template run and return the audited row count."""
    if result.output_format == "table":
        _print_table(result.result_df, title=f"Template Result: {result.template_name}")
        cli_output.render_pagination_footer(result.row_count, result.pagination)
        return result.row_count

    if result.output_format == "csv":
        _write_text_output(
            result.result_df.write_csv(),
            result.file,
            json_output=result.machine_output,
        )
        return result.row_count

    if result.output_format == "json":
        meta_extras: dict[str, Any] = {
            "filters_applied": result.filters_applied,
            **result.template_meta_extras,
        }
        if result.pivot_columns is not None:
            meta_extras["columns"] = _normalize_json_value(result.pivot_columns)
        payload = cli_output.truncate_rows_to_max_bytes(
            {
                "template_name": result.template_name,
                "row_count": result.row_count,
                "rows": _normalize_json_value(result.result_df.to_dicts()),
            },
            pagination=result.pagination,
            max_bytes=result.max_bytes,
            command="template run",
            meta_extras=meta_extras,
        )
        _write_json_output(
            {
                "_meta": _build_meta("template run", extras=meta_extras),
                **payload,
            },
            result.file,
        )
        return int(payload["row_count"])

    if result.output_format == "markdown":
        _write_text_output(cli_output.render_markdown_dataframe(result.result_df), result.file)
        return result.row_count

    assert result.file is not None
    result.file.parent.mkdir(parents=True, exist_ok=True)
    result.result_df.write_excel(result.file)
    cli_output.success(f"Saved to {result.file}")
    return result.row_count
