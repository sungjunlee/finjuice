"""CLI manifest command for machine-readable command discovery."""

from __future__ import annotations

from typing import Any

import click
import typer
import typer.main
from rich.tree import Tree

from finjuice import get_version
from finjuice.pipeline.cli import output
from finjuice.pipeline.cli.introspection import (
    base_type_schema,
    has_json_flag,
    iter_executable_commands_with_panels,
    option_property_name,
    rich_help_panel_name,
    serialize_default,
)
from finjuice.pipeline.cli.output import error_code_values, exit_code_items

MANIFEST_SCHEMA_VERSION = "1.0"
ERROR_SCHEMA_REF = "schemas/_error.schema.json"

MUTATING_COMMANDS = {
    "all",
    "audit clear",
    "budget edit",
    "doctor",
    "export",
    "import",
    "ingest",
    "init",
    "journal new",
    "journal resume",
    "migrate",
    "refresh",
    "rules add",
    "rules export",
    "rules gaps",
    "rules remove",
    "rules suggest",
    "tag",
    "template run",
    "transfer",
    "update-agents",
    "workspace create",
    "workspace remove",
}

CONFIRMATION_REQUIRED_COMMANDS = MUTATING_COMMANDS | {
    "workspace open",
}

RUNTIME_METADATA_COMMANDS = {
    "doctor",
    "history",
    "manifest",
    "open",
    "update-agents",
    "workspace create",
    "workspace list",
    "workspace open",
    "workspace remove",
    "workspace verify",
}

ARTIFACT_COMMANDS = {
    "export",
    "open",
}

COMMAND_EXAMPLES = {
    "manifest": ["finjuice manifest --json", "finjuice manifest --commands-only --json"],
    "query": ['finjuice query --json "SELECT * FROM transactions LIMIT 5"'],
    "status": ["finjuice status --json"],
    "rules add": [
        "finjuice rules add --dry-run --name dining_example --match example --tags 식비 --json"
    ],
}


def _first_paragraph(text: str | None) -> str:
    """Collapse the first paragraph of Click help text."""
    if not text:
        return ""

    paragraph_lines: list[str] = []
    for line in (line.strip() for line in text.splitlines()):
        if not line:
            if paragraph_lines:
                break
            continue
        paragraph_lines.append(line)
    return " ".join(paragraph_lines)


def _schema_type(param: click.Parameter) -> str:
    """Return a compact type label from the shared JSON Schema mapper."""
    if param.nargs != 1 or getattr(param, "multiple", False):
        return "array"

    schema_type = base_type_schema(param).get("type", "string")
    if isinstance(schema_type, list):
        return "|".join(str(item) for item in schema_type)
    return str(schema_type)


def _short_option(param: click.Option) -> str | None:
    """Return the first short option alias, if present."""
    opts = [str(option) for option in (getattr(param, "opts", []) or [])]
    for option in opts:
        if option.startswith("-") and not option.startswith("--"):
            return option
    return None


def _envvar(param: click.Option) -> Any:
    """Return a JSON-serializable envvar declaration."""
    envvar = getattr(param, "envvar", None)
    return serialize_default(envvar)


def _argument_spec(param: click.Argument) -> dict[str, Any]:
    """Serialize a Click argument for the manifest."""
    return {
        "name": option_property_name(param),
        "type": _schema_type(param),
        "required": param.required,
        "default": serialize_default(param.default),
        "help": getattr(param, "help", None),
    }


def _option_spec(param: click.Option) -> dict[str, Any]:
    """Serialize a Click option for the manifest."""
    return {
        "name": option_property_name(param),
        "short": _short_option(param),
        "type": _schema_type(param),
        "default": serialize_default(param.default),
        "envvar": _envvar(param),
        "help": getattr(param, "help", None),
        "is_flag": bool(getattr(param, "is_flag", False)),
    }


def _privacy_profile(path: str) -> str:
    """Return the privacy profile advertised for a command path."""
    if path in ARTIFACT_COMMANDS:
        return "artifact_path"
    if path in RUNTIME_METADATA_COMMANDS:
        return "local_runtime_metadata"
    return "local_financial_data"


def _output_schema_ref(path: str, command: click.Command) -> str | None:
    """Return the conventional sibling JSON Schema artifact path for a command."""
    if not has_json_flag(command):
        return None
    return f"schemas/{path.replace(' ', '_')}.schema.json"


def _command_safety_metadata(path: str) -> dict[str, Any]:
    """Return additive agent safety metadata for one command path."""
    mutates_data = path in MUTATING_COMMANDS
    return {
        "safe_readonly": not mutates_data,
        "mutates_data": mutates_data,
        "requires_confirmation": path in CONFIRMATION_REQUIRED_COMMANDS,
        "privacy_profile": _privacy_profile(path),
        "examples": COMMAND_EXAMPLES.get(path, []),
        "error_schema_ref": ERROR_SCHEMA_REF,
    }


def _command_spec(
    dotted_path: str,
    command: click.Command,
    rich_help_panel: str | None,
) -> dict[str, Any]:
    """Serialize one visible leaf command."""
    path = dotted_path.replace(".", " ")
    arguments: list[dict[str, Any]] = []
    options: list[dict[str, Any]] = []

    for param in command.params:
        if getattr(param, "hidden", False):
            continue
        if isinstance(param, click.Argument):
            arguments.append(_argument_spec(param))
        elif isinstance(param, click.Option):
            options.append(_option_spec(param))

    return {
        "name": command.name or path.rsplit(" ", maxsplit=1)[-1],
        "path": path,
        "help": _first_paragraph(command.help or command.short_help),
        "rich_help_panel": rich_help_panel,
        "arguments": arguments,
        "options": options,
        "output_schema_ref": _output_schema_ref(path, command),
        **_command_safety_metadata(path),
    }


def _commands_only_spec(command: dict[str, Any]) -> dict[str, Any]:
    """Return the compact command description used by --commands-only."""
    return {
        "path": command["path"],
        "help_oneline": _first_paragraph(command.get("help")),
        "output_schema_ref": command["output_schema_ref"],
    }


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
