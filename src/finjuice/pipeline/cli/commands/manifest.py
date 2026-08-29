"""CLI manifest command for machine-readable command discovery.

Per-command classification, parameter serialization, and command specs live in
:mod:`finjuice.pipeline.cli.commands.manifest_spec`.
"""

from __future__ import annotations

from typing import Any

import click
import typer
import typer.main
from rich.tree import Tree

from finjuice import get_version
from finjuice.pipeline.cli import output
from finjuice.pipeline.cli.commands.manifest_spec import (
    ERROR_SCHEMA_REF,
    _command_spec,
    _commands_only_spec,
    _option_spec,
)
from finjuice.pipeline.cli.introspection import (
    iter_executable_commands_with_panels,
    rich_help_panel_name,
)
from finjuice.pipeline.cli.output import error_code_values, exit_code_items

MANIFEST_SCHEMA_VERSION = "1.0"


def _click_command(cli_app: typer.Typer | click.Command) -> click.Command:
    """Return a Click command for either a Typer app or an already-built Click command."""
    if isinstance(cli_app, click.Command):
        return cli_app
    return typer.main.get_command(cli_app)


def _global_options(click_app: click.Command) -> list[dict[str, Any]]:
    """Serialize root-level options that apply before subcommands."""
    return [
        _option_spec(param)
        for param in click_app.params
        if isinstance(param, click.Option) and not getattr(param, "hidden", False)
    ]


def _root_env(global_options: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return environment variables advertised by root-level options."""
    env_items: list[dict[str, Any]] = []
    for option in global_options:
        envvar = option.get("envvar")
        if not envvar:
            continue
        env_items.append(
            {
                "name": envvar,
                "option": f"--{option['name'].replace('_', '-')}",
                "help": option.get("help"),
            }
        )
    return env_items


def _privacy_profiles() -> dict[str, dict[str, str]]:
    """Return reusable privacy profile descriptions for command metadata."""
    return {
        "local_financial_data": {
            "description": "Reads local private transaction, asset, rules, or budget data.",
            "external_disclosure": "never",
        },
        "local_runtime_metadata": {
            "description": "Reads or changes local runtime, workspace, or diagnostic metadata.",
            "external_disclosure": "never",
        },
        "artifact_path": {
            "description": "May write or open local artifact paths derived from private data.",
            "external_disclosure": "never",
        },
    }


def _examples() -> list[dict[str, str]]:
    """Return top-level examples for common agent discovery paths."""
    return [
        {"description": "Discover CLI contract", "command": "finjuice manifest --json"},
        {
            "description": "Use an explicit private data directory",
            "command": "finjuice --data-dir ~/.finjuice status --json",
        },
        {
            "description": "Bypass read-time report filters for one invocation",
            "command": "finjuice --no-filter status --json",
        },
    ]


def _build_manifest(
    cli_app: typer.Typer | click.Command,
    *,
    commands_only: bool,
) -> dict[str, Any]:
    """Build the finjuice CLI manifest from Typer/Click introspection."""
    click_app = _click_command(cli_app)
    commands_with_panels = (
        iter_executable_commands_with_panels(click_app)
        if isinstance(click_app, click.Group)
        else [
            (
                click_app.name or "",
                click_app,
                rich_help_panel_name(getattr(click_app, "rich_help_panel", None)),
            )
        ]
    )
    commands = [
        _command_spec(dotted_path, command, rich_help_panel)
        for dotted_path, command, rich_help_panel in commands_with_panels
    ]

    global_options = _global_options(click_app)
    result: dict[str, Any] = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "finjuice_version": get_version(),
        "commands": [_commands_only_spec(command) for command in commands]
        if commands_only
        else commands,
    }
    if commands_only:
        return result

    panels = sorted(
        {
            command["rich_help_panel"]
            for command in commands
            if isinstance(command.get("rich_help_panel"), str)
        }
    )
    result.update(
        {
            "error_codes": sorted(error_code_values()),
            "error_schema_ref": ERROR_SCHEMA_REF,
            "exit_codes": dict(exit_code_items()),
            "examples": _examples(),
            "global_options": global_options,
            "panels": panels,
            "privacy_profiles": _privacy_profiles(),
            "root_env": _root_env(global_options),
        }
    )
    return result


def _render_text(result: dict[str, Any]) -> None:
    """Render a human-readable command tree."""
    tree = Tree(
        f"finjuice manifest v{result['manifest_schema_version']} "
        f"(finjuice {result['finjuice_version']})"
    )
    for command in result["commands"]:
        label = command["path"]
        help_text = command.get("help") or command.get("help_oneline")
        if help_text:
            label = f"{label} [dim]- {help_text}[/dim]"
        tree.add(label)
    output.console.print(tree)


def register_manifest_command(app: typer.Typer) -> None:
    """Register the `finjuice manifest` command."""

    @app.command(
        name="manifest",
        rich_help_panel="Admin",
        help="Emit a machine-readable manifest of the finjuice CLI.",
        short_help="Emit CLI manifest",
    )
    def manifest(
        json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
        commands_only: bool = typer.Option(
            False,
            "--commands-only",
            help="Emit compact command discovery data only.",
        ),
    ) -> None:
        """Emit a self-describing manifest for agents and integrations."""
        result = _build_manifest(app, commands_only=commands_only)
        output.emit(result, json_output, _render_text, command="manifest")
