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
        file_path=Path("~/Downloads/banksalad.xlsx"),
        file_mtime="2025-11-01T16:05:51",
        source_rows=597,
        archived=False,
        authority_data_dir=Path("data"),
    )

    # Record import WITH archiving
    archive_path = archive_source_file(
        file_path=Path("~/Downloads/banksalad.xlsx"),
        file_id="241027_1",
        authority_data_dir=Path("data"),
    )
    file_id = record_import(
        file_path=Path("~/Downloads/banksalad.xlsx"),
        file_mtime="2025-11-01T16:05:51",
        source_rows=597,
        archived=True,
        archived_path=archive_path,
        authority_data_dir=Path("data"),
    )
"""

import hashlib
import os
import re
import stat
from datetime import datetime
from pathlib import Path

import polars as pl

from finjuice.pipeline.constants import FILE_ID_LENGTH_CHARS
from finjuice.pipeline.metadata.import_history_helpers import (
    get_metadata_path,
    get_source_file_info,  # noqa: F401 — re-exported for existing import_history imports
    list_source_files,  # noqa: F401 — re-exported for existing import_history imports
    list_unprocessed_xlsx,  # noqa: F401 — re-exported for existing import_history imports
    processed_original_filenames,  # noqa: F401 — re-exported for existing import_history imports
)
from finjuice.pipeline.storage.atomic_files import (
    OwnedTempMetadata,
)
from finjuice.pipeline.storage.atomic_files import (
    replace_with_owned_temp as _replace_with_owned_temp,
)
from finjuice.pipeline.storage.authority import legacy_write_lease
from finjuice.pipeline.storage.sqlite.objects import _assert_no_symlink_ancestors

_WINDOWS_RESERVED_DEVICES = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    | {f"COM{suffix}" for suffix in "0123456789\xb9\xb2\xb3"}
    | {f"LPT{suffix}" for suffix in "0123456789\xb9\xb2\xb3"}
)
_IMPORT_HISTORY_SCHEMA = {
    "file_id": pl.Utf8,
    "original_filename": pl.Utf8,
    "imported_from": pl.Utf8,
    "archived": pl.Utf8,
    "archived_path": pl.Utf8,
    "imported_at": pl.Utf8,
    "source_rows": pl.Utf8,
}


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


def archive_source_file(
    file_path: Path,
    file_id: str,
    *,
    authority_data_dir: Path,
) -> Path:
    """
    Copy source XLSX file to archives directory for reproducibility.

    Args:
        file_path: Path to source XLSX file
        file_id: file_id to use for archived filename
        authority_data_dir: Explicit data-root authority

    Returns:
        Path: Path to archived file

    Raises:
        FileNotFoundError: If source file doesn't exist
        ValueError: If file_id is not a single filename component
        OSError: If copy operation fails

    Example:
        >>> file_path = Path("~/Downloads/2024-10-27~2025-10-27.xlsx")
        >>> file_id = "241027_1"
        >>> archived_path = archive_source_file(
        ...     file_path, file_id, authority_data_dir=Path("data")
        ... )
        >>> print(archived_path)
        data/metadata/archives/241027_1.xlsx
    """
    archive_name = _archive_filename(file_id)
    archive_dir, authority_data_dir = _authority_archive_root(authority_data_dir)
    with legacy_write_lease(authority_data_dir):
        return _archive_source_file_unleased(file_path, archive_dir, archive_name)


def record_import(
    file_path: Path,
    file_mtime: str,
    source_rows: int,
    archived: bool = False,
    archived_path: Path | None = None,
    *,
    authority_data_dir: Path,
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
        file_path: Path to source XLSX file
        file_mtime: File modification time (ISO8601 format)
        source_rows: Number of transaction rows imported
        archived: Whether file was archived (default: False)
        archived_path: Path to archived file (required if archived=True)
        authority_data_dir: Explicit data-root authority

    Returns:
        str: file_id (8 chars, e.g., "241027_1")

    Example:
        >>> file_path = Path("data/imports/2024-10-27~2025-10-27.xlsx")
        >>> file_mtime = "2025-11-01T16:05:51"
        >>> file_id = record_import(
        ...     file_path, file_mtime, 597, archived=False, authority_data_dir=Path("data")
        ... )
        >>> print(file_id)
        241027_1
    """
    _ = file_mtime
    metadata_path, authority_data_dir = _authority_import_history_path(authority_data_dir)
    with legacy_write_lease(authority_data_dir):
        return _record_import_unleased(
            metadata_path, file_path, source_rows, archived, archived_path
        )


def _record_import_unleased(
    metadata_path: Path,
    file_path: Path,
    source_rows: int,
    archived: bool,
    archived_path: Path | None,
) -> str:
    """Mutate import history while the caller holds the legacy authority lease."""
    _assert_no_symlink_ancestors(metadata_path, allow_missing=True)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    df, existing_ids = _load_import_history(metadata_path)
    existing = df.filter(pl.col("imported_from") == str(file_path))
    if not existing.is_empty():
        df = _updated_import_history(df, file_path, source_rows, archived, archived_path)
        _write_import_history(metadata_path, df)
        return str(existing["file_id"][0])
    file_id = generate_file_id(file_path, existing_ids)
    df = pl.concat([df, _new_import_row(file_id, file_path, source_rows, archived, archived_path)])
    _write_import_history(metadata_path, df)
    return file_id


def _archive_source_file_unleased(file_path: Path, archive_dir: Path, archive_name: str) -> Path:
    """Copy exact source bytes into the canonical archive while the lease is held."""
    if not file_path.exists():
        raise FileNotFoundError(f"Source file not found: {file_path}")
    archived_path = archive_dir / archive_name
    _assert_no_symlink_ancestors(archived_path, allow_missing=True)
    archive_dir.mkdir(parents=True, exist_ok=True)
    payload, metadata = _capture_regular_source(file_path)
    _replace_with_owned_temp(archived_path, payload, metadata=metadata)
    return archived_path


def _load_import_history(metadata_path: Path) -> tuple[pl.DataFrame, set[str]]:
    """Load existing import history or an empty frame with the canonical schema."""
    if not metadata_path.exists():
        return pl.DataFrame(schema=_IMPORT_HISTORY_SCHEMA), set()
    df = pl.read_csv(metadata_path, schema=_IMPORT_HISTORY_SCHEMA)
    return df, set(df["file_id"].to_list())


def _updated_import_history(
    df: pl.DataFrame,
    file_path: Path,
    source_rows: int,
    archived: bool,
    archived_path: Path | None,
) -> pl.DataFrame:
    """Refresh timestamp/row-count and optional archive fields for a known source."""
    imported_from = str(file_path)
    df = _refresh_import_counts(df, imported_from, source_rows)
    if not archived:
        return df
    return _refresh_archive_fields(df, imported_from, archived_path)


def _refresh_import_counts(df: pl.DataFrame, imported_from: str, source_rows: int) -> pl.DataFrame:
    """Update imported_at and source_rows for the matching source path."""
    return df.with_columns(
        [
            pl.when(pl.col("imported_from") == imported_from)
            .then(pl.lit(datetime.now().isoformat()))
            .otherwise(pl.col("imported_at"))
            .alias("imported_at"),
            pl.when(pl.col("imported_from") == imported_from)
            .then(pl.lit(str(source_rows)))
            .otherwise(pl.col("source_rows"))
            .alias("source_rows"),
        ]
    )


def _refresh_archive_fields(
    df: pl.DataFrame, imported_from: str, archived_path: Path | None
) -> pl.DataFrame:
    """Mark a matching source as archived with the recorded archive path."""
    return df.with_columns(
        [
            pl.when(pl.col("imported_from") == imported_from)
            .then(pl.lit("yes"))
            .otherwise(pl.col("archived"))
            .alias("archived"),
            pl.when(pl.col("imported_from") == imported_from)
            .then(pl.lit(str(archived_path) if archived_path else ""))
            .otherwise(pl.col("archived_path"))
            .alias("archived_path"),
        ]
    )


def _new_import_row(
    file_id: str,
    file_path: Path,
    source_rows: int,
    archived: bool,
    archived_path: Path | None,
) -> pl.DataFrame:
    """Build one import-history row using the canonical 7-column schema."""
    return pl.DataFrame(
        {
            "file_id": [file_id],
            "original_filename": [file_path.name],
            "imported_from": [str(file_path)],
            "archived": ["yes" if archived else "no"],
            "archived_path": [str(archived_path) if archived_path else ""],
            "imported_at": [datetime.now().isoformat()],
            "source_rows": [str(source_rows)],
        }
    )


def _write_import_history(metadata_path: Path, df: pl.DataFrame) -> None:
    """Serialize import history before mutating the canonical CSV."""
    csv_text = df.write_csv()
    _replace_with_owned_temp(metadata_path, csv_text.encode("utf-8"))


def _archive_filename(file_id: str) -> str:
    """Reject traversal or absolute file_id values before joining archive paths."""
    if _unsafe_archive_file_id(file_id):
        raise ValueError("Archive file_id must be a single filename component.")
    return f"{file_id}.xlsx"


def _unsafe_archive_file_id(file_id: str) -> bool:
    """Return whether file_id is not a portable single path component."""
    if not file_id or file_id in {".", ".."}:
        return True
    if "\x00" in file_id or ":" in file_id or "/" in file_id or "\\" in file_id:
        return True
    if Path(file_id).name != file_id or file_id != file_id.rstrip(" ."):
        return True
    return file_id.split(".")[0].upper() in _WINDOWS_RESERVED_DEVICES


def _capture_regular_source(path: Path) -> tuple[bytes, OwnedTempMetadata]:
    """Read one regular file's bytes and timestamps from the same descriptor."""
    descriptor = _open_source_descriptor(path)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise OSError("Source file is not a regular file.")
        metadata = _owned_metadata_from_stat(info)
        return _read_all_from_fd(descriptor), metadata
    finally:
        os.close(descriptor)


def _open_source_descriptor(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    noatime = getattr(os, "O_NOATIME", 0)
    try:
        return os.open(path, flags | noatime)
    except OSError:
        if noatime == 0:
            raise
        return os.open(path, flags)


def _owned_metadata_from_stat(info: os.stat_result) -> OwnedTempMetadata:
    atime_ns = int(getattr(info, "st_atime_ns", info.st_atime * 1_000_000_000))
    mtime_ns = int(getattr(info, "st_mtime_ns", info.st_mtime * 1_000_000_000))
    return OwnedTempMetadata(atime_ns=atime_ns, mtime_ns=mtime_ns, mode=stat.S_IMODE(info.st_mode))


def _read_all_from_fd(descriptor: int) -> bytes:
    chunks = bytearray()
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            return bytes(chunks)
        chunks.extend(chunk)


def _authority_archive_root(authority_data_dir: Path) -> tuple[Path, Path]:
    """Return the only archive root allowed beneath an explicit data authority."""
    normalized_data_dir = authority_data_dir.expanduser().absolute()
    archive_dir = normalized_data_dir / "metadata" / "archives"
    _assert_no_symlink_ancestors(archive_dir, allow_missing=True)
    return archive_dir, normalized_data_dir


def _authority_import_history_path(authority_data_dir: Path) -> tuple[Path, Path]:
    """Return the only import-history path allowed beneath an explicit data authority."""
    normalized_data_dir = authority_data_dir.expanduser().absolute()
    metadata_path = get_metadata_path(normalized_data_dir / "metadata")
    _assert_no_symlink_ancestors(metadata_path, allow_missing=True)
    return metadata_path, normalized_data_dir
