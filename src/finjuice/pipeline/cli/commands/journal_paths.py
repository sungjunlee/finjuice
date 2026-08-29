"""Journal CLI topic slug, path, and directory helpers.

Owns filename-safe topic slugs, collision-safe new-entry paths, and
journal directory creation. Typer commands stay in
:mod:`finjuice.pipeline.cli.commands.journal`.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer

MAX_TOPIC_LENGTH = 48
_CONTROL_CHARACTERS = {chr(code) for code in range(32)} | {chr(127)}


def _resolve_topic(topic: Optional[str], now: datetime) -> str:
    """Return a safe topic slug for filename/front matter use."""
    if topic is None or not sys.stdin.isatty():
        if topic is None:
            return f"session-{now.strftime('%Y%m%d-%H%M%S')}"
        return _normalize_slug(topic, now)
    return _normalize_slug(topic, now)


def _normalize_slug(raw_topic: str, now: datetime) -> str:
    """Normalize user input into a safe filename slug."""
    sanitized = "".join(ch if ch not in _CONTROL_CHARACTERS else " " for ch in raw_topic)
    sanitized = sanitized.replace("/", "-").replace("\\", "-")
    sanitized = sanitized.strip().strip(".").lower()
    sanitized = sanitized.replace(".", "-")
    normalized_chars: list[str] = []
    previous_was_dash = False

    for ch in sanitized:
        if ch.isalnum() or ch in {"-", "_"}:
            normalized_chars.append(ch)
            previous_was_dash = False
            continue
        if ch.isspace() or ch in {":", ","}:
            if not previous_was_dash:
                normalized_chars.append("-")
                previous_was_dash = True
            continue

    slug = "".join(normalized_chars).strip("-_")
    while "--" in slug:
        slug = slug.replace("--", "-")
    slug = slug[:MAX_TOPIC_LENGTH].rstrip("-_")
    if not slug:
        return f"session-{now.strftime('%Y%m%d-%H%M%S')}"
    return slug


def _resolve_new_entry_path(journal_dir: Path, topic: str, now: datetime) -> Path:
    """Return a collision-safe journal path for today/topic."""
    date_prefix = now.strftime("%Y-%m-%d")
    base_name = f"{date_prefix}_{topic}"
    candidate = journal_dir / f"{base_name}.md"
    counter = 2

    while candidate.exists():
        candidate = journal_dir / f"{base_name}_{counter}.md"
        counter += 1

    return candidate


def _ensure_journal_dir(path: Path) -> Path:
    """Create the journal directory if needed and reject symlink targets."""
    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir() or path.is_symlink():
        raise typer.BadParameter(f"Journal directory must be a real directory: {path}")
    return path
