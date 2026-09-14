"""Deterministic derived CSV/report projections for one repository revision.

Compatibility CSV is a read artifact. Editing it cannot update SQLite.
Comparing a derived manifest to the active snapshot reports ``fresh``,
``stale``, ``foreign_generation``, or ``invalid``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import polars as pl

from finjuice.pipeline.query.snapshot import QuerySnapshot
from finjuice.pipeline.storage.csv_schema import CSV_COLUMNS
from finjuice.pipeline.storage.csv_transactions_serialize import (
    _cast_int_flag_columns,
    _serialize_tag_columns,
)
from finjuice.pipeline.storage.sqlite.paths import GenerationPaths

DerivedFreshness = Literal["fresh", "stale", "foreign_generation", "invalid"]

MANIFEST_NAME = "manifest.json"
TRANSACTIONS_CSV = "transactions.csv"
CATEGORY_REPORT_CSV = "category_report.csv"
DERIVED_FORMAT = "finjuice.derived-csv.v1"


@dataclass(frozen=True)
class DerivedBundle:
    """Paths written for one revision-pinned derived projection."""

    directory: Path
    manifest_path: Path
    transactions_csv: Path
    category_report_csv: Path


def write_derived_outputs(
    snapshot: QuerySnapshot,
    dest: Path | None = None,
) -> DerivedBundle:
    """Write canonical CSV and a category report for one snapshot revision.

    Args:
        snapshot: Revision-pinned query snapshot.
        dest: Output directory. Defaults to ``derived/<generation>/<revision>/``
            under the generation root.

    Returns:
        Paths to the written directory, manifest, and CSV files.
    """
    directory = dest if dest is not None else _default_derived_dir(snapshot)
    directory.mkdir(parents=True, exist_ok=True)
    transactions_csv = directory / TRANSACTIONS_CSV
    category_report_csv = directory / CATEGORY_REPORT_CSV
    report_frame = _category_report_frame(snapshot.frame)
    _write_csv(transactions_csv, _compatibility_csv_frame(snapshot.frame))
    _write_csv(category_report_csv, report_frame)
    manifest = {
        "format": DERIVED_FORMAT,
        "dataset_generation": snapshot.dataset_generation,
        "dataset_revision": snapshot.dataset_revision,
        "schema_version": snapshot.schema_version,
        "calculation_policy": snapshot.calculation_policy,
        "as_of": snapshot.as_of,
        "files": {
            TRANSACTIONS_CSV: _file_record(transactions_csv, snapshot.frame.height),
            CATEGORY_REPORT_CSV: _file_record(category_report_csv, report_frame.height),
        },
    }
    manifest_path = directory / MANIFEST_NAME
    _write_json(manifest_path, manifest)
    return DerivedBundle(
        directory=directory,
        manifest_path=manifest_path,
        transactions_csv=transactions_csv,
        category_report_csv=category_report_csv,
    )


def classify_derived(directory: Path, snapshot: QuerySnapshot) -> DerivedFreshness:
    """Compare a derived directory to the active snapshot revision.

    Args:
        directory: Directory that should contain ``manifest.json`` and CSVs.
        snapshot: Currently selected authoritative snapshot.

    Returns:
        ``fresh`` when identity and required file digests match; ``stale`` when
        the same generation has a different revision or a file digest mismatch;
        ``foreign_generation`` when the generation differs; ``invalid`` when
        the manifest is missing, unreadable, or omits required derived files.
    """
    payload = _load_manifest(directory / MANIFEST_NAME)
    generation = payload.get("dataset_generation") if payload else None
    revision = payload.get("dataset_revision") if payload else None
    files = payload.get("files") if payload else None
    if (
        payload is None
        or not isinstance(generation, str)
        or not isinstance(revision, int)
        or not isinstance(files, dict)
        or any(name not in files for name in (TRANSACTIONS_CSV, CATEGORY_REPORT_CSV))
    ):
        return "invalid"
    if generation != snapshot.dataset_generation:
        return "foreign_generation"
    if revision != snapshot.dataset_revision or _digests_mismatch(directory, files):
        return "stale"
    return "fresh"


def _default_derived_dir(snapshot: QuerySnapshot) -> Path:
    """Return the generation-owned derived path for this revision."""
    paths = GenerationPaths(snapshot.database.parent)
    return paths.derived_revision(snapshot.dataset_generation, snapshot.dataset_revision)


def _compatibility_csv_frame(frame: pl.DataFrame) -> pl.DataFrame:
    """Serialize the CSV-contract frame for a deterministic UTF-8 write."""
    ordered = frame.select(list(CSV_COLUMNS))
    return _serialize_tag_columns(_cast_int_flag_columns(ordered))


def _category_report_frame(frame: pl.DataFrame) -> pl.DataFrame:
    """Build a stable category aggregate report for one revision."""
    if frame.is_empty():
        return pl.DataFrame(schema={"category_final": pl.Utf8, "n": pl.UInt32, "total": pl.Float64})
    return (
        frame.group_by("category_final")
        .agg(pl.len().alias("n"), pl.col("amount").sum().alias("total"))
        .sort("category_final")
    )


def _write_csv(path: Path, frame: pl.DataFrame) -> None:
    """Atomically write one UTF-8 CSV with stable quoting and newlines."""
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    frame.write_csv(
        tmp_path,
        include_header=True,
        separator=",",
        quote_style="necessary",
        line_terminator="\n",
    )
    tmp_path.replace(path)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Atomically write canonical JSON (sorted keys, no generation timestamp)."""
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    tmp_path.write_text(encoded, encoding="utf-8")
    tmp_path.replace(path)


def _file_record(path: Path, row_count: int) -> dict[str, int | str]:
    """Return digest metadata for one derived file."""
    data = path.read_bytes()
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "byte_count": len(data),
        "row_count": row_count,
    }


def _load_manifest(path: Path) -> dict[str, Any] | None:
    """Return a parsed manifest object, or ``None`` when it is unusable."""
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _digests_mismatch(directory: Path, files: dict[str, Any]) -> bool:
    """Return True when a declared file is missing or its digest differs."""
    for name, record in files.items():
        if not isinstance(name, str) or not isinstance(record, dict):
            return True
        expected = record.get("sha256")
        path = directory / name
        if not isinstance(expected, str) or not path.is_file():
            return True
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            return True
    return False


__all__ = [
    "CATEGORY_REPORT_CSV",
    "DERIVED_FORMAT",
    "DerivedBundle",
    "DerivedFreshness",
    "MANIFEST_NAME",
    "TRANSACTIONS_CSV",
    "classify_derived",
    "write_derived_outputs",
]
