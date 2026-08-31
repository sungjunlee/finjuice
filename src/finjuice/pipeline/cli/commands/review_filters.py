"""Polars filter predicates for ``finjuice review``.

Owns list-dtype detection, untagged/rule-matched/default review
expressions, and match counting. Data loading, JSON row projection, and
the Typer command stay in :mod:`finjuice.pipeline.cli.commands.review`,
which re-exports these names so existing callers can keep importing from
that module. Human rendering lives in
:mod:`finjuice.pipeline.cli.commands.review_rendering`.
"""

from __future__ import annotations

import polars as pl


def _is_list_dtype(dtype: pl.DataType | None) -> bool:
    """Return True when the column is a Polars list type."""
    return dtype == pl.List(pl.Utf8) or (dtype is not None and str(dtype).startswith("List"))


def _untagged_expr(dtype: pl.DataType | None) -> pl.Expr:
    """Return an expression matching empty or null tags."""
    if _is_list_dtype(dtype):
        return (pl.col("tags_final").list.len() == 0) | pl.col("tags_final").is_null()

    return pl.col("tags_final").str.strip_chars().is_in(["[]", ""]) | pl.col("tags_final").is_null()


def _tags_present_expr(column: str, dtype: pl.DataType | None) -> pl.Expr:
    """Return an expression matching non-empty tag arrays stored as list or JSON text."""
    if _is_list_dtype(dtype):
        return (pl.col(column).list.len() > 0) & pl.col(column).is_not_null()

    return pl.col(column).is_not_null() & ~pl.col(column).str.strip_chars().is_in(["[]", ""])


def _rule_matched_expr(df: pl.DataFrame) -> pl.Expr:
    """Return the canonical rule_matched predicate for review signals."""
    expr = pl.lit(False)
    if "tags_rule" in df.columns:
        expr = expr | _tags_present_expr("tags_rule", df.schema.get("tags_rule"))
    if "category_rule" in df.columns:
        expr = expr | (
            pl.col("category_rule").is_not_null()
            & (pl.col("category_rule").str.strip_chars() != "")
        )
    return expr


def _default_review_expr(dtype: pl.DataType | None) -> pl.Expr:
    """Return the default review predicate used when no review flags are set."""
    return (
        (pl.col("needs_review") == 1)
        | _untagged_expr(dtype)
        | (pl.col("category_final") == "미분류")
    )


def _count_matches(df: pl.DataFrame, predicate: pl.Expr) -> int:
    """Return the number of rows matching *predicate*."""
    if df.is_empty():
        return 0
    return len(df.filter(predicate))
