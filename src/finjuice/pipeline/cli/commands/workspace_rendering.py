"""Human-readable Rich rendering for ``finjuice workspace``.

Owns create/list/remove/verify console output. Typer commands, registry
I/O, and symlink layout stay in :mod:`finjuice.pipeline.cli.commands.workspace_cmd`
and :mod:`finjuice.pipeline.cli.commands.workspace_helpers`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from finjuice.pipeline.cli.commands.workspace_helpers import (
    FILE_SYMLINKS,
    SYMLINK_TARGETS,
    is_valid_workspace,
)
from finjuice.pipeline.cli.output import console, error, success, warning


def _render_workspace_create_success(workspace_path: Path, data_dir: Path) -> None:
    """Render the post-create workspace structure and next-step hints."""
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


def _render_workspace_list(workspaces: list[dict[str, Any]], data_dir: Path) -> None:
    """Render the empty or populated workspace registry listing."""
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


def _render_workspace_remove_warning() -> None:
    """Render the pre-confirmation warning for workspace removal."""
    console.print()
    warning("This will remove the workspace directory and symlinks.")
    console.print("   Your actual data will NOT be deleted.\n")


def _render_workspace_remove_success(workspace_path: Path, data_dir: Path) -> None:
    """Render the post-remove confirmation that data remains intact."""
    console.print()
    success(f"Removed workspace: {workspace_path}")
    console.print(f"💾 Data remains safe at: {data_dir}")


def _render_workspace_verify(workspace_path: Path, results: list[tuple[str, str]]) -> bool:
    """Render symlink and metadata verification results.

    Returns:
        True when every symlink and the workspace metadata file is valid.
    """
    console.print(f"\n🔍 Verifying workspace: {workspace_path}\n")

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

    return all_valid
