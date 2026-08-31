"""Read-time normalization helpers for transaction CSV partitions.

Owns the post-load DataFrame shaping shared by the transaction readers:
datetime derivation from date/time columns, output column projection,
JSON tag decoding, and the empty-schema fallback frame. Public transaction
CRUD stays in :mod:`finjuice.pipeline.storage.csv_transactions`, which
re-exports these names so existing callers can keep importing from that
module.
"""

from __future__ import annotations

import polars as pl

from finjuice.pipeline.storage.csv_schema import CSV_COLUMNS, POLARS_SCHEMA

TAG_JSON_COLUMNS = ("tags_rule", "tags_ai", "tags_manual", "tags_final")


def _empty_transactions_df(columns: list[str] | None = None) -> pl.DataFrame:
    """Return an empty DataFrame shaped like the transaction schema."""
    schema = {col: POLARS_SCHEMA.get(col, pl.Utf8) for col in (columns or CSV_COLUMNS)}
    return pl.DataFrame(schema=schema)


def _normalize_datetime_column(df: pl.DataFrame) -> pl.DataFrame:
    """Derive a ``datetime`` column from ``date``/``time`` columns when missing."""
    if "datetime" in df.columns or "date" not in df.columns:
        return df
    if "time" in df.columns:
        return df.with_columns((pl.col("date") + "T" + pl.col("time")).alias("datetime"))
    return df.with_columns((pl.col("date") + "T00:00:00").alias("datetime"))


def _project_existing_columns(df: pl.DataFrame, columns: list[str] | None) -> pl.DataFrame:
    """Select requested columns that exist, leaving the frame untouched otherwise."""
    if columns is None:
        return df
    existing_cols = [c for c in columns if c in df.columns]
    if existing_cols:
        return df.select(existing_cols)
    return df


def _decode_tag_columns(df: pl.DataFrame) -> pl.DataFrame:
    """Parse JSON-encoded tag columns into ``List(Utf8)``."""
    for col in TAG_JSON_COLUMNS:
        if col in df.columns:
            df = df.with_columns(pl.col(col).str.json_decode(dtype=pl.List(pl.Utf8)).alias(col))
    return df
