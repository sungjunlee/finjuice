"""
Import history tracking for source XLSX files.

Provides centralized logging of all ingestion events with optional archiving
for reproducibility. Uses compact file_id system to reduce token consumption
in CSV partitions.

History CSV path construction and lookup/list helpers live in
:mod:`finjuice.pipeline.metadata.import_history_helpers` and are re-exported
here so existing callers can keep importing from this module.

Design Philosophy (Issue #62):
    - **Default**: Simple history logging (no file copying)
    - **Optional**: --archive flag copies XLSX to metadata/archives/ for reproducibility
    - **Honest**: archived column clearly shows preservation status

Directory structure:
    data/metadata/import_history.csv   # Central import log
    data/metadata/archives/            # Optional: archived XLSX files (gitignored)

CSV Schema (7 columns):
    file_id,original_filename,imported_from,archived,archived_path,imported_at,source_rows
    241027_1,2024-10-27~2025-10-27.xlsx,/path/to/file.xlsx,yes,metadata/archives/241027_1.xlsx,2025-11-02T10:30:15,597
    241127_1,nov_export.xlsx,~/Downloads/nov.xlsx,no,,2025-11-28T14:22:03,423

Example usage:
    # Record import without archiving
    file_id = record_import(
        metadata_dir=Path("data/metadata"),
        file_path=Path("~/Downloads/banksalad.xlsx"),
        file_mtime="2025-11-01T16:05:51",
        source_rows=597,
        archived=False
    )

    # Record import WITH archiving
    archive_path = archive_source_file(
        file_path=Path("~/Downloads/banksalad.xlsx"),
        archive_dir=Path("data/metadata/archives"),
        file_id="241027_1"
    )
    file_id = record_import(
        metadata_dir=Path("data/metadata"),
        file_path=Path("~/Downloads/banksalad.xlsx"),
        file_mtime="2025-11-01T16:05:51",
        source_rows=597,
        archived=True,
        archived_path=archive_path
    )
"""

import hashlib
import re
import shutil
from datetime import datetime
from pathlib import Path

import polars as pl

from finjuice.pipeline.constants import FILE_ID_LENGTH_CHARS
from finjuice.pipeline.metadata.import_history_helpers import (
    get_metadata_path,
    get_source_file_info,  # noqa: F401 — re-exported for existing import_history imports
    list_source_files,  # noqa: F401 — re-exported for existing import_history imports
)


def generate_file_id(file_path: Path, existing_ids: set[str]) -> str:
    """
    Generate short, human-readable file ID from source file path.

    Format: YYMMDD_N (FILE_ID_LENGTH_CHARS chars for standard dates)
    Examples:
        - "2024-10-27~2025-10-27.xlsx" → "241027_1"
        - "2024-10-27~2024-11-27.xlsx" (2nd file same day) → "241027_2"
        - "banksalad_export.xlsx" (non-standard) → "a3f2b1c4" (FILE_ID_LENGTH_CHARS-char hash)

    See: finjuice.pipeline.constants.FILE_ID_LENGTH_CHARS

    Args:
        file_path: Path to source XLSX file
        existing_ids: Set of already-assigned file_ids (for collision avoidance)

    Returns:
        str: Unique file_id

    Example:
        >>> file_path = Path("data/imports/2024-10-27~2025-10-27.xlsx")
        >>> file_id = generate_file_id(file_path, set())
        >>> print(file_id)
        241027_1
    """
    filename = file_path.stem  # Without extension

    # Try to extract date from standard Banksalad filename pattern: YYYY-MM-DD~YYYY-MM-DD
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", filename)

    if match:
        # Extract date components: YYYY-MM-DD → YYMMDD
        year, month, day = match.groups()
        yy = year[2:]  # Last 2 digits of year
        prefix = f"{yy}{month}{day}_"

        # Find next available sequence number
        seq = 1
        while f"{prefix}{seq}" in existing_ids:
            seq += 1

        return f"{prefix}{seq}"

    # Fallback: Use short hash for non-standard filenames
    file_hash = hashlib.sha256(str(file_path).encode("utf-8")).hexdigest()
    return file_hash[:FILE_ID_LENGTH_CHARS]


def archive_source_file(file_path: Path, archive_dir: Path, file_id: str) -> Path:
    """
    Copy source XLSX file to archives directory for reproducibility.

    Args:
        file_path: Path to source XLSX file
        archive_dir: Directory for archived files (e.g., data/metadata/archives/)
        file_id: file_id to use for archived filename

    Returns:
        Path: Path to archived file (relative or absolute)

    Raises:
        FileNotFoundError: If source file doesn't exist
        OSError: If copy operation fails

    Example:
        >>> file_path = Path("~/Downloads/2024-10-27~2025-10-27.xlsx")
        >>> archive_dir = Path("data/metadata/archives")
        >>> file_id = "241027_1"
        >>> archived_path = archive_source_file(file_path, archive_dir, file_id)
        >>> print(archived_path)
        data/metadata/archives/241027_1.xlsx
    """
    if not file_path.exists():
        raise FileNotFoundError(f"Source file not found: {file_path}")

    # Ensure archive directory exists
    archive_dir.mkdir(parents=True, exist_ok=True)

    # Construct archived filename: {file_id}.xlsx
    archived_path = archive_dir / f"{file_id}.xlsx"

    # Copy file to archive
    shutil.copy2(file_path, archived_path)

    return archived_path


def record_import(
    metadata_dir: Path,
    file_path: Path,
    file_mtime: str,
    source_rows: int,
    archived: bool = False,
    archived_path: Path | None = None,
) -> str:
    """
    Record an import event and return its file_id.

    If file is already registered (by imported_from path), returns existing file_id
    and updates the import history.

    New schema (7 columns):
        - file_id: 8-char identifier (e.g., "241027_1")
        - original_filename: basename of source file
        - imported_from: full path to source file at time of import
        - archived: "yes" if file was copied to archives/, "no" otherwise
        - archived_path: path to archived file (empty if not archived)
        - imported_at: ISO8601 timestamp of import
        - source_rows: number of rows imported from this file

    Args:
        metadata_dir: Directory for metadata (e.g., data/metadata/)
        file_path: Path to source XLSX file
        file_mtime: File modification time (ISO8601 format)
        source_rows: Number of transaction rows imported
        archived: Whether file was archived (default: False)
        archived_path: Path to archived file (required if archived=True)

    Returns:
        str: file_id (8 chars, e.g., "241027_1")

    Example:
        >>> metadata_dir = Path("data/metadata")
        >>> file_path = Path("data/imports/2024-10-27~2025-10-27.xlsx")
        >>> file_mtime = "2025-11-01T16:05:51"
        >>> file_id = record_import(metadata_dir, file_path, file_mtime, 597, archived=False)
        >>> print(file_id)
        241027_1
    """
    # Ensure metadata directory exists
    metadata_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = get_metadata_path(metadata_dir)

    # Define schema for import history
    schema = {
        "file_id": pl.Utf8,
        "original_filename": pl.Utf8,
        "imported_from": pl.Utf8,
        "archived": pl.Utf8,
        "archived_path": pl.Utf8,
        "imported_at": pl.Utf8,
        "source_rows": pl.Utf8,
    }

    # Load existing metadata if available
    if metadata_path.exists():
        df = pl.read_csv(metadata_path, schema=schema)

        # Check if file already registered (by imported_from path)
        existing = df.filter(pl.col("imported_from") == str(file_path))
        if not existing.is_empty():
            # Return existing file_id (don't create duplicate)
            file_id: str = str(existing["file_id"][0])

            # Update import timestamp and metadata
            df = df.with_columns(
                [
                    pl.when(pl.col("imported_from") == str(file_path))
                    .then(pl.lit(datetime.now().isoformat()))
                    .otherwise(pl.col("imported_at"))
                    .alias("imported_at"),
                    pl.when(pl.col("imported_from") == str(file_path))
                    .then(pl.lit(str(source_rows)))
                    .otherwise(pl.col("source_rows"))
                    .alias("source_rows"),
                ]
            )

            # Update archive status if changed
            if archived:
                df = df.with_columns(
                    [
                        pl.when(pl.col("imported_from") == str(file_path))
                        .then(pl.lit("yes"))
                        .otherwise(pl.col("archived"))
                        .alias("archived"),
                        pl.when(pl.col("imported_from") == str(file_path))
                        .then(pl.lit(str(archived_path) if archived_path else ""))
                        .otherwise(pl.col("archived_path"))
                        .alias("archived_path"),
                    ]
                )

            # Write updated metadata atomically
            tmp_path = metadata_path.with_suffix(".tmp")
            df.write_csv(tmp_path)
            tmp_path.replace(metadata_path)

            return file_id

        # Get existing file_ids for collision avoidance
        existing_ids = set(df["file_id"].to_list())
    else:
        # Create new empty DataFrame with schema
        df = pl.DataFrame(schema=schema)
        existing_ids = set()

    # Generate new file_id
    file_id = generate_file_id(file_path, existing_ids)

    # Append new import record
    new_row = pl.DataFrame(
        {
            "file_id": [file_id],
            "original_filename": [file_path.name],  # Basename only
            "imported_from": [str(file_path)],  # Full path at import time
            "archived": ["yes" if archived else "no"],
            "archived_path": [str(archived_path) if archived_path else ""],
            "imported_at": [datetime.now().isoformat()],
            "source_rows": [str(source_rows)],
        }
    )

    df = pl.concat([df, new_row])

    # Write atomically (temp file + rename)
    tmp_path = metadata_path.with_suffix(".tmp")
    df.write_csv(tmp_path)
    tmp_path.replace(metadata_path)

    return file_id
