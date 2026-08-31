"""Workspace path resolution helpers for ``finjuice workspace``.

Owns user-path resolve, empty-directory create, and existence/validity
guards used by create/remove/verify/open. Registry I/O and symlink layout
stay in :mod:`finjuice.pipeline.cli.commands.workspace_helpers`. Typer
commands stay in :mod:`finjuice.pipeline.cli.commands.workspace_cmd`.
"""

from __future__ import annotations

from pathlib import Path

import typer

from finjuice.pipeline.cli.commands.workspace_helpers import is_valid_workspace
from finjuice.pipeline.cli.output import console


def resolve_workspace_path(path: Path) -> Path:
    """Expand ``~`` and resolve the user-supplied workspace path."""
    return path.expanduser().resolve()


def ensure_empty_workspace_directory(workspace_path: Path) -> None:
    """Create the workspace directory, or exit if a non-empty path exists."""
    if workspace_path.exists():
        if any(workspace_path.iterdir()):
            console.print(
                f"Directory already exists and is not empty: {workspace_path}",
                style="red",
            )
            raise typer.Exit(code=1)
    else:
        workspace_path.mkdir(parents=True)


def require_existing_workspace(path: Path) -> Path:
    """Return a resolved workspace path, or exit if missing or invalid."""
    workspace_path = resolve_workspace_path(path)
    if not workspace_path.exists():
        console.print(f"Workspace not found: {workspace_path}", style="red")
        raise typer.Exit(code=1)

    if not is_valid_workspace(workspace_path):
        console.print(
            f"Not a valid workspace (missing .finjuice-workspace): {workspace_path}",
            style="red",
        )
        raise typer.Exit(code=1)

    return workspace_path
