"""Admin command for refreshing the AGENTS.md template."""

import logging
import shutil

import typer

from finjuice.pipeline.cli import output as cli_output
from finjuice.pipeline.cli.output import console
from finjuice.pipeline.cli.utils import get_config

logger = logging.getLogger(__name__)


def update_agents_command(ctx: typer.Context) -> None:
    """Update AGENTS.md to the latest template version."""
    from finjuice.pipeline.cli.commands.init_cmd import copy_template_file

    config = get_config(ctx)
    agents_file = config.data_dir / "AGENTS.md"

    if not agents_file.exists():
        cli_output.warning("AGENTS.md not found in data directory.")
        console.print()
        console.print("To create AGENTS.md, run:", style="yellow")
        console.print(f"   finjuice --data-dir {config.data_dir} init --with-agents")
        raise typer.Exit(code=1)

    try:
        backup_file = agents_file.with_suffix(".md.bak")
        shutil.copy2(agents_file, backup_file)
        logger.debug("Created backup: %s", backup_file)

        agents_file.unlink()
        copy_template_file("AGENTS.md", agents_file)

        cli_output.success("AGENTS.md updated")
        cli_output.info(f"   Backup saved: {backup_file.name}")
    except FileNotFoundError as exc:
        cli_output.error(f"Template not found: {exc}")
        raise typer.Exit(code=1)
    except PermissionError as exc:
        cli_output.error(f"Permission denied: {exc}")
        raise typer.Exit(code=1)
    except Exception as exc:  # intended catch-all for CLI robustness
        logger.error("Failed to update AGENTS.md: %s", exc, exc_info=True)
        cli_output.error(f"Update failed: {exc}")
        raise typer.Exit(code=1)


def register_update_agents_command(app: typer.Typer) -> None:
    """Register the update-agents admin command."""
    app.command(name="update-agents", rich_help_panel="Admin")(update_agents_command)
