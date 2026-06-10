"""
SQL security utilities for banksalad-tools.

Provides column/identifier whitelist validation to prevent SQL injection attacks.
All dynamic SQL identifiers (column names, order by clauses) should be validated
through this module before use.

Security issue: #31
Fixed: Issue #82 - Use schema_registry instead of hardcoded path
"""

import logging
import re
from importlib import resources
from pathlib import Path
from typing import Any, FrozenSet, cast

import yaml

from finjuice.pipeline.storage.schema_registry import load_schema_registry

logger = logging.getLogger(__name__)


_FALLBACK_V3_COLUMNS: FrozenSet[str] = frozenset(
    {
        "row_hash",
        "date",
        "time",
        "type_raw",
        "type_norm",
        "major_raw",
        "minor_raw",
        "merchant_raw",
        "memo_raw",
        "amount",
        "account",
        "currency",
        "counterparty",
        "datetime",
        "category_rule",
        "category_final",
        "tags_rule",
        "tags_ai",
        "tags_manual",
        "tags_final",
        "confidence",
        "needs_review",
        "is_transfer_candidate",
        "is_transfer",
        "transfer_group_id",
        "file_id",
        "source_row",
    }
)


def _columns_from_schema(schema: dict[str, Any]) -> FrozenSet[str]:
    current_version = int(schema["current_version"])
    schema_key = f"v{current_version}"
    columns = schema["schemas"][schema_key]["partition_schema"]["columns"]
    return frozenset(str(col["name"]) for col in columns)


def _load_packaged_schema_columns() -> FrozenSet[str] | None:
    """Load schema columns from the installed finjuice package resource."""
    try:
        schema_resource = resources.files("finjuice.templates").joinpath("schema.yaml")
        if not schema_resource.is_file():
            return None

        loaded = yaml.safe_load(schema_resource.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise TypeError("schema.yaml root must be a mapping")

        return _columns_from_schema(cast(dict[str, Any], loaded))
    except (FileNotFoundError, ModuleNotFoundError):
        return None
    except (KeyError, TypeError, ValueError, yaml.YAMLError) as e:
        logger.warning(f"Could not load packaged schema.yaml: {e}.")
        return None


def _load_valid_columns() -> FrozenSet[str]:
    """
    Load valid column names from schema.yaml.

    Returns:
        Frozen set of valid column names from current schema version

    Note:
        Reads existing schema files only (no file writes) to avoid import-time
        side effects on user data directories.
    """
    try:
        template_dir = Path(__file__).resolve().parents[4] / "templates"
        if (template_dir / "schema.yaml").exists():
            schema = load_schema_registry(template_dir)
            return _columns_from_schema(schema)
    except (FileNotFoundError, KeyError, TypeError, ValueError) as e:
        logger.warning(f"Could not load schema.yaml from filesystem: {e}.")

    packaged_columns = _load_packaged_schema_columns()
    if packaged_columns is not None:
        return packaged_columns

    try:
        from finjuice.pipeline.config import Config

        metadata_dir = Config.from_env().data_dir / "metadata"
        if (metadata_dir / "schema.yaml").exists():
            schema = load_schema_registry(metadata_dir)
            return _columns_from_schema(schema)
    except (FileNotFoundError, KeyError, TypeError, ValueError) as e:
        logger.warning(f"Could not load schema.yaml from data metadata: {e}.")

    # Fallback to hardcoded list only if schema.yaml is unavailable everywhere.
    logger.warning("Could not load schema.yaml. Using hardcoded v3 column list.")

    return _FALLBACK_V3_COLUMNS


# Valid columns loaded at module import (immutable)
VALID_COLUMNS: FrozenSet[str] = _load_valid_columns()

# SQL identifier pattern: alphanumeric + underscore only
_SAFE_IDENTIFIER_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
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


def validate_column_name(column: str) -> str:
    """
    Validate that a column name is in the schema whitelist.

    Args:
        column: Column name to validate

    Returns:
        The validated column name (unchanged)

    Raises:
        ValueError: If column name is not in the whitelist

    Example:
        >>> validate_column_name("amount")
        'amount'
        >>> validate_column_name("DROP TABLE--")
        ValueError: Invalid column name: DROP TABLE--
    """
    if column not in VALID_COLUMNS:
        raise ValueError(f"Invalid column name: {column}. Must be one of: {sorted(VALID_COLUMNS)}")
    return column


def validate_columns(columns: list[str]) -> list[str]:
    """
    Validate a list of column names.

    Args:
        columns: List of column names to validate

    Returns:
        List of validated column names

    Raises:
        ValueError: If any column name is not in the whitelist
    """
    return [validate_column_name(col) for col in columns]


def sanitize_order_by(order_by: str) -> str:
    """
    Sanitize ORDER BY clause for SQL queries.

    Validates that the order_by string contains only valid column names
    and direction keywords (ASC, DESC).

    Args:
        order_by: ORDER BY clause (e.g., "datetime DESC", "amount ASC, date DESC")

    Returns:
        The validated ORDER BY clause

    Raises:
        ValueError: If order_by contains invalid characters or column names

    Example:
        >>> sanitize_order_by("datetime DESC")
        'datetime DESC'
        >>> sanitize_order_by("amount; DROP TABLE--")
        ValueError: Invalid characters in order_by clause
    """
    # Check for SQL injection characters
    dangerous_chars = [";", "--", "/*", "*/", "'", '"', "\\"]
    for char in dangerous_chars:
        if char in order_by:
            raise ValueError(
                f"Invalid characters in order_by clause: {order_by}. "
                f"Found dangerous character: {char!r}"
            )

    # Parse and validate each part
    parts = order_by.split(",")
    validated_parts = []

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Split into column and direction
        tokens = part.split()
        if not tokens:
            continue

        # First token must be a valid column name
        column = tokens[0]
        if not _SAFE_IDENTIFIER_PATTERN.match(column):
            raise ValueError(
                f"Invalid identifier in order_by: {column}. "
                "Must contain only alphanumeric characters and underscores."
            )

        if column.lower() not in {col.lower() for col in VALID_COLUMNS}:
            raise ValueError(
                f"Invalid column name in order_by: {column}. "
                f"Must be one of: {sorted(VALID_COLUMNS)}"
            )

        # Optional direction (ASC/DESC)
        direction = ""
        if len(tokens) > 1:
            direction = tokens[1].upper()
            if direction not in ("ASC", "DESC"):
                raise ValueError(f"Invalid sort direction: {direction}. Must be ASC or DESC.")

        # Rebuild validated part
        if direction:
            validated_parts.append(f"{column} {direction}")
        else:
            validated_parts.append(column)

    if not validated_parts:
        raise ValueError("Empty order_by clause")

    return ", ".join(validated_parts)


def is_safe_identifier(identifier: str) -> bool:
    """
    Check if a string is a safe SQL identifier (alphanumeric + underscore).

    Args:
        identifier: String to check

    Returns:
        True if the identifier is safe for use in SQL

    Example:
        >>> is_safe_identifier("column_name")
        True
        >>> is_safe_identifier("DROP TABLE")
        False
    """
    return bool(_SAFE_IDENTIFIER_PATTERN.match(identifier))
