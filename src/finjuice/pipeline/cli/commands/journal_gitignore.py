"""Journal CLI gitignore safety helpers.

Owns git-root discovery, ignore-rule coverage checks, and the optional
local gitignore prompt. Typer commands stay in
:mod:`finjuice.pipeline.cli.commands.journal`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer


def _maybe_prompt_for_gitignore(journal_dir: Path) -> None:
    """Offer to add a local ignore rule for underscore-prefixed journal dirs."""
    git_root = _find_git_root(journal_dir)
    if git_root is None:
        return

    gitignore_path = git_root / ".gitignore"
    if _gitignore_covers_journal_dir(gitignore_path, journal_dir.name):
        return

    prompt = f"Add '_*/' to {gitignore_path} so private journals stay out of git?"
    if not typer.confirm(prompt, default=True):
        return

    existing = gitignore_path.read_text(encoding="utf-8") if gitignore_path.exists() else ""
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    gitignore_path.write_text(f"{existing}{prefix}_*/\n", encoding="utf-8")


def _find_git_root(start: Path) -> Optional[Path]:
    """Return the nearest git root for the journal directory."""
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _gitignore_covers_journal_dir(gitignore_path: Path, journal_dir_name: str) -> bool:
    """Detect `_*/` or explicit journal dir ignore entries."""
    if not gitignore_path.exists():
        return False

    expected_names = {
        "_*/",
        "/_*/",
        "**/_*/",
        f"{journal_dir_name}/",
        f"/{journal_dir_name}/",
        f"**/{journal_dir_name}/",
    }

    for raw_line in gitignore_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        if line in expected_names:
            return True

    return False
