"""Typed results for import command helpers and use cases."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict


class ImportFileResults(TypedDict):
    """Copy step results grouped by outcome."""

    imported: list[tuple[Path, Path]]
    skipped: list[tuple[Path, str]]
    errors: list[tuple[Path, str]]


@dataclass(frozen=True)
class ImportResult:
    """Final import command result ready for CLI emission."""

    payload: dict[str, Any]
    dry_run: bool
