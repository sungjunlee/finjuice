"""Import history CSV path and lookup helpers.

Owns history file path construction, file_id lookup, and listing of recorded
imports. Import recording, file_id generation, and source archiving stay in
:mod:`finjuice.pipeline.metadata.import_history`, which re-exports these
names so existing callers can keep importing from that module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl


def get_metadata_path(metadata_dir: Path) -> Path:
    """
    Get path to import history CSV.

    Args:
        metadata_dir: Base directory for metadata (e.g., data/metadata/)

    Returns:
        Path to import_history.csv

    Example:
        >>> metadata_dir = Path("data/metadata")
        >>> path = get_metadata_path(metadata_dir)
        >>> print(path)
        data/metadata/import_history.csv
    """
    return metadata_dir / "import_history.csv"


def get_source_file_info(metadata_dir: Path, file_id: str) -> dict[str, Any] | None:
    """
    Lookup import history by file_id.

    Args:
        metadata_dir: Directory for metadata
        file_id: file_id to lookup (e.g., "241027_1")

    Returns:
        dict with import metadata, or None if not found

    Example:
        >>> metadata_dir = Path("data/metadata")
        >>> info = get_source_file_info(metadata_dir, "241027_1")
        >>> print(info["original_filename"])
        2024-10-27~2025-10-27.xlsx
        >>> print(info["archived"])
        yes
    """
    metadata_path = get_metadata_path(metadata_dir)

    if not metadata_path.exists():
        return None

    df = pl.read_csv(metadata_path, schema_overrides={"file_id": pl.Utf8})

    # Find matching file_id
    matching = df.filter(pl.col("file_id") == file_id)

    if matching.is_empty():
        return None

    # Return as dict
    return matching.row(0, named=True)


def list_source_files(metadata_dir: Path) -> pl.DataFrame:
    """
    List all import history records.

    Args:
        metadata_dir: Directory for metadata

    Returns:
        Polars DataFrame with all import history (empty if no imports yet)

    Example:
        >>> metadata_dir = Path("data/metadata")
        >>> df = list_source_files(metadata_dir)
        >>> print(df.select(["file_id", "original_filename", "archived"]))
        file_id  original_filename                archived
        241027_1 2024-10-27~2025-10-27.xlsx      yes
        241127_1 nov_export.xlsx                 no
    """
    metadata_path = get_metadata_path(metadata_dir)

    if not metadata_path.exists():
        # Return empty DataFrame with schema
        return pl.DataFrame(
            schema={
                "file_id": pl.Utf8,
                "original_filename": pl.Utf8,
                "imported_from": pl.Utf8,
                "archived": pl.Utf8,
                "archived_path": pl.Utf8,
                "imported_at": pl.Utf8,
                "source_rows": pl.Utf8,
            }
        )

    return pl.read_csv(metadata_path, schema_overrides={"file_id": pl.Utf8})
