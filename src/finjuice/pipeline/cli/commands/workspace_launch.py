"""File-manager launch helpers for ``finjuice workspace``.

Owns the OS-specific open command and subprocess launch used by
``workspace open``. Path resolve/existence guards stay in
:mod:`finjuice.pipeline.cli.commands.workspace_paths`. Typer commands
stay in :mod:`finjuice.pipeline.cli.commands.workspace_cmd`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from finjuice.pipeline.constants import SUBPROCESS_TIMEOUT_SHORT


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


def open_workspace_path(workspace_path: Path) -> None:
    """Open ``workspace_path`` in the system file manager."""
    command = get_open_command()
    subprocess.run([command, str(workspace_path)], timeout=SUBPROCESS_TIMEOUT_SHORT)
