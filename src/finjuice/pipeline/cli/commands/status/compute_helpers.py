"""Partition-read and tagging-metric helpers for ``finjuice status``.

Owns v2/v3 partition schema normalization, date-range expansion, tagging
and transfer row counts, and untagged-merchant aggregation. Fact
orchestration stays in :mod:`finjuice.pipeline.cli.commands.status.compute`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl

from finjuice.pipeline.filters import exclude_transfers, only_transfers
from finjuice.pipeline.storage.csv_schema import POLARS_SCHEMA


def _read_status_partition(partition_path: Path) -> pl.DataFrame:
    """Read one status partition with the canonical Polars schema overrides."""
    df = pl.read_csv(
        partition_path,
        schema_overrides=POLARS_SCHEMA,
        null_values=["", "NA", "NULL"],
    )
    return _normalize_status_partition_schema(df)


def _normalize_status_partition_schema(df: pl.DataFrame) -> pl.DataFrame:
    """Backfill read-time v3 category columns for compatible v2 partitions."""
    if "is_transfer_candidate" not in df.columns:
        if "is_transfer" in df.columns:
            df = df.with_columns(
                pl.col("is_transfer")
                .cast(pl.Int64, strict=False)
                .fill_null(0)
                .alias("is_transfer_candidate")
            )
        else:
            df = df.with_columns(pl.lit(0).cast(pl.Int64).alias("is_transfer_candidate"))

    if "category_rule" not in df.columns:
        df = df.with_columns(pl.lit(None).cast(pl.Utf8).alias("category_rule"))
    else:
        df = df.with_columns(_blank_to_null("category_rule").alias("category_rule"))

    fallback_candidates: list[pl.Expr] = [_blank_to_null("category_rule")]
    fallback_candidates.append(
        _blank_to_null("minor_raw") if "minor_raw" in df.columns else pl.lit(None).cast(pl.Utf8)
    )
    fallback_candidates.append(
        _blank_to_null("major_raw") if "major_raw" in df.columns else pl.lit(None).cast(pl.Utf8)
    )
    fallback_candidates.append(pl.lit("미분류").cast(pl.Utf8))
    fallback_expr = pl.coalesce(fallback_candidates)

    if "category_final" not in df.columns:
        return df.with_columns(fallback_expr.alias("category_final"))

    return df.with_columns(
        pl.when(_blank_to_null("category_final").is_not_null())
        .then(pl.col("category_final").cast(pl.Utf8, strict=False))
        .otherwise(fallback_expr)
        .alias("category_final")
    )


def _blank_to_null(column_name: str) -> pl.Expr:
    """Return a string expression that treats blank values as null."""
    return pl.col(column_name).cast(pl.Utf8, strict=False).str.strip_chars().replace("", None)


def _expand_date_range(
    df: pl.DataFrame,
    min_date: Any | None,
    max_date: Any | None,
) -> tuple[Any | None, Any | None]:
    """Return the expanded min/max date range for one non-empty partition."""
    partition_min = df.select(pl.col("date").min()).item()
    partition_max = df.select(pl.col("date").max()).item()

    next_min = partition_min if min_date is None or partition_min < min_date else min_date
    next_max = partition_max if max_date is None or partition_max > max_date else max_date
    return next_min, next_max


def _count_tagging_rows(df: pl.DataFrame) -> dict[str, Any]:
    """Return tagging counters for one filtered partition."""
    tags_col = df.schema.get("tags_final")
    untagged = df.filter(_tags_empty_expr(tags_col))
    non_transfer = df.filter(_exclude_transfers_expr(df))
    suggestable_untagged = non_transfer.filter(_tags_empty_expr(tags_col))
    transfer_count = _count_transfer_rows(df)
    transfer_candidate_count = _count_transfer_candidate_rows(df)
    return {
        "untagged": untagged,
        "untagged_count": len(untagged),
        "suggestable_untagged_count": len(suggestable_untagged),
        "transfer_candidate_count": transfer_candidate_count,
        "transfer_excluded_count": transfer_count,
        "transfer_excluded_untagged_count": max(len(untagged) - len(suggestable_untagged), 0),
        "unconfirmed_transfer_candidate_count": max(
            transfer_candidate_count - transfer_count,
            0,
        ),
    }


def _add_untagged_merchants(
    merchant_counts: dict[str, int],
    untagged: pl.DataFrame,
) -> None:
    """Accumulate top-untagged merchant counts without logging row details."""
    if len(untagged) == 0 or "merchant_raw" not in untagged.columns:
        return
    for merchant in untagged["merchant_raw"].to_list():
        if merchant:
            merchant_counts[merchant] = merchant_counts.get(merchant, 0) + 1


def _top_untagged_merchants(
    merchant_counts: dict[str, int],
    *,
    top_n: int,
) -> tuple[list[dict[str, Any]], int]:
    """Return sorted untagged merchant payload and total unique count."""
    all_untagged_sorted = sorted(merchant_counts.items(), key=lambda item: item[1], reverse=True)
    return (
        [{"merchant": name, "count": count} for name, count in all_untagged_sorted[:top_n]],
        len(all_untagged_sorted),
    )


def _tags_empty_expr(dtype: pl.DataType | None) -> pl.Expr:
    """Return an expression matching empty or null final tags."""
    if dtype == pl.List(pl.Utf8) or (dtype is not None and str(dtype).startswith("List")):
        return (pl.col("tags_final").list.len() == 0) | pl.col("tags_final").is_null()

    return pl.col("tags_final").str.strip_chars().is_in(["[]", ""]) | pl.col("tags_final").is_null()


def _exclude_transfers_expr(df: pl.DataFrame) -> pl.Expr:
    """Return the transfer-exclusion expression, tolerating older schema partitions."""
    if "is_transfer" not in df.columns:
        return pl.lit(True)
    if "transfer_group_id" not in df.columns:
        return pl.col("is_transfer").fill_null(0) == 0
    return exclude_transfers()


def _count_transfer_rows(df: pl.DataFrame) -> int:
    """Return confirmed transfer row count, tolerating older schema partitions."""
    if "is_transfer" not in df.columns or df.is_empty():
        return 0
    if "transfer_group_id" not in df.columns:
        return len(df.filter(pl.col("is_transfer") == 1))
    return len(df.filter(only_transfers()))


def _count_transfer_candidate_rows(df: pl.DataFrame) -> int:
    """Return transfer-like candidate row count, tolerating older schema partitions."""
    if df.is_empty():
        return 0
    if "is_transfer_candidate" in df.columns:
        return len(df.filter(pl.col("is_transfer_candidate").fill_null(0) == 1))
    if "is_transfer" in df.columns:
        return len(df.filter(pl.col("is_transfer").fill_null(0) == 1))
    return 0
