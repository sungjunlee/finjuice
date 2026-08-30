"""Schema and column helpers for transaction CSV partitions.

Owns read-time column projection/defaults and write-time schema backfill.
Public transaction CRUD stays in :mod:`finjuice.pipeline.storage.csv_transactions`.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import polars as pl

from finjuice.pipeline.storage.csv_schema import CSV_COLUMNS


def _get_transaction_read_columns(path: Path, columns: list[str] | None) -> list[str] | None:
    """Return CSV columns needed for output projection plus datetime sorting."""
    if columns is None:
        return None

    with path.open(newline="", encoding="utf-8") as handle:
        header = next(csv.reader(handle), [])

    available = set(header)
    read_columns = [column for column in columns if column in available]
    if "is_transfer_candidate" in columns and "is_transfer_candidate" not in available:
        if "is_transfer" in available:
            read_columns.append("is_transfer")

    if "datetime" in available:
        read_columns.append("datetime")
    elif "date" in available:
        read_columns.append("date")
        if "time" in available:
            read_columns.append("time")

    return list(dict.fromkeys(read_columns)) or None


def _add_read_defaults(df: pl.DataFrame, columns: list[str] | None = None) -> pl.DataFrame:
    """Backfill additive read-time defaults for older compatible partitions."""
    defaults: list[pl.Expr] = []
    needs_notes = columns is None or "notes_manual" in columns
    needs_candidate = columns is None or "is_transfer_candidate" in columns
    needs_group_id = columns is None or "transfer_group_id" in columns

    if needs_notes and "notes_manual" not in df.columns:
        defaults.append(pl.lit("").cast(pl.Utf8).alias("notes_manual"))
    elif needs_notes:
        defaults.append(pl.col("notes_manual").cast(pl.Utf8, strict=False).fill_null(""))

    if needs_candidate and "is_transfer_candidate" not in df.columns:
        if "is_transfer" in df.columns:
            defaults.append(
                pl.col("is_transfer")
                .cast(pl.Int64, strict=False)
                .fill_null(0)
                .alias("is_transfer_candidate")
            )
        else:
            defaults.append(pl.lit(0).cast(pl.Int64).alias("is_transfer_candidate"))

    if needs_group_id and "transfer_group_id" not in df.columns:
        defaults.append(pl.lit(None).cast(pl.Utf8).alias("transfer_group_id"))

    if not defaults:
        return df
    return df.with_columns(defaults)


def _ensure_schema_columns(df: pl.DataFrame) -> pl.DataFrame:
    """Ensure all CSV schema columns exist with appropriate defaults.

    Handles test data or incomplete DataFrames by adding missing columns with
    sensible defaults (empty lists for tags, None for optional fields, etc.).
    """
    defaults = {
        "row_hash": pl.lit(None).cast(pl.Utf8),
        "date": pl.lit(None).cast(pl.Utf8),
        "time": pl.lit(None).cast(pl.Utf8),
        "type_raw": pl.lit(None).cast(pl.Utf8),
        "type_norm": pl.lit(None).cast(pl.Utf8),
        "major_raw": pl.lit(None).cast(pl.Utf8),
        "minor_raw": pl.lit(None).cast(pl.Utf8),
        "merchant_raw": pl.lit(None).cast(pl.Utf8),
        "memo_raw": pl.lit(None).cast(pl.Utf8),
        "notes_manual": pl.lit("").cast(pl.Utf8),
        "account": pl.lit(None).cast(pl.Utf8),
        "currency": pl.lit("KRW").cast(pl.Utf8),
        "counterparty": pl.lit(None).cast(pl.Utf8),
        "datetime": pl.lit(None).cast(pl.Utf8),
        "category_rule": pl.lit(None).cast(pl.Utf8),
        "category_final": pl.lit("미분류").cast(pl.Utf8),
        "transfer_group_id": pl.lit(None).cast(pl.Utf8),
        "file_id": pl.lit(None).cast(pl.Utf8),
        "amount": pl.lit(None).cast(pl.Float64),
        "confidence": pl.lit(None).cast(pl.Float64),
        "needs_review": pl.lit(0).cast(pl.Int64),
        "is_transfer_candidate": pl.lit(0).cast(pl.Int64),
        "is_transfer": pl.lit(0).cast(pl.Int64),
        "source_row": pl.lit(None).cast(pl.Int64),
        "tags_rule": pl.lit("[]").cast(pl.Utf8),
        "tags_ai": pl.lit("[]").cast(pl.Utf8),
        "tags_manual": pl.lit("[]").cast(pl.Utf8),
        "tags_final": pl.lit("[]").cast(pl.Utf8),
    }

    tag_columns = ["tags_rule", "tags_ai", "tags_manual", "tags_final"]
    for col in tag_columns:
        if col in df.columns:
            col_dtype = df.schema[col]
            if isinstance(col_dtype, pl.List):
                df = df.with_columns(
                    pl.col(col)
                    .map_elements(
                        lambda x: json.dumps(list(x) if x is not None else []), return_dtype=pl.Utf8
                    )
                    .alias(col)
                )

    def _null_if_blank(column_name: str) -> pl.Expr:
        """Convert blank strings to null for category fallback chain."""
        return pl.col(column_name).cast(pl.Utf8, strict=False).str.strip_chars().replace("", None)

    if "category_rule" not in df.columns:
        df = df.with_columns(defaults["category_rule"].alias("category_rule"))
    else:
        df = df.with_columns(_null_if_blank("category_rule").alias("category_rule"))

    fallback_candidates: list[pl.Expr] = [_null_if_blank("category_rule")]
    fallback_candidates.append(
        _null_if_blank("minor_raw") if "minor_raw" in df.columns else pl.lit(None).cast(pl.Utf8)
    )
    fallback_candidates.append(
        _null_if_blank("major_raw") if "major_raw" in df.columns else pl.lit(None).cast(pl.Utf8)
    )
    fallback_candidates.append(pl.lit("미분류").cast(pl.Utf8))
    fallback_expr = pl.coalesce(fallback_candidates)

    if "category_final" not in df.columns:
        df = df.with_columns(fallback_expr.alias("category_final"))
    else:
        df = df.with_columns(
            pl.when(_null_if_blank("category_final").is_not_null())
            .then(pl.col("category_final").cast(pl.Utf8, strict=False))
            .otherwise(fallback_expr)
            .alias("category_final")
        )

    for col in CSV_COLUMNS:
        if col not in df.columns:
            if col in defaults:
                df = df.with_columns(defaults[col].alias(col))
            else:
                df = df.with_columns(pl.lit(None).cast(pl.Utf8).alias(col))

    schema_columns = [col for col in CSV_COLUMNS if col in df.columns]
    extra_columns = [col for col in df.columns if col not in CSV_COLUMNS]
    return df.select(schema_columns + extra_columns)
