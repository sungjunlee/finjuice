"""DuckDB SQL/path boundary helpers.

Owns identifier quoting, string-literal quoting, and partition-root path
containment. Public SQL helper names stay in
:mod:`finjuice.pipeline.sql_utils`, which re-exports the public names used by
existing callers.
"""

from __future__ import annotations

import re
from pathlib import Path

_WINDOWS_ABSOLUTE_PATH_PATTERN = re.compile(r"^[a-zA-Z]:[\\/]")
_DOUBLE_QUOTE = '"'
_SINGLE_QUOTE = "'"


def quote_duckdb_identifier(identifier: str) -> str:
    """Return a double-quoted DuckDB identifier."""
    if identifier == "":
        raise ValueError("DuckDB identifier must not be empty.")
    escaped = identifier.replace(_DOUBLE_QUOTE, _DOUBLE_QUOTE * 2)
    return f"{_DOUBLE_QUOTE}{escaped}{_DOUBLE_QUOTE}"


def quote_duckdb_string_literal(value: object) -> str:
    """Return a single-quoted DuckDB string literal."""
    escaped = str(value).replace(_SINGLE_QUOTE, _SINGLE_QUOTE * 2)
    return f"{_SINGLE_QUOTE}{escaped}{_SINGLE_QUOTE}"


def resolve_duckdb_path_pattern(root: Path, pattern: str | Path = "*/*/*.csv") -> Path:
    """Resolve a DuckDB file/glob pattern under a trusted local root.

    DuckDB table functions can read local paths and external-looking URI strings. For
    user-controlled patterns, keep the pattern relative to the configured partition
    root and reject absolute paths, parent traversal, and Windows-style separators.
    Glob metacharacters are preserved as literal pattern text for DuckDB.
    """
    pattern_text = str(pattern)
    if not pattern_text or pattern_text.strip() == "":
        raise ValueError("DuckDB path pattern must not be empty.")
    if "\x00" in pattern_text:
        raise ValueError("DuckDB path pattern must not contain NUL bytes.")
    if "\\" in pattern_text:
        raise ValueError("DuckDB path pattern must use POSIX separators under the root.")
    if Path(pattern_text).is_absolute() or _WINDOWS_ABSOLUTE_PATH_PATTERN.match(pattern_text):
        raise ValueError("DuckDB path pattern must be relative to the partition root.")

    pattern_path = Path(pattern_text)
    if any(part == ".." for part in pattern_path.parts):
        raise ValueError("DuckDB path pattern must not traverse outside the partition root.")

    resolved_root = root.expanduser().resolve(strict=False)
    contained_path = resolved_root / pattern_path
    try:
        contained_path.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("DuckDB path pattern must stay under the partition root.") from exc
    return contained_path


def quote_duckdb_path_pattern(root: Path, pattern: str | Path = "*/*/*.csv") -> str:
    """Return a quoted DuckDB file/glob literal contained under ``root``."""
    return quote_duckdb_string_literal(resolve_duckdb_path_pattern(root, pattern))
