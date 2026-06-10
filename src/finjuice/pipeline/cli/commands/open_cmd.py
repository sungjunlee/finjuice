"""
Open command: Open data directories and files in file manager/editor.

Provides user-friendly access to data directories, especially useful after
migration to OS-specific locations (Issue #62).
"""

import logging
import platform
import subprocess
from pathlib import Path
from typing import Annotated, Callable, Optional

import typer

from finjuice.pipeline.cli.output import console

logger = logging.getLogger(__name__)


def get_open_command() -> str:
    """Get platform-specific command to open files/directories."""
    system = platform.system()
    if system == "Darwin":  # macOS
        return "open"
    elif system == "Linux":
        return "xdg-open"
    elif system == "Windows":
        return "explorer"
    else:
        raise NotImplementedError(f"Unsupported platform: {system}")


def find_latest_master(export_dir: Path) -> Optional[Path]:
    """Find latest master_YYYYMMDD.xlsx file."""
    master_files = sorted(export_dir.glob("master_*.xlsx"), reverse=True)
    if not master_files:
        return None
    return master_files[0]


def open_path(path: Path) -> None:
    """Open path in file manager or default application."""
    from finjuice.pipeline.constants import SUBPROCESS_TIMEOUT_SHORT

    command = get_open_command()
    subprocess.run([command, str(path)], timeout=SUBPROCESS_TIMEOUT_SHORT)


def register_open_command(app: typer.Typer) -> None:
    """Register the open command with the Typer app."""

    @app.command(name="open", rich_help_panel="Admin")
    def open_target(
        ctx: typer.Context,
        target: Annotated[
            Optional[str],
            typer.Argument(help="Target: . imports exports reports transactions/tx rules master"),
        ] = None,
    ) -> None:
        """
        Open data directories or files in file manager/editor.

        Opens the specified target in your system's file manager (Finder, Explorer)
        or default application.

        Examples:
            # Open data directory
            finjuice open

            # Open imports directory
            finjuice open imports

            # Open rules.yaml in editor
            finjuice open rules

            # Open latest master Excel file
            finjuice open master
        """
        from finjuice.pipeline.config import Config

        # Get config from context
        config: Optional[Config] = None
        if ctx.obj and "config" in ctx.obj:
            config = ctx.obj["config"]

        if config is None:
            console.print("Configuration not initialized", style="red")
            raise typer.Exit(code=1)

        # Build target mapping
        target_map: dict[Optional[str], Callable[[], Path]] = {
            None: lambda: config.data_dir,
            ".": lambda: config.data_dir,
            "imports": lambda: config.import_dir,
            "exports": lambda: config.export_dir,
            "reports": lambda: config.reports_dir,
            "transactions": lambda: config.csv_base_dir,
            "tx": lambda: config.csv_base_dir,  # Alias
            "rules": lambda: config.rules_file,
            "master": lambda: _get_master_or_raise(config.export_dir),
        }

        # Validate target
        if target not in target_map:
            console.print(
                f"Unknown target: '{target}'. "
                f"Valid targets: {', '.join(str(k) for k in target_map.keys() if k)}",
                style="red",
            )
            raise typer.Exit(code=1)

        # Get path
        try:
            path = target_map[target]()
        except FileNotFoundError as e:
            console.print(f"Not found: {e}", style="red")
            raise typer.Exit(code=1)

        # Check existence
        if not path.exists():
            console.print(f"Path does not exist: {path}", style="red")
            if target in ("imports", "exports", "reports", "transactions", "tx"):
                console.print("\nTip: Run 'finjuice refresh' to create directories", style="yellow")
            elif target == "rules":
                console.print("\nTip: Create rules.yaml or run 'finjuice init'", style="yellow")
            raise typer.Exit(code=1)

        # Open the path
        try:
            open_path(path)
            console.print(f"Opened: {path}")
        except Exception as e:  # intended catch-all for CLI robustness
            console.print(f"Failed to open: {e}", style="red")
            raise typer.Exit(code=1)


def _get_master_or_raise(export_dir: Path) -> Path:
    """Get latest master file or raise FileNotFoundError."""
    master = find_latest_master(export_dir)
    if master is None:
        raise FileNotFoundError(f"No master files found in {export_dir}")
    return master
