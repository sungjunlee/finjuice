"""Review-pressure collector for the checkup bundle."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl
import yaml

from finjuice.pipeline.checkup.models import ReviewPressureSummary, ReviewSample
from finjuice.pipeline.checkup.partitions import latest_partition_month, read_month_partition
from finjuice.pipeline.checkup.values import float_or_none, string_or_none
from finjuice.pipeline.config import Config
from finjuice.pipeline.tagging.rules_yaml_io import summarize_rule_notes


def collect_review_pressure(
    config: Config,
    *,
    sample_limit: int,
) -> ReviewPressureSummary:
    """Summarize latest-month transactions that need human attention."""
    latest_month = latest_partition_month(config.csv_base_dir)
    if latest_month is None:
        return ReviewPressureSummary(
            status="empty",
            actionable=False,
            month=None,
            total_candidates=0,
            needs_review_count=0,
            untagged_count=0,
            unclassified_count=0,
            low_confidence_count=0,
            samples=[],
        )

    df = read_month_partition(config.csv_base_dir, latest_month)
    if df is None or df.is_empty():
        return ReviewPressureSummary(
            status="empty",
            actionable=False,
            month=latest_month,
            total_candidates=0,
            needs_review_count=0,
            untagged_count=0,
            unclassified_count=0,
            low_confidence_count=0,
            samples=[],
        )

    review_expr = _review_pressure_expr(df)
    matching_review_df = df.filter(review_expr)
    review_df = _sort_review_candidates(matching_review_df, sample_limit=sample_limit)
    needs_review_count = (
        int(df.filter(pl.col("needs_review") == 1).height) if "needs_review" in df.columns else 0
    )
    untagged_count = int(df.filter(_untagged_expr(df)).height)
    unclassified_count = (
        int(df.filter(pl.col("category_final") == "미분류").height)
        if "category_final" in df.columns
        else 0
    )
    low_confidence_count = int(df.filter(_low_confidence_expr()).height)

    return ReviewPressureSummary(
        status="needs_attention" if matching_review_df.height > 0 else "healthy",
        actionable=matching_review_df.height > 0,
        month=latest_month,
        total_candidates=int(matching_review_df.height),
        needs_review_count=needs_review_count,
        untagged_count=untagged_count,
        unclassified_count=unclassified_count,
        low_confidence_count=low_confidence_count,
        samples=[
            ReviewSample(
                date=string_or_none(row.get("date")),
                merchant=string_or_none(row.get("merchant_raw")),
                amount=float_or_none(row.get("amount")),
                reasons=_review_reasons(row),
            )
            for row in review_df.to_dicts()
        ],
        rule_notes=(
            _load_checkup_rule_notes(config.rules_file) if matching_review_df.height > 0 else []
        ),
    )


def _is_list_dtype(dtype: pl.DataType | None) -> bool:
    """Return True when the column is a Polars list type."""
    return dtype == pl.List(pl.Utf8) or (dtype is not None and str(dtype).startswith("List"))


def _untagged_expr(df: pl.DataFrame) -> pl.Expr:
    """Return the default untagged predicate used by review surfaces."""
    dtype = df.schema.get("tags_final")
    if _is_list_dtype(dtype):
        return (pl.col("tags_final").list.len() == 0) | pl.col("tags_final").is_null()
    return pl.col("tags_final").str.strip_chars().is_in(["[]", ""]) | pl.col("tags_final").is_null()


def _default_review_expr(df: pl.DataFrame) -> pl.Expr:
    """Return the default review predicate from the latest-month review flow."""
    return (
        (pl.col("needs_review") == 1) | _untagged_expr(df) | (pl.col("category_final") == "미분류")
    )


def _low_confidence_expr() -> pl.Expr:
    """Return the low-confidence predicate used by review surfaces."""
    return pl.col("confidence").is_null() | (pl.col("confidence") < 0.7)


def _review_pressure_expr(df: pl.DataFrame) -> pl.Expr:
    """Return the broader review-pressure predicate for checkup bundles."""
    return _default_review_expr(df) | _low_confidence_expr()


def _sort_review_candidates(df: pl.DataFrame, *, sample_limit: int) -> pl.DataFrame:
    """Sort review candidates newest-first with schema fallback."""
    if df.is_empty():
        return df
    if "datetime" in df.columns:
        return df.sort("datetime", descending=True).head(sample_limit)
    if "date" in df.columns:
        return df.sort("date", descending=True).head(sample_limit)
    return df.head(sample_limit)


def _review_reasons(row: dict[str, Any]) -> list[str]:
    """Derive stable reason labels for one review row."""
    reasons: list[str] = []
    if row.get("needs_review") == 1:
        reasons.append("needs_review")

    tags_value = row.get("tags_final")
    if tags_value is None or tags_value == "[]" or tags_value == [] or tags_value == "":
        reasons.append("untagged")

    if row.get("category_final") == "미분류":
        reasons.append("unclassified")
    confidence = row.get("confidence")
    if confidence is None or float(confidence) < 0.7:
        reasons.append("low_confidence")
    return reasons


def _load_checkup_rule_notes(rules_file: Path) -> list[dict[str, Any]]:
    """Best-effort rule notes for review/checkup consumers."""
    try:
        return summarize_rule_notes(rules_file, limit=5)
    except (OSError, yaml.YAMLError):
        return []
