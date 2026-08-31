"""Workspace identity-file writers for ``finjuice workspace``.

Owns `.finjuice-workspace` metadata and README.md writes used by
``workspace create``. Registry I/O and the README template stay in
:mod:`finjuice.pipeline.cli.commands.workspace_helpers`. Typer commands
stay in :mod:`finjuice.pipeline.cli.commands.workspace_cmd`.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml

from finjuice.pipeline.cli.commands.workspace_helpers import (
    WORKSPACE_README_TEMPLATE,
    WORKSPACE_VERSION,
)


def write_workspace_metadata(workspace_path: Path, data_dir: Path) -> None:
    """Write `.finjuice-workspace` metadata for a newly created workspace."""
    metadata = {
        "version": WORKSPACE_VERSION,
        "data_dir": str(data_dir),
        "created_at": datetime.now().isoformat(),
    }
    metadata_file = workspace_path / ".finjuice-workspace"
    metadata_file.write_text(yaml.dump(metadata, default_flow_style=False))


def write_workspace_readme(workspace_path: Path) -> None:
    """Write the workspace README next to the identity metadata file."""
    readme_file = workspace_path / "README.md"
    readme_file.write_text(WORKSPACE_README_TEMPLATE)
