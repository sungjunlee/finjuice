"""
Workspace command: Manage symlink-based work directories.

Provides user-friendly workspace creation for easy data access,
especially useful for Claude Code and other AI tools (Issue #65).
"""

import logging
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Annotated, Optional

import typer
import yaml

from finjuice.pipeline.cli.commands.workspace_helpers import (
    FILE_SYMLINKS,
    SYMLINK_TARGETS,
    WORKSPACE_README_TEMPLATE,
    WORKSPACE_VERSION,
    create_symlinks,
    is_valid_workspace,
    load_workspace_registry,
    register_workspace,
    unregister_workspace,
    validate_data_directories,
    verify_symlinks,
)
from finjuice.pipeline.cli.output import console, error, success, warning

logger = logging.getLogger(__name__)

workspace_app = typer.Typer(help="Manage workspace directories (symlink-based)")


def get_open_command() -> str:
    """Get platform-specific command to open files/directories."""
    import platform

    system = platform.system()
    if system == "Darwin":
        return "open"
    elif system == "Linux":
        return "xdg-open"
    elif system == "Windows":
        return "explorer"
    else:
        raise NotImplementedError(f"Unsupported platform: {system}")


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
    workspace_path = path.expanduser().resolve()
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

    # Check workspace doesn't already exist with content
    if workspace_path.exists():
        if any(workspace_path.iterdir()):
            console.print(
                f"Directory already exists and is not empty: {workspace_path}",
                style="red",
            )
            raise typer.Exit(code=1)
    else:
        workspace_path.mkdir(parents=True)

    # Create symlinks
    try:
        create_symlinks(workspace_path, data_dir)
    except OSError as e:
        console.print(f"Failed to create symlinks: {e}", style="red")
        raise typer.Exit(code=1)

    # Write metadata
    metadata = {
        "version": WORKSPACE_VERSION,
        "data_dir": str(data_dir),
        "created_at": datetime.now().isoformat(),
    }
    metadata_file = workspace_path / ".finjuice-workspace"
    metadata_file.write_text(yaml.dump(metadata, default_flow_style=False))

    # Write README
    readme_file = workspace_path / "README.md"
    readme_file.write_text(WORKSPACE_README_TEMPLATE)

    # Register workspace
    register_workspace(data_dir, workspace_path)

    # Success message
    console.print()
    success(f"Created workspace: {workspace_path}")
    console.print()
    console.print("📁 Structure:")
    for target in SYMLINK_TARGETS:
        console.print(f"   {target}/ → {data_dir / target}")
    for target in FILE_SYMLINKS:
        console.print(f"   {target} → {data_dir / target}")

    console.print(f"\n💡 Now you can work from {workspace_path}")
    console.print("\n📋 Next steps:")
    console.print(f"   cd {workspace_path}")
    console.print("   ls -la imports/")
    console.print("   finjuice refresh")


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

    if not workspaces:
        console.print("\n📁 No workspaces found\n")
        console.print("Create one with: finjuice workspace create <path>")
        return

    console.print("\n📁 Active workspaces:\n", style="bold")
    for i, ws in enumerate(workspaces, 1):
        ws_path = Path(ws.get("path", ""))
        created = ws.get("created_at", "Unknown")

        # Check if still valid
        if ws_path.exists() and is_valid_workspace(ws_path):
            status = "✅ Valid"
        else:
            status = "❌ Invalid/Missing"

        console.print(f"   {i}. {ws_path}")
        console.print(f"      Created: {created}")
        console.print(f"      Status: {status}\n")

    console.print(f"💾 Data location: {data_dir}")


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
    workspace_path = path.expanduser().resolve()

    # Check workspace exists
    if not workspace_path.exists():
        console.print(f"Workspace not found: {workspace_path}", style="red")
        raise typer.Exit(code=1)

    # Check it's a valid workspace
    if not is_valid_workspace(workspace_path):
        console.print(
            f"Not a valid workspace (missing .finjuice-workspace): {workspace_path}",
            style="red",
        )
        raise typer.Exit(code=1)

    # Confirm removal
    if not force and not yes:
        console.print()
        warning("This will remove the workspace directory and symlinks.")
        console.print("   Your actual data will NOT be deleted.\n")
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

    console.print()
    success(f"Removed workspace: {workspace_path}")
    console.print(f"💾 Data remains safe at: {data_dir}")


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
    workspace_path = path.expanduser().resolve()

    # Check workspace exists
    if not workspace_path.exists():
        console.print(f"Workspace not found: {workspace_path}", style="red")
        raise typer.Exit(code=1)

    # Check it's a valid workspace
    if not is_valid_workspace(workspace_path):
        console.print(
            f"Not a valid workspace (missing .finjuice-workspace): {workspace_path}",
            style="red",
        )
        raise typer.Exit(code=1)

    console.print(f"\n🔍 Verifying workspace: {workspace_path}\n")

    # Verify symlinks
    results = verify_symlinks(workspace_path)
    all_valid = True

    for name, status in results:
        if status == "valid":
            success(f"{name} → Valid symlink")
        elif status == "broken":
            error(f"{name} → Broken symlink")
            all_valid = False
        elif status == "missing":
            error(f"{name} → Missing")
            all_valid = False
        else:
            warning(f"{name} → Not a symlink")
            all_valid = False

    # Check metadata
    metadata_file = workspace_path / ".finjuice-workspace"
    if metadata_file.exists():
        success(".finjuice-workspace → Valid metadata")
    else:
        error(".finjuice-workspace → Missing")
        all_valid = False

    console.print()
    if all_valid:
        success("All checks passed!")
    else:
        error("Some checks failed")
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
    workspace_path = path.expanduser().resolve()

    # Check workspace exists
    if not workspace_path.exists():
        console.print(f"Workspace not found: {workspace_path}", style="red")
        raise typer.Exit(code=1)

    # Check it's a valid workspace
    if not is_valid_workspace(workspace_path):
        console.print(
            f"Not a valid workspace (missing .finjuice-workspace): {workspace_path}",
            style="red",
        )
        raise typer.Exit(code=1)

    # Open in file manager
    try:
        from finjuice.pipeline.constants import SUBPROCESS_TIMEOUT_SHORT

        command = get_open_command()
        subprocess.run([command, str(workspace_path)], timeout=SUBPROCESS_TIMEOUT_SHORT)
        console.print(f"Opened: {workspace_path}")
    except Exception as e:  # intended catch-all for CLI robustness
        console.print(f"Failed to open: {e}", style="red")
        raise typer.Exit(code=1)


def register_workspace_command(app: typer.Typer) -> None:
    """Register the workspace command group with the Typer app."""
    app.add_typer(workspace_app, name="workspace", rich_help_panel="Admin")
