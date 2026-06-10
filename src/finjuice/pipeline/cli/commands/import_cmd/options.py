"""Typed options for the import command use case."""

from dataclasses import dataclass
from pathlib import Path

import typer

from finjuice.pipeline.config import Config


@dataclass(frozen=True)
class ImportOptions:
    """Normalized CLI options for an import run."""

    ctx: typer.Context
    config: Config
    files: tuple[Path, ...]
    file: Path | None
    force: bool
    dry_run: bool
    password: str | None
    json_output: bool
    no_scan: bool = False

    @property
    def emit_text(self) -> bool:
        """Return whether human-readable output should be printed."""
        return not self.json_output
