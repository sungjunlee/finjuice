"""Rules management command group for the finjuice CLI.

The command implementations live in ``rules_cmd`` modules. This module remains
as the stable import path for the Typer command group.
"""

import sys
from typing import Optional

import typer

from finjuice.pipeline.cli.commands.rules_cmd.export import export_rules_command, list_rules_command
from finjuice.pipeline.cli.commands.rules_cmd.gaps import analyze_gaps_command
from finjuice.pipeline.cli.commands.rules_cmd.mutations import add_rule_command, remove_rule_command
from finjuice.pipeline.cli.commands.rules_cmd.suggest import suggest_rules_command
from finjuice.pipeline.cli.commands.rules_cmd.testing import test_rule_command
from finjuice.pipeline.cli.commands.validate_rules import validate_rules_command

rules_app = typer.Typer(name="rules", help="Manage tagging rules")

rules_app.command(name="validate")(validate_rules_command)
rules_app.command(name="list")(list_rules_command)
rules_app.command(name="add")(add_rule_command)
rules_app.command(name="remove")(remove_rule_command)
rules_app.command(name="test")(test_rule_command)
rules_app.command(name="suggest")(suggest_rules_command)
rules_app.command(name="export")(export_rules_command)
rules_app.command(name="gaps")(analyze_gaps_command)


__all__ = [
    "add_rule_command",
    "analyze_gaps_command",
    "export_rules_command",
    "list_rules_command",
    "register_rules_commands",
    "remove_rule_command",
    "rules_app",
    "suggest_rules_command",
    "sys",
    "test_rule_command",
    "validate_rules_command",
]


def register_rules_commands(app: typer.Typer, *, rich_help_panel: Optional[str] = None) -> None:
    """Register the rules command group with the main Typer app."""
    if rich_help_panel is not None:
        app.add_typer(rules_app, name="rules", rich_help_panel=rich_help_panel)
    else:
        app.add_typer(rules_app, name="rules")
