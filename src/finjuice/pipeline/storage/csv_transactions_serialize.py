"""Write-time serialization helpers for transaction CSV partitions.

Owns integer flag casting and tag-list JSON encoding before CSV write.
Public transaction CRUD stays in
:mod:`finjuice.pipeline.storage.csv_transactions`, which re-exports these
names so existing callers can keep importing from that module.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

import polars as pl


def _cast_int_flag_columns(df: pl.DataFrame) -> pl.DataFrame:
    """Cast integer flag columns and fill transfer flags with 0."""
    int_columns = ["needs_review", "is_transfer_candidate", "is_transfer", "source_row"]
    for col in int_columns:
        if col in df.columns:
            column_expr = pl.col(col).cast(pl.Int64, strict=False)
            if col in {"is_transfer_candidate", "is_transfer"}:
                column_expr = column_expr.fill_null(0)
            df = df.with_columns(column_expr.alias(col))
    return df


def _serialize_list(x: Any) -> str:
    """Serialize tag collections to UTF-8 JSON without double-encoding.

    Strings that already hold JSON (including legacy ``\\uXXXX``-escaped
    partitions written before the UTF-8 storage fix) are parsed and
    re-serialized with ``ensure_ascii=False`` so refreshes migrate
    legacy cells to plain UTF-8.
    """
    if x is None:
        return "[]"
    if isinstance(x, str):
        stripped = x.strip()
        if stripped == "":
            return "[]"
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return json.dumps(parsed, ensure_ascii=False)
        return stripped
    payload = list(x) if isinstance(x, Iterable) and not isinstance(x, (str, bytes)) else [x]
    return json.dumps(payload, ensure_ascii=False)


def _serialize_tag_columns(df: pl.DataFrame) -> pl.DataFrame:
    """Encode tag list columns as JSON strings for CSV storage."""
    tag_columns = ["tags_rule", "tags_ai", "tags_manual", "tags_final"]
    for col in tag_columns:
        if col in df.columns:
            df = df.with_columns(
                pl.col(col).map_elements(_serialize_list, return_dtype=pl.Utf8).alias(col)
            )
    return df
