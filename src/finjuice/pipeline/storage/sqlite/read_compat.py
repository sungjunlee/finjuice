"""CSV-contract-compatible transaction reads from the authoritative SQLite repository.

Provisional read adapter for the SSOT query-compatibility slice (#436). It
projects typed repository rows into the legacy CSV transaction frame contract
(:data:`~finjuice.pipeline.storage.csv_schema.CSV_COLUMNS`) so existing read
commands keep their human and JSON output contracts while reading from SQLite.

The generation root is runtime configuration (``FINJUICE_SQLITE_GENERATION``);
its location is never hard-coded here, per the migration/recovery contract.
Reads are deterministic for one dataset revision: rows are projected from a
validated snapshot and sorted by ``datetime`` with a stable sort.

TODO(#436 follow-up): wire ``query``/``explain`` and the detailed status
insights snapshot to the same SQLite read path.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import polars as pl

from finjuice.pipeline.storage.csv_schema import CSV_COLUMNS, POLARS_SCHEMA
from finjuice.pipeline.storage.csv_transactions_read_normalize import TAG_JSON_COLUMNS
from finjuice.pipeline.storage.sqlite.paths import GenerationPaths
from finjuice.pipeline.storage.sqlite.repository import RepositoryReader
from finjuice.pipeline.tagging.manual import build_manual_tags, split_manual_tags

logger = logging.getLogger(__name__)

GENERATION_ENV_VAR = "FINJUICE_SQLITE_GENERATION"

FALLBACK_CATEGORY = "미분류"


class SqliteReadSourceError(RuntimeError):
    """The configured SQLite read source is missing or unusable."""


def resolve_generation_database() -> Path | None:
    """Return the configured generation database path, or ``None`` in CSV mode.

    Returns:
        Path to the published ``finjuice.sqlite3`` when the environment
        variable ``FINJUICE_SQLITE_GENERATION`` names a generation root,
        otherwise ``None`` so callers keep using CSV partitions.

    Raises:
        SqliteReadSourceError: If the variable is set but the generation
            root holds no published repository database.
    """
    raw = os.getenv(GENERATION_ENV_VAR, "").strip()
    if not raw:
        return None
    database = GenerationPaths(Path(raw)).database
    if not database.is_file():
        raise SqliteReadSourceError(
            f"{GENERATION_ENV_VAR} is set but no published repository database was found."
        )
    return database


def read_transactions_frame(database: Path) -> pl.DataFrame:
    """Project repository transactions into the legacy CSV read frame contract.

    Args:
        database: Path to a published ``finjuice.sqlite3`` repository file.

    Returns:
        DataFrame with :data:`CSV_COLUMNS` in order, JSON tag columns decoded
        to ``List(Utf8)``, sorted ascending by ``datetime`` (stable).
    """
    with RepositoryReader(database) as reader:
        transactions = reader.rows("transactions")
        context = _ReadContext.build(reader)
    rows = [_project_row(transaction, context) for transaction in transactions]
    return _build_frame(rows).sort("datetime")


def read_month_frame(database: Path, year: int, month: int) -> pl.DataFrame:
    """Return the projected frame restricted to one ``YYYY-MM`` month."""
    return filter_month_frame(read_transactions_frame(database), year, month)


def filter_month_frame(df: pl.DataFrame, year: int, month: int) -> pl.DataFrame:
    """Filter a projected frame to rows whose ``date`` falls in one month."""
    label = f"{year:04d}-{month:02d}"
    return df.filter(pl.col("date").str.slice(0, 7) == label)


def latest_month_label(df: pl.DataFrame) -> str | None:
    """Return the ``YYYY-MM`` label of the newest row, or ``None`` if empty."""
    if df.is_empty():
        return None
    max_date = df.select(pl.col("date").max()).item()
    return None if max_date is None else str(max_date)[:7]


def distinct_month_count(df: pl.DataFrame) -> int:
    """Return the number of distinct ``YYYY-MM`` months present in a frame."""
    if df.is_empty():
        return 0
    return int(df.select(pl.col("date").str.slice(0, 7).n_unique()).item())


@dataclass(frozen=True)
class _ReadContext:
    """Lookup tables needed to project typed rows into CSV-shaped rows."""

    exact_values: dict[str, dict[str, Any]]
    money_values: dict[str, dict[str, Any]]
    locators: dict[str, dict[str, Any]]
    row_hashes: dict[str, str]

    @classmethod
    def build(cls, reader: RepositoryReader) -> "_ReadContext":
        """Collect projection inputs from one reader snapshot."""
        exact_values = {row["value_id"]: row for row in reader.rows("exact_values")}
        money_values = {row["value_id"]: row for row in reader.rows("money_values")}
        locators: dict[str, dict[str, Any]] = {}
        for row in reader.rows("record_provenance"):
            locators[row["provenance_id"]] = json.loads(row["legacy_locator_json"])
        return cls(
            exact_values=exact_values,
            money_values=money_values,
            locators=locators,
            row_hashes=_current_row_hashes(reader),
        )


def _current_row_hashes(reader: RepositoryReader) -> dict[str, str]:
    """Return non-superseded legacy ``row_hash`` mappings per entity."""
    superseded = {
        row["previous_mapping_id"] for row in reader.rows("legacy_identifier_supersessions")
    }
    mappings = sorted(
        (
            row
            for row in reader.rows("legacy_identifiers")
            if row["identifier_kind"] == "row_hash" and row["mapping_id"] not in superseded
        ),
        key=lambda row: str(row["mapping_id"]),
    )
    row_hashes: dict[str, str] = {}
    for mapping in mappings:
        row_hashes.setdefault(str(mapping["entity_id"]), str(mapping["identifier_value"]))
    return row_hashes


def _project_row(transaction: dict[str, Any], context: _ReadContext) -> dict[str, Any]:
    """Project one typed transaction row into the CSV column contract."""
    locator = context.locators.get(transaction["provenance_id"], {})
    tags_manual = _persisted_manual_tags(
        _decoded_tags(transaction["tags_manual_json"]),
        transaction["category_manual"],
    )
    source_row = locator.get("source_row")
    return {
        "row_hash": context.row_hashes.get(transaction["entity_id"]) or locator.get("row_hash"),
        "date": transaction["date_raw"],
        "time": transaction["time_raw"],
        "type_raw": transaction["type_raw"],
        "type_norm": transaction["type_norm"],
        "major_raw": transaction["major_raw"],
        "minor_raw": transaction["minor_raw"],
        "merchant_raw": transaction["merchant_raw"],
        "memo_raw": transaction["memo_raw"],
        "notes_manual": transaction["notes_manual"] or "",
        "amount": _exact_float(context.exact_values.get(transaction["amount_value_id"])),
        "account": transaction["account_text"],
        "currency": _currency_code(context.money_values.get(transaction["amount_value_id"])),
        "counterparty": transaction["counterparty"],
        "datetime": transaction["datetime_raw"],
        "category_rule": transaction["category_rule"],
        "category_final": _category_final(transaction),
        "tags_rule": _decoded_tags(transaction["tags_rule_json"]),
        "tags_ai": _decoded_tags(transaction["tags_ai_json"]),
        "tags_manual": tags_manual,
        "tags_final": _decoded_tags(transaction["tags_final_json"]),
        "confidence": _exact_float(context.exact_values.get(transaction["confidence_value_id"])),
        "needs_review": _optional_int(transaction["needs_review"]),
        "is_transfer_candidate": _transfer_flag(transaction["is_transfer_candidate"]),
        "is_transfer": _transfer_flag(transaction["is_transfer"]),
        "transfer_group_id": transaction["transfer_group_id"],
        "file_id": locator.get("file_id"),
        "source_row": None if source_row is None else int(source_row),
    }


def _decoded_tags(value: str) -> list[str]:
    """Decode one canonical JSON tag array column."""
    decoded = json.loads(value)
    return [str(tag) for tag in decoded]


def _persisted_manual_tags(visible_tags: list[str], category_manual: str | None) -> list[str]:
    """Rebuild the persisted ``tags_manual`` payload with its override marker."""
    visible, embedded_override = split_manual_tags(visible_tags)
    return build_manual_tags(visible, category_manual or embedded_override)


def _exact_float(value_row: dict[str, Any] | None) -> float | None:
    """Reconstruct the CSV-compatible float for one exact value row."""
    if value_row is None:
        return None
    coefficient = Decimal(str(value_row["coefficient"]))
    return float(coefficient.scaleb(-int(value_row["scale"])))


def _currency_code(money_row: dict[str, Any] | None) -> str | None:
    """Return the known currency code, or ``None`` when unknown or absent."""
    if money_row is None or money_row["currency_unknown"]:
        return None
    return str(money_row["currency_code"])


def _category_final(transaction: dict[str, Any]) -> str:
    """Apply the writer-side category fallback chain to one typed row."""
    for value in (
        transaction["category_final"],
        transaction["category_rule"],
        transaction["minor_raw"],
        transaction["major_raw"],
    ):
        if value is not None and str(value).strip():
            return str(value)
    return FALLBACK_CATEGORY


def _optional_int(value: bool | int | None) -> int | None:
    """Return the nullable integer flag for one stored boolean."""
    return None if value is None else int(value)


def _transfer_flag(value: bool | int | None) -> int:
    """Mirror the CSV writer, which fills transfer flags with ``0``."""
    return 0 if value is None else int(value)


def _frame_schema() -> dict[str, pl.DataType]:
    """Return the decoded-frame schema for the CSV column contract."""
    schema: dict[str, pl.DataType] = {}
    for column in CSV_COLUMNS:
        if column in TAG_JSON_COLUMNS:
            schema[column] = pl.List(pl.Utf8)
        else:
            schema[column] = cast(pl.DataType, POLARS_SCHEMA[column])
    return schema


def _build_frame(rows: list[dict[str, Any]]) -> pl.DataFrame:
    """Build a column-ordered frame from projected CSV-shaped rows."""
    columns = {column: [row[column] for row in rows] for column in CSV_COLUMNS}
    return pl.DataFrame(columns, schema=_frame_schema())


__all__ = [
    "GENERATION_ENV_VAR",
    "SqliteReadSourceError",
    "distinct_month_count",
    "filter_month_frame",
    "latest_month_label",
    "read_month_frame",
    "read_transactions_frame",
    "resolve_generation_database",
]
