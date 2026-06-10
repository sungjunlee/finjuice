"""Core journal-entry metadata loading shared by the CLI and context bundles.

The journal markdown files are read-only inputs for several surfaces: the
`journal` CLI command group renders them, and `pipeline.context` summarizes them
for AI agents. This module owns the side-effect-free parsing so non-CLI core
code does not need to import `finjuice.pipeline.cli.*`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml


@dataclass(frozen=True)
class JournalEntry:
    """Parsed journal entry metadata for list/resume commands."""

    path: Path
    filename: str
    topic: str
    created: Optional[str]
    size_bytes: int
    created_sort_key: float

    def to_dict(self) -> dict[str, Any]:
        """Serialize for `journal list --json`."""
        return {
            "path": str(self.path),
            "filename": self.filename,
            "topic": self.topic,
            "created": self.created,
            "size_bytes": self.size_bytes,
        }


def load_journal_entries(journal_dir: Path) -> list[JournalEntry]:
    """Load markdown journal metadata sorted newest first."""
    if not journal_dir.exists():
        return []

    entries: list[JournalEntry] = []
    for path in sorted(journal_dir.glob("*.md")):
        if not path.is_file():
            continue
        entries.append(_parse_entry(path))

    return sorted(entries, key=lambda entry: entry.created_sort_key, reverse=True)


def _parse_entry(path: Path) -> JournalEntry:
    """Parse front matter for list/resume views."""
    payload = _read_front_matter(path)
    stat_result = path.stat()
    created = payload.get("created")
    topic = payload.get("topic") or _topic_from_filename(path)
    created_sort_key = _parse_created_sort_key(created, stat_result.st_mtime)

    return JournalEntry(
        path=path.resolve(),
        filename=path.name,
        topic=str(topic),
        created=str(created) if created is not None else None,
        size_bytes=stat_result.st_size,
        created_sort_key=created_sort_key,
    )


def _read_front_matter(path: Path) -> dict[str, Any]:
    """Return parsed YAML front matter or an empty mapping."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}

    try:
        _, raw_front_matter, _ = text.split("---\n", 2)
    except ValueError:
        return {}

    payload = yaml.safe_load(raw_front_matter) or {}
    return payload if isinstance(payload, dict) else {}


def _topic_from_filename(path: Path) -> str:
    """Fallback topic parsed from the filename."""
    stem = path.stem
    if len(stem) > 11 and stem[10] == "_":
        return stem[11:]
    return stem


def _parse_created_sort_key(created: Any, mtime: float) -> float:
    """Build a sortable timestamp from front matter or file metadata."""
    if isinstance(created, str):
        try:
            return datetime.fromisoformat(created).timestamp()
        except ValueError:
            pass
    return mtime
