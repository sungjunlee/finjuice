"""Header-matching helpers for schema detection.

Owns CSV header reading and matching against schema definitions, including
additive read-compatibility matching and legacy-version inference. Detection,
summaries, and the public API stay in
:mod:`finjuice.pipeline.storage.schema_detect`, which re-exports these
helpers so existing callers can keep importing from that module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _read_csv_header(csv_path: Path) -> tuple[str, ...]:
    """Read only the header row from a CSV partition."""
    import csv

    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    with open(csv_path, encoding="utf-8") as f:
        reader = csv.reader(f)
        try:
            return tuple(next(reader))
        except StopIteration:
            raise ValueError(f"Empty CSV file: {csv_path}") from None


def _schema_columns(schema_def: dict[str, Any]) -> tuple[str, ...]:
    """Return ordered partition column names for one schema definition."""
    return tuple(col["name"] for col in schema_def["partition_schema"]["columns"])


def _header_matches_schema(header: tuple[str, ...], schema_def: dict[str, Any]) -> bool:
    """Return whether a CSV header matches a schema, including additive read compatibility."""
    expected_columns = _schema_columns(schema_def)
    if header == expected_columns:
        return True

    optional_missing = set(schema_def.get("read_compatible_missing_columns", []))
    if not optional_missing:
        return False

    if len(header) >= len(expected_columns):
        return False

    header_index = 0
    for expected_column in expected_columns:
        if header_index < len(header) and header[header_index] == expected_column:
            header_index += 1
            continue
        if expected_column in optional_missing:
            continue
        return False

    return header_index == len(header)


def _missing_read_compatible_columns(
    header: tuple[str, ...],
    schema_def: dict[str, Any],
) -> set[str] | None:
    """Return additive columns missing from a readable legacy header, if compatible."""
    expected_columns = _schema_columns(schema_def)
    if header == expected_columns:
        return set()

    optional_missing = set(schema_def.get("read_compatible_missing_columns", []))
    if not optional_missing or len(header) >= len(expected_columns):
        return None

    missing_columns: set[str] = set()
    header_index = 0
    for expected_column in expected_columns:
        if header_index < len(header) and header[header_index] == expected_column:
            header_index += 1
            continue
        if expected_column in optional_missing:
            missing_columns.add(expected_column)
            continue
        return None

    if header_index != len(header):
        return None
    return missing_columns


def _infer_read_compatible_legacy_version(
    *,
    current_version: int,
    missing_columns: set[str],
) -> int:
    """Infer the legacy version represented by an active schema with additive gaps."""
    if missing_columns == {"notes_manual"} and current_version >= 4:
        return 3
    if {"category_rule", "category_final"}.issubset(missing_columns):
        return 2
    return current_version
