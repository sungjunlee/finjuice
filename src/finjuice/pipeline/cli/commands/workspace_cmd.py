"""
Workspace command: Manage symlink-based work directories.

Provides user-friendly workspace creation for easy data access,
especially useful for Claude Code and other AI tools (Issue #65).

Path resolve/existence guards live in
:mod:`finjuice.pipeline.cli.commands.workspace_paths`. File-manager
launch helpers live in
:mod:`finjuice.pipeline.cli.commands.workspace_launch`. Identity-file
writers live in :mod:`finjuice.pipeline.cli.commands.workspace_files`.
Human rendering lives in
:mod:`finjuice.pipeline.cli.commands.workspace_rendering`.
"""

import logging
import shutil
from pathlib import Path
from typing import Annotated, Optional

import typer

from finjuice.pipeline.cli.commands.workspace_files import (
    write_workspace_metadata,
    write_workspace_readme,
)
from finjuice.pipeline.cli.commands.workspace_helpers import (
    FILE_SYMLINKS,  # noqa: F401 — re-exported for existing workspace imports
    SYMLINK_TARGETS,  # noqa: F401 — re-exported for existing workspace imports
    WORKSPACE_README_TEMPLATE,  # noqa: F401 — re-exported for existing workspace imports
    WORKSPACE_VERSION,  # noqa: F401 — re-exported for existing workspace imports
    create_symlinks,
    is_valid_workspace,  # noqa: F401 — re-exported for existing workspace imports
    load_workspace_registry,
    register_workspace,
    unregister_workspace,
    validate_data_directories,
    verify_symlinks,
)
from finjuice.pipeline.cli.commands.workspace_launch import (
    get_open_command,  # noqa: F401 — re-exported for existing workspace imports
    open_workspace_path,
)
from finjuice.pipeline.cli.commands.workspace_paths import (
    ensure_empty_workspace_directory,
    require_existing_workspace,
    resolve_workspace_path,
)
from finjuice.pipeline.cli.commands.workspace_rendering import (
    _render_workspace_create_success,
    _render_workspace_list,
    _render_workspace_remove_success,
    _render_workspace_remove_warning,
    _render_workspace_verify,
)
from finjuice.pipeline.cli.output import console

logger = logging.getLogger(__name__)

workspace_app = typer.Typer(help="Manage workspace directories (symlink-based)")


@workspace_app.command("create")
def workspace_create(
    ctx: typer.Context,
    path: Annotated[
        Path,
        typer.Argument(help="Path to create workspace"),
    ],
) -> None:
    """
    Create a new workspace directory with symlinks.

    Creates a workspace with symlinks to the data directory, making it
    easy to access your finance data from convenient locations.

    Examples:
        # Create workspace in Documents
        finjuice workspace create ~/Documents/my-finance

        # Create workspace on Desktop
        finjuice workspace create ~/Desktop/finance-review
    """
    from finjuice.pipeline.config import Config, validate_not_program_repo_path

    # Get config from context
    config: Optional[Config] = None
    if ctx.obj and "config" in ctx.obj:
        config = ctx.obj["config"]

    if config is None:
        console.print("Configuration not initialized", style="red")
        raise typer.Exit(code=1)

    data_dir = config.data_dir
    workspace_path = resolve_workspace_path(path)
    try:
        validate_not_program_repo_path(workspace_path, context="workspace directory")
    except ValueError as exc:
        console.print(str(exc), style="red")
        raise typer.Exit(code=1) from exc

    # Validate data directories exist
    missing = validate_data_directories(data_dir)
    if missing:
        console.print(
            f"Data directories not found: {', '.join(missing)}",
            style="red",
        )
        console.print("\nRun 'finjuice init' to create required directories")
        raise typer.Exit(code=1)

    ensure_empty_workspace_directory(workspace_path)

    # Create symlinks
    try:
        create_symlinks(workspace_path, data_dir)
    except OSError as e:
        console.print(f"Failed to create symlinks: {e}", style="red")
        raise typer.Exit(code=1)

    write_workspace_metadata(workspace_path, data_dir)
    write_workspace_readme(workspace_path)

    # Register workspace
    register_workspace(data_dir, workspace_path)

    _render_workspace_create_success(workspace_path, data_dir)


@workspace_app.command("list")
def workspace_list(
    ctx: typer.Context,
) -> None:
    """
    List all active workspaces.

    Shows all workspaces that have been created and their status.
    """
    from finjuice.pipeline.config import Config

    # Get config from context
    config: Optional[Config] = None
    if ctx.obj and "config" in ctx.obj:
        config = ctx.obj["config"]

    if config is None:
        console.print("Configuration not initialized", style="red")
        raise typer.Exit(code=1)

    data_dir = config.data_dir
    registry = load_workspace_registry(data_dir)
    workspaces = registry.get("workspaces", [])
    _render_workspace_list(workspaces, data_dir)


@workspace_app.command("remove")
def workspace_remove(
    ctx: typer.Context,
    path: Annotated[
        Path,
        typer.Argument(help="Workspace path to remove"),
    ],
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Skip confirmation"),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation"),
    ] = False,
) -> None:
    """
    Remove a workspace directory (data remains safe).

    Removes the workspace directory and symlinks but does NOT delete
    your actual data.
    """
    from finjuice.pipeline.config import Config

    # Get config from context
    config: Optional[Config] = None
    if ctx.obj and "config" in ctx.obj:
        config = ctx.obj["config"]

    if config is None:
        console.print("Configuration not initialized", style="red")
        raise typer.Exit(code=1)

    data_dir = config.data_dir
    workspace_path = require_existing_workspace(path)

    # Confirm removal
    if not force and not yes:
        _render_workspace_remove_warning()
        confirm = typer.confirm("Proceed?")
        if not confirm:
            console.print("Cancelled")
            raise typer.Exit(code=0)

    # Remove workspace
    try:
        shutil.rmtree(workspace_path)
    except OSError as e:
        console.print(f"Failed to remove workspace: {e}", style="red")
        raise typer.Exit(code=1)

    # Unregister
    unregister_workspace(data_dir, workspace_path)

    _render_workspace_remove_success(workspace_path, data_dir)


@workspace_app.command("verify")
def workspace_verify(
    ctx: typer.Context,
    path: Annotated[
        Path,
        typer.Argument(help="Workspace path to verify"),
    ],
) -> None:
    """
    Verify workspace symlinks are valid.

    Checks that all symlinks in the workspace point to valid targets.
    """
    workspace_path = require_existing_workspace(path)

    # Verify symlinks
    results = verify_symlinks(workspace_path)
    all_valid = _render_workspace_verify(workspace_path, results)
    if not all_valid:
        raise typer.Exit(code=1)


@workspace_app.command("open")
def workspace_open(
    ctx: typer.Context,
    path: Annotated[
        Path,
        typer.Argument(help="Workspace path to open"),
    ],
) -> None:
    """
    Open workspace in file manager.

    Opens the workspace directory in your system's file manager
    (Finder on macOS, Explorer on Windows, etc.).
    """
    workspace_path = require_existing_workspace(path)

    # Open in file manager
    try:
        open_workspace_path(workspace_path)
        console.print(f"Opened: {workspace_path}")
    except Exception as e:  # intended catch-all for CLI robustness
        console.print(f"Failed to open: {e}", style="red")
        raise typer.Exit(code=1)


def register_workspace_command(app: typer.Typer) -> None:
    """Register the workspace command group with the Typer app."""
    app.add_typer(workspace_app, name="workspace", rich_help_panel="Admin")
