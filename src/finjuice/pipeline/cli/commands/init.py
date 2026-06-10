"""finjuice CLI init/history/show — thin command-registration shim."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import typer

from finjuice.pipeline.cli.commands.history_cmd import history_command
from finjuice.pipeline.cli.commands.init_cmd import init_command
from finjuice.pipeline.cli.commands.show_cmd import show_command


def register_init_commands(app: typer.Typer) -> None:
    """Register all initialization and utility commands with the main Typer app."""
    app.command(name="init", rich_help_panel="Admin")(init_command)
    app.command(name="history", rich_help_panel="Admin")(history_command)
    app.command(name="show", rich_help_panel="Analysis")(show_command)


__all__ = [
    "register_init_commands",  # Public API — command registration hook used by cli.main.
]
