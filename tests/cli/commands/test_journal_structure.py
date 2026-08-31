"""Structure checks for the split journal command implementation."""

from pathlib import Path

from finjuice.pipeline.cli.commands import journal as journal_module
from finjuice.pipeline.cli.commands import journal_gitignore

COMMANDS_DIR = Path("src/finjuice/pipeline/cli/commands")


def test_journal_gitignore_helpers_live_in_helper_module() -> None:
    """Git-root and ignore-rule helpers should not live in the Typer module."""
    journal_text = (COMMANDS_DIR / "journal.py").read_text(encoding="utf-8")
    gitignore_text = (COMMANDS_DIR / "journal_gitignore.py").read_text(encoding="utf-8")

    assert "def new_entry" in journal_text
    assert "def list_entries" in journal_text
    assert "def resume_entry" in journal_text
    assert "def _maybe_prompt_for_gitignore" not in journal_text
    assert "def _find_git_root" not in journal_text
    assert "def _gitignore_covers_journal_dir" not in journal_text
    assert "def _maybe_prompt_for_gitignore" in gitignore_text
    assert "def _find_git_root" in gitignore_text
    assert "def _gitignore_covers_journal_dir" in gitignore_text


def test_journal_gitignore_helpers_reexport_from_entrypoint() -> None:
    """Existing journal.py imports should keep resolving to the gitignore helpers."""
    journal_text = (COMMANDS_DIR / "journal.py").read_text(encoding="utf-8")

    assert "def new_entry" in journal_text
    assert "_maybe_prompt_for_gitignore" in journal_text
    assert "_find_git_root" in journal_text
    assert "_gitignore_covers_journal_dir" in journal_text
    assert (
        journal_module._maybe_prompt_for_gitignore is journal_gitignore._maybe_prompt_for_gitignore
    )
    assert journal_module._find_git_root is journal_gitignore._find_git_root
    assert (
        journal_module._gitignore_covers_journal_dir
        is journal_gitignore._gitignore_covers_journal_dir
    )
    assert callable(journal_module.new_entry)
    assert callable(journal_module.list_entries)
    assert callable(journal_module.resume_entry)
