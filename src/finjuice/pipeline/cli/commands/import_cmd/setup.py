"""First-run setup helpers for the import command."""

from pathlib import Path


def is_first_run(data_dir: Path) -> bool:
    """Return True if data directory needs initialization."""
    return not data_dir.exists() or not (data_dir / "rules.yaml").exists()
