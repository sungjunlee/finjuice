"""Exclusive publication of derived journal notes outside canonical inputs."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from finjuice.pipeline.config import Config
from finjuice.pipeline.export.canonical_output import (
    validate_canonical_output_destination,
    write_canonical_output,
)

_ERROR = "Journal output could not be saved safely outside protected paths."


def validate_journal_destination(config: Config, path: Path) -> Path:
    """Resolve a protected-path-checked destination without filesystem writes."""
    try:
        if path.expanduser().is_symlink():
            raise ValueError(_ERROR)
        target = validate_canonical_output_destination(config, path)
        if target.exists() and not target.is_file():
            raise ValueError(_ERROR)
        return target
    except (OSError, ValueError, RuntimeError):
        raise ValueError(_ERROR) from None


def write_journal_entry(config: Config, path: Path, content: str) -> None:
    """Publish a private new note atomically; never replace an existing entry."""
    try:
        target = validate_journal_destination(config, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target = validate_journal_destination(config, path)
        _publish(config, target, content.encode("utf-8"))
    except (OSError, ValueError, RuntimeError):
        raise ValueError(_ERROR) from None


def _publish(config: Config, target: Path, content: bytes) -> None:
    descriptor, name = tempfile.mkstemp(prefix=".journal-", suffix=".tmp", dir=target.parent)
    staging = Path(name)
    identity = os.fstat(descriptor)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        checked = validate_journal_destination(config, target)
        if checked != target:
            raise ValueError(_ERROR)
        current = staging.lstat()
        if (current.st_dev, current.st_ino) != (identity.st_dev, identity.st_ino):
            raise ValueError(_ERROR)
        os.link(staging, target, follow_symlinks=False)
    finally:
        try:
            current = staging.lstat()
            if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
                staging.unlink()
        except FileNotFoundError:
            pass


def write_journal_gitignore(config: Config, path: Path, content: str) -> None:
    """Replace an ignore file safely without modifying a linked canonical source."""
    try:
        target = validate_journal_destination(config, path)
        write_canonical_output(config, target, content.encode("utf-8"))
    except (OSError, ValueError, RuntimeError):
        raise ValueError(_ERROR) from None
